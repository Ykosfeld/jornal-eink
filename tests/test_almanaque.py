import datetime as dt
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from src.almanaque import (
    _candidatos_imagem,
    _feriados,
    _linha_item,
    _peso_feriado,
    _janela_texto,
    coletar_almanaque,
    evento_tem_tom_leve,
    formatar_ano,
    temas_encontrados,
)
from src.epub_builder import montar_epub
from src.itens import item_almanaque
from src.layout import fontes_usadas, montar_secoes, resolver_layout


class Resposta:
    def __init__(self, dados):
        self.dados = dados
        self.content = b""

    def raise_for_status(self):
        return None

    def json(self):
        return self.dados


class SessaoFalsa:
    def get(self, url, params=None, timeout=None):
        if "onthisday/all/" in url:
            data = url.rsplit("/", 2)[-2:]
            day = int(data[-1])
            return Resposta({
                "selected": [],
                "events": [{
                    "text": f"Inauguração do observatório no dia {day}",
                    "year": 1931,
                    "pages": [{
                        "title": "Observatório",
                        "titles": {"canonical": f"Observatorio_{day}"},
                        "pageid": day,
                        "description": "Instituição dedicada à astronomia",
                        "extract": "Observatório astronômico.",
                        "content_urls": {"desktop": {
                            "page": f"https://pt.wikipedia.org/wiki/Observatorio_{day}"
                        }},
                    }],
                }],
                "births": [],
                "deaths": [],
                "holidays": [{"text": "Dia Mundial dos Animais"}],
            })
        if "pt.wikipedia.org/api/rest_v1/feed/featured/" in url:
            return Resposta({
                "image": None,
                "dyk": [{"text": "Uma curiosidade <especial>."}],
            })
        if "en.wikipedia.org/api/rest_v1/feed/featured/" in url:
            day = int(url.rsplit("/", 1)[-1])
            return Resposta({"tfa": {
                "title": f"Bird {day}",
                "titles": {"canonical": f"Bird_{day}"},
                "description": "A bird studied by an astronomer.",
                "extract": "Full article must not be shown.",
                "content_urls": {"desktop": {
                    "page": f"https://en.wikipedia.org/wiki/Bird_{day}"
                }},
            }})
        raise AssertionError(f"URL inesperada: {url}")


class AlmanaqueTests(unittest.TestCase):
    def test_filtro_de_tom_e_palavras_inteiras(self):
        self.assertFalse(evento_tem_tom_leve("O massacre matou 111 prisioneiros"))
        self.assertFalse(evento_tem_tom_leve("Ataque terrorista"))
        self.assertFalse(evento_tem_tom_leve("Bombardeio de cidades"))
        self.assertFalse(evento_tem_tom_leve("Execução de um condenado"))
        self.assertEqual(temas_encontrados("A ave voou pela parte da avenida", {
            "Aves": ["ave"], "Arte": ["arte"]
        }), ["Aves"])
        self.assertEqual(temas_encontrados("Um ornitólogo", {"Aves": ["ornitologo"]}), ["Aves"])
        self.assertEqual(temas_encontrados("A birdie sings", {"Aves": ["bird"]}), [])
        self.assertEqual(
            temas_encontrados("jogo eletrônico", {"Jogos": ["jogo eletronico"]}),
            ["Jogos"],
        )

    def test_formata_anos_e_intervalos(self):
        self.assertEqual(formatar_ano(-44), "44 a.C.")
        self.assertEqual(formatar_ano(0), "0 a.C.")
        self.assertEqual(
            _janela_texto(dt.date(2026, 12, 28), dt.date(2027, 1, 3)),
            "28 de dezembro a 3 de janeiro",
        )

    def test_dia_a_dia_preserva_nome_e_texto_da_efemeride(self):
        nascimento = {
            "year": 1994,
            "text": "Markus Hoelgaard, ciclista norueguês.",
            "pages": [{
                "title": "Markus_Hoelgaard",
                "titles": {"canonical": "Markus_Hoelgaard"},
                "description": "ciclista norueguês",
                "content_urls": {"desktop": {
                    "page": "https://pt.wikipedia.org/wiki/Markus_Hoelgaard"
                }},
            }],
        }
        linha = _linha_item(nascimento, {}, "nascimento")
        self.assertEqual(linha["texto"], "Markus Hoelgaard, ciclista norueguês.")
        self.assertEqual(linha["url"], "https://pt.wikipedia.org/wiki/Markus_Hoelgaard")

        morte = {
            "year": 1918,
            "text": "Józef Engling, religioso católico alemão (n. 1898).",
            "pages": [
                {
                    "title": "Józef_Engling",
                    "titles": {"canonical": "Józef_Engling"},
                    "content_urls": {"desktop": {
                        "page": "https://pt.wikipedia.org/wiki/J%C3%B3zef_Engling"
                    }},
                },
                {
                    "title": "1898",
                    "titles": {"canonical": "1898"},
                    "description": "ano",
                    "content_urls": {"desktop": {
                        "page": "https://pt.wikipedia.org/wiki/1898"
                    }},
                },
            ],
        }
        linha = _linha_item(morte, {}, "morte")
        self.assertEqual(linha["texto"], morte["text"])
        self.assertEqual(linha["ano"], "1918")
        self.assertEqual(linha["url"], "https://pt.wikipedia.org/wiki/J%C3%B3zef_Engling")

    def test_nao_cria_link_para_pagina_de_ano(self):
        evento = {
            "year": 1918,
            "text": "Um acontecimento histórico.",
            "pages": [{
                "title": "1898",
                "titles": {"canonical": "1898"},
                "description": "ano",
                "content_urls": {"desktop": {
                    "page": "https://pt.wikipedia.org/wiki/1898"
                }},
            }],
        }
        linha = _linha_item(evento, {}, "evento")
        self.assertEqual(linha["texto"], evento["text"])
        self.assertEqual(linha["url"], "")

    def test_filtra_imagem_de_evento(self):
        base = {
            "title": "Natureza",
            "thumbnail": {
                "source": "https://thumb.wikimedia.org/file/330px-natureza.jpg",
                "width": 330, "height": 250,
            },
        }
        self.assertIsNotNone(_candidatos_imagem(base, 150, 2.2))
        escudo = {**base, "title": "EscudoPMESP.png"}
        self.assertIsNone(_candidatos_imagem(escudo, 150, 2.2))
        svg = {**base, "thumbnail": {
            **base["thumbnail"], "source": "https://thumb.wikimedia.org/file/mapa.svg",
        }}
        self.assertIsNone(_candidatos_imagem(svg, 150, 2.2))

    def test_layout_acrescenta_almanaque_sem_mover_fontes_configuradas(self):
        cfg = {"temas": {"Astronomia": []}, "secoes": [
            {"nome": "Ciência", "fontes": ["Astronomia"]}
        ]}
        secoes = resolver_layout(cfg)
        self.assertEqual([s["nome"] for s in secoes], ["Ciência", "Almanaque"])
        self.assertIn("almanaque", fontes_usadas(secoes))
        cfg["secoes"].insert(0, {"nome": "Agenda", "fontes": ["almanaque"]})
        secoes = resolver_layout(cfg)
        self.assertEqual([s["nome"] for s in secoes], ["Agenda", "Ciência"])

    def test_filtra_feriados_ruidosos_e_limita_um_por_dia(self):
        inicio = dt.date(2026, 10, 4)
        dados = [
            (inicio, {"holidays": [
                {"text": "Dia Mundial dos Animais"},
                {"text": "Feriado em Paulo Afonso (BA) e outras cidades"},
                {"text": "Aniversário da cidade de Engenheiro Paulo de Frontin"},
                {"text": "Dia do Barman"},
            ]}),
            (inicio + dt.timedelta(days=1), {"holidays": [
                {"text": "Dia Mundial dos Animais"},
                {"text": "Dia Nacional da Ciência"},
            ]}),
        ]
        resultado = _feriados(dados, inicio, {"feriados": {"quantidade": 5}}, random.Random(2))
        textos = [x["texto"] for x in resultado]
        self.assertNotIn("Feriado em Paulo Afonso (BA) e outras cidades", textos)
        self.assertNotIn("Aniversário da cidade de Engenheiro Paulo de Frontin", textos)
        self.assertEqual(len(textos), len(set(textos)))
        self.assertTrue(all(n <= 1 for n in Counter(x["data"] for x in resultado).values()))
        self.assertEqual(_peso_feriado("Dia Mundial dos Animais"), 5)
        self.assertEqual(_peso_feriado("Dia do Barman"), 2)

    def test_resposta_vazia_em_todos_os_dias_retorna_none(self):
        class SessaoVazia:
            def get(self, *args, **kwargs):
                return Resposta({})

        self.assertIsNone(coletar_almanaque(
            SessaoVazia(), {"almanaque": {"destaque": {"ativar": False}}},
            dt.date(2026, 10, 4), semente=1,
        ))

    def test_coleta_e_adapter_nao_expoem_extract_do_artigo(self):
        hoje = dt.date(2026, 10, 4)
        cfg = {
            "almanaque": {
                "ativar": True,
                "imagem": False,
                "destaque": {
                    "ativar": True,
                    "maximo": 3,
                    "chamadas": ["Importado da Wikipédia em inglês"],
                    "chamadas_tema": ["Tem gringo famoso na área"],
                    "palavras_chave_en": {"Astronomia": ["astronomer"]},
                },
                "palavras_chave": {"Astronomia": ["astronomia"]},
            },
            "imagens": {"ativar": False},
        }
        resultado = coletar_almanaque(SessaoFalsa(), cfg, hoje, semente=4)
        self.assertEqual(len(resultado["dias"]), 7)
        self.assertEqual(len(resultado["destaques"]), 3)
        self.assertTrue(all("Astronomia" in item["temas"] for item in resultado["destaques"]))
        item = item_almanaque(resultado)
        self.assertIn("[EN]", item["html"])
        self.assertIn('lang="en"', item["html"])
        self.assertNotIn("Full article must not be shown", item["html"])
        self.assertIn("&lt;especial&gt;", item["html"])
        secoes = montar_secoes(
            [{"nome": "Almanaque", "fontes": ["almanaque"], "ordem": "sequencial"}],
            {"almanaque": [item]},
        )
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / "almanaque.epub"
            montar_epub(
                {"titulo": "Jornal de teste", "autor": "Teste", "idioma": "pt"},
                secoes, hoje, destino, numero_edicao=1,
            )
            with ZipFile(destino) as epub:
                pagina = next(nome for nome in epub.namelist() if nome.endswith("item_001.xhtml"))
                corpo = epub.read(pagina).decode("utf-8")
                self.assertIn("[EN]", corpo)
                self.assertEqual(corpo.count("<img "), 0)


if __name__ == "__main__":
    unittest.main()
