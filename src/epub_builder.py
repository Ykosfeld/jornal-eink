"""Montagem do .epub (capa, seções, capítulos, TOC, spine). Não conhece fontes nem config de fontes."""
import html

from ebooklib import epub

from .capa import gerar_capa, html_controle
from .relatorio import html_estrutura, html_secao_vazia

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


def _capitulo_item(livro, css, it, n):
    """Um capítulo a partir de um item uniforme (ver src/itens.py). `n` = contador global."""
    nota = (f'<p class="nota">Nota do editor: <i>{html.escape(it["nota"])}</i></p>'
            if it.get("nota") else "")
    img_html = ""
    if it.get("imagem"):
        nome_img = f"img/item_{n:03d}.jpg"
        livro.add_item(epub.EpubItem(uid=f"img_item_{n:03d}", file_name=nome_img,
                                     media_type="image/jpeg", content=it["imagem"]["bytes"]))
        img_html = (f'<p class="imagem"><img src="{nome_img}" '
                    f'alt="{html.escape(it["titulo"], quote=True)}"/></p>')
    corpo = (f'<p class="tema">{html.escape(it["rotulo"])}</p><h1>{html.escape(it["titulo"])}</h1>'
             f'{nota}{img_html}{it["html"]}<p class="fonte">{it["credito"]}</p>')
    c = capitulo(f"item_{n:03d}.xhtml", it["titulo_toc"], corpo, css, it["lang"])
    livro.add_item(c)
    return c


def montar_epub(cfg, secoes, data, destino, numero_edicao=None, curiosidades=()):
    """Monta o epub. Devolve o `info` da capa (semente, níveis etc.) para log.

    secoes:        resultado de layout.montar_secoes (cada uma com "nome", "itens", "fontes", "ordem")
    curiosidades:  [(tema, titulo, pageid)] dos artigos SORTEADOS da Wikipédia. Só eles alimentam a semente
                   da capa (como antes), então reorganizar seções não muda o desenho.
    """
    livro = epub.EpubBook()
    livro.set_identifier(f"jornal-{data.isoformat()}")
    livro.set_title(f"{cfg['titulo']} — {data.strftime('%d/%m/%Y')}")
    livro.set_language(cfg["idioma"])
    livro.add_author(cfg["autor"])

    css = epub.EpubItem(uid="estilo", file_name="estilo.css", media_type="text/css", content=CSS)
    livro.add_item(css)

    png_capa, info_capa = gerar_capa(cfg["titulo"], data, [p for _, _, p in curiosidades], numero_edicao)
    livro.set_cover("capa.png", png_capa, create_page=False)   # capa dos metadados (biblioteca do X4)
    capa = capitulo("capa.xhtml", "Capa",
                    f'<div class="capa"><img src="capa.png" alt="{html.escape(cfg["titulo"], quote=True)}"/></div>',
                    css)
    livro.add_item(capa)

    grupos, n, vazias = [], 0, 0
    for s in secoes:
        if s["itens"]:
            caps = []
            for it in s["itens"]:
                n += 1
                caps.append(_capitulo_item(livro, css, it, n))
        else:
            vazias += 1
            c = capitulo(f"vazia_{vazias:02d}.xhtml", "Sem itens nesta edição", html_secao_vazia(s), css)
            livro.add_item(c)
            caps = [c]
        grupos.append((s["nome"], caps))

    # Última página: dados de controle da capa (semente, níveis...) + estrutura da edição.
    controle = capitulo("controle.xhtml", "Nota de controle",
                        html_controle(info_capa, list(curiosidades)) + html_estrutura(secoes), css)
    livro.add_item(controle)

    livro.toc = [capa] + [(epub.Section(nome), cs) for nome, cs in grupos] + [controle]
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = [capa, "nav"] + [c for _, cs in grupos for c in cs] + [controle]

    destino.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(destino), livro)
    return info_capa