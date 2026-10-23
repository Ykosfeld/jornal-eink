import datetime as dt
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from src.arquivo import arquivar
from src.epub_builder import montar_epub
from src.leitura import minutos_de_leitura
from src.layout import ErroLayout, montar_secoes, validar_layout


class FeatureTests(unittest.TestCase):
    def test_tempo_remove_tags_arredonda_e_tem_minimo(self):
        self.assertEqual(minutos_de_leitura("<p>" + ("x" * 1001) + "</p>", 1000), 2)
        self.assertEqual(minutos_de_leitura("<p>curto</p>", 1000), 1)

    def test_arquivo_morto_ordena_pela_data_do_nome(self):
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            for nome in ("jornal_2026-10-01.epub", "jornal_2026-10-02.epub"):
                (raiz / nome).write_text(nome)
            atual = raiz / "jornal_2026-10-03.epub"
            atual.write_text("atual")
            arquivados = arquivar(raiz, atual, {"ativar": True})
            self.assertEqual(set(arquivados), {"jornal_2026-10-01.epub", "jornal_2026-10-02.epub"})
            self.assertTrue(atual.exists())
            self.assertTrue((raiz / "anteriores" / "jornal_2026-10-01.epub").exists())

    def test_layout_rejeita_divisoria_nao_booleana(self):
        with self.assertRaisesRegex(ErroLayout, "divisoria.*booleana"):
            validar_layout({"temas": {"X": []}}, [
                {"nome": "Seção", "fontes": ["X"], "divisoria": "sim"},
            ])

    def test_epub_tem_sumario_divisoria_e_item_estavel(self):
        item = {
            "fonte_id": "x", "fonte": "Fonte", "rotulo": "X", "titulo": "Título",
            "titulo_toc": "Título", "url": "https://example.com", "html": "<p>texto</p>",
            "lang": "pt", "imagem": None, "credito": "Fonte", "nota": "",
        }
        secoes = montar_secoes(
            [{"nome": "Seção", "fontes": ["x"], "ordem": "sequencial"}], {"x": [item]},
        )
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "jornal.epub"
            montar_epub(
                {"titulo": "Jornal", "autor": "Autor", "idioma": "pt"},
                secoes, dt.date(2026, 10, 3), destino,
            )
            with ZipFile(destino) as epub:
                nomes = epub.namelist()
                self.assertTrue(any(nome.endswith("sumario.xhtml") for nome in nomes))
                self.assertTrue(any(nome.endswith("secao_01.xhtml") for nome in nomes))
                self.assertTrue(any(nome.endswith("item_001.xhtml") for nome in nomes))
                sumario = epub.read(next(nome for nome in nomes if nome.endswith("sumario.xhtml")))
                self.assertIn(b"item_001.xhtml", sumario)

    def test_css_epub_tipografia_eink_sem_margem_entre_paragrafos(self):
        from src.epub_builder import CSS
        self.assertIn("p { text-align: justify; margin: 0; text-indent: 1.25em; }", CSS)
        self.assertIn("h1 + p", CSS)
        self.assertIn("break-inside: avoid", CSS)
        self.assertIn(".abertura-coluna", CSS)
        self.assertIn(".ponte-transicao", CSS)

    def test_limpar_generico_higieniza_br_e_paragrafos(self):
        from src.feeds import limpar_generico
        html_feed = "<p>Primeiro parágrafo.<br><br>Segundo parágrafo.</p><p><br>Terceiro parágrafo.<br></p>"
        limpo, _ = limpar_generico(html_feed, 1000)
        self.assertNotIn("<br><br>", limpo)
        self.assertIn("<p>Primeiro parágrafo.</p>", limpo)
        self.assertIn("<p>Segundo parágrafo.</p>", limpo)
        self.assertIn("<p>Terceiro parágrafo.</p>", limpo)

    def test_escolha_do_editor_respeita_limite_e_mantem_pendencias(self):
        from unittest.mock import patch, MagicMock
        from src.escolha import coletar_escolhas, consumir_fila

        conteudo = (
            "https://pt.wikipedia.org/wiki/Item_1\n"
            "https://pt.wikipedia.org/wiki/Item_2\n"
            "https://pt.wikipedia.org/wiki/Item_3\n"
            "https://pt.wikipedia.org/wiki/Item_4\n"
        )
        with tempfile.TemporaryDirectory() as pasta:
            arq = Path(pasta) / "fila.txt"
            arq.write_text(conteudo, encoding="utf-8")

            cfg = {
                "escolha_do_editor": {"arquivo": str(arq), "quantidade": 2},
                "wikipedia": {"api": "https://pt.wikipedia.org/w/api.php"},
            }

            def mock_obter(sessao, ecfg, wbase, e):
                return {
                    "fonte": "Wikipédia", "titulo": e["url"].split("/")[-1],
                    "url": e["url"], "html": "<p>teste</p>", "chars": 500,
                    "lang": "pt", "imagem": None,
                }

            with patch("src.escolha.obter_escolha", side_effect=mock_obter):
                itens, fila = coletar_escolhas(MagicMock(), cfg)

            self.assertEqual(len(itens), 2)
            self.assertEqual(itens[0]["titulo"], "Item_1")
            self.assertEqual(itens[1]["titulo"], "Item_2")

            consumir_fila(fila)
            restante = arq.read_text(encoding="utf-8").splitlines()
            self.assertEqual(restante, [
                "https://pt.wikipedia.org/wiki/Item_3",
                "https://pt.wikipedia.org/wiki/Item_4",
            ])


if __name__ == "__main__":
    unittest.main()
