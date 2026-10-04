"""Seções vazias e controle: capítulo placeholder, bloco da Nota de controle, relatório JSON e resumo no stdout."""
import datetime as dt
import html
import json

from .config import resolver_caminho


def _fonte_txt(f):
    return f["fonte"] + (f" ({f['motivo']})" if f["motivo"] else "")


def html_secao_vazia(secao):
    esperadas = "; ".join(html.escape(_fonte_txt(f)) for f in secao["fontes"])
    return (f'<p class="tema">{html.escape(secao["nome"])}</p><h1>Sem itens nesta edição</h1>'
            f'<p>Nenhuma das fontes desta seção rendeu itens. Fontes esperadas: {esperadas}.</p>')


def html_estrutura(secoes):
    """Bloco "Estrutura da edição", anexado à Nota de controle."""
    partes = ["<h2>Estrutura da edição</h2>"]
    for s in secoes:
        n = len(s["itens"])
        lis = "".join(
            f"<li>{html.escape(f['fonte'])}: {f['itens']} item(ns)"
            + (f" — sem item: {html.escape(f['motivo'])}" if f["motivo"] else "") + "</li>"
            for f in s["fontes"])
        aviso = " <b>(vazia)</b>" if n == 0 else ""
        partes.append(f"<h3>{html.escape(s['nome'])}{aviso}</h3>"
                      f"<p><small>ordem {html.escape(s['ordem'])} · {n} item(ns)</small></p><ul>{lis}</ul>")
    return "".join(partes)


def dados_relatorio(secoes, data, numero_edicao=None, arquivo=None, qualidade=None, arquivados=None):
    return {
        "data": data.isoformat(),
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "numero_edicao": numero_edicao,
        "arquivo": arquivo,
        "secoes": [{"nome": s["nome"], "ordem": s["ordem"], "itens": len(s["itens"]),
                    "vazia": not s["itens"],
                    "fontes": [{"fonte": f["fonte"], "itens": f["itens"], "motivo": f["motivo"]}
                               for f in s["fontes"]]} for s in secoes],
        "fontes_sem_item": [{"secao": s["nome"], "fonte": f["fonte"], "motivo": f["motivo"]}
                            for s in secoes for f in s["fontes"] if not f["itens"]],
        "qualidade": qualidade or {},
        "arquivados": list(arquivados or []),
    }


def gravar_relatorio(rcfg, dados, nome_base):
    """Grava `<pasta>/<nome_base>.relatorio.json` (atômico). Devolve o caminho, ou None se desativado."""
    if not rcfg.get("ativar", True):
        return None
    pasta = resolver_caminho(rcfg.get("pasta", "relatorios"))
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome_base}.relatorio.json"
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)
    return caminho


def resumo_texto(secoes, qualidade=None):
    """Linhas para o stdout: itens por seção, com aviso destacado nas vazias."""
    linhas = ["Seções:"]
    for s in secoes:
        det = ", ".join(f"{f['fonte']} {f['itens']}" for f in s["fontes"])
        if s["itens"]:
            linhas.append(f"  {s['nome']}: {len(s['itens'])} item(ns)  [{det}]")
        else:
            motivos = "; ".join(f"{f['fonte']}: {f['motivo']}" for f in s["fontes"])
            linhas.append(f"  !! {s['nome']}: VAZIA — {motivos}")
    if qualidade:
        linhas.append(
            f"Qualidade: {qualidade['backend']} · classe mínima {qualidade['classe_minima']} · "
            f"{qualidade['avaliados']} avaliados, {qualidade['aprovados']} aprovados, "
            f"{qualidade['reprovados']} reprovados, {qualidade['falhas']} falhas"
        )
        if qualidade["sem_filtro"]:
            linhas.append("  !! Aceitos sem filtro: " + ", ".join(qualidade["sem_filtro"]))
    return "\n".join(linhas)
