"""Prioriza artigos de Música e Música Clássica a partir da API do Last.fm."""
import datetime as dt
import logging
import os
import re
import unicodedata
from urllib.parse import urlsplit

import requests

from .qualidade import avaliar_qualidade
from .wikipedia import api, artigo_aceitavel, buscar_artigo

logger = logging.getLogger(__name__)

PADRAO = {
    "ativar": False,
    "usuario": "",
    "api_key": "",
    "janela_dias": 7,
    "max_itens": 10,
    "temas": ["Música", "Música clássica"],
    "bonus_idioma_pt": 1000,
    "peso_classe": 2000,
    "api_url": "https://ws.audioscrobbler.com/2.0/",
}

def _normalizar_rotulo(texto):
    sem_acentos = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in sem_acentos if not unicodedata.combining(c)).split())


_PALAVRAS_MUSICA = {
    _normalizar_rotulo(p) for p in {
        "músic", "banda", "cantor", "álbum", "canção", "single", "compositor",
        "music", "band", "singer", "album", "song", "discografia", "discography",
        "musician", "musical", "record", "gravação", "rock", "pop", "jazz", "metal",
        "clássica", "classical", "opera", "ópera", "symphony", "sinfonia",
    }
}

_PALAVRAS_CLASSICA = {
    _normalizar_rotulo(p) for p in {
        "música clássica", "música erudita", "compositores clássicos", "compositores da era clássica",
        "ópera", "óperas", "sinfonia", "sinfonias", "concerto", "concertos",
        "classical music", "classical composers", "operas", "symphonies",
        "baroque composers", "romantic composers", "classical pianists", "classical musicians",
        "conductors", "regentes", "orquestra", "orchestra",
    }
}

_SUFIXOS_MUSICAIS = {
    _normalizar_rotulo(p) for p in {
        "banda", "músico", "música", "cantor", "cantora", "álbum", "canção",
        "band", "musician", "singer", "album", "song", "composer", "compositor",
    }
}


def validar_config(cfg):
    """Valida opções Last.fm e devolve a configuração com padrões."""
    resultado = {**PADRAO, **(cfg or {})}
    api_key = resultado.get("api_key") or os.environ.get("LASTFM_API_KEY", "")
    resultado["api_key"] = api_key.strip() if isinstance(api_key, str) else ""

    usuario = resultado.get("usuario")
    if not isinstance(usuario, str):
        raise ValueError("personalizacao_cultural.lastfm.usuario deve ser texto")
    resultado["usuario"] = usuario.strip()

    if resultado["ativar"]:
        if not resultado["usuario"]:
            raise ValueError("personalizacao_cultural.lastfm.usuario é obrigatório quando a integração estiver ativa")
        if not resultado["api_key"]:
            raise ValueError(
                "personalizacao_cultural.lastfm.api_key (ou variável LASTFM_API_KEY) é obrigatória quando a integração estiver ativa"
            )

    for chave in ("janela_dias", "max_itens", "bonus_idioma_pt", "peso_classe"):
        valor = resultado.get(chave)
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            raise ValueError(f"lastfm.{chave} deve ser um inteiro positivo")

    temas = resultado.get("temas")
    if not isinstance(temas, (list, tuple)) or not temas:
        raise ValueError("lastfm.temas deve ser uma lista com pelo menos um tema")
    resultado["temas"] = list(temas)

    api_url = resultado.get("api_url")
    if api_url:
        partes = urlsplit(api_url)
        if partes.scheme not in {"http", "https"} or not partes.netloc:
            raise ValueError("api_url do Last.fm deve ser uma URL HTTP(S) válida")

    return resultado


def _extrair_texto(obj):
    if isinstance(obj, dict):
        return obj.get("#text") or obj.get("name") or ""
    if isinstance(obj, str):
        return obj
    return ""


def coletar_scrobbles(sessao, config, hoje):
    """Consulta os scrobbles recentes do usuário na API oficial do Last.fm."""
    janela_dias = config["janela_dias"]
    limite_data = hoje - dt.timedelta(days=janela_dias - 1)
    inicio_dt = dt.datetime(limite_data.year, limite_data.month, limite_data.day, 0, 0, 0, tzinfo=dt.timezone.utc)
    fim_dt = dt.datetime(hoje.year, hoje.month, hoje.day, 23, 59, 59, tzinfo=dt.timezone.utc)

    params = {
        "method": "user.getrecenttracks",
        "user": config["usuario"],
        "api_key": config["api_key"],
        "format": "json",
        "from": str(int(inicio_dt.timestamp())),
        "to": str(int(fim_dt.timestamp())),
        "limit": "200",
    }
    r = sessao.get(config["api_url"], params=params, timeout=30)
    r.raise_for_status()
    dados = r.json()
    if not isinstance(dados, dict):
        raise ValueError("resposta da API do Last.fm não é um objeto JSON válido")
    if "error" in dados:
        raise ValueError(f"erro retornado pela API do Last.fm: {dados.get('message', 'código ' + str(dados['error']))}")
    return dados


def interpretar_recenttracks(dados, hoje, janela_dias=7, max_itens=10):
    """Extrai faixas recentes da resposta e agrupa/ordena entidades por scrobbles."""
    recent = dados.get("recenttracks") if isinstance(dados, dict) else None
    if not isinstance(recent, dict):
        raise ValueError("resposta do Last.fm sem bloco recenttracks")

    raw_tracks = recent.get("track", [])
    if isinstance(raw_tracks, dict):
        raw_tracks = [raw_tracks]
    elif not isinstance(raw_tracks, list):
        raw_tracks = []

    limite_data = hoje - dt.timedelta(days=janela_dias - 1)
    inicio_ts = int(dt.datetime(limite_data.year, limite_data.month, limite_data.day, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp())
    fim_ts = int(dt.datetime(hoje.year, hoje.month, hoje.day, 23, 59, 59, tzinfo=dt.timezone.utc).timestamp())

    agrupados = {}
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        artista = _extrair_texto(item.get("artist")).strip()
        faixa = str(item.get("name") or "").strip()
        album = _extrair_texto(item.get("album")).strip()
        if not artista:
            logger.warning("Item Last.fm ignorado: falta artista")
            continue

        attr = item.get("@attr")
        is_now_playing = isinstance(attr, dict) and attr.get("nowplaying") == "true"
        date_info = item.get("date")
        if is_now_playing:
            uts = fim_ts
        elif isinstance(date_info, dict) and date_info.get("uts"):
            try:
                uts = int(date_info["uts"])
            except ValueError:
                logger.warning("Item Last.fm ignorado: timestamp inválido")
                continue
        else:
            logger.warning("Item Last.fm ignorado: sem data ou nowplaying")
            continue

        if uts < inicio_ts or uts > fim_ts:
            continue

        chave_artista = _normalizar_rotulo(artista)
        if chave_artista not in agrupados:
            agrupados[chave_artista] = {
                "nome": artista,
                "scrobbles": 0,
                "ultimo_uts": uts,
                "albuns": {},
                "faixas": {},
            }
        art_info = agrupados[chave_artista]
        art_info["scrobbles"] += 1
        if uts > art_info["ultimo_uts"]:
            art_info["ultimo_uts"] = uts

        if album:
            chave_album = _normalizar_rotulo(album)
            if chave_album not in art_info["albuns"]:
                art_info["albuns"][chave_album] = {"nome": album, "scrobbles": 0, "ultimo_uts": uts}
            alb_info = art_info["albuns"][chave_album]
            alb_info["scrobbles"] += 1
            if uts > alb_info["ultimo_uts"]:
                alb_info["ultimo_uts"] = uts

        if faixa:
            chave_faixa = _normalizar_rotulo(faixa)
            if chave_faixa not in art_info["faixas"]:
                art_info["faixas"][chave_faixa] = {"nome": faixa, "scrobbles": 0, "ultimo_uts": uts}
            faixa_info = art_info["faixas"][chave_faixa]
            faixa_info["scrobbles"] += 1
            if uts > faixa_info["ultimo_uts"]:
                faixa_info["ultimo_uts"] = uts

    artistas = list(agrupados.values())
    artistas.sort(key=lambda a: (a["scrobbles"], a["ultimo_uts"]), reverse=True)
    return artistas[:max_itens]


def _titulos_candidatos(sessao, wcfg, termo, tipo, artista=None):
    """Devolve candidatos diretos e resultados da busca na Wikipédia."""
    diretos = []
    lang = wcfg.get("lang", "pt")
    if tipo == "artista":
        sufixos = (
            ["músico", "cantor", "cantora", "banda", "grupo musical", "compositor"]
            if lang == "pt"
            else ["musician", "singer", "band", "musical group", "composer"]
        )
        diretos.append(termo)
        diretos.extend(f"{termo} ({suf})" for suf in sufixos)
        consulta = f'"{termo}"'
    elif tipo == "álbum":
        suf_art = f"álbum de {artista}" if lang == "pt" else f"{artista} album"
        suf_padrao = "álbum" if lang == "pt" else "album"
        if artista:
            diretos.append(f"{termo} ({suf_art})")
        diretos.append(f"{termo} ({suf_padrao})")
        diretos.append(termo)
        consulta = f'"{termo}" "{artista}"' if artista else f'"{termo}"'
    else:  # faixa
        suf_art = f"canção de {artista}" if lang == "pt" else f"{artista} song"
        suf_padrao = "canção" if lang == "pt" else "song"
        if artista:
            diretos.append(f"{termo} ({suf_art})")
        diretos.append(f"{termo} ({suf_padrao})")
        diretos.append(termo)
        consulta = f'"{termo}" "{artista}"' if artista else f'"{termo}"'

    try:
        resp = api(sessao, wcfg, action="query", list="search", srsearch=consulta, srnamespace=0, srlimit=5)
        titulos_busca = [r["title"] for r in resp.get("query", {}).get("search", [])]
    except (requests.RequestException, ValueError) as e:
        logger.warning("Falha na busca da Wikipédia para '%s': %s", consulta, e)
        titulos_busca = []

    resultado = []
    vistos = set()
    for t in diretos + titulos_busca:
        norm = _normalizar_rotulo(t)
        if norm not in vistos:
            vistos.add(norm)
            resultado.append(t)
    return resultado


def _eh_artigo_musical(art, categorias):
    """Valida se o artigo pertence ao domínio musical para evitar homônimos."""
    titulo_norm = _normalizar_rotulo(art.get("titulo", ""))
    for suf in _SUFIXOS_MUSICAIS:
        if f"({suf})" in titulo_norm:
            return True
    for cat in categorias:
        cat_norm = _normalizar_rotulo(cat)
        if any(palavra in cat_norm for palavra in _PALAVRAS_MUSICA):
            return True
    texto_inicio = _normalizar_rotulo(art.get("html", "")[:600])
    return any(palavra in texto_inicio for palavra in ("cantor", "banda", "álbum", "música", "album", "singer", "song"))


def _eh_musica_classica(art, categorias):
    """Detecta se o artigo ou suas categorias referem-se a música clássica/erudita."""
    for cat in categorias:
        cat_norm = _normalizar_rotulo(cat)
        if any(marcador in cat_norm for marcador in _PALAVRAS_CLASSICA):
            return True
    texto_inicio = _normalizar_rotulo(art.get("html", "")[:800])
    return any(marcador in texto_inicio for marcador in _PALAVRAS_CLASSICA)


def _obter_categorias(sessao, wcfg, pageid):
    """Obtém as categorias da página na Wikipédia."""
    try:
        resp = api(sessao, wcfg, action="query", prop="categories", pageids=pageid, cllimit=50)
        pages = resp.get("query", {}).get("pages", [])
        if pages and isinstance(pages[0], dict):
            return [c.get("title", "") for c in pages[0].get("categories", [])]
    except (requests.RequestException, ValueError) as e:
        logger.warning("Falha ao obter categorias para pageid %s: %s", pageid, e)
    return []


def _buscar_melhor_no_idioma(sessao, wcfg, termo, tipo, artista, usados_titulos, usados_ids, filtro_qualidade):
    """Busca um candidato aceitável no idioma e calcula seu score balanceado."""
    titulos = _titulos_candidatos(sessao, wcfg, termo, tipo, artista)
    for titulo in titulos:
        try:
            art = buscar_artigo(sessao, wcfg, titulo)
        except (requests.RequestException, ValueError) as e:
            logger.warning("Falha ao carregar artigo '%s': %s", titulo, e)
            continue
        if not art:
            continue

        titulo_norm = _normalizar_rotulo(art["titulo"].replace("_", " "))
        if titulo_norm in usados_titulos or art["pageid"] in usados_ids:
            continue

        categorias = _obter_categorias(sessao, wcfg, art["pageid"])
        if not _eh_artigo_musical(art, categorias):
            continue

        if not artigo_aceitavel(sessao, wcfg, art, filtro_qualidade):
            continue

        art["lang"] = wcfg.get("lang", "pt")
        classica = _eh_musica_classica(art, categorias)

        classe = 3  # padrão C se sem filtro
        ativo = getattr(filtro_qualidade, "ativo", False)
        disjuntor = getattr(filtro_qualidade, "disjuntor_acionado", False)
        if ativo and not disjuntor:
            modelo = "enwiki-articlequality" if art["lang"] == "en" else "ptwiki-articlequality"
            cfg_filtro = getattr(filtro_qualidade, "config", {})
            cfg_av = {**cfg_filtro, "modelo": modelo}
            cl, _ = avaliar_qualidade(sessao, art.get("revid"), cfg_av)
            if cl is not None:
                classe = cl

        return art, classe, classica
    return None, None, False


def _avaliar_candidato_bilingue(
    sessao, cfg_base, termo, tipo, artista, usados_titulos, usados_ids, filtro_qualidade, fmcfg
):
    """Busca o artigo em pt e en e escolhe a melhor versão pelo score ponderado."""
    wcfg_pt = {
        **cfg_base["wikipedia"],
        "api": "https://pt.wikipedia.org/w/api.php",
        "lang": "pt",
        "imagens": cfg_base.get("imagens", {"ativar": False}),
    }
    wcfg_en = {
        **cfg_base["wikipedia"],
        "api": "https://en.wikipedia.org/w/api.php",
        "lang": "en",
        "imagens": cfg_base.get("imagens", {"ativar": False}),
    }

    art_pt, classe_pt, class_pt = _buscar_melhor_no_idioma(
        sessao, wcfg_pt, termo, tipo, artista, usados_titulos, usados_ids, filtro_qualidade
    )
    art_en, classe_en, class_en = _buscar_melhor_no_idioma(
        sessao, wcfg_en, termo, tipo, artista, usados_titulos, usados_ids, filtro_qualidade
    )

    if not art_pt and not art_en:
        return None, False

    peso_classe = fmcfg.get("peso_classe", 2000)
    bonus_pt = fmcfg.get("bonus_idioma_pt", 1000)
    max_chars = cfg_base.get("wikipedia", {}).get("max_caracteres", 15000)

    score_pt = -1
    if art_pt:
        score_pt = (classe_pt * peso_classe) + min(art_pt["chars"], max_chars) + bonus_pt

    score_en = -1
    if art_en:
        score_en = (classe_en * peso_classe) + min(art_en["chars"], max_chars)

    if art_pt and (not art_en or score_pt >= score_en):
        return art_pt, class_pt
    return art_en, class_en


def priorizar_artigos_musica(sessao, cfg, usados, usados_ids, hoje, filtro_qualidade=None, temas_alvo=None):
    """Devolve ({tema: artigo}, motivo); se {tema: artigo} estiver vazio, motivo aciona o sorteio normal."""
    pcfg = cfg.get("personalizacao_cultural") or {}
    fmcfg = validar_config(pcfg.get("lastfm") if pcfg else cfg.get("lastfm"))
    if not fmcfg["ativar"]:
        return {}, "integração Last.fm desativada"

    temas_alvo = list(temas_alvo or fmcfg["temas"])
    try:
        dados = coletar_scrobbles(sessao, fmcfg, hoje)
        artistas = interpretar_recenttracks(dados, hoje, fmcfg["janela_dias"], fmcfg["max_itens"])
    except (requests.RequestException, ValueError) as e:
        logger.warning("Last.fm indisponível; usando sorteio normal para música: %s", e)
        return {}, "falha ao consultar Last.fm"

    if not artistas:
        return {}, "nenhuma música ouvida na janela configurada"

    usados_titulos = {_normalizar_rotulo(t.replace("_", " ")) for t in usados}
    resultado = {}
    precisa_classica = "Música clássica" in temas_alvo
    precisa_musica = "Música" in temas_alvo

    for art_info in artistas:
        candidatos = [("artista", art_info["nome"], art_info["nome"])]
        albuns_ord = sorted(art_info["albuns"].values(), key=lambda x: (x["scrobbles"], x["ultimo_uts"]), reverse=True)
        for alb in albuns_ord:
            candidatos.append(("álbum", alb["nome"], art_info["nome"]))
        faixas_ord = sorted(art_info["faixas"].values(), key=lambda x: (x["scrobbles"], x["ultimo_uts"]), reverse=True)
        for fx in faixas_ord:
            candidatos.append(("faixa", fx["nome"], art_info["nome"]))

        for tipo, termo, artista_nome in candidatos:
            artigo, eh_classica = _avaliar_candidato_bilingue(
                sessao, cfg, termo, tipo, artista_nome, usados_titulos, usados_ids, filtro_qualidade, fmcfg
            )
            if not artigo:
                continue

            destino_tema = None
            if eh_classica:
                if precisa_classica and "Música clássica" not in resultado:
                    destino_tema = "Música clássica"
                elif not precisa_classica and precisa_musica and "Música" not in resultado:
                    destino_tema = "Música"
            else:
                if precisa_musica and "Música" not in resultado:
                    destino_tema = "Música"

            if destino_tema:
                artigo["caminho"] = f"Last.fm · {artista_nome} ({tipo})"
                artigo["nota"] = "Um passarinho vermelho me contou que você andou ouvindo bastante isso ultimamente."
                resultado[destino_tema] = artigo
                usados_titulos.add(_normalizar_rotulo(artigo["titulo"].replace("_", " ")))
                usados_ids.add(artigo["pageid"])
                break  # Não seleciona outro item do mesmo artista na mesma edição

        if (not precisa_musica or "Música" in resultado) and (not precisa_classica or "Música clássica" in resultado):
            return resultado, ""

    # Se ainda faltar "Música" e só houveram artistas clássicos (ou vice-versa), tenta preencher o tema restante
    if precisa_musica and "Música" not in resultado:
        for art_info in artistas:
            candidatos = [("artista", art_info["nome"], art_info["nome"])]
            albuns_ord = sorted(art_info["albuns"].values(), key=lambda x: (x["scrobbles"], x["ultimo_uts"]), reverse=True)
            for alb in albuns_ord:
                candidatos.append(("álbum", alb["nome"], art_info["nome"]))
            faixas_ord = sorted(art_info["faixas"].values(), key=lambda x: (x["scrobbles"], x["ultimo_uts"]), reverse=True)
            for fx in faixas_ord:
                candidatos.append(("faixa", fx["nome"], art_info["nome"]))

            for tipo, termo, artista_nome in candidatos:
                artigo, _ = _avaliar_candidato_bilingue(
                    sessao, cfg, termo, tipo, artista_nome, usados_titulos, usados_ids, filtro_qualidade, fmcfg
                )
                if not artigo:
                    continue
                artigo["caminho"] = f"Last.fm · {artista_nome} ({tipo})"
                artigo["nota"] = "Um passarinho vermelho me contou que você andou ouvindo bastante isso ultimamente."
                resultado["Música"] = artigo
                usados_titulos.add(_normalizar_rotulo(artigo["titulo"].replace("_", " ")))
                usados_ids.add(artigo["pageid"])
                return resultado, ""

    if resultado:
        return resultado, ""
    return {}, "sem candidato relacionado novo que passe pelos critérios"
