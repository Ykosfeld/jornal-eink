"""Fórmulas: converte o LaTeX que a Wikipédia entrega em MathML."""
import html
import re

from latex2mathml.converter import convert as latex_para_mathml

# A Wikipédia entrega fórmulas como "{\displaystyle ...}" (chaves aninhadas, por isso não dá para usar regex simples)
_ABRE_FORMULA = re.compile(r"\{\s*\\(?:displaystyle|textstyle|scriptstyle)\b")


def _fim_do_bloco(texto, inicio):
    """Dado o índice logo após a '{' de abertura, devolve o índice da '}' que a fecha (ou -1)."""
    profundidade, i = 1, inicio
    while i < len(texto):
        c = texto[i]
        if c == "\\":
            i += 2          # \{ e \} não contam
            continue
        if c == "{":
            profundidade += 1
        elif c == "}":
            profundidade -= 1
            if profundidade == 0:
                return i
        i += 1
    return -1


def converter_formulas(fragmento, mathml=True):
    """Troca cada '{\\displaystyle ...}' por <math> (ou, se falhar/desativado, por <i>LaTeX</i>)."""
    saida, pos = [], 0
    while True:
        m = _ABRE_FORMULA.search(fragmento, pos)
        if not m:
            saida.append(fragmento[pos:])
            break
        fim = _fim_do_bloco(fragmento, m.start() + 1)
        if fim < 0:                      # chaves desbalanceadas: deixa como está
            saida.append(fragmento[pos:])
            break
        saida.append(fragmento[pos:m.start()])
        latex = html.unescape(fragmento[m.end():fim]).strip()
        if latex:                        # fórmula vazia: descarta
            try:
                if not mathml:
                    raise ValueError
                mm = latex_para_mathml(latex)
                # alttext: leitores sem suporte a MathML ainda podem mostrar o texto
                mm = mm.replace("<math", f'<math alttext="{html.escape(latex, quote=True)}"', 1)
                saida.append(mm)
            except Exception:  # noqa: BLE001
                saida.append(f"<i>{html.escape(latex)}</i>")
        pos = fim + 1
    return "".join(saida)
