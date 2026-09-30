"""Histórico de itens já publicados (para nunca repetir entre edições)."""
import datetime as dt
import json
import sys

from .config import resolver_caminho


def caminho_historico(hcfg):
    return resolver_caminho(hcfg["arquivo"])


def carregar_historico(caminho, esquecer_semanas, hoje):
    """Lê o histórico; descarta registros mais antigos que `esquecer_semanas` (0 = nunca esquece)."""
    if not caminho.exists():
        return []
    try:
        registros = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Histórico corrompido ({caminho}): {e}\nCorrija ou renomeie o arquivo e rode de novo.")
    if esquecer_semanas > 0:
        limite = hoje - dt.timedelta(weeks=esquecer_semanas)
        registros = [r for r in registros if dt.date.fromisoformat(r["data"]) >= limite]
    return registros


def salvar_historico(caminho, registros):
    """Grava de forma atômica (arquivo temporário + rename), para não corromper se cair no meio."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(registros, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)
