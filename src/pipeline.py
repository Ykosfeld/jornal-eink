"""Orquestração: coleta de todas as seções -> epub -> histórico."""
import datetime as dt
import random
import sys

import requests

from .config import resolver_caminho
from .epub_builder import montar_epub
from .escolha import coletar_escolhas, consumir_fila
from .feeds import coletar_noticias
from .historico import caminho_historico, carregar_historico, salvar_historico
from .wikipedia import sortear_artigo


def numero_da_edicao(cfg, hoje):
    """Nº da edição = semanas desde `primeira_edicao` (config) + 1. Sem estado; None se não configurado."""
    primeira = cfg.get("primeira_edicao")
    if isinstance(primeira, str):
        primeira = dt.date.fromisoformat(primeira)
    if not primeira or hoje < primeira:
        return None
    return (hoje - primeira).days // 7 + 1


def coletar_curiosidades(sessao, cfg, usados, usados_ids, rng, hoje):
    """Um artigo da Wikipedia por tema. Devolve (artigos, registros_novos, temas_pulados)."""
    wcfg = {**cfg["wikipedia"], "imagens": cfg.get("imagens", {"ativar": False})}
    artigos, novos, pulados = [], [], []
    for tema, cats in cfg["temas"].items():
        print(f"[{tema}] sorteando...", end=" ", flush=True)
        try:
            art = sortear_artigo(sessao, wcfg, cats, usados, usados_ids, rng)
        except requests.RequestException as e:
            print(f"falha de rede ({e})")
            pulados.append(tema)
            continue
        if art is None:
            print("nenhum artigo novo encontrado — tema pulado")
            pulados.append(tema)
            continue
        usados.add(art["titulo"])
        usados_ids.add(art["pageid"])
        artigos.append((tema, art))
        novos.append({"pageid": art["pageid"], "titulo": art["titulo"],
                      "tema": tema, "data": hoje.isoformat()})
        extra = ", com imagem" if art.get("imagem") else ""
        print(f'{art["titulo"]}  ({art["caminho"]}, {art["chars"]} chars{extra})')
    return artigos, novos, pulados


def coletar_secao_noticias(sessao, cfg, usados_urls, agora):
    ncfg = cfg.get("noticias") or {}
    if not (ncfg.get("ativar") and (ncfg.get("feeds") or ncfg.get("opml"))):
        return []
    print("\n[Notícias] coletando...")
    return coletar_noticias(sessao, ncfg, usados_urls, agora)


def coletar_secao_dw(sessao, cfg, usados_urls, agora):
    dcfg = cfg.get("dw") or {}
    if not (dcfg.get("ativar") and dcfg.get("feed")):
        return []
    print("\n[DW] coletando...")
    return coletar_noticias(sessao, {
        "feeds": [{"nome": "DW · Top-Thema mit Vokabeln", "url": dcfg["feed"]}],
        "por_feed": dcfg.get("quantidade", 3), "max_total": dcfg.get("quantidade", 3),
        "dias": dcfg.get("dias", 14), "max_caracteres": dcfg.get("max_caracteres", 12000),
        "min_caracteres": dcfg.get("min_caracteres", 800), "lang": "de",
        "sufixo_url": dcfg.get("sufixo_url"),
        "extrator": "dw",
    }, usados_urls, agora)


def gerar_edicao(sessao, cfg, semente=None, usar_hist=True, escolhas=()):
    hoje = dt.date.today()
    agora = dt.datetime.now(dt.timezone.utc)

    hcfg = {"arquivo": "historico.json", "esquecer_apos_semanas": 0, **cfg.get("historico", {})}
    caminho_hist = caminho_historico(hcfg)
    registros = carregar_historico(caminho_hist, hcfg["esquecer_apos_semanas"], hoje) if usar_hist else []
    print(f"Histórico: {len(registros)} item(ns) já publicado(s)" if usar_hist
          else "Histórico desativado (--sem-historico)")
    # Registros da Wikipedia têm pageid; os de notícias/DW/escolha têm url.
    usados = {r["titulo"] for r in registros if "pageid" in r}
    usados_ids = {r["pageid"] for r in registros if "pageid" in r}
    usados_urls = {r["url"] for r in registros if "url" in r}

    # Escolha do editor primeiro: o que foi escolhido à mão não pode ser sorteado de novo
    # (nem repetido nas notícias). Não consome o `rng`, então --semente continua reprodutível.
    escolha_itens, fila = coletar_escolhas(sessao, cfg, escolhas, registros)
    for it in escolha_itens:
        usados_urls.add(it["url"])
        if "pageid" in it:                       # só artigos da wiki do sorteio automático
            usados.add(it["titulo"])
            usados_ids.add(it["pageid"])

    rng = random.Random(semente)
    artigos, novos, pulados = coletar_curiosidades(sessao, cfg, usados, usados_ids, rng, hoje)
    noticias = coletar_secao_noticias(sessao, cfg, usados_urls, agora)
    dw = coletar_secao_dw(sessao, cfg, usados_urls, agora)

    novos += [{"tipo": "escolha", "url": it["url"], "titulo": it["titulo"], "fonte": it["fonte"],
               "data": hoje.isoformat(), **({"pageid": it["pageid"]} if "pageid" in it else {})}
              for it in escolha_itens]
    novos += [{"tipo": tipo, "url": it["url"], "titulo": it["titulo"],
               "fonte": it["fonte"], "data": hoje.isoformat()}
              for tipo, itens in (("noticia", noticias), ("dw", dw)) for it in itens]

    if not (escolha_itens or artigos or noticias or dw):
        sys.exit("Nada obtido; epub não gerado.")

    destino = resolver_caminho(cfg["saida"]) / f"jornal_{hoje.isoformat()}.epub"
    info_capa = montar_epub(cfg, artigos, hoje, destino, numero_da_edicao(cfg, hoje),
                            noticias, dw, escolhas=escolha_itens)
    if usar_hist:
        salvar_historico(caminho_hist, registros + novos)   # só depois do epub gerado com sucesso
        consumir_fila(fila)                                 # idem: a fila só esvazia após publicar
    elif fila["publicados"]:
        print("(--sem-historico: a fila de escolhas foi mantida)")

    print(f"\nEpub gerado: {destino}  ({len(escolha_itens)} escolha(s) do editor, {len(noticias)} notícias, "
          f"{len(artigos)} curiosidades, {len(dw)} da DW)")
    print(f"Capa: semente {info_capa['semente']}, {info_capa['niveis']} níveis, "
          f"{info_capa['faixas_cinza']} faixas de cinza")
    if pulados:
        print("ATENÇÃO — temas sem artigo nesta edição: " + ", ".join(pulados)
              + "\n  (categorias esgotadas ou falha de rede; considere adicionar mais raízes no config.yaml)")
    return destino