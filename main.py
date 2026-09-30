#!/usr/bin/env python3
"""Jornal Semanal (.epub) — Notícias + Curiosidades (Wikipedia) + Deutsch üben (DW) + capa generativa.

Uso:
    python main.py                     # gera a edição da semana
    python main.py --validar           # testa as categorias da Wikipedia do config
    python main.py --validar-feeds     # testa os feeds (notícias e DW)
    python main.py --semente 42 --sem-historico   # teste reprodutível, sem mexer no histórico
"""
import argparse

from src.config import carregar_config, criar_sessao
from src.feeds import validar_feeds
from src.pipeline import gerar_edicao
from src.wikipedia import validar_categorias


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--validar", action="store_true", help="só testa as categorias do config")
    ap.add_argument("--validar-feeds", action="store_true", help="só testa os feeds (notícias e DW)")
    ap.add_argument("--semente", type=int, help="semente do sorteio (reprodutível)")
    ap.add_argument("--sem-historico", action="store_true",
                    help="não lê nem grava o histórico (use em testes)")
    args = ap.parse_args()

    cfg = carregar_config(args.config)
    sessao = criar_sessao()

    if args.validar:
        validar_categorias(sessao, cfg)
    elif args.validar_feeds:
        ncfg, dcfg = cfg.get("noticias") or {}, cfg.get("dw") or {}
        validar_feeds(sessao, [ncfg, {"feeds": [dcfg["feed"]]} if dcfg.get("feed") else {}])
    else:
        gerar_edicao(sessao, cfg, semente=args.semente, usar_hist=not args.sem_historico)


if __name__ == "__main__":
    main()