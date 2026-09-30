#!/usr/bin/env python3
"""Gerador do Jornal Semanal (.epub) — Semanas 1-2: Notícias + Curiosidades (Wikipedia) + Deutsch üben (DW) + capa generativa."""
import argparse
import datetime as dt
import html
import io
import json
import random
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from ebooklib import epub

from capa import gerar_capa, html_controle
from feeds import coletar_noticias, validar_feeds

HEADERS = {
    # A Wikimedia exige um User-Agent identificável. Troque pelo seu contato.
    "User-Agent": "JornalSemanalEink/0.1 (projeto pessoal; contato: yuri.kosfeld@gmail.com)"
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
.capa { text-align: center; margin: 0; padding: 0; }
.capa img { width: 100%; height: auto; max-height: 100%; }
table { font-size: 0.85em; border-collapse: collapse; margin: 0.8em 0; }
td { padding: 0.2em 1em 0.2em 0; vertical-align: top; }
small { font-size: 0.8em; }
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
    return {"pageid": pag["pageid"], "titulo": pag["title"], "url": pag["fullurl"],
            "html": corpo, "chars": total,
            "imagem": baixar_imagem(sessao, pag, icfg)}


def sortear_artigo(sessao, cfg, categorias, usados, usados_ids, rng):
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
            if art and art["pageid"] in usados_ids:
                break  # redirecionou para um artigo já publicado: novo sorteio
            if art and art["chars"] >= cfg["min_caracteres"]:
                art["caminho"] = " › ".join(caminho)
                return art
            break  # artigo curto/vazio: novo sorteio
    return None


# ---------------------------------------------------------------- EPUB

def capitulo(arquivo, titulo, corpo, css, lang="pt"):
    c = epub.EpubHtml(title=titulo, file_name=arquivo, lang=lang)
    c.content = f"<html><body>{corpo}</body></html>"
    c.add_item(css)
    return c


def montar_epub(cfg, artigos, data, destino, numero_edicao=None, noticias=(), dw=()):
    """Monta o epub. Devolve o `info` da capa (semente, níveis etc.) para log."""
    livro = epub.EpubBook()
    livro.set_identifier(f"jornal-{data.isoformat()}")
    livro.set_title(f"{cfg['titulo']} — {data.strftime('%d/%m/%Y')}")
    livro.set_language(cfg["idioma"])
    livro.add_author(cfg["autor"])

    css = epub.EpubItem(uid="estilo", file_name="estilo.css", media_type="text/css", content=CSS)
    livro.add_item(css)

    # Capa generativa: a semente sai dos pageids dos artigos da Wikipedia + data.
    # (Notícias e DW não entram: não têm pageid e mudariam o desenho se a coleta variasse.)
    png_capa, info_capa = gerar_capa(cfg["titulo"], data, [a["pageid"] for _, a in artigos],
                                     numero_edicao)
    livro.set_cover("capa.png", png_capa, create_page=False)   # capa dos metadados (biblioteca do X4)
    capa = capitulo("capa.xhtml", "Capa",
                    f'<div class="capa"><img src="capa.png" alt="{html.escape(cfg["titulo"], quote=True)}"/></div>',
                    css)
    livro.add_item(capa)

    def externos(prefixo, itens):
        """Capítulos de notícias e DW (itens vindos de feeds.py)."""
        caps_ext = []
        for i, it in enumerate(itens, 1):
            u = html.escape(it["url"])
            rotulo = html.escape(it["fonte"]) + (f' · {it["data"]}' if it["data"] else "")
            corpo = (f'<p class="tema">{rotulo}</p><h1>{html.escape(it["titulo"])}</h1>{it["html"]}'
                     f'<p class="fonte">Fonte: <a href="{u}">{u}</a></p>')
            c = capitulo(f"{prefixo}_{i:02d}.xhtml", f'{it["fonte"]}: {it["titulo"]}', corpo, css, it["lang"])
            livro.add_item(c)
            caps_ext.append(c)
        return caps_ext

    caps_not = externos("not", noticias)

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

    caps_dw = externos("dw", dw)

    # Última página: dados de controle da capa (semente, níveis...) só para curiosidade/depuração.
    controle = capitulo("controle.xhtml", "Nota de controle",
                        html_controle(info_capa, [(t, a["titulo"], a["pageid"]) for t, a in artigos]),
                        css)
    livro.add_item(controle)

    grupos = [("Notícias", caps_not), ("Curiosidades", caps), ("Deutsch üben", caps_dw)]
    livro.toc = [capa] + [(epub.Section(nome), cs) for nome, cs in grupos if cs] + [controle]
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = [capa, "nav"] + [c for _, cs in grupos for c in cs] + [controle]

    destino.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(destino), livro)
    return info_capa


# ---------------------------------------------------------------- Histórico

def caminho_historico(hcfg):
    p = Path(hcfg["arquivo"]).expanduser()
    return p if p.is_absolute() else Path(__file__).resolve().parent / p


def carregar_historico(caminho, esquecer_semanas, hoje):
    """Lê o histórico; descarta registros mais antigos que `esquecer_semanas` (0 = nunca esquece)."""
    if not caminho.exists():
        return []
    try:
        registros = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Histórico corrompido ({caminho}): {e}\nCorrija ou renomeie o arquivo e rode de novo.")
    if esquecer_semanas > 0:
        limite = hoje - dt.timedelta(weeks=esquecer_semanas)
        registros = [r for r in registros if dt.date.fromisoformat(r["data"]) >= limite]
    return registros


def salvar_historico(caminho, registros):
    """Grava de forma atômica (arquivo temporário + rename), para não corromper se cair no meio."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(registros, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)


def numero_da_edicao(cfg, hoje):
    """Nº da edição = semanas desde `primeira_edicao` (config) + 1. Sem estado; None se não configurado."""
    primeira = cfg.get("primeira_edicao")
    if isinstance(primeira, str):
        primeira = dt.date.fromisoformat(primeira)
    if not primeira or hoje < primeira:
        return None
    return (hoje - primeira).days // 7 + 1


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
    ap.add_argument("--validar-feeds", action="store_true", help="só testa os feeds (notícias e DW)")
    ap.add_argument("--semente", type=int, help="semente do sorteio (reprodutível)")
    ap.add_argument("--sem-historico", action="store_true",
                    help="não lê nem grava o histórico (use em testes)")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    sessao = requests.Session()
    sessao.headers.update(HEADERS)

    if args.validar:
        validar(sessao, cfg)
        return
    if args.validar_feeds:
        ncfg, dcfg = cfg.get("noticias") or {}, cfg.get("dw") or {}
        validar_feeds(sessao, [ncfg, {"feeds": [dcfg["feed"]]} if dcfg.get("feed") else {}])
        return

    hoje = dt.date.today()
    hcfg = {"arquivo": "historico.json", "esquecer_apos_semanas": 0, **cfg.get("historico", {})}
    usar_hist = not args.sem_historico
    caminho_hist = caminho_historico(hcfg)
    registros = carregar_historico(caminho_hist, hcfg["esquecer_apos_semanas"], hoje) if usar_hist else []
    print(f"Histórico: {len(registros)} item(ns) já publicado(s)" if usar_hist
          else "Histórico desativado (--sem-historico)")
    # Registros da Wikipedia têm pageid; os de notícias/DW têm url.
    usados = {r["titulo"] for r in registros if "pageid" in r}
    usados_ids = {r["pageid"] for r in registros if "pageid" in r}
    usados_urls = {r["url"] for r in registros if "url" in r}

    rng = random.Random(args.semente)
    wcfg = {**cfg["wikipedia"], "imagens": cfg.get("imagens", {"ativar": False})}
    artigos, novos, pulados = [], [], []
    for tema, cats in cfg["temas"].items():
        print(f"[{tema}] sorteando...", end=" ", flush=True)
        try:
            art = sortear_artigo(sessao, wcfg, cats, usados, usados_ids, rng)
        except requests.RequestException as e:
            print(f"falha de rede ({e})")
            pulados.append(tema)
            continue
        if art is None:
            print("nenhum artigo novo encontrado — tema pulado")
            pulados.append(tema)
            continue
        usados.add(art["titulo"])
        usados_ids.add(art["pageid"])
        artigos.append((tema, art))
        novos.append({"pageid": art["pageid"], "titulo": art["titulo"],
                      "tema": tema, "data": hoje.isoformat()})
        extra = ", com imagem" if art.get("imagem") else ""
        print(f'{art["titulo"]}  ({art["caminho"]}, {art["chars"]} chars{extra})')

    agora = dt.datetime.now(dt.timezone.utc)
    noticias, dw = [], []
    ncfg = cfg.get("noticias") or {}
    if ncfg.get("ativar") and (ncfg.get("feeds") or ncfg.get("opml")):
        print("\n[Notícias] coletando...")
        noticias = coletar_noticias(sessao, ncfg, usados_urls, agora)
    dcfg = cfg.get("dw") or {}
    if dcfg.get("ativar") and dcfg.get("feed"):
        print("\n[DW] coletando...")
        dw = coletar_noticias(sessao, {
            "feeds": [{"nome": "DW · Top-Thema mit Vokabeln", "url": dcfg["feed"]}],
            "por_feed": dcfg.get("quantidade", 3), "max_total": dcfg.get("quantidade", 3),
            "dias": dcfg.get("dias", 14), "max_caracteres": dcfg.get("max_caracteres", 12000),
            "min_caracteres": dcfg.get("min_caracteres", 800), "lang": "de",
        }, usados_urls, agora)
    novos += [{"tipo": tipo, "url": it["url"], "titulo": it["titulo"],
               "fonte": it["fonte"], "data": hoje.isoformat()}
              for tipo, itens in (("noticia", noticias), ("dw", dw)) for it in itens]

    if not (artigos or noticias or dw):
        sys.exit("Nada obtido; epub não gerado.")

    destino = Path(cfg["saida"]).expanduser() / f"jornal_{hoje.isoformat()}.epub"
    info_capa = montar_epub(cfg, artigos, hoje, destino, numero_da_edicao(cfg, hoje), noticias, dw)
    if usar_hist:
        salvar_historico(caminho_hist, registros + novos)   # só depois do epub gerado com sucesso
    print(f"\nEpub gerado: {destino}  ({len(noticias)} notícias, {len(artigos)} curiosidades, {len(dw)} da DW)")
    print(f"Capa: semente {info_capa['semente']}, {info_capa['niveis']} níveis, "
          f"{info_capa['faixas_cinza']} faixas de cinza")
    if pulados:
        print("ATENÇÃO — temas sem artigo nesta edição: " + ", ".join(pulados)
              + "\n  (categorias esgotadas ou falha de rede; considere adicionar mais raízes no config.yaml)")


if __name__ == "__main__":
    main()