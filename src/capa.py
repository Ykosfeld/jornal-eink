#!/usr/bin/env python3
"""Capa do jornal: mapa topográfico com faixas de cinza e curvas de nível.

A semente vem dos pageids dos artigos + data, então a capa é uma "impressão digital" da edição.
O nome do jornal NÃO entra na semente: renomear o jornal não altera o desenho de edições futuras.
"""
import datetime as dt
import hashlib
import html
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LARGURA, ALTURA = 480, 800
TITULO_PROVISORIO = "Jornal Semanal"   # usado só nos testes; no gerador vem de config.yaml (`titulo`)

FONTE_NEGRITO = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
FONTE_NORMAL = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"


# ------------------------------------------------------------------ semente

def _hash_int(texto, n=8):
    return int.from_bytes(hashlib.sha256(texto.encode()).digest()[:n], "big")


def semente_da_edicao(pageids, data):
    """Determinística e independente da ordem dos artigos. (Não usar hash(): é aleatorizado.)"""
    base = "|".join(str(p) for p in sorted(pageids)) + "|" + data.isoformat()
    return _hash_int(base)


# ------------------------------------------------------------------ relevo

def _ruido_gradiente(rng, h, w, celula):
    """Ruído de gradiente (Perlin) vetorizado — sem o viés de grade do value noise."""
    gh, gw = h // celula + 3, w // celula + 3
    ang = rng.random((gh, gw)) * 2 * np.pi
    gx, gy = np.cos(ang), np.sin(ang)
    ys, xs = np.arange(h) / celula, np.arange(w) / celula
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]

    def fade(t):
        return t * t * t * (t * (t * 6 - 15) + 10)

    def canto(dy, dx):
        gxx = gx[y0 + dy][:, x0 + dx]
        gyy = gy[y0 + dy][:, x0 + dx]
        return gxx * (fx - dx) + gyy * (fy - dy)

    u, v = fade(fx), fade(fy)
    topo = canto(0, 0) * (1 - u) + canto(0, 1) * u
    base = canto(1, 0) * (1 - u) + canto(1, 1) * u
    return topo * (1 - v) + base * v


def _campo(seed, pageids):
    rng = np.random.default_rng(seed)
    celula_base = int(rng.integers(120, 260))
    oitavas = int(rng.integers(3, 5))               # 3 ou 4 (antes ia até 5 e ficava agitado)
    persist = float(rng.uniform(0.38, 0.50))        # antes ia até 0,62
    campo, amp, cel = np.zeros((ALTURA, LARGURA)), 1.0, celula_base
    for _ in range(oitavas):
        campo += amp * _ruido_gradiente(rng, ALTURA, LARGURA, max(cel, 16))
        amp *= persist
        cel //= 2
    campo = (campo - campo.min()) / (campo.max() - campo.min())

    # cada artigo vira uma colina (ou vale) em posição própria
    yy, xx = np.mgrid[0:ALTURA, 0:LARGURA]
    for pid in pageids:
        h = _hash_int(f"pico:{pid}")
        px = (h & 0xFFFF) / 0xFFFF * LARGURA
        py = ((h >> 16) & 0xFFFF) / 0xFFFF * ALTURA
        raio = 60 + ((h >> 32) & 0xFF) / 255 * 90
        sinal = 1 if (h >> 40) & 1 else -1
        campo += sinal * 0.30 * np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / (2 * raio ** 2))

    campo = (campo - campo.min()) / (campo.max() - campo.min())
    return campo, rng, {"celula_base": celula_base, "oitavas": oitavas, "persistencia": round(persist, 3)}


def _dilatar(m, n):
    out = m.copy()
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            if dx * dx + dy * dy <= n * n + 1:
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def _curvas(q, indice_a_cada):
    """q = matriz de níveis inteiros. Devolve máscaras das curvas finas e das mestras."""
    fina = np.zeros(q.shape, bool)
    mestra = np.zeros(q.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        viz = np.roll(np.roll(q, -dy, 0), -dx, 1)
        borda = q != viz
        fina |= borda
        mestra |= borda & (np.maximum(q, viz) % indice_a_cada == 0)
    for m in (fina, mestra):
        m[-1, :] = False
        m[:, -1] = False
    return fina, _dilatar(mestra, 1)


# ------------------------------------------------------------------ texto

def _fonte(tamanho, negrito=True):
    try:
        return ImageFont.truetype(FONTE_NEGRITO if negrito else FONTE_NORMAL, tamanho)
    except OSError:
        try:
            return ImageFont.load_default(tamanho)   # Pillow >= 10.1
        except TypeError:
            return ImageFont.load_default()


def _quebrar(d, texto, fonte, larg_max):
    linhas, atual = [], ""
    for p in texto.split():
        tentativa = f"{atual} {p}".strip()
        if d.textlength(tentativa, font=fonte) <= larg_max or not atual:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = p
    return linhas + [atual]


def _ajustar_titulo(d, titulo, larg_max, max_linhas=3):
    """Maior tamanho de fonte em que o título cabe na caixa (aguenta nomes futuros mais longos)."""
    texto = titulo.upper()
    for tam in range(40, 15, -2):
        f = _fonte(tam)
        linhas = _quebrar(d, texto, f, larg_max)
        if len(linhas) <= max_linhas and all(d.textlength(l, font=f) <= larg_max for l in linhas):
            return f, tam, linhas
    f = _fonte(16)
    return f, 16, _quebrar(d, texto, f, larg_max)


def _centro(d, y, texto, fonte):
    d.text(((LARGURA - d.textlength(texto, font=fonte)) / 2, y), texto, font=fonte, fill=0)


# ------------------------------------------------------------------ API

def gerar_capa(titulo, data, pageids, numero_edicao=None):
    """Devolve (bytes PNG, info). `info` alimenta a página de controle no fim do epub."""
    pageids = list(pageids)
    seed = semente_da_edicao(pageids, data)
    campo, rng, params = _campo(seed, pageids)

    niveis = int(rng.integers(22, 37))
    faixas = int(rng.integers(4, 8))                 # nº de tons de cinza
    invertido = bool(rng.random() < 0.25)            # 25%: baixadas escuras (lagos), topos claros
    q = np.floor(campo * niveis).clip(0, niveis - 1).astype(int)

    # faixa de cinza derivada do nível: a troca de tom sempre cai exatamente sobre uma curva
    banda = (q * faixas // niveis)
    t = banda / (faixas - 1)
    if invertido:
        t = 1 - t
    cinza = 250 - t * (250 - 168)                    # 250 (claro) … 168 (escuro)

    fina, mestra = _curvas(q, indice_a_cada=5)
    img = cinza.astype(np.uint8)
    img[fina] = 70
    img[mestra] = 0

    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)

    # cabeçalho: caixa branca com moldura dupla; altura se adapta ao número de linhas do título
    x0, x1, y0 = 30, LARGURA - 30, 56
    fonte_t, tam, linhas = _ajustar_titulo(d, titulo, larg_max=(x1 - x0) - 40)
    alt_linha = int(tam * 1.22)
    y_regua = y0 + 22 + alt_linha * len(linhas) + 12
    y1 = y_regua + 46
    d.rectangle([x0, y0, x1, y1], fill=255, outline=0, width=3)
    d.rectangle([x0 + 7, y0 + 7, x1 - 7, y1 - 7], outline=0, width=1)
    for i, l in enumerate(linhas):
        _centro(d, y0 + 22 + i * alt_linha, l, fonte_t)
    d.line([x0 + 40, y_regua, x1 - 40, y_regua], fill=0, width=1)
    rotulo = data.strftime("%d/%m/%Y")
    if numero_edicao:
        rotulo = f"Nº {numero_edicao}  ·  {rotulo}"
    _centro(d, y_regua + 12, rotulo, _fonte(17, negrito=False))
    d.rectangle([0, 0, LARGURA - 1, ALTURA - 1], outline=0, width=3)

    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    info = {"semente": seed, "niveis": niveis, "faixas_cinza": faixas, "invertido": invertido,
            "n_artigos": len(pageids), "data": data.isoformat(), **params}
    return buf.getvalue(), info


def html_controle(info, artigos=None):
    """Corpo HTML da página de controle (último capítulo do epub). `artigos`: lista de (tema, título, pageid)."""
    linhas = [
        ("Semente", f'{info["semente"]}'),
        ("Curvas de nível", f'{info["niveis"]} (mestra a cada 5)'),
        ("Faixas de cinza", f'{info["faixas_cinza"]}' + (" — invertido" if info["invertido"] else "")),
        ("Oitavas de ruído", f'{info["oitavas"]}'),
        ("Persistência", f'{info["persistencia"]}'),
        ("Escala base", f'{info["celula_base"]} px'),
        ("Artigos na edição", f'{info["n_artigos"]}'),
    ]
    tab = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in linhas)
    lista = ""
    if artigos:
        itens = "".join(f"<li>{html.escape(t)}: {html.escape(a)} <small>(id {p})</small></li>"
                        for t, a, p in artigos)
        lista = f"<h2>Artigos que geraram a capa</h2><ul>{itens}</ul>"
    return (f'<h1>Nota de controle</h1>'
            f'<p>A capa desta edição foi gerada a partir dos identificadores dos artigos e da data '
            f'({html.escape(info["data"])}). Os mesmos artigos e a mesma data produzem sempre o mesmo mapa.</p>'
            f'<table>{tab}</table>{lista}')


if __name__ == "__main__":
    import random
    import sys
    saida = Path(sys.argv[1] if len(sys.argv) > 1 else "amostras")
    saida.mkdir(exist_ok=True)
    hoje = dt.date(2026, 10, 2)
    for i in range(6):
        r = random.Random(i)
        ids = [r.randint(1_000, 6_000_000) for _ in range(11)]
        dados, info = gerar_capa(TITULO_PROVISORIO, hoje + dt.timedelta(weeks=i), ids, numero_edicao=i + 1)
        (saida / f"capa_{i + 1}.png").write_bytes(dados)
        print(i + 1, info)
