"""Montagem do .epub (capa, capítulos, TOC, spine)."""
import html
from urllib.parse import urlsplit

from ebooklib import epub

from .capa import gerar_capa, html_controle

CSS = """
body { font-family: serif; line-height: 1.4; margin: 0 0.5em; }
h1 { font-size: 1.5em; margin: 0.6em 0 0.2em; }
h2 { font-size: 1.2em; margin-top: 1.2em; }
h3 { font-size: 1.05em; }
p { text-align: justify; margin: 0.5em 0; }
.tema { font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.08em; }
.nota { font-style: italic; text-align: left; border-left: 2px solid #000; padding-left: 0.6em; margin: 0.8em 0; }
.fonte { font-size: 0.8em; margin-top: 2em; border-top: 1px solid #000; padding-top: 0.5em; }
img { max-width: 100%; height: auto; }
.imagem { text-align: center; margin: 0.6em 0; }
.capa { text-align: center; margin: 0; padding: 0; }
.capa img { width: 100%; height: auto; max-height: 100%; }
table { font-size: 0.85em; border-collapse: collapse; margin: 0.8em 0; }
td { padding: 0.2em 1em 0.2em 0; vertical-align: top; }
small { font-size: 0.8em; }
math { font-size: 1em; }
"""


def capitulo(arquivo, titulo, corpo, css, lang="pt"):
    c = epub.EpubHtml(title=titulo, file_name=arquivo, lang=lang)
    c.content = f"<html><body>{corpo}</body></html>"
    if "<math" in corpo:
        c.properties.append("mathml")
    c.add_item(css)
    return c


def _capitulos_externos(livro, css, prefixo, itens):
    """Capítulos de notícias e DW (itens vindos de feeds.py)."""
    caps = []
    for i, it in enumerate(itens, 1):
        u = html.escape(it["url"])
        rotulo = html.escape(it["fonte"]) + (f' · {it["data"]}' if it["data"] else "")
        corpo = (f'<p class="tema">{rotulo}</p><h1>{html.escape(it["titulo"])}</h1>{it["html"]}'
                 f'<p class="fonte">Fonte: <a href="{u}">{u}</a></p>')
        c = capitulo(f"{prefixo}_{i:02d}.xhtml", f'{it["fonte"]}: {it["titulo"]}', corpo, css, it["lang"])
        livro.add_item(c)
        caps.append(c)
    return caps


def _capitulos_escolha(livro, css, itens):
    """Escolha do Editor (itens de escolha.py): Wikipédia (com imagem) ou qualquer site, nota opcional."""
    caps = []
    for i, it in enumerate(itens, 1):
        u = html.escape(it["url"])
        rotulo = html.escape(it["fonte"]) + (f' · {it["data"]}' if it.get("data") else "")
        nota = (f'<p class="nota">Nota do editor: <i>{html.escape(it["nota"])}</i></p>'
                if it.get("nota") else "")
        img_html, img_credito = "", ""
        if it.get("imagem"):
            nome_img = f"img/esc_{i:02d}.jpg"
            livro.add_item(epub.EpubItem(uid=f"img_esc_{i:02d}", file_name=nome_img,
                                         media_type="image/jpeg", content=it["imagem"]["bytes"]))
            img_html = (f'<p class="imagem"><img src="{nome_img}" '
                        f'alt="{html.escape(it["titulo"], quote=True)}"/></p>')
            arq = it["imagem"]["arquivo"]
            if arq:
                link = f"https://{urlsplit(it['url']).netloc}/wiki/File:" + arq.replace(" ", "_")
                img_credito = f' Imagem: <a href="{html.escape(link)}">página do arquivo</a> (Wikimedia).'
        licenca = " (CC BY-SA 4.0)." if it.get("wikipedia") else ""
        corpo = (f'<p class="tema">{rotulo}</p><h1>{html.escape(it["titulo"])}</h1>{nota}{img_html}{it["html"]}'
                 f'<p class="fonte">Fonte: {html.escape(it["fonte"])} — <a href="{u}">{u}</a>'
                 f'{licenca}{img_credito}</p>')
        c = capitulo(f"esc_{i:02d}.xhtml", f'{it["fonte"]}: {it["titulo"]}', corpo, css, it["lang"])
        livro.add_item(c)
        caps.append(c)
    return caps


def _capitulos_wikipedia(livro, css, artigos):
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
    return caps


def montar_epub(cfg, artigos, data, destino, numero_edicao=None, noticias=(), dw=(), escolhas=()):
    """Monta o epub. Devolve o `info` da capa (semente, níveis etc.) para log."""
    livro = epub.EpubBook()
    livro.set_identifier(f"jornal-{data.isoformat()}")
    livro.set_title(f"{cfg['titulo']} — {data.strftime('%d/%m/%Y')}")
    livro.set_language(cfg["idioma"])
    livro.add_author(cfg["autor"])

    css = epub.EpubItem(uid="estilo", file_name="estilo.css", media_type="text/css", content=CSS)
    livro.add_item(css)

    # Capa generativa: a semente sai dos pageids dos artigos da Wikipedia + data.
    # (Escolha do editor, notícias e DW não entram: mudariam o desenho se a coleta variasse.)
    png_capa, info_capa = gerar_capa(cfg["titulo"], data, [a["pageid"] for _, a in artigos], numero_edicao)
    livro.set_cover("capa.png", png_capa, create_page=False)   # capa dos metadados (biblioteca do X4)
    capa = capitulo("capa.xhtml", "Capa",
                    f'<div class="capa"><img src="capa.png" alt="{html.escape(cfg["titulo"], quote=True)}"/></div>',
                    css)
    livro.add_item(capa)

    caps_esc = _capitulos_escolha(livro, css, escolhas)
    caps_not = _capitulos_externos(livro, css, "not", noticias)
    caps_wiki = _capitulos_wikipedia(livro, css, artigos)
    caps_dw = _capitulos_externos(livro, css, "dw", dw)

    # Última página: dados de controle da capa (semente, níveis...) só para curiosidade/depuração.
    controle = capitulo("controle.xhtml", "Nota de controle",
                        html_controle(info_capa, [(t, a["titulo"], a["pageid"]) for t, a in artigos]),
                        css)
    livro.add_item(controle)

    grupos = [("Escolha do Editor", caps_esc), ("Notícias", caps_not),
              ("Curiosidades", caps_wiki), ("Deutsch üben", caps_dw)]
    livro.toc = [capa] + [(epub.Section(nome), cs) for nome, cs in grupos if cs] + [controle]
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = [capa, "nav"] + [c for _, cs in grupos for c in cs] + [controle]

    destino.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(destino), livro)
    return info_capa