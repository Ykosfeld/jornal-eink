"""Item uniforme: adaptadores na borda de cada coletor (Wikipédia, notícias/DW, Escolha do editor).

Contrato (campos que o builder usa):
    fonte_id   id da fonte de origem (tema, 'noticias', 'dw', 'editor', 'almanaque'): agrupa nas seções
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

_DIAS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo")


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
            "nota": art.get("nota", ""), "pageid": art["pageid"]}


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


def item_almanaque(alm):
    """Transforma a estrutura do coletor em um único item uniforme do capítulo."""
    partes = []
    legenda = alm.get("legenda")
    if legenda and legenda.get("texto"):
        lang = str(legenda.get("lang") or "pt")
        texto = html.escape(legenda["texto"])
        if lang != "pt":
            texto = f'<span lang="{html.escape(lang, quote=True)}">{texto}</span>'
        partes.append(
            f'<p class="legenda">Imagem de {html.escape(legenda["dia"])}: '
            f'{texto}</p>'
        )

    surpresa = alm.get("surpresa")
    if surpresa:
        partes.append("<h2>Surpresa da semana</h2>")
        evento = f'{html.escape(surpresa["ano"])} — {html.escape(surpresa["texto"])}'
        if surpresa.get("url"):
            evento = f'<a href="{html.escape(surpresa["url"], quote=True)}">{evento}</a>'
        partes.append(f"<p>{evento}</p>")
        if surpresa.get("descricao"):
            partes.append(f"<p>{html.escape(surpresa['descricao'])}</p>")

    partes.append("<h2>Dia a dia</h2>")
    for dia in alm.get("dias", []):
        data = dia["data"]
        partes.append(
            f'<h3 class="dia">{html.escape(dia["nome"].capitalize())}, {data.day}</h3>'
        )
        linhas = []
        for categoria in ("evento", "birth", "death"):
            linha = dia["linhas"].get(categoria)
            if not linha:
                continue
            texto = f'{html.escape(linha["ano"])} — {html.escape(linha["texto"])}'
            if linha.get("url"):
                texto = f'<a href="{html.escape(linha["url"], quote=True)}">{texto}</a>'
            linhas.append(f"<li>{texto}</li>")
        if linhas:
            partes.append("<ul>" + "".join(linhas) + "</ul>")

    if alm.get("feriados"):
        partes.append("<h2>Feriados e datas</h2><ul>")
        for feriado in alm["feriados"]:
            data = feriado["data"]
            partes.append(
                f'<li>{data.day}/{data.month} · {html.escape(feriado["texto"])}</li>'
            )
        partes.append("</ul>")

    if alm.get("destaques"):
        partes.append("<h2>Em destaque na Wikipédia em inglês</h2>")
        for destaque in alm["destaques"]:
            chamada = html.escape(destaque.get("chamada", ""))
            temas = destaque.get("temas") or []
            estilo = "<b>" if temas else "<i>"
            chamada_html = f"{estilo}{chamada}{'</b>' if temas else '</i>'}"
            titulo = html.escape(destaque["titulo"])
            link = html.escape(destaque["url"], quote=True)
            titulo_html = f'<a href="{link}"><span lang="en">{titulo}</span></a>'
            if temas:
                titulo_html = f"<b>{titulo_html}</b>"
            descricao = html.escape(destaque.get("descricao", ""))
            trecho = (f" — <span lang=\"en\">{descricao}</span>" if descricao else "")
            data = destaque["data"]
            partes.append(
                f'<p>{chamada_html} <small>[EN]</small><br/>{titulo_html}{trecho} '
                f'<small>{_DIAS[data.weekday()]}, {data.day}</small>'
            )
            if temas:
                partes.append(
                    f'<br/><i>Combina com {html.escape(", ".join(temas))}.</i>'
                )
            if destaque.get("url_pt"):
                url_pt = html.escape(destaque["url_pt"], quote=True)
                partes.append(f'<br/><small>Há <a href="{url_pt}">versão em português</a>.</small>')
            partes.append("</p>")

    if alm.get("dyk"):
        partes.append("<h2>Você sabia?</h2><ul>")
        partes.extend(f"<li>{html.escape(texto)}</li>" for texto in alm["dyk"])
        partes.append("</ul>")

    credito_imagem = ""
    if alm.get("credito_imagem"):
        url = html.escape(alm["credito_imagem"], quote=True)
        credito_imagem = f' Imagem: <a href="{url}">página do arquivo</a> (Wikimedia).'
    credito = ("Fonte: Wikipédia em português e inglês (CC BY-SA 4.0)." + credito_imagem)
    return {
        "fonte_id": "almanaque",
        "fonte": "Wikipédia",
        "rotulo": "Almanaque",
        "titulo": alm["titulo"],
        "titulo_toc": alm["titulo"],
        "url": "https://pt.wikipedia.org/",
        "html": "".join(partes),
        "lang": "pt",
        "data": "",
        "imagem": alm.get("imagem"),
        "credito": credito,
        "nota": "",
    }
