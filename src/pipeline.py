"""Orquestração: layout -> coleta das fontes usadas -> seções -> epub -> histórico/relatório."""
import datetime as dt
import random
import sys

import requests

from .config import resolver_caminho
from .epub_builder import montar_epub
from .escolha import coletar_escolhas, consumir_fila
from .feeds import coletar_noticias
from .historico import caminho_historico, carregar_historico, salvar_historico
from .itens import item_curiosidade, item_editor, item_externo
from .layout import ErroLayout, fontes_usadas, montar_secoes, resolver_layout
from .relatorio import dados_relatorio, gravar_relatorio, resumo_texto
from .wikipedia import sortear_artigo


def numero_da_edicao(cfg, hoje):
    """Nº da edição = semanas desde `primeira_edicao` (config) + 1. Sem estado; None se não configurado."""
    primeira = cfg.get("primeira_edicao")
    if isinstance(primeira, str):
        primeira = dt.date.fromisoformat(primeira)
    if not primeira or hoje < primeira:
        return None
    return (hoje - primeira).days // 7 + 1


def coletar_curiosidades(sessao, cfg, usados, usados_ids, rng, hoje, temas=None):
    """Um artigo da Wikipedia por tema (`temas`: {tema: categorias}; padrão: todos de cfg["temas"]).

    Devolve (artigos, registros_novos, pulados), com `pulados` = {tema: motivo}.
    Os temas são sorteados na ordem de `cfg["temas"]` (não na das seções): --semente segue reprodutível.
    """
    wcfg = {**cfg["wikipedia"], "imagens": cfg.get("imagens", {"ativar": False})}
    temas = cfg["temas"] if temas is None else temas
    artigos, novos, pulados = [], [], {}
    for tema, cats in temas.items():
        print(f"[{tema}] sorteando...", end=" ", flush=True)
        try:
            art = sortear_artigo(sessao, wcfg, cats, usados, usados_ids, rng)
        except requests.RequestException as e:
            print(f"falha de rede ({e})")
            pulados[tema] = "falha de rede"
            continue
        if art is None:
            print("nenhum artigo novo encontrado — tema pulado")
            pulados[tema] = "esgotada"
            continue
        usados.add(art["titulo"])
        usados_ids.add(art["pageid"])
        artigos.append((tema, art))
        novos.append({"pageid": art["pageid"], "titulo": art["titulo"],
                      "tema": tema, "data": hoje.isoformat()})
        extra = ", com imagem" if art.get("imagem") else ""
        print(f'{art["titulo"]}  ({art["caminho"]}, {art["chars"]} chars{extra})')
    return artigos, novos, pulados


def _noticias_ativas(cfg):
    ncfg = cfg.get("noticias") or {}
    return bool(ncfg.get("ativar") and (ncfg.get("feeds") or ncfg.get("opml")))


def _dw_ativa(cfg):
    dcfg = cfg.get("dw") or {}
    return bool(dcfg.get("ativar") and dcfg.get("feed"))


def coletar_secao_noticias(sessao, cfg, usados_urls, agora):
    if not _noticias_ativas(cfg):
        return []
    print("\n[Notícias] coletando...")
    return coletar_noticias(sessao, cfg.get("noticias") or {}, usados_urls, agora)


def coletar_secao_dw(sessao, cfg, usados_urls, agora):
    if not _dw_ativa(cfg):
        return []
    dcfg = cfg.get("dw") or {}
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
    # Layout primeiro: qualquer erro de configuração falha antes de qualquer requisição de rede.
    try:
        layout = resolver_layout(cfg)
    except ErroLayout as e:
        sys.exit(str(e))
    usadas = fontes_usadas(layout)

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

    coletado, motivos = {}, {}

    # Escolha do editor primeiro: o que foi escolhido à mão não pode ser sorteado de novo
    # (nem repetido nas notícias). Não consome o `rng`, então --semente continua reprodutível.
    escolha_itens, fila = [], {"publicados": set()}
    if "editor" in usadas:
        escolha_itens, fila = coletar_escolhas(sessao, cfg, escolhas, registros)
        for it in escolha_itens:
            usados_urls.add(it["url"])
            if "pageid" in it:                       # só artigos da wiki do sorteio automático
                usados.add(it["titulo"])
                usados_ids.add(it["pageid"])
        coletado["editor"] = [item_editor(it) for it in escolha_itens]
        if not escolha_itens:
            motivos["editor"] = "fila vazia ou links com falha"
    elif escolhas:
        print("Aviso: --escolha ignorado, pois 'editor' não está em nenhuma seção do layout.")

    rng = random.Random(semente)
    temas_usados = {t: c for t, c in (cfg.get("temas") or {}).items() if t in usadas}
    artigos, novos, pulados = coletar_curiosidades(sessao, cfg, usados, usados_ids, rng, hoje, temas_usados)
    for tema, art in artigos:
        coletado[tema] = [item_curiosidade(tema, art)]
    motivos.update(pulados)

    noticias, dw = [], []
    if "noticias" in usadas:
        noticias = coletar_secao_noticias(sessao, cfg, usados_urls, agora)
        coletado["noticias"] = [item_externo("noticias", it) for it in noticias]
        if not noticias:
            motivos["noticias"] = "sem itens na janela" if _noticias_ativas(cfg) else "desativada"
    if "dw" in usadas:
        dw = coletar_secao_dw(sessao, cfg, usados_urls, agora)
        coletado["dw"] = [item_externo("dw", it) for it in dw]
        if not dw:
            motivos["dw"] = "sem itens na janela" if _dw_ativa(cfg) else "desativada"
    if "letterboxd" in usadas:
        motivos["letterboxd"] = "coletor não implementado"

    novos += [{"tipo": "escolha", "url": it["url"], "titulo": it["titulo"], "fonte": it["fonte"],
               "data": hoje.isoformat(), **({"pageid": it["pageid"]} if "pageid" in it else {})}
              for it in escolha_itens]
    novos += [{"tipo": tipo, "url": it["url"], "titulo": it["titulo"],
               "fonte": it["fonte"], "data": hoje.isoformat()}
              for tipo, itens in (("noticia", noticias), ("dw", dw)) for it in itens]

    if not any(coletado.values()):
        sys.exit("Nada obtido; epub não gerado.")

    secoes = montar_secoes(layout, coletado, motivos)
    # A semente da capa vem só dos artigos sorteados (não do editor/notícias/DW), como antes.
    curiosidades = [(tema, art["titulo"], art["pageid"]) for tema, art in artigos]

    destino = resolver_caminho(cfg["saida"]) / f"jornal_{hoje.isoformat()}.epub"
    numero = numero_da_edicao(cfg, hoje)
    info_capa = montar_epub(cfg, secoes, hoje, destino, numero, curiosidades)
    if usar_hist:
        salvar_historico(caminho_hist, registros + novos)   # só depois do epub gerado com sucesso
        consumir_fila(fila)                                 # idem: a fila só esvazia após publicar
    elif fila["publicados"]:
        print("(--sem-historico: a fila de escolhas foi mantida)")

    rcfg = {"ativar": True, "pasta": "relatorios", **(cfg.get("relatorio") or {})}
    rel = gravar_relatorio(rcfg, dados_relatorio(secoes, hoje, numero, destino.name), destino.stem)

    print(f"\nEpub gerado: {destino}  ({len(escolha_itens)} escolha(s) do editor, {len(noticias)} notícias, "
          f"{len(artigos)} curiosidades, {len(dw)} da DW)")
    print(f"Capa: semente {info_capa['semente']}, {info_capa['niveis']} níveis, "
          f"{info_capa['faixas_cinza']} faixas de cinza")
    print(resumo_texto(secoes))
    if rel:
        print(f"Relatório: {rel}")
    if pulados:
        print("ATENÇÃO — temas sem artigo nesta edição: "
              + ", ".join(f"{t} ({m})" for t, m in pulados.items())
              + "\n  (categorias esgotadas ou falha de rede; considere adicionar mais raízes no config.yaml)")
    return destino