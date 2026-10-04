"""Cálculo uniforme de tempo estimado de leitura."""
import math

from bs4 import BeautifulSoup


def validar_config(cfg):
    valor = (cfg or {}).get("caracteres_por_minuto", 1000)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ValueError("leitura.caracteres_por_minuto deve ser um inteiro positivo")
    return valor


def minutos_de_leitura(html_ou_texto, caracteres_por_minuto=1000):
    """Conta caracteres de texto sem tags, com mínimo de um minuto."""
    if isinstance(caracteres_por_minuto, bool) or caracteres_por_minuto <= 0:
        raise ValueError("caracteres_por_minuto deve ser positivo")
    texto = BeautifulSoup(str(html_ou_texto or ""), "lxml").get_text()
    return max(1, math.ceil(len(texto) / caracteres_por_minuto))
