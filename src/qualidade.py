"""Filtro de qualidade da Wikipédia usando o backend Lift Wing."""
import logging
import math
import os
import time

import requests

from .wikipedia import CLASSES_QUALIDADE

logger = logging.getLogger(__name__)

BACKEND_URL = "https://api.wikimedia.org/service/lw/inference/v1/models"
_NOMES_CLASSE = {nome.casefold(): valor for nome, valor in CLASSES_QUALIDADE.items()}


def _numero_positivo(valor, nome):
    if (isinstance(valor, bool) or not isinstance(valor, (int, float))
            or not math.isfinite(valor) or valor <= 0):
        raise ValueError(f"{nome} deve ser um número positivo")
    return valor


def validar_config(cfg):
    """Valida o bloco `filtro_qualidade` e devolve sua configuração normalizada."""
    filtro = cfg.get("filtro_qualidade") or {}
    if not isinstance(filtro, dict):
        raise ValueError("wikipedia.filtro_qualidade deve ser um mapa")
    ativo = filtro.get("ativar", False)
    if not isinstance(ativo, bool):
        raise ValueError("filtro_qualidade.ativar deve ser booleano")
    classe = str(filtro.get("classe_minima", "B")).upper()
    if classe not in CLASSES_QUALIDADE:
        raise ValueError(f"classe mínima de qualidade inválida: {classe}")
    timeout = _numero_positivo(filtro.get("timeout", 10), "timeout do filtro de qualidade")
    backend = str(filtro.get("backend", "liftwing")).casefold()
    if backend != "liftwing":
        raise ValueError(f"backend de qualidade inválido: {backend} (use liftwing)")
    modelo = filtro.get("modelo", "ptwiki-articlequality")
    if not isinstance(modelo, str) or not modelo.strip():
        raise ValueError("filtro_qualidade.modelo deve ser texto não vazio")
    max_falhas = filtro.get("falhas_consecutivas_max", 3)
    if (isinstance(max_falhas, bool) or not isinstance(max_falhas, int)
            or max_falhas <= 0):
        raise ValueError("falhas_consecutivas_max deve ser um inteiro positivo")
    return {
        "ativar": ativo,
        "classe_minima": classe,
        "timeout": timeout,
        "backend": backend,
        "modelo": modelo.strip(),
        "falhas_consecutivas_max": max_falhas,
    }


def _extrair_previsao(dados, revid):
    try:
        return dados["ptwiki"]["scores"][str(revid)]["articlequality"]["score"]["prediction"]
    except (KeyError, TypeError):
        pass
    try:
        return dados["prediction"]
    except (KeyError, TypeError):
        return None


def interpretar_resposta(dados, revid):
    previsao = _extrair_previsao(dados, revid)
    if previsao is None:
        return None, "resposta sem previsão articlequality"
    texto = str(previsao).strip()
    if texto.isdigit() and texto in {"1", "2", "3", "4", "5", "6"}:
        return int(texto), None
    classe = _NOMES_CLASSE.get(texto.casefold())
    if classe is not None:
        return classe, None
    return None, f"classe articlequality desconhecida: {texto}"


def avaliar_qualidade(sessao, revid, config):
    """Devolve `(classe ordinal, erro)` para uma revisão."""
    if revid is None:
        return None, "ID da revisão ausente"
    url = f"{BACKEND_URL}/{config['modelo']}:predict"
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("WIKIMEDIA_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    tentativas = 2
    for tentativa in range(tentativas):
        try:
            resposta = sessao.post(
                url, json={"rev_id": revid}, headers=headers, timeout=config["timeout"],
            )
            status = getattr(resposta, "status_code", 200)
            if status == 429 and tentativa == 0:
                retry = getattr(resposta, "headers", {}).get("Retry-After", 0)
                try:
                    espera = min(max(float(retry), 0), 30)
                except (TypeError, ValueError):
                    espera = 0
                if espera:
                    time.sleep(espera)
                continue
            if status >= 500 and status < 600 and tentativa == 0:
                time.sleep(0.2)
                continue
            resposta.raise_for_status()
            return interpretar_resposta(resposta.json(), revid)
        except requests.Timeout as e:
            if tentativa == 0:
                time.sleep(0.2)
                continue
            return None, str(e)
        except (requests.RequestException, ValueError) as e:
            return None, str(e)
    return None, "Lift Wing indisponível após nova tentativa"


class FiltroQualidade:
    """Estado do filtro durante uma edição inteira."""

    def __init__(self, cfg):
        self.config = validar_config(cfg)
        self.ativo = self.config["ativar"]
        self.classe_minima = CLASSES_QUALIDADE[self.config["classe_minima"]]
        self.falhas_consecutivas = 0
        self.disjuntor_acionado = False
        self._avisou_disjuntor = False
        self.avaliados = 0
        self.aprovados = 0
        self.reprovados = 0
        self.falhas = 0
        self.sem_filtro = []

    def aceitavel(self, sessao, art):
        if not self.ativo:
            return True
        if self.disjuntor_acionado:
            self._registrar_sem_filtro(art["titulo"])
            return True
        self.avaliados += 1
        classe, erro = avaliar_qualidade(sessao, art.get("revid"), self.config)
        if erro:
            self.falhas += 1
            self.falhas_consecutivas += 1
            if self.falhas_consecutivas >= self.config["falhas_consecutivas_max"]:
                self.disjuntor_acionado = True
                if not self._avisou_disjuntor:
                    logger.warning(
                        "FILTRO DE QUALIDADE INDISPONÍVEL — aceitando candidatos sem filtro "
                        "pelo restante desta edição"
                    )
                    self._avisou_disjuntor = True
            self._registrar_sem_filtro(art["titulo"])
            logger.warning(
                "Lift Wing indisponível para '%s'; aceitando candidato sem filtro: %s",
                art["titulo"], erro,
            )
            return True
        self.falhas_consecutivas = 0
        if classe is not None and classe >= self.classe_minima:
            self.aprovados += 1
            return True
        self.reprovados += 1
        return False

    def _registrar_sem_filtro(self, titulo):
        if titulo not in self.sem_filtro:
            self.sem_filtro.append(titulo)

    def relatorio(self):
        return {
            "backend": self.config["backend"],
            "classe_minima": self.config["classe_minima"],
            "avaliados": self.avaliados,
            "aprovados": self.aprovados,
            "reprovados": self.reprovados,
            "falhas": self.falhas,
            "disjuntor_acionado": self.disjuntor_acionado,
            "sem_filtro": list(self.sem_filtro),
        }
