"""Testes unitários para o módulo de geração do painel HTML estático (src/painel.py)."""
import json
from pathlib import Path
import tempfile
import unittest

from src.painel import (
    coletar_historico,
    coletar_relatorios,
    gerar_painel,
    renderizar_painel_html,
)


class TestPainel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp_dir.name)
        self.pasta_relatorios = self.raiz / "relatorios"
        self.pasta_relatorios.mkdir()
        self.caminho_hist = self.raiz / "historico.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_coletar_relatorios_vazio_ou_inexistente(self):
        # Pasta vazia
        self.assertEqual(coletar_relatorios(self.pasta_relatorios), [])
        # Pasta inexistente
        self.assertEqual(coletar_relatorios(self.raiz / "inexistente"), [])

    def test_coletar_relatorios_ordenados(self):
        r1 = {"data": "2026-10-04", "numero_edicao": 1, "secoes": []}
        r2 = {"data": "2026-10-18", "numero_edicao": 3, "secoes": []}
        r3 = {"data": "2026-10-11", "numero_edicao": 2, "secoes": []}
        (self.pasta_relatorios / "jornal_2026-10-04.relatorio.json").write_text(json.dumps(r1), encoding="utf-8")
        (self.pasta_relatorios / "jornal_2026-10-18.relatorio.json").write_text(json.dumps(r2), encoding="utf-8")
        (self.pasta_relatorios / "jornal_2026-10-11.relatorio.json").write_text(json.dumps(r3), encoding="utf-8")

        res = coletar_relatorios(self.pasta_relatorios)
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0]["data"], "2026-10-18")
        self.assertEqual(res[1]["data"], "2026-10-11")
        self.assertEqual(res[2]["data"], "2026-10-04")

    def test_coletar_historico_normalizacao(self):
        itens_raw = [
            {"pageid": 123, "titulo": "Teoria Quântica", "tema": "Física", "data": "2026-10-04"},
            {"tipo": "escolha", "url": "https://example.com/artigo", "titulo": "Ensaio", "fonte": "Blog", "data": "2026-10-11"},
            {"tipo": "noticia", "url": "https://news.com/1", "titulo": "Notícia 1", "fonte": "Jornal", "data": "2026-10-18"}
        ]
        self.caminho_hist.write_text(json.dumps(itens_raw), encoding="utf-8")
        itens = coletar_historico(self.caminho_hist)

        self.assertEqual(len(itens), 3)
        # Mais recente primeiro
        self.assertEqual(itens[0]["data"], "2026-10-18")
        self.assertEqual(itens[0]["tipo"], "noticia")
        # Item da wikipedia sem tipo explícito ganha 'wikipedia'
        item_wiki = [i for i in itens if i["titulo"] == "Teoria Quântica"][0]
        self.assertEqual(item_wiki["tipo"], "wikipedia")
        self.assertTrue("pt.wikipedia.org" in item_wiki["url"])

    def test_renderizar_painel_html_com_escape_e_estrutura(self):
        relatorios = [{
            "data": "2026-10-18",
            "gerado_em": "2026-10-19T00:00:00+00:00",
            "numero_edicao": 3,
            "arquivo": "jornal_2026-10-18.epub",
            "secoes": [{"nome": "Cultura <>&", "vazia": False, "itens": 2, "fontes": [{"fonte": "Arte", "itens": 2, "motivo": None}]}],
            "fontes_sem_item": [{"secao": "Ciência", "fonte": "Astronomia", "motivo": "esgotada"}],
            "qualidade": {"backend": "liftwing", "classe_minima": "C", "avaliados": 10, "aprovados": 8, "reprovados": 2}
        }]
        historico = [{
            "tipo": "wikipedia",
            "tema": "Arte <tag>",
            "fonte": "Wikipédia",
            "titulo": "Pintura & Escultura",
            "url": "https://pt.wikipedia.org/wiki/Pintura",
            "data": "2026-10-18",
            "pageid": 999
        }]
        cfg = {"titulo": "Gazeta dos Gazeteiros"}
        html_out = renderizar_painel_html(relatorios, historico, cfg)

        self.assertIn("<!DOCTYPE html>", html_out)
        self.assertIn("Gazeta dos Gazeteiros", html_out)
        # Checa escape do título na seção de temas
        self.assertIn("Arte &lt;tag&gt;", html_out)
        # Checa alerta de fontes esgotadas
        self.assertIn("Astronomia", html_out)
        self.assertIn("esgotada", html_out)
        # Checa dados embutidos
        self.assertIn("dados-relatorios", html_out)
        self.assertIn("dados-historico", html_out)

    def test_gerar_painel_arquivo_fisico(self):
        destino_html = self.raiz / "meu_painel.html"
        cfg = {
            "titulo": "Teste Painel",
            "relatorio": {"pasta": str(self.pasta_relatorios)},
            "historico": {"arquivo": str(self.caminho_hist)},
            "painel": {"arquivo": str(destino_html)},
        }
        resultado = gerar_painel(cfg, abrir=False)
        self.assertEqual(resultado, destino_html)
        self.assertTrue(destino_html.exists())
        self.assertIn("Teste Painel", destino_html.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
