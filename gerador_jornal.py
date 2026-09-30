#!/usr/bin/env python3
"""Gerador do Jornal Semanal (.epub) — Semana 1: apenas seção Curiosidades (Wikipedia)."""
import argparse
import datetime as dt
import html
import io
import random
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from ebooklib import epub

HEADERS = {
    # A Wikimedia exige um User-Agent identificável. Troque pelo seu contato.
    "User-Agent": "JornalSemanalEink/0.1 (projeto pessoal; contato: seu-email@exemplo.com)"
}

SECOES_IGNORADAS = {
    "referências", "ver também", "ligações externas", "notas", "bibliografia",
    "leitura adicional", "ligações externas", "fontes", "links externos",
}
TAGS_PERMITIDAS = {"p", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "b", "i", "em", "strong", "sup", "sub", "br"}

CSS = """
body { font-family: serif; line-height: 1.4; margin: 0 0.5em; }
h1 { font-size: 1.5em; margin: 0.6em 0 0.2em; }
h2 { font-size: 1.2em; margin-top: 1.2em; }
h3 { font-size: 1.05em; }
p { text-align: justify; margin: 0.5em 0; }
.tema { font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.08em; }
.fonte { font-size: 0.8em; margin-top: 2em; border-top: 1px solid #000; padding-top: 0.5em; }
img { max-width: 100%; height: auto; }
.imagem { text-align: center; margin: 0.6em 0; }
.capa { text-align: center; margin-top: 30%; }
.capa h1 { font-size: 2.2em; }
"""


# ---------------------------------------------------------------- Wikipedia

def api(sessao, cfg, **params):
    params.update(format="json", formatversion=2)
    r = sessao.get(cfg["api"], params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def membros(sessao, cfg, categoria, max_paginas_api=2):
    """Devolve (artigos, subcategorias) de uma categoria."""
    artigos, subs, cont = [], [], {}
    for _ in range(max_paginas_api):
        d = api(sessao, cfg, action="query", list="categorymembers",
                cmtitle=f"Categoria:{categoria}", cmtype="page|subcat",
                cmnamespace="0|14", cmlimit=500, **cont)
        for m in d.get("query", {}).get("categorymembers", []):
            if m["ns"] == 14:
                subs.append(m["title"].split(":", 1)[1])
            else:
                artigos.append(m["title"])
        if "continue" not in d:
            break
        cont = d["continue"]
    return artigos, subs


def limpar_html(extrato, max_chars):
    """Limpa o HTML devolvido por prop=extracts para algo adequado a e-ink."""
    soup = BeautifulSoup(extrato, "lxml")
    corpo = soup.body or soup
    saida, pulando, total = [], False, 0
    for no in list(corpo.children):
        nome = getattr(no, "name", None)
        if nome is None:
            continue
        if nome in ("h2", "h3"):
            pulando = no.get_text(strip=True).lower() in SECOES_IGNORADAS
        if pulando or nome not in TAGS_PERMITIDAS:
            continue
        for t in no.find_all(True):
            if t.name not in TAGS_PERMITIDAS:
                t.unwrap()
            else:
                t.attrs = {}
        no.attrs = {}
        texto = no.get_text(strip=True)
        if not texto:
            continue
        # cabeçalho sem conteúdo depois dele é removido no fim
        total += len(texto)
        saida.append((nome, str(no)))
        if total >= max_chars and nome == "p":
            break
    while saida and saida[-1][0] in ("h2", "h3", "h4"):
        saida.pop()
    return "\n".join(h for _, h in saida), total


def preparar_imagem(dados, icfg):
    """Tons de cinza + contraste + redimensionamento + JPEG, pensado para e-ink."""
    img = Image.open(io.BytesIO(dados))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(fundo, img)
    img = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    img.thumbnail((icfg["largura_max"], icfg["altura_max"]), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=icfg["qualidade_jpeg"], optimize=True)
    return buf.getvalue()


def baixar_imagem(sessao, pag, icfg):
    """Baixa e prepara a imagem de destaque do artigo. Devolve None se não houver/der erro."""
    thumb = pag.get("thumbnail")
    if not icfg.get("ativar") or not thumb:
        return None
    if min(thumb.get("width", 0), thumb.get("height", 0)) < icfg["tamanho_min"]:
        return None
    try:
        r = sessao.get(thumb["source"], timeout=30)
        r.raise_for_status()
        return {"bytes": preparar_imagem(r.content, icfg), "arquivo": pag.get("pageimage", "")}
    except Exception:  # noqa: BLE001 — imagem é opcional, nunca derruba o artigo
        return None


def buscar_artigo(sessao, cfg, titulo):
    icfg = cfg.get("imagens", {"ativar": False})
    d = api(sessao, cfg, action="query", prop="extracts|info|pageimages", inprop="url",
            titles=titulo, exlimit=1, redirects=1,
            piprop="thumbnail|name", pithumbsize=icfg.get("thumb", 800), pilicense="free")
    pag = d["query"]["pages"][0]
    if pag.get("missing") or not pag.get("extract"):
        return None
    corpo, total = limpar_html(pag["extract"], cfg["max_caracteres"])
    return {"titulo": pag["title"], "url": pag["fullurl"], "html": corpo, "chars": total,
            "imagem": baixar_imagem(sessao, pag, icfg)}


def sortear_artigo(sessao, cfg, categorias, usados, rng):
    """Escolhe uma raiz, desce aleatoriamente por subcategorias até achar um artigo aceitável."""
    ignorados = tuple(cfg["titulos_ignorados_prefixos"])
    for _ in range(cfg["tentativas"]):
        cat = rng.choice(categorias)
        caminho = [cat]
        for nivel in range(cfg["profundidade_max"] + 1):    
            artigos, subs = membros(sessao, cfg, cat)
            artigos = [a for a in artigos if not a.startswith(ignorados) and a not in usados]
            if nivel == cfg["profundidade_max"] or not subs:
                opcoes = [("a", a) for a in artigos]
            else:
                opcoes = [("a", a) for a in artigos] + [("s", s) for s in subs]
            if not opcoes:
                break
            tipo, escolha = rng.choice(opcoes)
            if tipo == "s":
                cat = escolha
                caminho.append(cat)
                continue
            art = buscar_artigo(sessao, cfg, escolha)
            if art and art["chars"] >= cfg["min_caracteres"]:
                art["caminho"] = " › ".join(caminho)
                return art
            break  # artigo curto/vazio: novo sorteio
    return None


# ---------------------------------------------------------------- EPUB

def capitulo(arquivo, titulo, corpo, css):
    c = epub.EpubHtml(title=titulo, file_name=arquivo, lang="pt")
    c.content = f"<html><body>{corpo}</body></html>"
    c.add_item(css)
    return c


def montar_epub(cfg, artigos, data, destino):
    livro = epub.EpubBook()
    livro.set_identifier(f"jornal-{data.isoformat()}")
    livro.set_title(f"{cfg['titulo']} — {data.strftime('%d/%m/%Y')}")
    livro.set_language(cfg["idioma"])
    livro.add_author(cfg["autor"])

    css = epub.EpubItem(uid="estilo", file_name="estilo.css", media_type="text/css", content=CSS)
    livro.add_item(css)

    capa = capitulo("capa.xhtml", "Capa",
                    f'<div class="capa"><h1>{html.escape(cfg["titulo"])}</h1>'
                    f'<p>{data.strftime("%d/%m/%Y")}</p></div>', css)
    livro.add_item(capa)

    caps = []
    for i, (tema, art) in enumerate(artigos, 1):
        img_html, img_credito = "", ""
        if art.get("imagem"):
            nome_img = f"img/cur_{i:02d}.jpg"
            livro.add_item(epub.EpubItem(uid=f"img_{i:02d}", file_name=nome_img,
                                         media_type="image/jpeg", content=art["imagem"]["bytes"]))
            img_html = (f'<p class="imagem"><img src="{nome_img}" '
                        f'alt="{html.escape(art["titulo"], quote=True)}"/></p>')
            arq = art["imagem"]["arquivo"]
            if arq:
                link = "https://pt.wikipedia.org/wiki/Ficheiro:" + arq.replace(" ", "_")
                img_credito = f' Imagem: <a href="{html.escape(link)}">página do arquivo</a> (Wikimedia).'
        corpo = (f'<p class="tema">{html.escape(tema)}</p>'
                 f'<h1>{html.escape(art["titulo"])}</h1>{img_html}{art["html"]}'
                 f'<p class="fonte">Fonte: Wikipédia — <a href="{html.escape(art["url"])}">{html.escape(art["url"])}</a>'
                 f' (CC BY-SA 4.0).{img_credito}</p>')
        c = capitulo(f"cur_{i:02d}.xhtml", f'{tema}: {art["titulo"]}', corpo, css)
        livro.add_item(c)
        caps.append(c)

    livro.toc = [capa, (epub.Section("Curiosidades"), caps)]
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", capa] + caps

    destino.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(destino), livro)


# ---------------------------------------------------------------- CLI

def validar(sessao, cfg):
    """Confere se cada categoria existe e mostra quantos artigos/subcategorias tem."""
    ruins = 0
    for tema, cats in cfg["temas"].items():
        print(f"\n{tema}")
        for cat in cats:
            try:
                a, s = membros(sessao, cfg["wikipedia"], cat, max_paginas_api=1)
            except Exception as e:  # noqa: BLE001
                print(f"  ERRO  {cat}: {e}")
                ruins += 1
                continue
            marca = "OK   " if (a or s) else "VAZIA"
            if not (a or s):
                ruins += 1
            print(f"  {marca} {cat}: {len(a)} artigos, {len(s)} subcategorias")
    print(f"\n{ruins} categoria(s) com problema.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--validar", action="store_true", help="só testa as categorias do config")
    ap.add_argument("--semente", type=int, help="semente do sorteio (reprodutível)")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    sessao = requests.Session()
    sessao.headers.update(HEADERS)

    if args.validar:
        validar(sessao, cfg)
        return

    rng = random.Random(args.semente)
    wcfg = {**cfg["wikipedia"], "imagens": cfg.get("imagens", {"ativar": False})}
    artigos, usados = [], set()
    for tema, cats in cfg["temas"].items():
        print(f"[{tema}] sorteando...", end=" ", flush=True)
        try:
            art = sortear_artigo(sessao, wcfg, cats, usados, rng)
        except requests.RequestException as e:
            print(f"falha de rede ({e})")
            continue
        if art is None:
            print("nenhum artigo encontrado — tema pulado")
            continue
        usados.add(art["titulo"])
        artigos.append((tema, art))
        extra = ", com imagem" if art.get("imagem") else ""
        print(f'{art["titulo"]}  ({art["caminho"]}, {art["chars"]} chars{extra})')

    if not artigos:
        sys.exit("Nenhum artigo obtido; epub não gerado.")

    hoje = dt.date.today()
    destino = Path(cfg["saida"]).expanduser() / f"jornal_{hoje.isoformat()}.epub"
    montar_epub(cfg, artigos, hoje, destino)
    print(f"\nEpub gerado: {destino}  ({len(artigos)} artigos)")


if __name__ == "__main__":
    main()