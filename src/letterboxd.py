"""Prioriza artigos de Cinema a partir do RSS pessoal do Letterboxd."""
import datetime as dt
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .wikipedia import api, artigo_aceitavel, buscar_artigo

logger = logging.getLogger(__name__)

PADRAO = {
    "ativar": False,
    "feed_url": "",
    "janela_dias": 7,
    "max_filmes": 7,
    "max_creditos_por_filme": 5,
}

_CREDITOS = {
    "direcao", "diretor", "diretora", "realizacao", "realizado por",
    "roteiro", "roteirista", "argumento", "screenplay", "written by",
    "elenco", "estrelando", "protagonistas", "cast", "starring",
    "musica", "trilha sonora", "compositor", "compositora", "music",
    "music by",
}
_ROTULOS_FILME = _CREDITOS | {
    "lancamento", "data de lancamento", "data de estreia", "estreia",
    "release date", "ano", "year", "genero",
}
_ROTULOS_ANO = {"lancamento", "data de lancamento", "data de estreia",
                "estreia", "release date", "ano", "year"}
_ROTULOS_TITULO = {"titulo", "titulo original", "nome original", "original title"}


def validar_config(cfg):
    """Valida opções Letterboxd e devolve a configuração com padrões."""
    resultado = {**PADRAO, **(cfg or {})}
    url = resultado["feed_url"]
    if not isinstance(url, str):
        raise ValueError("personalizacao_cultural.letterboxd.feed_url deve ser texto")
    if resultado["ativar"]:
        partes = urlsplit(url)
        if partes.scheme not in {"http", "https"} or not partes.netloc:
            raise ValueError("feed_url do Letterboxd deve ser uma URL HTTP(S) válida")
    for chave in ("janela_dias", "max_filmes", "max_creditos_por_filme"):
        valor = resultado[chave]
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            raise ValueError(f"letterboxd.{chave} deve ser um inteiro positivo")
    return resultado


def _filho(elemento, nome):
    for filho in elemento:
        if filho.tag.rsplit("}", 1)[-1] == nome:
            return filho.text
    return None


def _chave_filme(titulo, ano, tmdb_id):
    if tmdb_id:
        return ("tmdb", tmdb_id)
    normalizado = unicodedata.normalize("NFKC", titulo).casefold().strip()
    return ("titulo", normalizado, ano or "")


def interpretar_rss(conteudo, hoje, janela_dias=7, max_filmes=7):
    """Extrai filmes recentes do RSS e ordena por nota e data assistida."""
    if isinstance(janela_dias, bool) or not isinstance(janela_dias, int) or janela_dias <= 0:
        raise ValueError("janela_dias deve ser um inteiro positivo")
    if isinstance(max_filmes, bool) or not isinstance(max_filmes, int) or max_filmes <= 0:
        raise ValueError("max_filmes deve ser um inteiro positivo")
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError as e:
        raise ValueError(f"RSS do Letterboxd inválido: {e}") from e

    limite = hoje - dt.timedelta(days=janela_dias - 1)
    encontrados = {}
    for item in (no for no in raiz.iter() if no.tag.rsplit("}", 1)[-1] == "item"):
        titulo = (_filho(item, "filmTitle") or "").strip()
        data_txt = (_filho(item, "watchedDate") or "").strip()
        ano = (_filho(item, "filmYear") or "").strip() or None
        if not titulo or not data_txt:
            logger.warning("Item do RSS Letterboxd ignorado: falta título ou watchedDate")
            continue
        try:
            assistido = dt.date.fromisoformat(data_txt)
        except ValueError:
            logger.warning("Item do RSS Letterboxd ignorado: watchedDate inválida")
            continue
        if assistido < limite or assistido > hoje:
            continue

        nota_txt = (_filho(item, "memberRating") or "").strip()
        try:
            nota = float(nota_txt) if nota_txt else None
        except ValueError:
            logger.warning("Item do RSS Letterboxd ignorado: memberRating inválida")
            continue
        if nota is not None and not 0 <= nota <= 5:
            logger.warning("Item do RSS Letterboxd ignorado: memberRating fora do intervalo")
            continue

        filme = {
            "titulo": titulo,
            "ano": ano,
            "nota": nota,
            "assistido": assistido,
            "url": _filho(item, "link"),
            "tmdb_id": _filho(item, "movieId"),
        }
        chave = _chave_filme(titulo, ano, filme["tmdb_id"])
        anterior = encontrados.get(chave)
        if anterior is None or (
            (nota is not None, nota or 0, assistido)
            > (anterior["nota"] is not None, anterior["nota"] or 0, anterior["assistido"])
        ):
            encontrados[chave] = filme

    filmes = list(encontrados.values())
    filmes.sort(key=lambda filme: (
        filme["nota"] is not None,
        filme["nota"] if filme["nota"] is not None else 0,
        filme["assistido"],
    ), reverse=True)
    return filmes[:max_filmes]


def _normalizar_rotulo(texto):
    sem_acentos = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in sem_acentos if not unicodedata.combining(c)).split())


def creditos_do_filme(html, ano):
    """Devolve links de crédito de uma infocaixa de filme, se puder validá-la."""
    soup = BeautifulSoup(html or "", "lxml")
    infobox = soup.select_one("table.infobox")
    if not infobox:
        return None

    reconhecida = False
    anos_lancamento = set()
    creditos = []
    vistos = set()
    for linha in infobox.select("tr"):
        rotulo = linha.find(["th", "td"], class_=re.compile(r"(?:^|\s)infobox-label(?:\s|$)"))
        if rotulo is None:
            rotulo = linha.find("th")
        valor = linha.find("td")
        if rotulo is None or valor is None:
            continue
        chave = _normalizar_rotulo(rotulo.get_text(" ", strip=True).rstrip(":"))
        if chave in _ROTULOS_FILME:
            reconhecida = True
        if chave in _ROTULOS_ANO:
            anos_lancamento.update(re.findall(r"(?<!\d)(?:18|19|20|21)\d{2}(?!\d)", valor.get_text(" ", strip=True)))
        if chave not in _CREDITOS:
            continue
        for ancora in valor.select("a[href^='/wiki/']"):
            titulo = ancora.get("title") or ancora.get_text(" ", strip=True)
            if not titulo or ":" in titulo or titulo in vistos:
                continue
            vistos.add(titulo)
            creditos.append(titulo)

    if not reconhecida or (ano and ano not in anos_lancamento):
        return None
    return creditos


def _titulo_original_corresponde(html, filme):
    soup = BeautifulSoup(html or "", "lxml")
    infobox = soup.select_one("table.infobox")
    if not infobox:
        return False
    esperado = _normalizar_rotulo(filme["titulo"])
    for cabecalho in infobox.select("th.infobox-above, caption"):
        if _normalizar_rotulo(cabecalho.get_text(" ", strip=True)) == esperado:
            return True
    for linha in infobox.select("tr"):
        rotulo = linha.find("th")
        valor = linha.find("td")
        if rotulo is None or valor is None:
            continue
        chave = _normalizar_rotulo(rotulo.get_text(" ", strip=True).rstrip(":"))
        if chave in _ROTULOS_TITULO:
            nomes = {_normalizar_rotulo(valor.get_text(" ", strip=True))}
            nomes.update(_normalizar_rotulo(a.get_text(" ", strip=True)) for a in valor.select("a"))
            if esperado in nomes:
                return True
    return False


def _titulos_candidatos(sessao, wcfg, filme):
    consulta = f'"{filme["titulo"]}"'
    if filme["ano"]:
        consulta += f' {filme["ano"]}'
    resposta = api(
        sessao, wcfg, action="query", list="search", srsearch=consulta,
        srnamespace=0, srlimit=5,
    )
    if "error" in resposta or not isinstance(resposta.get("query"), dict):
        raise ValueError("resposta inválida da busca da Wikipédia")
    return [r["title"] for r in resposta["query"].get("search", [])]


def _titulo_corresponde(titulo, filme):
    base = re.sub(r"\s*\([^()]*\)\s*$", "", titulo.replace("_", " ")).strip()
    return _normalizar_rotulo(base) == _normalizar_rotulo(filme["titulo"])


def priorizar_artigo(sessao, cfg, usados, usados_ids, hoje, filtro_qualidade=None):
    """Devolve (artigo, motivo); `(None, motivo)` aciona o sorteio normal."""
    pcfg = cfg.get("personalizacao_cultural") or {}
    lcfg = validar_config(pcfg.get("letterboxd") if pcfg else cfg.get("letterboxd"))
    if not lcfg["ativar"]:
        return None, "integração Letterboxd desativada"

    try:
        resposta = sessao.get(lcfg["feed_url"], timeout=30)
        resposta.raise_for_status()
        filmes = interpretar_rss(
            resposta.content, hoje, lcfg["janela_dias"], lcfg["max_filmes"],
        )
    except (requests.RequestException, ValueError) as e:
        logger.warning("Letterboxd indisponível; usando sorteio normal de Cinema: %s", e)
        return None, "falha ao consultar Letterboxd"
    if not filmes:
        return None, "nenhum filme assistido na janela configurada"

    wcfg = {**cfg["wikipedia"], "imagens": cfg.get("imagens", {"ativar": False})}
    usados_titulos = {_normalizar_rotulo(t.replace("_", " ")) for t in usados}
    creditos_vistos = set()
    for filme in filmes:
        try:
            titulos = _titulos_candidatos(sessao, wcfg, filme)
        except (requests.RequestException, ValueError) as e:
            logger.warning("Falha ao buscar filme '%s' na Wikipédia: %s", filme["titulo"], e)
            continue
        for titulo in titulos:
            try:
                art = buscar_artigo(sessao, wcfg, titulo)
            except (requests.RequestException, ValueError) as e:
                logger.warning("Falha ao carregar artigo do filme '%s': %s", filme["titulo"], e)
                continue
            if not art:
                continue
            try:
                resposta_parse = api(
                    sessao, wcfg, action="parse", pageid=art["pageid"], prop="text",
                )
            except (requests.RequestException, ValueError) as e:
                logger.warning("Falha ao ler créditos do filme '%s': %s", filme["titulo"], e)
                continue
            bloco_parse = resposta_parse.get("parse")
            creditos_html = bloco_parse.get("text") if isinstance(bloco_parse, dict) else None
            if not isinstance(creditos_html, str):
                logger.warning("Resposta sem HTML de infocaixa para '%s'", filme["titulo"])
                continue
            creditos = creditos_do_filme(creditos_html, filme["ano"])
            if (creditos is None
                    or (not _titulo_corresponde(titulo, filme)
                        and not _titulo_original_corresponde(creditos_html, filme))):
                continue

            candidatos = [(art, "filme", None)]
            for nome in creditos[:lcfg["max_creditos_por_filme"]]:
                candidatos.append((None, "crédito", nome))

            for candidato, relacao, nome in candidatos:
                if nome:
                    chave = _normalizar_rotulo(nome.replace("_", " "))
                    if chave in creditos_vistos:
                        continue
                    creditos_vistos.add(chave)
                    try:
                        candidato = buscar_artigo(sessao, wcfg, nome)
                    except (requests.RequestException, ValueError) as e:
                        logger.warning("Falha ao carregar artigo de crédito '%s': %s", nome, e)
                        continue
                    if not candidato:
                        continue
                titulo_candidato = candidato["titulo"]
                if (_normalizar_rotulo(titulo_candidato.replace("_", " ")) in usados_titulos
                        or candidato["pageid"] in usados_ids):
                    continue
                if not artigo_aceitavel(sessao, wcfg, candidato, filtro_qualidade):
                    continue
                candidato["caminho"] = f"Letterboxd · {filme['titulo']} ({relacao})"
                candidato["nota"] = (
                    "Um passarinho azul, verde e laranja me contou que você ia gostar."
                )
                return candidato, ""
    return None, "sem candidato relacionado novo que passe pelos critérios"
