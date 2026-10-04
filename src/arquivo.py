"""Rotação opcional das edições publicadas na pasta de saída."""
import datetime as dt
import re
from pathlib import Path

_PADRAO = re.compile(r"^jornal_(\d{4}-\d{2}-\d{2})\.epub$")


def validar_config(cfg):
    """Valida e normaliza `arquivo_morto`."""
    config = {"ativar": False, "subpasta": "anteriores", "manter_na_raiz": 1, **(cfg or {})}
    if not isinstance(config["ativar"], bool):
        raise ValueError("arquivo_morto.ativar deve ser booleano")
    subpasta = config["subpasta"]
    if (not isinstance(subpasta, str) or not subpasta or subpasta in {".", ".."}
            or "/" in subpasta or "\\" in subpasta or ".." in subpasta):
        raise ValueError("arquivo_morto.subpasta deve ser um nome simples sem separadores ou '..'")
    manter = config["manter_na_raiz"]
    if isinstance(manter, bool) or not isinstance(manter, int) or manter < 1:
        raise ValueError("arquivo_morto.manter_na_raiz deve ser um inteiro >= 1")
    return config


def arquivar(saida, recem_gerado, cfg):
    """Move edições antigas e devolve seus nomes; falhas de move são avisos não fatais."""
    config = validar_config(cfg)
    if not config["ativar"]:
        return []
    saida = Path(saida)
    candidatos = []
    for caminho in saida.iterdir():
        if not caminho.is_file() or caminho == recem_gerado:
            continue
        match = _PADRAO.fullmatch(caminho.name)
        if match:
            try:
                data = dt.date.fromisoformat(match.group(1))
            except ValueError:
                continue
            candidatos.append((data, caminho))
    candidatos.sort(key=lambda item: item[0], reverse=True)
    destino = saida / config["subpasta"]
    arquivados = []
    for _, caminho in candidatos[config["manter_na_raiz"] - 1:]:
        try:
            destino.mkdir(parents=True, exist_ok=True)
            caminho.replace(destino / caminho.name)
            arquivados.append(caminho.name)
        except OSError as e:
            print(f"Aviso: não foi possível arquivar {caminho.name}: {e}")
    return arquivados
