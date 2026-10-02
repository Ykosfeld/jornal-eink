"""Coleta e seleção de conteúdo da Wikipédia para o capítulo semanal Almanaque.

O feed observado pode declarar uma miniatura de 640 px cuja URL contém `960px-`;
as dimensões declaradas governam o filtro e a URL é mantida para a imagem do dia.
"""
import random
import re
import unicodedata
from datetime import timedelta
from urllib.parse import quote, unquote, urlsplit

import requests

from .wikipedia import preparar_imagem

_DIAS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo")
_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
          "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
_TOM_VETADO = re.compile(
    r"\b(?:guerra|batalha|massacr\w*|atentado|genocidio|execu\w+|epidemia|pandemia|"
    r"mat(?:a|am|ando|ou|aram)|mort(?:o|os|e|es)|assassin\w+|bomba\w*|bombardeio|"
    r"terror\w*|ataque\w*|invas\w+|golpe|ditadur\w+|tortur\w+|prisioneir\w+|"
    r"vitima\w*|desastre|naufrag\w+|acident\w+|incendio|explosao|sequestr\w+|"
    r"exterminio|holocausto|escravid\w+|fome|chacina)\b"
)
_POSITIVO = re.compile(
    r"\b(?:estreia|estreou|primeira|primeiro|inaugura\w*|lancamento|lanca\w*|"
    r"descobr\w+|invent\w+|publica\w*|fundad\w+|transmiss\w+)\b"
)
_GENERICOS = (
    "futebolista", "jogador de futebol", "politico", "deputado", "vereador",
    "prefeito", "candidato", "pastor", "apresentador", "influenciador",
)
_IMAGEM_INADEQUADA = re.compile(
    r"\b(?:escudo|brasao|logo|logotipo|bandeira|flag|mapa|map|coat|emblem|seal|icon|symbol)\b"
)


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").casefold())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _regex_termo(termo):
    partes = [re.escape(parte) for parte in normalizar(termo).split()]
    if not partes:
        return re.compile(r"(?!)")
    return re.compile(r"\b" + r"\s+".join(partes) + r"\b")


def temas_encontrados(texto, palavras_chave):
    normalizado = normalizar(texto)
    encontrados = []
    for tema, palavras in palavras_chave.items():
        if any(_regex_termo(palavra).search(normalizado) for palavra in palavras):
            encontrados.append(tema)
    return encontrados


def evento_tem_tom_leve(texto):
    return _TOM_VETADO.search(normalizar(texto)) is None


def _paginas(item):
    paginas = item.get("pages")
    return paginas if isinstance(paginas, list) else []


def _mapa(valor):
    return valor if isinstance(valor, dict) else {}


def _identidades(item):
    identidades = set()
    paginas = [p for p in _paginas(item) if isinstance(p, dict)]
    if paginas:
        pagina = paginas[0]
        canonical = _mapa(pagina.get("titles")).get("canonical")
        pageid = pagina.get("pageid")
        if canonical:
            identidades.add(f"titulo:{str(canonical).casefold()}")
        if pageid is not None:
            identidades.add(f"pageid:{pageid}")
    if item.get("pageid") is not None:
        identidades.add(f"pageid:{item['pageid']}")
    if not identidades and item.get("text"):
        identidades.add(f"texto:{normalizar(item['text'])}")
    return identidades


def _pagina_relevante(item, palavras_chave):
    paginas = [pagina for pagina in _paginas(item) if isinstance(pagina, dict)]
    if not paginas:
        return {}

    texto_item = normalizar(item.get("text", ""))

    def titulo(pagina):
        return str(pagina.get("title") or "").replace("_", " ")

    def pagina_util(pagina):
        nome = normalizar(titulo(pagina)).strip()
        descricao = normalizar(pagina.get("description", "")).strip()
        return not (re.fullmatch(r"\d{1,4}", nome) or descricao in {"ano", "year"})

    paginas_uteis = [pagina for pagina in paginas if pagina_util(pagina)]
    if not paginas_uteis:
        return {}

    citadas = [
        pagina for pagina in paginas_uteis
        if titulo(pagina) and _regex_termo(titulo(pagina)).search(texto_item)
    ]
    if citadas:
        return max(citadas, key=lambda pagina: len(titulo(pagina)))

    def pontuacao(pagina):
        texto = " ".join(str(pagina.get(chave) or "")
                         for chave in ("title", "description", "extract"))
        return (
            len(temas_encontrados(texto, palavras_chave)),
            bool(pagina.get("description")),
            len(titulo(pagina)),
        )

    return max(paginas_uteis, key=pontuacao)


def _peso(item, palavras_chave, tipo="evento", penalizadas=_GENERICOS):
    pagina = _pagina_relevante(item, palavras_chave)
    texto = " ".join(str(valor or "") for valor in (
        item.get("text"), pagina.get("title"), pagina.get("description"), pagina.get("extract")
    ))
    temas = temas_encontrados(texto, palavras_chave)
    peso = 1 + 3 * len(temas)
    normalizado = normalizar(texto)
    if tipo == "evento" and _POSITIVO.search(normalizado):
        peso += 2
    if tipo == "nascimento" and any(_regex_termo(p).search(normalizado) for p in penalizadas):
        peso = max(0.3, min(peso, 0.3))
    return peso


def _url_pagina(pagina, idioma="pt"):
    url = _mapa(_mapa(pagina.get("content_urls")).get("desktop")).get("page")
    partes = urlsplit(url) if isinstance(url, str) else None
    return url if (partes and partes.scheme == "https"
                   and partes.hostname == f"{idioma}.wikipedia.org") else ""


def _escolher_pagina(item, palavras_chave):
    pagina = _pagina_relevante(item, palavras_chave)
    return {
        "titulo": str(pagina.get("title") or ""),
        "descricao": str(pagina.get("description") or ""),
        "extract": str(pagina.get("extract") or ""),
        "url": _url_pagina(pagina),
        "lang": pagina.get("lang", "pt"),
    }


def _chave_evento(item):
    identidades = _identidades(item)
    if identidades:
        return tuple(sorted(identidades)) + (str(item.get("year", "")),)
    return ("texto:" + normalizar(item.get("text", "")), item.get("year"))


def _candidatos_evento(dia):
    vistos, saida = set(), []
    selected = dia.get("selected")
    events = dia.get("events")
    selected = selected if isinstance(selected, list) else []
    events = events if isinstance(events, list) else []
    for item in selected + events:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"]:
            continue
        chave = _chave_evento(item)
        if chave in vistos:
            continue
        vistos.add(chave)
        if evento_tem_tom_leve(item["text"]):
            saida.append(item)
    return saida


def _escolher_ponderado(itens, pesos, rng):
    return rng.choices(itens, weights=pesos, k=1)[0] if itens else None


def formatar_ano(ano):
    try:
        ano = int(ano)
    except (TypeError, ValueError):
        return ""
    return f"{abs(ano)} a.C." if ano <= 0 else str(ano)


def _peso_feriado(texto):
    normalizado = normalizar(texto)
    if normalizado.startswith(("dia mundial", "dia internacional")):
        return 5
    if normalizado.startswith(("dia nacional", "dia do ", "dia da ")):
        return 2
    return 1


def _dia_semana(data):
    return _DIAS[data.weekday()]


def _janela_texto(inicio, fim):
    if inicio.month == fim.month and inicio.year == fim.year:
        return f"{inicio.day} a {fim.day} de {_MESES[fim.month - 1]}"
    return (f"{inicio.day} de {_MESES[inicio.month - 1]} a "
            f"{fim.day} de {_MESES[fim.month - 1]}")


def _feriados(dados_dia, inicio, cfg, rng):
    fcfg = cfg.get("feriados") or {}
    quantidade = max(0, int(fcfg.get("quantidade", 5)))
    ancoras = fcfg.get("ancoras") or {}
    datas = [inicio + timedelta(days=i) for i in range(len(dados_dia))]
    opcoes_ancora = []
    for data in datas:
        nome = ancoras.get(data.strftime("%m-%d"))
        if nome:
            opcoes_ancora.append({"data": data, "texto": str(nome), "peso": 1})
    if len(opcoes_ancora) > 2:
        opcoes_ancora = rng.sample(opcoes_ancora, 2)

    saida = list(opcoes_ancora[:quantidade])
    vistos = {normalizar(x["texto"]) for x in saida}
    candidatos = []
    for data, dia in dados_dia:
        por_dia = []
        feriados_dia = dia.get("holidays")
        if not isinstance(feriados_dia, list):
            continue
        for item in feriados_dia:
            texto = item.get("text", "") if isinstance(item, dict) else str(item)
            normalizado = normalizar(texto)
            if (not texto or len(texto) > 70 or "padroeiro" in normalizado
                    or normalizado.startswith(("feriado em", "feriado municipal",
                                               "aniversario da cidade", "aniversario do municipio"))
                    or normalizado in vistos):
                continue
            peso = _peso_feriado(texto)
            por_dia.append({"data": data, "texto": texto, "peso": peso})
        if por_dia:
            candidatos.extend(por_dia)

    dias_usados = set()
    while candidatos and len(saida) < quantidade:
        elegiveis = [x for x in candidatos if x["data"] not in dias_usados
                     and normalizar(x["texto"]) not in vistos]
        if not elegiveis:
            break
        escolhido = _escolher_ponderado(elegiveis, [x["peso"] for x in elegiveis], rng)
        saida.append(escolhido)
        dias_usados.add(escolhido["data"])
        vistos.add(normalizar(escolhido["texto"]))
        candidatos.remove(escolhido)
    return sorted(saida, key=lambda x: (x["data"], normalizar(x["texto"])))


def _nome_arquivo(url):
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1]).casefold()


def _url_pagina_arquivo(pag, source):
    file_page = pag.get("file_page")
    if isinstance(file_page, str):
        partes = urlsplit(file_page)
        if partes.scheme == "https" and partes.hostname == "commons.wikimedia.org":
            return file_page
    nome = unquote(urlsplit(source).path.rsplit("/", 1)[-1])
    nome = re.sub(r"^\d+px-", "", nome, flags=re.IGNORECASE)
    if nome:
        return "https://commons.wikimedia.org/wiki/File:" + quote(nome, safe="()_,")
    return ""


def _candidatos_imagem(registro, min_tamanho, proporcao_max, feed=False):
    pag = _mapa(registro).get("image") if feed else registro
    if not isinstance(pag, dict):
        return None
    thumb = pag.get("thumbnail")
    if not isinstance(thumb, dict) or not thumb.get("source"):
        return None
    if not isinstance(thumb["source"], str):
        return None
    try:
        partes_url = urlsplit(thumb["source"])
    except ValueError:
        return None
    if (partes_url.scheme != "https"
            or partes_url.hostname not in {"thumb.wikimedia.org", "upload.wikimedia.org"}):
        return None
    try:
        largura, altura = int(thumb.get("width", 0)), int(thumb.get("height", 0))
    except (TypeError, ValueError):
        return None
    if min(largura, altura) < min_tamanho or min(largura, altura) == 0:
        return None
    if max(largura, altura) / min(largura, altura) > proporcao_max:
        return None
    nome = _nome_arquivo(thumb["source"])
    nome_base = re.sub(r"^\d+px-", "", nome)
    titulo = str(pag.get("title") or "")
    titulo_normalizado = normalizar(titulo.rsplit(":", 1)[-1]).rsplit(".", 1)[0]
    nome_inadequado = re.match(
        r"^(?:escudo|brasao|logo|logotipo|bandeira|flag|mapa|coat|emblem|seal|icon|symbol)",
        normalizar(nome_base).rsplit(".", 1)[0],
    )
    titulo_inadequado = re.match(
        r"^(?:escudo|brasao|logo|logotipo|bandeira|flag|mapa|coat|emblem|seal|icon|symbol)",
        titulo_normalizado,
    )
    if (nome.endswith(".svg") or normalizar(titulo).endswith(".svg")
            or titulo_inadequado or nome_inadequado
            or _IMAGEM_INADEQUADA.search(normalizar(titulo + " " + nome))):
        return None
    if not nome.endswith((".jpg", ".jpeg", ".png")):
        return None
    descricao = pag.get("description")
    if isinstance(descricao, dict):
        legenda = str(descricao.get("text") or "")
        lang = str(descricao.get("lang") or "pt")
    else:
        legenda = str(descricao or "")
        lang = "pt"
    return {
        "title": titulo,
        "url": thumb["source"],
        "largura": largura,
        "original_largura": _mapa(pag.get("originalimage")).get("width"),
        "descricao": legenda,
        "lang": lang,
        "file_page": _url_pagina_arquivo(pag, thumb["source"]),
        "peso": 1,
        "extensao": ".jpeg" if nome.endswith((".jpg", ".jpeg")) else ".png",
    }


def _baixar_imagem(sessao, candidata, icfg, tentar_500=False):
    urls = [candidata["url"]]
    try:
        original_largura = int(candidata.get("original_largura") or 0)
    except (TypeError, ValueError):
        original_largura = 0
    if tentar_500 and (not original_largura or original_largura >= 500):
        url_500 = re.sub(r"/\d+px-", "/500px-", candidata["url"], count=1)
        if url_500 != candidata["url"]:
            urls.insert(0, url_500)
    for url in urls:
        try:
            resposta = sessao.get(url, timeout=30)
            resposta.raise_for_status()
            return preparar_imagem(resposta.content, icfg)
        except Exception as erro:  # noqa: BLE001 — a imagem é opcional para o capítulo
            print(f"[Almanaque] não foi possível processar imagem ({url}): {erro}")
    return None


def _tfa_tematicos(tfa, data, palavras_en):
    texto = " ".join(str(tfa.get(chave) or "")
                     for chave in ("title", "description", "extract"))
    contagens = {
        tema: sum(bool(_regex_termo(p).search(normalizar(texto))) for p in palavras)
        for tema, palavras in palavras_en.items()
    }
    maior = max(contagens.values(), default=0)
    temas = [tema for tema, quantidade in contagens.items() if quantidade == maior and maior]
    url = _mapa(_mapa(tfa.get("content_urls")).get("desktop")).get("page", "")
    if not isinstance(url, str):
        return None
    partes_url = urlsplit(url)
    if partes_url.scheme != "https" or partes_url.hostname != "en.wikipedia.org":
        return None
    canonical = _mapa(tfa.get("titles")).get("canonical") or tfa.get("title")
    titulo = str(tfa.get("title") or canonical or "")
    if not canonical or not titulo:
        return None
    return {
        "canonical": canonical,
        "titulo": titulo,
        "descricao": str(tfa.get("description") or ""),
        "url": url,
        "data": data,
        "temas": temas,
        "url_pt": "",
    }


def _verificar_versao_pt(sessao, destaque):
    try:
        resposta = sessao.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "prop": "langlinks", "lllang": "pt",
                    "titles": destaque["canonical"], "format": "json", "formatversion": 2},
            timeout=30,
        )
        resposta.raise_for_status()
        dados = resposta.json()
        if not isinstance(dados, dict):
            raise ValueError("resposta não é um objeto JSON")
    except (requests.RequestException, ValueError) as erro:
        print(f"[Almanaque] falha ao consultar versão em português de "
              f"{destaque['canonical']}: {erro}")
        return
    paginas = _mapa(dados.get("query")).get("pages", [])
    if not isinstance(paginas, list):
        print(f"[Almanaque] resposta de langlinks inválida para {destaque['canonical']}")
        return
    langlinks = _mapa(paginas[0]).get("langlinks") if paginas else None
    if isinstance(langlinks, list) and langlinks and isinstance(langlinks[0], dict):
        titulo_pt = langlinks[0].get("title")
        if isinstance(titulo_pt, str) and titulo_pt:
            destaque["url_pt"] = "https://pt.wikipedia.org/wiki/" + quote(
                titulo_pt.replace(" ", "_"), safe="()_"
            )


def _texto_limpo(texto):
    from bs4 import BeautifulSoup

    return BeautifulSoup(str(texto or ""), "html.parser").get_text(" ", strip=True)


def coletar_almanaque(sessao, cfg, hoje, semente=None):
    """Coleta e seleciona conteúdo da semana; retorna None se nada utilizável foi obtido."""
    acfg = cfg.get("almanaque") or {}
    if not acfg.get("ativar", True):
        return None

    rng = random.Random(f"almanaque|{semente}|{hoje.isoformat()}") if semente is not None else random.Random()
    dias = max(1, int(acfg.get("dias", 7)))
    janela = [hoje + timedelta(days=i) for i in range(dias)]
    dados_pt, destaques_candidatos = [], []
    destaque_cfg = acfg.get("destaque") or {}
    destaque_ativo = destaque_cfg.get("ativar", True)
    idioma = destaque_cfg.get("idioma", "en")

    for data in janela:
        dia = {}
        for etiqueta, url in (
            ("onthisday", f"https://pt.wikipedia.org/api/rest_v1/feed/onthisday/all/{data:%m/%d}"),
            ("featured", f"https://pt.wikipedia.org/api/rest_v1/feed/featured/{data:%Y/%m/%d}"),
        ):
            try:
                resposta = sessao.get(url, timeout=30)
                resposta.raise_for_status()
                conteudo = resposta.json()
                if not isinstance(conteudo, dict):
                    raise ValueError("resposta não é um objeto JSON")
                esperado = {"events", "births", "deaths", "holidays", "selected"} if etiqueta == "onthisday" else {
                    "image", "dyk", "onthisday", "news"
                }
                if not esperado.intersection(conteudo):
                    raise ValueError("blocos esperados ausentes na resposta")
                dia[etiqueta] = conteudo
            except (requests.RequestException, ValueError) as erro:
                print(f"[Almanaque] {data.isoformat()} ({etiqueta}): sem dados ({erro})")
                dia[etiqueta] = {}

        if destaque_ativo:
            url = f"https://{idioma}.wikipedia.org/api/rest_v1/feed/featured/{data:%Y/%m/%d}"
            try:
                resposta = sessao.get(url, timeout=30)
                resposta.raise_for_status()
                resposta_en = resposta.json()
                if not isinstance(resposta_en, dict):
                    raise ValueError("resposta não é um objeto JSON")
                destaque = resposta_en.get("tfa")
                if isinstance(destaque, dict):
                    item = _tfa_tematicos(
                        destaque, data,
                        destaque_cfg.get("palavras_chave_en") or {},
                    )
                    if item:
                        destaques_candidatos.append(item)
            except (requests.RequestException, ValueError) as erro:
                print(f"[Almanaque] {data.isoformat()} (destaque {idioma}): sem dados ({erro})")
        dados_pt.append((data, dia))

    palavras_chave = acfg.get("palavras_chave") or {}
    identidade_usada = set()
    todos_eventos = []
    for data, dia in dados_pt:
        todos_eventos.extend((data, item) for item in _candidatos_evento(dia.get("onthisday") or {}))
    surpresa = _escolher_ponderado(
        [item for _, item in todos_eventos],
        [_peso(item, palavras_chave) for _, item in todos_eventos],
        rng,
    )
    if surpresa:
        identidade_usada.update(_identidades(surpresa))
        pagina = _escolher_pagina(surpresa, palavras_chave)
        surpresa = {
            "ano": formatar_ano(surpresa.get("year")),
            "texto": surpresa.get("text", ""),
            "url": pagina["url"],
            "descricao": pagina["extract"],
            "identidades": _identidades(surpresa),
            "pages": _paginas(surpresa),
        }
        surpresa["descricao"] = _truncar_frase(
            surpresa["descricao"], int(acfg.get("max_caracteres_extrato", 400))
        )

    lista_dias = []
    for data, dia in dados_pt:
        dados = dia.get("onthisday") or {}
        linhas = {}
        eventos = _candidatos_evento(dados)
        eventos = [x for x in eventos if not (_identidades(x) & identidade_usada)]
        evento = _escolher_ponderado(eventos, [_peso(x, palavras_chave) for x in eventos], rng)
        if evento:
            identidade_usada.update(_identidades(evento))
            linhas["evento"] = _linha_item(evento, palavras_chave, "evento")

        for categoria in ("births", "deaths"):
            candidatos = []
            for item in dados.get(categoria) or []:
                if not isinstance(item, dict) or not _paginas(item):
                    continue
                descricao = next(
                    (p.get("description") for p in _paginas(item)
                     if isinstance(p, dict) and p.get("description")),
                    "",
                )
                if not descricao or (_identidades(item) & identidade_usada):
                    continue
                try:
                    ano = int(item.get("year"))
                except (TypeError, ValueError):
                    continue
                if categoria == "deaths" and ano > hoje.year - int(acfg.get("anos_minimos_mortes", 50)):
                    continue
                candidatos.append(item)
            escolhido = _escolher_ponderado(
                candidatos,
                [_peso(x, palavras_chave,
                       "nascimento" if categoria == "births" else "morte",
                       acfg.get("palavras_penalizadas", _GENERICOS)) for x in candidatos],
                rng,
            )
            if escolhido:
                identidade_usada.update(_identidades(escolhido))
                linhas[categoria[:-1]] = _linha_item(escolhido, palavras_chave)
        lista_dias.append({"data": data, "nome": _dia_semana(data), "linhas": linhas})

    feriados = _feriados(
        [(data, dia.get("onthisday") or {}) for data, dia in dados_pt], hoje, acfg, rng
    )

    imagens, imagem_config = [], cfg.get("imagens") or {}
    imagem_ativa = acfg.get("imagem", True) and imagem_config.get("ativar", True)
    if imagem_ativa:
        minimo = int(imagem_config.get("tamanho_min", 150))
        proporcao = float(acfg.get("imagem_proporcao_max", 2.2))
        palavras_imagem = palavras_chave
        for data, dia in dados_pt:
            candidato = _candidatos_imagem(
                (dia.get("featured") or {}).get("image"),
                minimo, proporcao, feed=True,
            )
            if not candidato:
                continue
            candidato["data"] = data
            candidato["peso"] += 3 * len(temas_encontrados(
                candidato["title"] + " " + candidato["descricao"], palavras_imagem
            ))
            imagens.append(candidato)

    imagem = legenda = credito_imagem = None
    icfg = {"ativar": True, "largura_max": 480, "altura_max": 400,
            "qualidade_jpeg": 70, "tamanho_min": 150, **imagem_config}
    imagens_unicas = {}
    for candidato in imagens:
        imagens_unicas.setdefault(candidato["title"] or candidato["url"], candidato)
    imagens = list(imagens_unicas.values())
    imagens_jpg = [x for x in imagens if x["extensao"] in (".jpg", ".jpeg")]
    imagens = imagens_jpg or [x for x in imagens if x["extensao"] == ".png"]
    if imagens:
        escolhido = _escolher_ponderado(imagens, [x["peso"] for x in imagens], rng)
        conteudo_imagem = _baixar_imagem(sessao, escolhido, icfg)
        if conteudo_imagem:
            imagem = {"bytes": conteudo_imagem, "arquivo": escolhido["title"]}
            legenda = {"texto": escolhido["descricao"], "lang": escolhido["lang"],
                       "dia": _dia_semana(escolhido["data"])}
            credito_imagem = escolhido["file_page"]
            if not credito_imagem:
                titulo_arquivo = escolhido["title"].removeprefix("File:")
                credito_imagem = "https://commons.wikimedia.org/wiki/" + requests.utils.quote(
                    titulo_arquivo.replace(" ", "_"), safe="()_"
                )

    if imagem is None and surpresa:
        candidatos = []
        for pagina in surpresa["pages"]:
            candidato = _candidatos_imagem(
                pagina, int(imagem_config.get("tamanho_min", 150)),
                float(acfg.get("imagem_proporcao_max", 2.2)),
            )
            if candidato:
                candidato["peso"] += 3 * len(temas_encontrados(
                    candidato["title"] + " " + pagina.get("description", ""),
                    palavras_chave,
                ))
                candidato["tentar_500"] = True
                candidatos.append(candidato)
        candidatos_jpg = [x for x in candidatos if x["extensao"] in (".jpg", ".jpeg")]
        candidatos = candidatos_jpg or [x for x in candidatos if x["extensao"] == ".png"]
        if candidatos:
            candidato = _escolher_ponderado(candidatos, [x["peso"] for x in candidatos], rng)
            conteudo_imagem = _baixar_imagem(sessao, candidato, icfg, tentar_500=True)
            if conteudo_imagem:
                imagem = {"bytes": conteudo_imagem, "arquivo": candidato["title"]}
                legenda = {"texto": candidato["descricao"], "lang": "pt",
                           "dia": _dia_semana(hoje)}
                credito_imagem = candidato["file_page"] or candidato["url"]

    max_destaques = max(0, int(destaque_cfg.get("maximo", 3)))
    dedup = {}
    for item in destaques_candidatos:
        dedup.setdefault(item["canonical"], item)
    destaques_candidatos = list(dedup.values())
    tematicos = [x for x in destaques_candidatos if x["temas"]]
    outros = [x for x in destaques_candidatos if not x["temas"]]
    rng.shuffle(tematicos)
    rng.shuffle(outros)
    destaques = (tematicos + outros)[:max_destaques]
    destaques.sort(key=lambda x: x["data"])
    if destaque_cfg.get("verificar_pt"):
        for item in destaques:
            _verificar_versao_pt(sessao, item)
    for item in destaques:
        if item["temas"]:
            print(f'Escolha do Editor: {item["url"]} | destaque da semana')

    chamadas, chamadas_tema = list(destaque_cfg.get("chamadas") or []), list(
        destaque_cfg.get("chamadas_tema") or []
    )
    rng.shuffle(chamadas)
    rng.shuffle(chamadas_tema)
    usados_chamadas = set()
    for item in destaques:
        disponiveis = chamadas_tema if item["temas"] else chamadas
        chamada = next((c for c in disponiveis if c not in usados_chamadas), "")
        if chamada:
            usados_chamadas.add(chamada)
        item["chamada"] = chamada

    dyk = []
    vistos_dyk = set()
    textos_usados = set()
    if surpresa:
        textos_usados.add(normalizar(surpresa["texto"]))
    textos_usados.update(
        normalizar(linha.get("texto", ""))
        for dia in lista_dias for linha in dia["linhas"].values()
    )
    textos_usados.update(normalizar(item["texto"]) for item in feriados)
    textos_usados.update(normalizar(item["titulo"]) for item in destaques)
    for _, dia in dados_pt:
        itens_dyk = (dia.get("featured") or {}).get("dyk") or []
        if not isinstance(itens_dyk, list):
            continue
        for item in itens_dyk:
            if not isinstance(item, dict):
                continue
            texto = item.get("text") or _texto_limpo(item.get("html"))
            chave = normalizar(texto)
            if texto and chave not in vistos_dyk and chave not in textos_usados:
                vistos_dyk.add(chave)
                dyk.append(texto)
    if dyk:
        rng.shuffle(dyk)
        dyk = dyk[:2]

    if not any((imagem, surpresa, feriados, destaques, dyk,
                any(dia["linhas"] for dia in lista_dias))):
        return None

    fim = janela[-1]
    return {
        "inicio": hoje,
        "fim": fim,
        "titulo": f"Almanaque · {_janela_texto(hoje, fim)}",
        "imagem": imagem,
        "legenda": legenda,
        "credito_imagem": credito_imagem,
        "surpresa": surpresa,
        "dias": lista_dias,
        "feriados": feriados,
        "destaques": destaques,
        "dyk": dyk,
    }


def _linha_item(item, palavras_chave, tipo="descricao"):
    pagina = _escolher_pagina(item, palavras_chave)
    texto = str(item.get("text") or "")
    if tipo != "evento" and pagina["titulo"]:
        if not _regex_termo(pagina["titulo"].replace("_", " ")).search(normalizar(texto)):
            texto = f'{pagina["titulo"].replace("_", " ")}, {texto}'.strip(" ,")
    return {
        "ano": formatar_ano(item.get("year")),
        "texto": texto or (pagina["descricao"] if tipo != "evento" else ""),
        "url": pagina["url"],
        "identidades": _identidades(item),
    }


def _truncar_frase(texto, limite):
    texto = " ".join(str(texto or "").split())
    if len(texto) <= limite:
        return texto
    trecho = texto[:limite]
    fim = max(trecho.rfind(". "), trecho.rfind("! "), trecho.rfind("? "))
    return trecho[:fim + 1] if fim >= 0 else trecho.rstrip() + "…"
