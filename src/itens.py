"""Item uniforme: adaptadores na borda de cada coletor (Wikipédia, notícias/DW, Escolha do editor).

Contrato (campos que o builder usa):
    fonte_id   id da fonte de origem (tema, 'noticias', 'dw', 'editor'): agrupa nas seções
    fonte      nome de exibição (feed, "Wikipédia", site)  [mantido: o histórico grava este campo]
    rotulo     texto do <p class="tema">
    titulo, titulo_toc, url, html, lang, data
    imagem     None ou {"bytes", "arquivo"}
    credito    HTML interno do rodapé (o builder envolve em <p class="fonte">)
    nota       comentário do editor ('' se não houver)
    pageid     só Wikipédia
Os coletores não mudam; cada função devolve um dict novo com os campos extras.
"""
import html
from urllib.parse import urlsplit


def _rotulo(fonte, data):
    return fonte + (f" · {data}" if data else "")


def item_curiosidade(tema, art):
    """(tema, artigo de wikipedia.buscar_artigo) -> item uniforme."""
    u = html.escape(art["url"])
    img_credito = ""
    if art.get("imagem") and art["imagem"].get("arquivo"):
        link = "https://pt.wikipedia.org/wiki/Ficheiro:" + art["imagem"]["arquivo"].replace(" ", "_")
        img_credito = f' Imagem: <a href="{html.escape(link)}">página do arquivo</a> (Wikimedia).'
    return {"fonte_id": tema, "fonte": "Wikipédia", "rotulo": tema,
            "titulo": art["titulo"], "titulo_toc": f'{tema}: {art["titulo"]}',
            "url": art["url"], "html": art["html"], "chars": art["chars"],
            "lang": "pt", "data": "", "imagem": art.get("imagem"),
            "credito": f'Fonte: Wikipédia — <a href="{u}">{u}</a> (CC BY-SA 4.0).{img_credito}',
            "nota": "", "pageid": art["pageid"]}


def item_externo(fonte_id, it):
    """Item de feeds.coletar_noticias (notícias ou DW) -> item uniforme."""
    u = html.escape(it["url"])
    return {**it, "fonte_id": fonte_id, "rotulo": _rotulo(it["fonte"], it["data"]),
            "titulo_toc": f'{it["fonte"]}: {it["titulo"]}',
            "imagem": None, "credito": f'Fonte: <a href="{u}">{u}</a>', "nota": ""}


def item_editor(it):
    """Item de escolha.coletar_escolhas -> item uniforme (mantém pageid quando existir)."""
    u = html.escape(it["url"])
    img_credito = ""
    if it.get("imagem") and it["imagem"].get("arquivo"):
        link = f"https://{urlsplit(it['url']).netloc}/wiki/File:" + it["imagem"]["arquivo"].replace(" ", "_")
        img_credito = f' Imagem: <a href="{html.escape(link)}">página do arquivo</a> (Wikimedia).'
    licenca = " (CC BY-SA 4.0)." if it.get("wikipedia") else ""
    return {**it, "fonte_id": "editor", "rotulo": _rotulo(it["fonte"], it.get("data")),
            "titulo_toc": f'{it["fonte"]}: {it["titulo"]}',
            "imagem": it.get("imagem"), "nota": it.get("nota", ""),
            "credito": f'Fonte: {html.escape(it["fonte"])} — <a href="{u}">{u}</a>{licenca}{img_credito}'}
