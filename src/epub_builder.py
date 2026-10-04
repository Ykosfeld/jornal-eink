"""Montagem do .epub (capa, seções, capítulos, TOC, spine). Não conhece fontes nem config de fontes."""
import html
import tempfile

from ebooklib import epub

from .capa import gerar_capa, html_controle
from .leitura import minutos_de_leitura, validar_config as validar_leitura_config
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
.divisoria { page-break-before: always; text-align: center; margin: 8em 1em; padding: 2em 0; }
.divisoria h1 { font-size: 1.8em; }
.divisoria p { text-align: center; }
.legenda { font-style: italic; }
.dia { margin-top: 1.2em; }
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


def _corpo_item(it, n, livro=None):
    """Um capítulo a partir de um item uniforme (ver src/itens.py). `n` = contador global."""
    nota = (f'<p class="nota">Nota do editor: <i>{html.escape(it["nota"])}</i></p>'
            if it.get("nota") else "")
    img_html = ""
    if it.get("imagem") and livro is not None:
        nome_img = f"img/item_{n:03d}.jpg"
        livro.add_item(epub.EpubItem(uid=f"img_item_{n:03d}", file_name=nome_img,
                                     media_type="image/jpeg", content=it["imagem"]["bytes"]))
        img_html = (f'<p class="imagem"><img src="{nome_img}" '
                    f'alt="{html.escape(it["titulo"], quote=True)}"/></p>')
    return (f'<p class="tema">{html.escape(it["rotulo"])}</p><h1>{html.escape(it["titulo"])}</h1>'
             f'{nota}{img_html}{it["html"]}<p class="fonte">{it["credito"]}</p>')


def _capitulo_item(livro, css, it, n):
    corpo = _corpo_item(it, n, livro)
    c = capitulo(f"item_{n:03d}.xhtml", it["titulo_toc"], corpo, css, it["lang"])
    livro.add_item(c)
    return c


def _divisoria(livro, css, secao, numero, tempos):
    total = sum(tempos)
    if secao["itens"]:
        corpo = (f'<div class="divisoria"><h1>{html.escape(secao["nome"])}</h1>'
                 f'<p>{len(secao["itens"])} matéria(s) · ~{total} min</p></div>')
    else:
        corpo = html_secao_vazia(secao)
    c = capitulo(f"secao_{numero:02d}.xhtml", secao["nome"], corpo, css)
    livro.add_item(c)
    return c


def _sumario(livro, css, cfg, data, numero_edicao, entradas, total):
    horas, minutos = divmod(total, 60)
    leitura = f"{minutos} min" if not horas else f"{horas} h {minutos:02d} min"
    linhas = [
        f"<h1>Nesta edição</h1>",
        f"<p>{html.escape(cfg['titulo'])} · {data.strftime('%d/%m/%Y')}"
        + (f" · Nº {numero_edicao}" if numero_edicao is not None else "") + "</p>",
        f"<p>Cerca de {leitura} de leitura</p>",
    ]
    for nome, itens in entradas:
        linhas.append(f"<h2>{html.escape(nome)}</h2><ul>")
        for it, arquivo, minutos in itens:
            linhas.append(
                f'<li><a href="{arquivo}">{html.escape(it["titulo"])}</a> — '
                f'{html.escape(it["fonte"])} · ~{minutos} min</li>'
            )
        linhas.append("</ul>")
    c = capitulo("sumario.xhtml", "Nesta edição", "".join(linhas), css)
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

    validar_leitura_config(cfg.get("leitura"))
    sumario_cfg = {"ativar": True, **(cfg.get("sumario") or {})}
    if not isinstance(sumario_cfg["ativar"], bool):
        raise ValueError("sumario.ativar deve ser booleano")
    divisorias_cfg = {"ativar": True, "minimo_itens": 1, **(cfg.get("divisorias") or {})}
    if not isinstance(divisorias_cfg["ativar"], bool):
        raise ValueError("divisorias.ativar deve ser booleano")
    if (isinstance(divisorias_cfg["minimo_itens"], bool)
            or not isinstance(divisorias_cfg["minimo_itens"], int)
            or divisorias_cfg["minimo_itens"] < 0):
        raise ValueError("divisorias.minimo_itens deve ser um inteiro >= 0")
    cpm = validar_leitura_config(cfg.get("leitura"))

    planos, n = [], 0
    for secao in secoes:
        entradas, tempos = [], []
        for it in secao["itens"]:
            n += 1
            minutos = minutos_de_leitura(_corpo_item(it, n), cpm)
            entradas.append((it, f"item_{n:03d}.xhtml", minutos))
            tempos.append(minutos)
        planos.append((secao, entradas, tempos))

    total_leitura = sum(minutos for _, entradas, _ in planos for _, _, minutos in entradas)
    sumario = None
    if sumario_cfg["ativar"]:
        sumario = _sumario(
            livro, css, cfg, data, numero_edicao,
            [(s["nome"], entradas) for s, entradas, _ in planos if entradas],
            total_leitura,
        )

    grupos, n, vazias = [], 0, 0
    for indice, (s, entradas, tempos) in enumerate(planos, 1):
        usar_divisoria = (
            divisorias_cfg["ativar"] and s.get("divisoria") is not False
            and (not s["itens"] or len(s["itens"]) >= divisorias_cfg["minimo_itens"])
        )
        divisor = _divisoria(livro, css, s, indice, tempos) if usar_divisoria else None
        if s["itens"]:
            caps = []
            for it, _, _ in entradas:
                n += 1
                caps.append(_capitulo_item(livro, css, it, n))
        else:
            if divisor is not None:
                caps = [divisor]
            else:
                vazias += 1
                c = capitulo(f"vazia_{vazias:02d}.xhtml", "Sem itens nesta edição",
                             html_secao_vazia(s), css)
                livro.add_item(c)
                caps = [c]
        grupos.append((s["nome"], caps, divisor))

    # Última página: dados de controle da capa (semente, níveis...) + estrutura da edição.
    controle = capitulo("controle.xhtml", "Nota de controle",
                        html_controle(info_capa, list(curiosidades)) + html_estrutura(secoes), css)
    livro.add_item(controle)

    livro.toc = [capa]
    if sumario is not None:
        livro.toc.append(sumario)
    livro.toc += [
        (epub.Section(nome, href=divisor.file_name if divisor else None), cs)
        for nome, cs, divisor in grupos
    ] + [controle]
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = [capa]
    if sumario is not None:
        livro.spine.append(sumario)
    livro.spine += [("nav", "no")] + [c for _, cs, _ in grupos for c in cs] + [controle]

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destino.parent) as pasta_tmp:
        temporario = destino.parent / pasta_tmp / destino.name
        epub.write_epub(str(temporario), livro)
        temporario.replace(destino)
    return info_capa