"""Configuração, caminhos e sessão HTTP compartilhados por todos os módulos."""
from pathlib import Path

import requests
import yaml

# Raiz do repositório (a pasta que contém main.py e config.yaml).
RAIZ = Path(__file__).resolve().parent.parent

HEADERS = {
    # A Wikimedia exige um User-Agent identificável. Troque pelo seu contato.
    "User-Agent": "JornalSemanalEink/0.1 (projeto pessoal; contato: yuri.kosfeld@gmail.com)"
}


def resolver_caminho(p):
    """Caminho relativo é interpretado a partir da raiz do repo (funciona igual no cron)."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else RAIZ / p


def carregar_config(caminho="config.yaml"):
    return yaml.safe_load(resolver_caminho(caminho).read_text(encoding="utf-8"))


def criar_sessao():
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
    return sessao
