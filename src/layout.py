"""Layout do jornal: seções × fontes (padrão, validação, ordenação). Sem rede, sem dependências externas."""
import difflib
from itertools import zip_longest

# Fontes que não são temas da Wikipédia. Não podem ser usadas como nome de tema.
RESERVADAS = ("noticias", "dw", "editor", "letterboxd", "almanaque")
ORDENS = ("sequencial", "intercalar")


class ErroLayout(ValueError):
    """Layout inválido. A mensagem lista todos os problemas encontrados de uma vez."""


# ---------------------------------------------------------------- padrão

def layout_padrao(cfg):
    """Layout equivalente ao comportamento anterior à feature (único lugar onde ele é definido)."""
    temas = list((cfg.get("temas") or {}).keys())
    secoes = [
        {"nome": "Escolha do Editor", "fontes": ["editor"]},
        {"nome": "Notícias", "fontes": ["noticias"]},
    ]
    if temas:
        secoes.append({"nome": "Curiosidades", "fontes": temas})
    secoes.append({"nome": "Deutsch üben", "fontes": ["dw"]})
    return secoes


# ---------------------------------------------------------------- validação

def _sugestao(fonte, conhecidas):
    mapa = {c.lower(): c for c in conhecidas}
    achado = difflib.get_close_matches(fonte.lower(), list(mapa), n=1, cutoff=0.6)
    return f" Você quis dizer '{mapa[achado[0]]}'?" if achado else ""


def validar_layout(cfg, secoes):
    """Valida `secoes` e devolve a versão normalizada: [{"nome", "fontes", "ordem"}].

    Levanta ErroLayout (com todos os problemas) se algo estiver errado.
    """
    erros = []
    temas = list((cfg.get("temas") or {}).keys())
    for t in temas:
        if t in RESERVADAS:
            erros.append(f"tema '{t}': nome reservado (reservados: {', '.join(RESERVADAS)}); renomeie o tema em `temas:`")
    conhecidas = temas + [r for r in RESERVADAS if r not in temas]

    if not isinstance(secoes, list) or not secoes:
        raise ErroLayout("Layout inválido:\n  - `secoes` deve ser uma lista com pelo menos uma seção")

    vistas = {}     # fonte -> nome da seção onde apareceu primeiro
    saida = []
    for i, s in enumerate(secoes, 1):
        if not isinstance(s, dict):
            erros.append(f"seção #{i}: deve ser um mapa com 'nome' e 'fontes'")
            continue
        nome = s.get("nome")
        nome_ok = isinstance(nome, str) and nome.strip()
        rot = f"seção '{nome.strip()}'" if nome_ok else f"seção #{i}"
        if not nome_ok:
            erros.append(f"{rot}: falta o campo 'nome'")

        ordem = s.get("ordem")
        if ordem is None:
            ordem = "sequencial"
        if ordem not in ORDENS:
            erros.append(f"{rot}: ordem '{ordem}' inválida (use {' ou '.join(ORDENS)})")

        fontes = s.get("fontes")
        if not isinstance(fontes, list) or not fontes:
            erros.append(f"{rot}: 'fontes' deve ser uma lista não vazia")
            continue
        for f in fontes:
            if not isinstance(f, str):
                erros.append(f"{rot}: fonte {f!r} inválida (esperado um nome de tema ou fonte reservada)")
                continue
            if f not in conhecidas:
                erros.append(f"{rot}: fonte '{f}' não existe (nem tema em `temas:`, nem fonte reservada).{_sugestao(f, conhecidas)}")
                continue
            if f in vistas:
                onde = "na mesma seção" if vistas[f] == rot else f"também na {vistas[f]}"
                erros.append(f"{rot}: fonte '{f}' repetida ({onde}); cada fonte só pode aparecer uma vez")
            else:
                vistas[f] = rot
        if nome_ok and ordem in ORDENS:
            saida.append({"nome": nome.strip(), "fontes": [f for f in fontes if isinstance(f, str)],
                          "ordem": ordem})

    if erros:
        raise ErroLayout("Layout inválido:\n" + "\n".join(f"  - {e}" for e in erros))
    return saida


def resolver_layout(cfg):
    """Resolve e valida `secoes`; garante a seção Almanaque ao final se omitida."""
    bruto = cfg.get("secoes")
    if bruto is None:
        bruto = layout_padrao(cfg)
    secoes = validar_layout(cfg, bruto)
    if "almanaque" not in fontes_usadas(secoes):
        secoes.append({"nome": "Almanaque", "fontes": ["almanaque"], "ordem": "sequencial"})
    return secoes


def fontes_usadas(secoes):
    return {f for s in secoes for f in s["fontes"]}


# ---------------------------------------------------------------- ordenação / montagem

_VAZIO = object()


def ordenar_itens(listas, ordem):
    """`listas`: uma lista de itens por fonte, na ordem de `fontes`."""
    if ordem == "intercalar":
        return [x for linha in zip_longest(*listas, fillvalue=_VAZIO) for x in linha if x is not _VAZIO]
    return [x for l in listas for x in l]


def montar_secoes(secoes, coletado, motivos=None):
    """Resolve cada seção: itens ordenados + contagem por fonte (com motivo quando a fonte rendeu 0)."""
    motivos = motivos or {}
    saida = []
    for s in secoes:
        listas = [coletado.get(f, []) for f in s["fontes"]]
        fontes = [{"fonte": f, "itens": len(l), "motivo": None if l else motivos.get(f, "sem itens")}
                  for f, l in zip(s["fontes"], listas)]
        saida.append({"nome": s["nome"], "ordem": s["ordem"], "fontes": fontes,
                      "itens": ordenar_itens(listas, s["ordem"])})
    return saida


def imprimir_layout(secoes):
    """Resumo para `--validar-layout`: seção -> fontes -> modo de ordem."""
    for s in secoes:
        print(f"{s['nome']}  [ordem: {s['ordem']}]")
        for f in s["fontes"]:
            print(f"    - {f}")
    print(f"\nLayout válido: {len(secoes)} seção(ões), {len(fontes_usadas(secoes))} fonte(s).")
