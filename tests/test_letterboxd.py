import datetime as dt
import unittest
from unittest.mock import patch

import requests

from src.itens import item_curiosidade
from src.letterboxd import (
    _titulo_original_corresponde,
    creditos_do_filme,
    interpretar_rss,
    priorizar_artigo,
    validar_config,
)
from src.pipeline import coletar_curiosidades


RSS = """<?xml version="1.0"?>
<rss version="2.0"
 xmlns:letterboxd="https://letterboxd.com"
 xmlns:tmdb="https://themoviedb.org">
  <channel>
    {items}
  </channel>
</rss>"""


def entrada(titulo, watched, rating=None, year="2020", tmdb_id=None, pubdate=""):
    nota = f"<letterboxd:memberRating>{rating}</letterboxd:memberRating>" if rating else ""
    ano = f"<letterboxd:filmYear>{year}</letterboxd:filmYear>" if year else ""
    tmdb = f"<tmdb:movieId>{tmdb_id}</tmdb:movieId>" if tmdb_id else ""
    return f"""<item>
      <title>Activity title</title>
      <pubDate>{pubdate}</pubDate>
      <letterboxd:watchedDate>{watched}</letterboxd:watchedDate>
      <letterboxd:filmTitle>{titulo}</letterboxd:filmTitle>
      {ano}{nota}{tmdb}
      <description>Private note must not be parsed.</description>
    </item>"""


def artigo(titulo, pageid, revid=100):
    return {
        "titulo": titulo,
        "pageid": pageid,
        "revid": revid,
        "chars": 1000,
        "url": f"https://pt.wikipedia.org/wiki/{titulo.replace(' ', '_')}",
        "html": "<p>Texto do artigo.</p>",
        "imagem": None,
    }


class Resposta:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class Sessao:
    def __init__(self, content):
        self.content = content

    def get(self, url, timeout=None):
        return Resposta(self.content)


class SessaoIndisponivel:
    def get(self, url, timeout=None):
        raise requests.ConnectionError("indisponível")


class LetterboxdTests(unittest.TestCase):
    def test_parsing_usa_watched_date_ignora_pubdate_e_ordenacao(self):
        rss = RSS.format(items="".join([
            entrada("Filme antigo", "2026-09-25", 5, tmdb_id="1",
                    pubdate="Fri, 2 Oct 2026 12:00:00 +0000"),
            entrada("Mais recente", "2026-10-01", 4, tmdb_id="2"),
            entrada("Nota alta", "2026-09-28", 5, tmdb_id="3"),
            entrada("Sem nota", "2026-10-02", tmdb_id="4"),
            entrada("Sem nota mais velho", "2026-09-30", tmdb_id="5"),
        ]))

        filmes = interpretar_rss(rss, dt.date(2026, 10, 2))

        self.assertEqual(
            [filme["titulo"] for filme in filmes],
            ["Nota alta", "Mais recente", "Sem nota", "Sem nota mais velho"],
        )
        self.assertIsNone(filmes[-1]["nota"])
        self.assertNotIn("description", filmes[0])

    def test_deduplica_reassistida_preservando_maior_nota(self):
        rss = RSS.format(items="".join([
            entrada("Mesmo filme", "2026-10-01", 4, tmdb_id="42"),
            entrada("Mesmo filme", "2026-10-02", 5, tmdb_id="42"),
        ]))

        filmes = interpretar_rss(rss, dt.date(2026, 10, 2))

        self.assertEqual(len(filmes), 1)
        self.assertEqual(filmes[0]["nota"], 5)
        self.assertEqual(filmes[0]["assistido"], dt.date(2026, 10, 2))

    def test_janela_limites_e_malformacao(self):
        rss = RSS.format(items="".join([
            entrada("Limite incluído", "2026-09-26", 5, tmdb_id="1"),
            entrada("Fora da janela", "2026-09-25", 5, tmdb_id="2"),
            "<item><letterboxd:filmTitle>Sem data</letterboxd:filmTitle></item>",
        ]))

        with self.assertLogs("src.letterboxd", level="WARNING"):
            filmes = interpretar_rss(rss, dt.date(2026, 10, 2))

        self.assertEqual([f["titulo"] for f in filmes], ["Limite incluído"])
        with self.assertRaisesRegex(ValueError, "RSS do Letterboxd inválido"):
            interpretar_rss("<rss>", dt.date(2026, 10, 2))

    def test_configuracao_exige_url_e_limites_positivos_quando_ativa(self):
        with self.assertRaisesRegex(ValueError, "URL HTTP"):
            validar_config({"ativar": True, "feed_url": "file:///rss"})
        with self.assertRaisesRegex(ValueError, "janela_dias"):
            validar_config({
                "ativar": True,
                "feed_url": "https://letterboxd.com/example/rss/",
                "janela_dias": 0,
            })

    def test_infobox_extrai_somente_links_de_creditos_e_valida_ano(self):
        html = """
        <table class="infobox">
          <tr><th class="infobox-label">Direção</th>
              <td><a href="/wiki/Directora" title="Directora">Directora</a></td></tr>
          <tr><th>Elenco</th>
              <td><a href="/wiki/Actor">Actor</a><a href="/wiki/Character">Character</a></td></tr>
          <tr><th>Lançamento</th><td>12 de março de 2020</td></tr>
          <tr><th>Estúdio</th><td><a href="/wiki/Studio">Studio</a></td></tr>
        </table>
        """

        self.assertEqual(creditos_do_filme(html, "2020"), ["Directora", "Actor", "Character"])
        self.assertIsNone(creditos_do_filme(html, "2021"))
        self.assertIsNone(creditos_do_filme("<p>Sem infobox</p>", "2020"))

    def test_confirma_titulo_original_em_artigo_com_titulo_traduzido(self):
        html = """
        <table class="infobox">
          <tr><th>Título original</th><td>Original Film</td></tr>
        </table>
        """

        self.assertTrue(_titulo_original_corresponde(html, {"titulo": "Original Film"}))
        self.assertFalse(_titulo_original_corresponde(html, {"titulo": "Outro Filme"}))

    @patch("src.letterboxd.artigo_aceitavel", return_value=True)
    @patch("src.letterboxd.api")
    @patch("src.letterboxd.buscar_artigo")
    @patch("src.letterboxd._titulos_candidatos", return_value=["Filme"])
    def test_seleciona_credito_novo_quando_artigo_do_filme_esta_no_historico(
        self, _buscar_titulos, buscar, api_mock, _ores,
    ):
        rss = RSS.format(items=entrada("Filme", "2026-10-02", 5, tmdb_id="1"))
        sessao = Sessao(rss.encode())
        filme = artigo("Filme", 10)
        diretora = artigo("Directora", 11)
        buscar.side_effect = [filme, diretora]
        api_mock.return_value = {"parse": {"text": """
          <table class="infobox">
            <tr><th>Direção</th><td><a href="/wiki/Directora">Directora</a></td></tr>
            <tr><th>Lançamento</th><td>2020</td></tr>
          </table>
        """}}
        cfg = {
            "personalizacao_cultural": {
                "ativar": True,
                "letterboxd": {
                    "ativar": True,
                    "feed_url": "https://letterboxd.com/example/rss/",
                },
            },
            "wikipedia": {"min_caracteres": 300},
        }

        selecionado, motivo = priorizar_artigo(
            sessao, cfg, {"Filme"}, {10}, dt.date(2026, 10, 2),
        )

        self.assertEqual(motivo, "")
        self.assertEqual(selecionado["titulo"], "Directora")
        self.assertEqual(selecionado["caminho"], "Letterboxd · Filme (crédito)")
        self.assertIn("passarinho azul, verde e laranja", selecionado["nota"])

    @patch("src.letterboxd.artigo_aceitavel", side_effect=[False, True])
    @patch("src.letterboxd.api")
    @patch("src.letterboxd.buscar_artigo")
    @patch("src.letterboxd._titulos_candidatos", return_value=["Filme"])
    def test_tenta_credito_se_artigo_do_filme_falha_ores(
        self, _buscar_titulos, buscar, api_mock, _ores,
    ):
        rss = RSS.format(items=entrada("Filme", "2026-10-02", 5, tmdb_id="1"))
        sessao = Sessao(rss.encode())
        buscar.side_effect = [artigo("Filme", 10), artigo("Directora", 11)]
        api_mock.return_value = {"parse": {"text": """
          <table class="infobox">
            <tr><th>Direção</th><td><a href="/wiki/Directora">Directora</a></td></tr>
            <tr><th>Lançamento</th><td>2020</td></tr>
          </table>
        """}}

        selecionado, _ = priorizar_artigo(
            sessao,
            {"personalizacao_cultural": {
                "ativar": True,
                "letterboxd": {
                    "ativar": True,
                    "feed_url": "https://letterboxd.com/example/rss/",
                },
             },
             "wikipedia": {"min_caracteres": 300}},
            set(), set(), dt.date(2026, 10, 2),
        )

        self.assertEqual(selecionado["titulo"], "Directora")

    @patch("src.letterboxd._titulos_candidatos")
    def test_sem_filmes_na_janela_nao_consulta_wikipedia(self, busca):
        sessao = Sessao(RSS.format(items=entrada("Filme antigo", "2026-09-01", 5)).encode())

        artigo_encontrado, motivo = priorizar_artigo(
            sessao,
            {"letterboxd": {"ativar": True, "feed_url": "https://letterboxd.com/example/rss/"},
             "wikipedia": {"min_caracteres": 300}},
            set(), set(), dt.date(2026, 10, 2),
        )

        self.assertIsNone(artigo_encontrado)
        self.assertIn("nenhum filme", motivo)
        busca.assert_not_called()

    def test_falha_de_rede_retorna_motivo_de_fallback(self):
        with self.assertLogs("src.letterboxd", level="WARNING"):
            selecionado, motivo = priorizar_artigo(
                SessaoIndisponivel(),
                {"letterboxd": {
                    "ativar": True,
                    "feed_url": "https://letterboxd.com/example/rss/",
                }, "wikipedia": {"min_caracteres": 300}},
                set(), set(), dt.date(2026, 10, 2),
            )

        self.assertIsNone(selecionado)
        self.assertEqual(motivo, "falha ao consultar Letterboxd")

    @patch("src.pipeline.sortear_artigo")
    def test_artigo_priorizado_usa_pipeline_sem_persistir_dados_do_feed(self, sortear):
        selecionado = {
            **artigo("Diretora", 11),
            "caminho": "Letterboxd · Filme (crédito)",
            "nota": "Um passarinho azul, verde e laranja me contou que você ia gostar.",
        }
        cfg = {
            "wikipedia": {
                "api": "https://pt.wikipedia.org/w/api.php",
                "max_caracteres": 1000,
                "min_caracteres": 300,
            },
            "imagens": {"ativar": False},
            "temas": {"Cinema": []},
        }

        artigos, novos, pulados = coletar_curiosidades(
            object(), cfg, set(), set(), object(), dt.date(2026, 10, 2),
            priorizados={"Cinema": selecionado},
        )

        sortear.assert_not_called()
        self.assertEqual(artigos[0][1]["nota"], selecionado["nota"])
        self.assertEqual(novos, [{
            "pageid": 11,
            "titulo": "Diretora",
            "tema": "Cinema",
            "data": "2026-10-02",
        }])
        self.assertEqual(pulados, {})

    def test_item_curiosidade_mostra_mensagem_somente_se_definida(self):
        artigo_base = {
            **artigo("Filme", 10),
            "chars": 1000,
        }

        item = item_curiosidade("Cinema", artigo_base)

        self.assertEqual(item["nota"], "")
        artigo_base["nota"] = "Um passarinho azul, verde e laranja me contou que você ia gostar."
        item_com_nota = item_curiosidade("Cinema", artigo_base)
        self.assertEqual(item_com_nota["nota"], artigo_base["nota"])


if __name__ == "__main__":
    unittest.main()
