"""Coluna de Fofocas — Tribunal do Cotidiano (r/AmItheAsshole).

Coleta posts semanais do subreddit r/AmItheAsshole via API pública .json do Reddit,
aplica filtros de elegibilidade, calcula score composto priorizando controvérsia e diversidade,
extrai o comentário mais votado e formata uma seção contínua com moldura editorial em português.
"""
from dataclasses import dataclass
import html
import math
import re
import time
from typing import Dict, List, Optional, Set, Tuple

import requests

from .config import criar_sessao

USER_AGENT_REDDIT = "linux:jornal-eink:v1.0 (leitor pessoal xteink-x4)"

FLAIRS_VALIDOS: Set[str] = {
    "Asshole",
    "Not the A-hole",
    "Everyone Sucks",
    "No A-holes here",
}

MAPA_VEREDITOS: Dict[str, Dict[str, str]] = {
    "Asshole": {
        "codigo": "YTA",
        "veredito": "CULPADO(A) — O Babaca da História",
        "subtitulo": "O júri não teve piedade do autor deste relato.",
    },
    "Not the A-hole": {
        "codigo": "NTA",
        "veredito": "INOCENTE — Livre de Culpa",
        "subtitulo": "Absolvido(a) com louvor: o problema está nos outros.",
    },
    "Everyone Sucks": {
        "codigo": "ESH",
        "veredito": "CULPA RECÍPROCA — Ninguém se Salva",
        "subtitulo": "Condenação coletiva: todo mundo errou feio no caso.",
    },
    "No A-holes here": {
        "codigo": "NAH",
        "veredito": "CASO ARQUIVADO — Sem Vilões",
        "subtitulo": "Apenas um mal-entendido humano, sem culpados.",
    },
}


@dataclass
class CasoAITA:
    id: str                      # ex: "aita_1abcde"
    titulo: str                  # Inglês
    autor: str                   # u/username
    corpo_html: str              # Inglês (higienizado)
    palavras: int
    tempo_leitura_min: int
    score: int
    upvote_ratio: float
    num_comments: int
    flair_original: str          # ex: "Asshole"
    veredito_pt: str             # ex: "CULPADO(A) — O Babaca da História"
    subtitulo_veredito_pt: str   # ex: "O júri não teve piedade..."
    comentario_autor: Optional[str]
    comentario_corpo_html: Optional[str]  # Inglês
    comentario_score: Optional[int]
    frase_martelo_pt: str        # Fechamento criativo em PT-BR


@dataclass
class SecaoFofocas:
    titulo_coluna: str
    abertura_editorial_pt: str   # Texto de topo da coluna
    casos: List[CasoAITA]
    ponte_transicao_pt: Optional[str]  # Texto entre Caso #1 e Caso #2


def validar_config(fcfg: Optional[dict]) -> dict:
    """Valida e preenche padrões da configuração da coluna de fofocas."""
    if fcfg is None:
        return {"habilitado": False}
    if not isinstance(fcfg, dict):
        raise ValueError("fofocas deve ser um mapa de configurações")
    habilitado = fcfg.get("habilitado", True)
    if not isinstance(habilitado, bool):
        raise ValueError("fofocas.habilitado deve ser booleano")
    qtd = fcfg.get("quantidade_posts", 2)
    if isinstance(qtd, bool) or not isinstance(qtd, int) or qtd < 1:
        raise ValueError("fofocas.quantidade_posts deve ser um inteiro >= 1")
    return fcfg


# -----------------------------------------------------------------------------
# 1. Coleta na API Pública do Reddit
# -----------------------------------------------------------------------------

def _fazer_requisicao_reddit(sessao: requests.Session, url: str, timeout: int = 10, max_retries: int = 2) -> Optional[requests.Response]:
    """Executa requisição GET ao Reddit com headers apropriados e política de retries."""
    headers = {"User-Agent": USER_AGENT_REDDIT}
    for tentativa in range(max_retries + 1):
        try:
            resp = sessao.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504):
                if tentativa < max_retries:
                    time.sleep(3)
                    continue
            print(f"Aviso Reddit: HTTP {resp.status_code} ao acessar {url}")
            return None
        except Exception as e:
            if tentativa < max_retries:
                time.sleep(3)
                continue
            print(f"Aviso Reddit: falha de rede ao acessar {url} ({e})")
            return None
    return None


def buscar_candidatos_reddit(sessao: requests.Session, fcfg: dict) -> List[dict]:
    """Coleta listagem semanal do subreddit via endpoint top.json."""
    subreddit = fcfg.get("subreddit", "AmItheAsshole")
    periodo = fcfg.get("periodo", "week")
    limite = fcfg.get("limite_busca", 100)
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t={periodo}&limit={limite}"

    resp = _fazer_requisicao_reddit(sessao, url)
    if not resp:
        return []

    try:
        dados = resp.json()
        children = dados.get("data", {}).get("children", [])
    except Exception as e:
        print(f"Aviso Reddit: erro ao decodificar JSON de candidatos: {e}")
        return []

    candidatos = []
    for item in children:
        p = item.get("data")
        if not p:
            continue
        candidatos.append({
            "id": p.get("id", ""),
            "title": p.get("title", ""),
            "author": p.get("author", "[anônimo]"),
            "selftext": p.get("selftext", ""),
            "score": int(p.get("score") or 0),
            "upvote_ratio": float(p.get("upvote_ratio") or 0.0),
            "num_comments": int(p.get("num_comments") or 0),
            "link_flair_text": (p.get("link_flair_text") or "").strip(),
            "permalink": p.get("permalink", ""),
            "over_18": bool(p.get("over_18", False)),
        })
    return candidatos


def buscar_top_comment(sessao: requests.Session, permalink: str, max_palavras: int = 140) -> Optional[Tuple[str, str, int]]:
    """Busca o comentário humano mais votado (Voz do Júri) e aplica truncamento seguro."""
    if not permalink:
        return None
    url = f"https://www.reddit.com{permalink}.json?sort=top&limit=10"
    resp = _fazer_requisicao_reddit(sessao, url)
    if not resp:
        return None

    try:
        dados = resp.json()
        if not isinstance(dados, list) or len(dados) < 2:
            return None
        comentarios_data = dados[1].get("data", {}).get("children", [])
    except Exception as e:
        print(f"Aviso Reddit: erro ao decodificar comentários: {e}")
        return None

    for item in comentarios_data:
        if item.get("kind") != "t1":
            continue
        c = item.get("data", {})
        autor = c.get("author", "")
        body = c.get("body", "")
        stickied = c.get("stickied", False)
        score = int(c.get("score") or 0)

        if autor == "AutoModerator" or stickied:
            continue
        if not body or body in ("[deleted]", "[removed]"):
            continue

        body_truncado = truncar_comentario_sentenca(body, max_palavras)
        return autor, body_truncado, score

    return None


# -----------------------------------------------------------------------------
# 2. Higienização de Texto e Truncamento de Sentenças
# -----------------------------------------------------------------------------

def truncar_comentario_sentenca(texto: str, max_palavras: int = 140) -> str:
    """Se o comentário ultrapassar max_palavras, trunca no fim da sentença mais próxima de 140 palavras."""
    palavras = texto.split()
    if len(palavras) <= max_palavras:
        return texto

    # Divide por fronteira de sentença (. ! ?)
    sentencas = re.split(r'(?<=[.!?])\s+', texto.strip())
    acumulado: List[str] = []
    total_palavras = 0

    for s in sentencas:
        p_count = len(s.split())
        if total_palavras + p_count <= max_palavras:
            acumulado.append(s)
            total_palavras += p_count
        else:
            # Avalia se a sentença atual está razoavelmente próxima ou se encerra
            if not acumulado:
                # Primeira sentença já excede o limite: trunca por palavras
                return " ".join(palavras[:max_palavras]) + " [...]"
            break

    resultado = " ".join(acumulado).strip()
    if not resultado.endswith((".", "!", "?")):
        resultado += "."
    return resultado + " [...]"


def higienizar_markdown_eink(texto_md: str) -> str:
    """Converte markdown simples de relatos do Reddit para HTML limpo para e-ink."""
    if not texto_md:
        return ""

    # Remove zero-width spaces e escapes de quebra
    t = texto_md.replace("\u200b", "").replace("&#x200B;", "").replace("&amp;#x200B;", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    # Divide em parágrafos separados por linhas em branco
    blocos = re.split(r'\n\s*\n', t.strip())
    paragrafos_html = []

    for bloco in blocos:
        bloco = bloco.strip()
        if not bloco:
            continue

        # Trata blockquote do Reddit (linhas começando com >)
        linhas = bloco.split("\n")
        linhas_limpas = []
        is_quote = all(linha.strip().startswith("&gt;") or linha.strip().startswith(">") for linha in linhas if linha.strip())
        for linha in linhas:
            l = linha.strip()
            if is_quote:
                l = re.sub(r'^(?:&gt;|>)\s*', '', l)
            linhas_limpas.append(html.escape(l))

        conteudo = " ".join(linhas_limpas).strip()
        if not conteudo:
            continue

        # Destaca inícios com EDIT:, UPDATE:, TL;DR: etc.
        padrao_edit = r'^(EDIT\d*|Edit\d*|UPDATE\d*|Update\d*|TL;?\s*DR):?\s*(.*)$'
        m = re.match(padrao_edit, conteudo, re.IGNORECASE)
        if m:
            rotulo = m.group(1).upper()
            resto = m.group(2)
            conteudo = f"<strong>{rotulo}:</strong> {resto}" if resto else f"<strong>{rotulo}</strong>"

        if is_quote:
            paragrafos_html.append(f"<blockquote><p>{conteudo}</p></blockquote>")
        else:
            paragrafos_html.append(f"<p>{conteudo}</p>")

    return "".join(paragrafos_html)


# -----------------------------------------------------------------------------
# 3. Hard Filters e Elegibilidade
# -----------------------------------------------------------------------------

def filtrar_elegiveis(candidatos: List[dict], usados_aita: Set[str], fcfg: dict) -> List[dict]:
    """Descarta posts repetidos, fora da janela de tamanho, com texto removido ou flair inválida."""
    p_min = fcfg.get("palavras_min", 150)
    p_max = fcfg.get("palavras_max", 750)
    filtrar_nsfw = fcfg.get("filtrar_nsfw", False)

    elegiveis = []
    for c in candidatos:
        pid = c.get("id")
        identificador = f"aita_{pid}"
        if identificador in usados_aita:
            continue

        flair = c.get("link_flair_text")
        if flair not in FLAIRS_VALIDOS:
            continue

        selftext = c.get("selftext", "").strip()
        if not selftext or selftext in ("[removed]", "[deleted]"):
            continue

        if filtrar_nsfw and c.get("over_18"):
            continue

        palavras = len(selftext.split())
        if palavras < p_min or palavras > p_max:
            continue

        c["palavras"] = palavras
        elegiveis.append(c)

    return elegiveis


# -----------------------------------------------------------------------------
# 4. Modelo de Pontuação e Diversidade
# -----------------------------------------------------------------------------

def _fator_tamanho(palavras: int, fcfg: dict) -> float:
    """Calcula Li com base na faixa ideal."""
    p_min = fcfg.get("palavras_min", 150)
    p_max = fcfg.get("palavras_max", 750)
    p_ideal_min = fcfg.get("palavras_ideal_min", 250)
    p_ideal_max = fcfg.get("palavras_ideal_max", 450)

    if p_ideal_min <= palavras <= p_ideal_max:
        return 1.0
    if p_min <= palavras < p_ideal_min:
        return 0.5 + 0.5 * ((palavras - p_min) / max(1, p_ideal_min - p_min))
    if p_ideal_max < palavras <= p_max:
        return 1.0 - 0.5 * ((palavras - p_ideal_max) / max(1, p_max - p_ideal_max))
    return 0.5


def calcular_scores(candidatos: List[dict], fcfg: dict) -> List[Tuple[float, dict]]:
    """Calcula o score composto S_i para cada candidato elegível."""
    if not candidatos:
        return []

    pesos = fcfg.get("pesos", {})
    w_e = pesos.get("engajamento", 0.45)
    w_c = pesos.get("polemica", 0.35)
    w_l = pesos.get("tamanho", 0.20)

    mult_flair = {
        "Asshole": 1.35,
        "Everyone Sucks": 1.30,
        "No A-holes here": 1.15,
        "Not the A-hole": 1.00,
        **(fcfg.get("multiplicadores_flair") or {}),
    }

    # 1. Engajamento normalizado
    logs_engajamento = [math.log(1 + max(0, c["score"])) for c in candidatos]
    max_log_eng = max(logs_engajamento) if logs_engajamento else 1.0

    # 2. Polêmica bruta
    indices_c = []
    for c in candidatos:
        c_bruto = (c["num_comments"] / max(c["score"], 100)) + 2.0 * (1.0 - c["upvote_ratio"])
        indices_c.append(c_bruto)

    min_c = min(indices_c) if indices_c else 0.0
    max_c = max(indices_c) if indices_c else 1.0
    range_c = (max_c - min_c) + 1e-6

    pontuados = []
    for i, c in enumerate(candidatos):
        e_hat = logs_engajamento[i] / max_log_eng if max_log_eng > 0 else 0.0
        c_hat = (indices_c[i] - min_c) / range_c
        l_i = _fator_tamanho(c["palavras"], fcfg)
        m_flair = mult_flair.get(c["link_flair_text"], 1.0)

        score_final = (w_e * e_hat + w_c * c_hat + w_l * l_i) * m_flair
        pontuados.append((score_final, c))

    pontuados.sort(key=lambda x: x[0], reverse=True)
    return pontuados


def selecionar_dupla_diversa(candidatos_pontuados: List[Tuple[float, dict]], quantidade: int = 2, forcar_diversidade: bool = True) -> List[dict]:
    """Seleciona até N posts priorizando vereditos diferentes entre si."""
    if not candidatos_pontuados:
        return []
    if quantidade <= 1 or len(candidatos_pontuados) == 1:
        return [candidatos_pontuados[0][1]]

    c1 = candidatos_pontuados[0][1]
    if not forcar_diversidade:
        return [c1, candidatos_pontuados[1][1]]

    # Busca o primeiro subsequente com flair diferente
    for _, c_sub in candidatos_pontuados[1:]:
        if c_sub["link_flair_text"] != c1["link_flair_text"]:
            return [c1, c_sub]

    # Fallback: pega o segundo melhor score
    return [c1, candidatos_pontuados[1][1]]


# -----------------------------------------------------------------------------
# 5. Costura Editorial e Textos em Português
# -----------------------------------------------------------------------------

def gerar_abertura_editorial(codigos_vereditos: List[str], quantidade: int) -> str:
    """Gera a nota de abertura dinâmica da coluna conforme a combinação de vereditos."""
    if quantidade == 1:
        return (
            "Direto dos arquivos morais da internet para a sua tela: um dilema real julgado por milhares de estranhos. "
            "Leia o depoimento original abaixo antes de espiar a sentença final no rodapé."
        )

    codigos = set(codigos_vereditos[:2])
    culpados = {"YTA", "ESH"}
    inocentes = {"NTA", "NAH"}

    tem_culpado = bool(codigos & culpados)
    tem_inocente = bool(codigos & inocentes)

    if tem_culpado and tem_inocente:
        return (
            "A sessão desta semana do nosso Tribunal do Cotidiano traz o equilíbrio perfeito do drama humano: de um lado, "
            "uma alma injustiçada que buscou refúgio na internet; do outro, alguém que cavou a própria cova achando que tinha razão. "
            "Leia os autos (no original em inglês) e tire suas conclusões antes de conferir a sentença."
        )
    if codigos.issubset(culpados):
        return (
            "Semana de tolerância zero no júri popular. Nos dois processos em pauta nesta edição, a falta de noção falou mais alto "
            "e ninguém saiu ileso. Prepare o espírito crítico: os depoimentos a seguir testam os limites da paciência alheia."
        )
    # Ambos inocentes
    return (
        "Dois casos de tirar o fôlego onde a pergunta 'será que eu sou o errado?' parecia ter resposta óbvia para todo mundo — menos "
        "para quem viveu o drama. Confira os dois relatos mais comentados da semana e o veredito implacável da comunidade."
    )


def gerar_ponte_transicao(codigo_caso1: str) -> str:
    """Gera a ponte de concatenação que amarra o Caso #1 ao Caso #2."""
    pontes = {
        "NTA": (
            "Enquanto o primeiro depoente saiu do tribunal com a consciência limpa e o apoio da galeria, o próximo processo da pauta "
            "coloca a balança moral novamente à prova. Mudam os personagens, mas a pergunta continua a mesma: quem passou dos limites aqui?"
        ),
        "YTA": (
            "Depois de uma condenação exemplar no primeiro processo da pauta, limpamos o banco dos réus para ouvir uma segunda história. "
            "Será que o próximo autor terá uma defesa mais convincente ou caminhará para a mesma sentença?"
        ),
        "ESH": (
            "Deixando para trás o caos generalizado do primeiro caso — onde ninguém escapou do martelo do juiz —, avançamos para o segundo e "
            "último processo desta edição. Respire fundo e acompanhe os próximos autos."
        ),
        "NAH": (
            "O primeiro caso terminou em paz diplomática, mas a calma raramente dura muito tempo nos corredores deste tribunal. "
            "Vamos ao segundo relato da semana."
        ),
    }
    return pontes.get(codigo_caso1, pontes["NTA"])


def gerar_bater_do_martelo(post: dict, comentario_score: Optional[int]) -> str:
    """Gera a frase criativa de encerramento do veredito com base nas métricas."""
    ratio = post.get("upvote_ratio", 0.0)
    comentarios = post.get("num_comments", 0)
    flair = post.get("link_flair_text", "")
    score = post.get("score", 0)

    # 1. Alta controvérsia
    if ratio < 0.78 or comentarios > 2500:
        return f"Martelo batido após sessões acaloradas: a audiência brigou nos corredores com mais de {comentarios} comentários nos autos."

    # 2. Condenação esmagadora
    if flair == "Asshole" and comentario_score is not None and comentario_score > score:
        return f"Martelo batido com rigor máximo: a resposta do júri teve mais aplausos ({comentario_score} votos) do que a própria defesa do réu."

    # 3. Consenso absoluto
    if ratio >= 0.92:
        pct = int(round(ratio * 100))
        return f"Martelo batido por quase unanimidade ({pct}% de aprovação nos autos). Processo encerrado."

    # 4. Padrão
    return f"Martelo batido com {score} votos registrados na ata do tribunal. Caso encerrado."


# -----------------------------------------------------------------------------
# 6. Orquestrador Principal do Módulo
# -----------------------------------------------------------------------------

def obter_secao_fofocas(cfg: dict, registros_historico: list, sessao: Optional[requests.Session] = None) -> Optional[SecaoFofocas]:
    """Ponto de entrada: coleta, filtra, seleciona, busca comentários e monta SecaoFofocas."""
    fcfg = cfg.get("fofocas") or {}
    if not fcfg.get("habilitado", True):
        return None

    sessao = sessao or criar_sessao()
    usados_aita = {r["id"] for r in registros_historico if "id" in r and str(r["id"]).startswith("aita_")}

    candidatos_brutos = buscar_candidatos_reddit(sessao, fcfg)
    if not candidatos_brutos:
        return None

    elegiveis = filtrar_elegiveis(candidatos_brutos, usados_aita, fcfg)
    if not elegiveis:
        return None

    pontuados = calcular_scores(elegiveis, fcfg)
    qtd = fcfg.get("quantidade_posts", 2)
    forcar_div = fcfg.get("forcar_vereditos_diferentes", True)
    vencedores = selecionar_dupla_diversa(pontuados, quantidade=qtd, forcar_diversidade=forcar_div)

    casos: List[CasoAITA] = []
    incluir_top = fcfg.get("incluir_top_comment", True)
    max_palavras_c = fcfg.get("max_palavras_comentario", 140)

    for p in vencedores:
        c_autor, c_corpo, c_score = None, None, None
        if incluir_top and p.get("permalink"):
            comment_res = buscar_top_comment(sessao, p["permalink"], max_palavras=max_palavras_c)
            if comment_res:
                c_autor, c_corpo, c_score = comment_res

        flair = p["link_flair_text"]
        info_veredito = MAPA_VEREDITOS.get(flair, {
            "codigo": "DESCONHECIDO",
            "veredito": flair,
            "subtitulo": "Sentença proferida pela comunidade.",
        })

        corpo_higienizado = higienizar_markdown_eink(p["selftext"])
        comentario_higienizado = higienizar_markdown_eink(c_corpo) if c_corpo else None
        palavras = p["palavras"]
        tempo_min = max(1, math.ceil(palavras / 200))
        martelo = gerar_bater_do_martelo(p, c_score)

        casos.append(CasoAITA(
            id=f"aita_{p['id']}",
            titulo=p["title"],
            autor=p["author"],
            corpo_html=corpo_higienizado,
            palavras=palavras,
            tempo_leitura_min=tempo_min,
            score=p["score"],
            upvote_ratio=p["upvote_ratio"],
            num_comments=p["num_comments"],
            flair_original=flair,
            veredito_pt=info_veredito["veredito"],
            subtitulo_veredito_pt=info_veredito["subtitulo"],
            comentario_autor=c_autor,
            comentario_corpo_html=comentario_higienizado,
            comentario_score=c_score,
            frase_martelo_pt=martelo,
        ))

    if not casos:
        return None

    codigos = [MAPA_VEREDITOS.get(c.flair_original, {}).get("codigo", "NTA") for c in casos]
    abertura = gerar_abertura_editorial(codigos, len(casos))
    ponte = gerar_ponte_transicao(codigos[0]) if len(casos) > 1 else None

    titulo_coluna = fcfg.get("titulo_coluna", "Tribunal do Cotidiano")
    return SecaoFofocas(
        titulo_coluna=titulo_coluna,
        abertura_editorial_pt=abertura,
        casos=casos,
        ponte_transicao_pt=ponte,
    )
