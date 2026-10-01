#!/usr/bin/env python3
"""Escolha do Editor: artigos avulsos (Wikipédia ou qualquer site) indicados à mão.

Os links vêm de duas fontes, somadas: o arquivo de fila (`escolha_do_editor.txt`) e `--escolha` na CLI.
Sintaxe de cada entrada (uma por linha; linhas vazias e `# comentários` são ignorados):

    URL [| nota do editor] [| @arquivo.html] [| lang=xx]

- nota do editor: aparece em itálico no topo do capítulo.
- @arquivo.html: página já salva por você (caminho relativo à raiz do repo). Usa o HTML em vez de baixar o
  link, útil para paywall ou páginas que exigem login. O link continua obrigatório (fonte e idioma).
- lang=xx: força o idioma do capítulo (senão vem de <html lang>, ou do `lang` padrão do config).

Links da Wikipédia (em qualquer idioma) usam a API: com imagem e fórmulas, como nas curiosidades.
"""
import re
from urllib.parse import unquote, urlsplit

from readability import Document

from .config import resolver_caminho
from .feeds import limpar_generico
from .wikipedia import buscar_artigo

PADRAO = {
    "arquivo": "escolha_do_editor.txt",
    "max_caracteres": 30000,
    "min_caracteres": 300,   # abaixo disso: provável paywall / extração ruim
    "lang": "pt",            # idioma assumido quando a página não declara <html lang>
}

_WIKI = re.compile(r"([\w-]+)(?:\.m)?\.wikipedia\.org")
_LANG_HTML = re.compile(r"<html[^>]*?\blang\s*=\s*[\"']?([A-Za-z]{2,3})", re.I)


# ---------------------------------------------------------------- fila

def interpretar_linha(linha):
    """'URL | nota | @arquivo.html | lang=en' -> dict. None se vazia/comentário; ValueError se inválida."""
    texto = linha.strip()
    if not texto or texto.startswith("#"):
        return None
    url, *campos = [c.strip() for c in texto.split("|")]
    if not re.match(r"https?://", url, re.I):
        raise ValueError("a entrada deve começar com um link http(s)")
    e = {"url": url, "nota": "", "arquivo_html": None, "lang": None, "idx": None}
    notas = []
    for c in campos:
        if not c:
            continue
        if re.fullmatch(r"@\S+", c):
            e["arquivo_html"] = c[1:]
        elif re.fullmatch(r"lang\s*=\s*[A-Za-z-]{2,8}", c, re.I):
            e["lang"] = c.split("=", 1)[1].strip().lower()
        else:
            notas.append(c)
    e["nota"] = " | ".join(notas)
    return e


def ler_fila(caminho):
    """Devolve (linhas_brutas, entradas). Cada entrada guarda `idx`, a posição da linha no arquivo."""
    if not caminho.exists():
        return [], []
    linhas = caminho.read_text(encoding="utf-8-sig").splitlines()
    entradas = []
    for idx, linha in enumerate(linhas):
        try:
            e = interpretar_linha(linha)
        except ValueError as err:
            print(f"  {caminho.name}, linha {idx + 1}: ignorada ({err})")
            continue
        if e:
            e["idx"] = idx
            entradas.append(e)
    return linhas, entradas


def consumir_fila(fila):
    """Remove da fila só o que foi publicado (comentários e links que falharam ficam)."""
    if not fila["publicados"]:
        return
    restantes = [l for i, l in enumerate(fila["linhas"]) if i not in fila["publicados"]]
    caminho = fila["caminho"]
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text("\n".join(restantes) + ("\n" if restantes else ""), encoding="utf-8")
    tmp.replace(caminho)
    pendentes = sum(1 for l in restantes if l.strip() and not l.strip().startswith("#"))
    if pendentes:
        print(f"Fila de escolhas: {pendentes} link(s) pendente(s), será(ão) tentado(s) na próxima edição")


# ---------------------------------------------------------------- obtenção

def titulo_de_url(url):
    """'https://en.wikipedia.org/wiki/Foo_bar' -> ('en', 'Foo bar'); None se não for Wikipédia."""
    p = urlsplit(url)
    m = _WIKI.fullmatch(p.netloc.lower())
    if m and p.path.startswith("/wiki/") and len(p.path) > 6:
        return m.group(1), unquote(p.path[len("/wiki/"):]).replace("_", " ")
    return None


def baixar_pagina(sessao, url):
    r = sessao.get(url, timeout=30)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":   # requests assume latin-1 sem charset no header
        r.encoding = r.apparent_encoding
    return r.text


def _de_wikipedia(sessao, ecfg, wbase, lang, titulo):
    wcfg = {**wbase, "api": f"https://{lang}.wikipedia.org/w/api.php",
            "max_caracteres": ecfg["max_caracteres"]}
    art = buscar_artigo(sessao, wcfg, titulo)
    if not art:
        raise ValueError(f"artigo '{titulo}' não encontrado em {lang}.wikipedia.org (ou sem texto)")
    item = {"fonte": "Wikipédia" if lang == "pt" else f"Wikipédia ({lang})",
            "titulo": art["titulo"], "url": art["url"], "html": art["html"], "chars": art["chars"],
            "data": "", "lang": lang, "imagem": art["imagem"], "wikipedia": True}
    # pageid só vale dentro da wiki do sorteio automático (ids de wikis diferentes colidem)
    if urlsplit(wbase["api"]).netloc == f"{lang}.wikipedia.org":
        item["pageid"] = art["pageid"]
    return item


def _de_html(url, texto, ecfg, lang=None, do_arquivo=False):
    doc = Document(texto, url=url)
    corpo, total = limpar_generico(doc.summary(html_partial=True), ecfg["max_caracteres"])
    if total < ecfg["min_caracteres"]:
        dica = "" if do_arquivo else " — provável paywall ou página dinâmica; salve a página e use '| @arquivo.html'"
        raise ValueError(f"só {total} caracteres extraídos{dica}")
    m = _LANG_HTML.search(texto[:5000])
    titulo = (doc.short_title() or "").strip() or url
    return {"fonte": urlsplit(url).netloc.removeprefix("www."), "titulo": titulo, "url": url,
            "html": corpo, "chars": total, "data": "",
            "lang": lang or (m.group(1).lower() if m else ecfg["lang"])}


def obter_escolha(sessao, ecfg, wbase, e):
    """HTML fornecido > Wikipédia (API) > download do link. Levanta exceção se não der."""
    url = e["url"]
    if e["arquivo_html"]:
        caminho = resolver_caminho(e["arquivo_html"])
        if not caminho.is_file():
            raise ValueError(f"arquivo HTML não encontrado: {caminho}")
        texto = caminho.read_text(encoding="utf-8", errors="replace")
        return _de_html(url, texto, ecfg, e["lang"], do_arquivo=True)
    wiki = titulo_de_url(url)
    if wiki:
        return _de_wikipedia(sessao, ecfg, wbase, *wiki)
    return _de_html(url, baixar_pagina(sessao, url), ecfg, e["lang"])


# ---------------------------------------------------------------- coleta

def coletar_escolhas(sessao, cfg, extras=(), registros=()):
    """Lê a fila (arquivo) + `extras` (entradas da CLI). Devolve (itens, fila).

    `fila` é passada depois a `consumir_fila`, quando o epub já foi gerado com sucesso.
    Itens que falham não entram e permanecem no arquivo para a próxima edição.
    """
    ecfg = {**PADRAO, **(cfg.get("escolha_do_editor") or {})}
    caminho = resolver_caminho(ecfg["arquivo"])
    linhas, entradas = ler_fila(caminho)
    for linha in extras:
        try:
            e = interpretar_linha(linha)
        except ValueError as err:
            print(f"  --escolha ignorado ({err}): {linha}")
            continue
        if e:
            entradas.append(e)

    fila = {"caminho": caminho, "linhas": linhas, "publicados": set()}
    if not entradas:
        return [], fila

    print("\n[Escolha do Editor] coletando...")
    wbase = {**cfg["wikipedia"], "imagens": cfg.get("imagens", {"ativar": False})}
    ja_urls = {r["url"]: r["data"] for r in registros if "url" in r}
    ja_ids = {r["pageid"] for r in registros if "pageid" in r}

    def baixa(e):
        if e["idx"] is not None:
            fila["publicados"].add(e["idx"])

    itens, nesta_edicao = [], set()
    for e in entradas:
        if e["url"] in nesta_edicao:      # mesmo link duas vezes (fila + CLI): publica uma vez
            baixa(e)
            continue
        try:
            item = obter_escolha(sessao, ecfg, wbase, e)
        except Exception as err:  # noqa: BLE001 — um link ruim não derruba a edição
            destino = "mantido na fila" if e["idx"] is not None else "não está na fila, tente de novo"
            print(f"  ! {e['url']}: {err} ({destino})")
            continue
        item["nota"] = e["nota"]
        quando = ja_urls.get(item["url"]) or ja_urls.get(e["url"])
        if quando:
            print(f"    aviso: já publicado em {quando}; incluído mesmo assim")
        elif item.get("pageid") in ja_ids:
            print("    aviso: este artigo já saiu no sorteio da Wikipédia; incluído mesmo assim")
        nesta_edicao.update({e["url"], item["url"]})
        itens.append(item)
        baixa(e)
        extra = ", com imagem" if item.get("imagem") else ""
        print(f'  + [{item["fonte"]}] {item["titulo"]}  ({item["chars"]} chars, {item["lang"]}{extra})')
    return itens, fila
