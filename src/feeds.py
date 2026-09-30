#!/usr/bin/env python3
"""Coleta de notícias a partir de feeds RSS/Atom e arquivos OPML (Semana 2).

Usado tanto para a seção Notícias quanto para a seção da DW (Deutsch üben).
"""
import collections
import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup
from readability import Document

TAGS_PERMITIDAS = {"p", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "b", "i", "em", "strong", "sup", "sub", "br"}
BLOCOS = ["p", "h2", "h3", "h4", "ul", "ol", "blockquote"]
UTC = dt.timezone.utc

PADRAO = {
    "feeds": [], "opml": [],
    "por_feed": 2,          # máx. de itens por feed
    "max_total": 12,        # máx. de itens na seção (revezando entre os feeds)
    "dias": 7,              # só entradas publicadas nos últimos N dias (0 = sem limite)
    "max_caracteres": 8000,
    "min_caracteres": 500,  # abaixo disso tenta o resumo do feed e usa o mais longo
    "lang": "pt",
}


def resolver_caminho(p):
    """Caminho relativo é interpretado a partir da pasta do script (funciona igual no cron)."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else Path(__file__).resolve().parent / p


# ---------------------------------------------------------------- fontes (RSS + OPML)

def ler_opml(sessao, fonte):
    """Lê um .opml (caminho local ou URL). Devolve [(nome, url_do_feed)], incluindo pastas aninhadas."""
    if fonte.startswith(("http://", "https://")):
        r = sessao.get(fonte, timeout=30)
        r.raise_for_status()
        dados = r.content
    else:
        dados = resolver_caminho(fonte).read_bytes()
    raiz = ET.fromstring(dados)
    return [(o.get("title") or o.get("text"), o.get("xmlUrl"))
            for o in raiz.iter("outline") if o.get("xmlUrl")]


def carregar_feeds(sessao, cfg):
    """Une feeds listados diretamente e feeds vindos de OPML, sem duplicatas. [(nome|None, url)]"""
    brutos = []
    for f in cfg["feeds"]:
        brutos.append((None, f) if isinstance(f, str) else (f.get("nome"), f["url"]))
    for fonte in cfg["opml"]:
        try:
            achados = ler_opml(sessao, fonte)
            print(f"  OPML {fonte}: {len(achados)} feed(s)")
            brutos += achados
        except Exception as e:  # noqa: BLE001
            print(f"  OPML {fonte}: ERRO ({e})")
    vistos, saida = set(), []
    for nome, url in brutos:
        if url not in vistos:
            vistos.add(url)
            saida.append((nome, url))
    return saida


def ler_feed(sessao, url):
    r = sessao.get(url, timeout=30)
    r.raise_for_status()
    return feedparser.parse(r.content)


# ---------------------------------------------------------------- texto

def data_entrada(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    return dt.datetime(*t[:6], tzinfo=UTC) if t else None


def texto_da_entrada(e):
    """HTML que o próprio feed traz (conteúdo completo, se houver; senão o resumo)."""
    if e.get("content"):
        return e["content"][0].get("value", "")
    return e.get("summary", "")


def limpar_generico(fragmento, max_chars):
    """HTML qualquer (saída do readability ou resumo de feed) -> blocos simples para e-ink."""
    soup = BeautifulSoup(fragmento or "", "lxml")
    saida, total = [], 0
    for no in soup.find_all(BLOCOS):
        if no.find_parent(["p", "ul", "ol", "blockquote"]):
            continue  # já vai dentro do bloco pai
        for t in no.find_all(True):
            if t.name not in TAGS_PERMITIDAS:
                t.unwrap()
            else:
                t.attrs = {}
        no.attrs = {}
        texto = no.get_text(strip=True)
        if len(texto) < 2:
            continue
        total += len(texto)
        saida.append((no.name, str(no)))
        if total >= max_chars and no.name == "p":
            break
    while saida and saida[-1][0] in ("h2", "h3", "h4"):
        saida.pop()
    return "\n".join(h for _, h in saida), total


def obter_item(sessao, entrada, nome, cfg):
    """Baixa a página da entrada e extrai o texto; se falhar/curto, usa o que o feed trouxe."""
    url = entrada.get("link")
    titulo = (entrada.get("title") or "").strip()
    if not url or not titulo:
        return None
    corpo, total = "", 0
    try:
        r = sessao.get(url, timeout=30)
        r.raise_for_status()
        corpo, total = limpar_generico(Document(r.text).summary(html_partial=True), cfg["max_caracteres"])
    except Exception:  # noqa: BLE001 — cai no resumo do feed
        pass
    if total < cfg["min_caracteres"]:
        c2, t2 = limpar_generico(texto_da_entrada(entrada), cfg["max_caracteres"])
        if t2 > total:
            corpo, total = c2, t2
    if total < 150:
        return None
    d = data_entrada(entrada)
    return {"fonte": nome, "titulo": titulo, "url": url, "html": corpo, "chars": total,
            "data": d.strftime("%d/%m/%Y") if d else "", "lang": cfg["lang"]}


# ---------------------------------------------------------------- coleta

def coletar_noticias(sessao, cfg_usuario, usados_urls, agora):
    """Devolve lista de itens, revezando entre os feeds até `max_total`. Atualiza `usados_urls`."""
    cfg = {**PADRAO, **cfg_usuario}
    limite = agora - dt.timedelta(days=cfg["dias"]) if cfg["dias"] else None
    minimo = dt.datetime.min.replace(tzinfo=UTC)

    filas = []
    for nome, url in carregar_feeds(sessao, cfg):
        try:
            feed = ler_feed(sessao, url)
        except Exception as e:  # noqa: BLE001
            print(f"  {nome or url}: falha ao ler feed ({e})")
            continue
        nome = nome or feed.feed.get("title") or url
        entradas = [(data_entrada(e), e) for e in feed.entries
                    if e.get("link") not in usados_urls]
        entradas = [(d, e) for d, e in entradas if not (limite and d and d < limite)]
        entradas.sort(key=lambda x: x[0] or minimo, reverse=True)
        print(f"  {nome}: {len(entradas)} entrada(s) na janela")
        filas.append({"nome": nome, "fila": collections.deque(e for _, e in entradas), "n": 0})

    itens = []
    while len(itens) < cfg["max_total"]:
        ativos = [f for f in filas if f["fila"] and f["n"] < cfg["por_feed"]]
        if not ativos:
            break
        for f in ativos:
            if len(itens) >= cfg["max_total"]:
                break
            item = obter_item(sessao, f["fila"].popleft(), f["nome"], cfg)
            if item and item["url"] not in usados_urls:
                itens.append(item)
                usados_urls.add(item["url"])
                f["n"] += 1
                print(f'  + [{f["nome"]}] {item["titulo"]}  ({item["chars"]} chars)')
    return itens


def validar_feeds(sessao, cfgs):
    """`cfgs`: lista de configs (notícias, DW). Mostra, por feed, se abre e qual a entrada mais recente."""
    for cfg_usuario in cfgs:
        cfg = {**PADRAO, **cfg_usuario}
        for nome, url in carregar_feeds(sessao, cfg):
            try:
                feed = ler_feed(sessao, url)
                datas = [d for d in map(data_entrada, feed.entries) if d]
                recente = max(datas).strftime("%d/%m/%Y") if datas else "sem data"
                marca = "OK  " if feed.entries else "VAZIO"
                print(f"  {marca} {nome or feed.feed.get('title') or url}: "
                      f"{len(feed.entries)} entradas, mais recente {recente}")
            except Exception as e:  # noqa: BLE001
                print(f"  ERRO {nome or url}: {e}")
