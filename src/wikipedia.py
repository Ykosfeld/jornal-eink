"""Wikipedia: sorteio de artigos por categoria, limpeza de HTML e imagem de destaque."""
import io
import logging
import math

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

from .formulas import converter_formulas

logger = logging.getLogger(__name__)
ORES_API = "https://ores.wikimedia.org/v3/scores/ptwiki/"
CLASSES_QUALIDADE = {"STUB": 1, "START": 2, "C": 3, "B": 4, "GA": 5, "FA": 6}

SECOES_IGNORADAS = {
    "referências", "ver também", "ligações externas", "notas", "bibliografia",
    "leitura adicional", "fontes", "links externos",
    "references", "see also", "external links", "notes", "further reading", "bibliography", "sources",
    "einzelnachweise", "weblinks", "literatur", "siehe auch", "anmerkungen",
}
TAGS_PERMITIDAS = {"p", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "b", "i", "em", "strong", "sup", "sub", "br"}


# ---------------------------------------------------------------- API

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


# ---------------------------------------------------------------- Conteúdo

def limpar_html(extrato, max_chars, mathml=True):
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
        total += len(texto)
        saida.append((nome, converter_formulas(str(no), mathml)))
        if total >= max_chars and nome == "p":
            break
    # cabeçalho sem conteúdo depois dele é removido
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
    d = api(sessao, cfg, action="query", prop="extracts|info|pageimages|revisions", inprop="url",
            titles=titulo, exlimit=1, redirects=1,
            piprop="thumbnail|name", pithumbsize=icfg.get("thumb", 800), pilicense="free",
            rvprop="ids", rvlimit=1)
    pag = d["query"]["pages"][0]
    if pag.get("missing") or not pag.get("extract"):
        return None
    corpo, total = limpar_html(pag["extract"], cfg["max_caracteres"], cfg.get("mathml", True))
    revisoes = pag.get("revisions", [])
    return {"pageid": pag["pageid"], "titulo": pag["title"], "url": pag["fullurl"],
            "html": corpo, "chars": total,
            "revid": revisoes[0].get("revid") if revisoes else None,
            "imagem": baixar_imagem(sessao, pag, icfg)}


def avaliar_qualidade_ores(sessao, revid, timeout):
    """Devolve (classe ordinal, erro); erro None indica uma avaliação utilizável."""
    if revid is None:
        return None, "ID da revisão ausente"
    try:
        resposta = sessao.get(
            ORES_API,
            params={"models": "articlequality", "revids": revid},
            timeout=timeout,
        )
        resposta.raise_for_status()
        dados = resposta.json()
    except (requests.RequestException, ValueError) as e:
        return None, str(e)

    try:
        previsao = dados["ptwiki"]["scores"][str(revid)]["articlequality"]["score"]["prediction"]
    except (KeyError, TypeError):
        return None, "resposta sem previsão articlequality"
    classe = str(previsao)
    if classe not in {"1", "2", "3", "4", "5", "6"}:
        return None, f"classe articlequality desconhecida: {classe}"
    return int(classe), None


# ---------------------------------------------------------------- Sorteio

def sortear_artigo(sessao, cfg, categorias, usados, usados_ids, rng):
    """Escolhe uma raiz, desce aleatoriamente por subcategorias até achar um artigo aceitável."""
    ignorados = tuple(cfg["titulos_ignorados_prefixos"])
    filtro = cfg.get("filtro_qualidade", {})
    filtro_ativo = filtro.get("ativar", False)
    classe_minima = None
    timeout_ores = filtro.get("timeout", 10)
    if filtro_ativo:
        nome_classe = str(filtro.get("classe_minima", "B")).upper()
        if nome_classe not in CLASSES_QUALIDADE:
            raise ValueError(f"classe mínima ORES inválida: {nome_classe}")
        classe_minima = CLASSES_QUALIDADE[nome_classe]
        if (isinstance(timeout_ores, bool) or not isinstance(timeout_ores, (int, float))
                or not math.isfinite(timeout_ores) or timeout_ores <= 0):
            raise ValueError("timeout do ORES deve ser um número positivo")
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
                if filtro_ativo:
                    classe, erro = avaliar_qualidade_ores(sessao, art.get("revid"), timeout_ores)
                    if erro:
                        logger.warning(
                            "ORES indisponível para '%s'; aceitando candidato sem filtro de qualidade: %s",
                            art["titulo"], erro,
                        )
                    elif classe is not None and classe < classe_minima:
                        break
                art["caminho"] = " › ".join(caminho)
                return art
            break  # artigo curto/vazio: novo sorteio
    return None


def validar_categorias(sessao, cfg):
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
