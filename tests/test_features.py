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


if __name__ == "__main__":
    unittest.main()
