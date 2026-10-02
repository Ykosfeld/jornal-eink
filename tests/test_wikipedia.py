import random
import unittest
from unittest.mock import patch

import requests

from src.wikipedia import avaliar_qualidade_ores, buscar_artigo, limpar_html, sortear_artigo


class Resposta:
    def __init__(self, dados):
        self.dados = dados

    def raise_for_status(self):
        return None

    def json(self):
        return self.dados


class SessaoFalsa:
    def __init__(self, resposta=None, erro=None):
        self.resposta = resposta
        self.erro = erro
        self.chamadas = []

    def get(self, url, params=None, timeout=None):
        self.chamadas.append((url, params, timeout))
        if self.erro:
            raise self.erro
        return self.resposta


def configuracao(**extra):
    return {
        "api": "https://pt.wikipedia.org/w/api.php",
        "max_caracteres": 15000,
        "min_caracteres": 20,
        "tentativas": 2,
        "profundidade_max": 0,
        "titulos_ignorados_prefixos": [],
        **extra,
    }


class WikipediaQualityTests(unittest.TestCase):
    def test_limpar_html_converte_formula_wikipedia_uma_unica_vez(self):
        extrato = """
        <p>Fermat: <span class="mwe-math-element">
          <span class="mwe-math-mathml-inline">
            <math><semantics><mrow><mn>5</mn></mrow>
              <annotation encoding="application/x-tex">{\\displaystyle 5}</annotation>
            </semantics></math>
          </span>
          <img class="mwe-math-fallback-image-inline" alt="{\\displaystyle 5}"/>
        </span> até <span class="mwe-math-element">
          <span class="mwe-math-mathml-inline">
            <math><semantics><mrow><msub><mi>F</mi><mn>23288</mn></msub></mrow>
              <annotation encoding="application/x-tex">F_{23288}</annotation>
            </semantics></math>
          </span>
          <img class="mwe-math-fallback-image-inline" alt="{\\displaystyle F_{23288}}"/>
        </span>.</p>
        """

        corpo, _ = limpar_html(extrato, 15000)

        self.assertEqual(corpo.count("<math"), 2)
        self.assertNotIn("<img", corpo)
        self.assertIn("F_{23288}", corpo)
        self.assertIn("<msub>", corpo)
        self.assertEqual(corpo.count("<mn>5</mn>"), 1)
        self.assertIn("Fermat:", corpo)
        self.assertIn("até", corpo)

    def test_limpar_html_preserva_formula_sem_mathml_sem_repetir_fallback(self):
        extrato = """
        <p>Valor <span class="mwe-math-element">
          <math><semantics><mn>5</mn>
            <annotation encoding="application/x-tex">{\\displaystyle 5}</annotation>
          </semantics></math>
          <img alt="{\\displaystyle 5}"/>
        </span>.</p>
        """

        corpo, _ = limpar_html(extrato, 15000, mathml=False)

        self.assertEqual(corpo.count("<i>"), 1)
        self.assertNotIn("<img", corpo)
        self.assertIn("Valor", corpo)

    def test_buscar_artigo_retorna_id_da_revisao_atual(self):
        sessao = SessaoFalsa(Resposta({"query": {"pages": [{
            "pageid": 12,
            "title": "Artigo redirecionado",
            "fullurl": "https://pt.wikipedia.org/wiki/Artigo_redirecionado",
            "extract": "<p>Texto do artigo com conteúdo suficiente.</p>",
            "revisions": [{"revid": 456}],
        }]}}))

        artigo = buscar_artigo(sessao, configuracao(), "Artigo")

        self.assertEqual(artigo["revid"], 456)
        parametros = sessao.chamadas[0][1]
        self.assertIn("revisions", parametros["prop"])
        self.assertEqual(parametros["rvprop"], "ids")
        self.assertEqual(parametros["rvlimit"], 1)

    def test_avaliar_ores_envia_revisao_e_timeout_e_interpreta_classe(self):
        sessao = SessaoFalsa(Resposta({"ptwiki": {"scores": {"456": {
            "articlequality": {"score": {"prediction": "4"}}
        }}}}))

        classe, erro = avaliar_qualidade_ores(sessao, 456, 7)

        self.assertEqual((classe, erro), (4, None))
        _, parametros, timeout = sessao.chamadas[0]
        self.assertEqual(parametros, {"models": "articlequality", "revids": 456})
        self.assertEqual(timeout, 7)

    def test_falha_ores_e_resposta_invalida_sao_inutilizaveis(self):
        sessao_indisponivel = SessaoFalsa(erro=requests.Timeout("timeout"))
        sessao_sem_nota = SessaoFalsa(Resposta({"ptwiki": {"scores": {}}}))

        self.assertIsNone(avaliar_qualidade_ores(sessao_indisponivel, 456, 1)[0])
        self.assertIsNotNone(avaliar_qualidade_ores(sessao_sem_nota, 456, 1)[1])

    @patch("src.wikipedia.membros", return_value=(["Candidato"], []))
    @patch("src.wikipedia.buscar_artigo")
    @patch("src.wikipedia.avaliar_qualidade_ores", side_effect=[(3, None), (4, None)])
    def test_rejeita_classe_inferior_e_tenta_outro_candidato(
        self, avaliar, buscar, _membros
    ):
        buscar.return_value = {
            "pageid": 12,
            "titulo": "Candidato",
            "chars": 100,
            "revid": 456,
        }

        artigo = sortear_artigo(
            object(), configuracao(filtro_qualidade={"ativar": True, "classe_minima": "B"}),
            ["Raiz"], set(), set(), random.Random(1),
        )

        self.assertEqual(artigo["titulo"], "Candidato")
        self.assertEqual(avaliar.call_count, 2)

    @patch("src.wikipedia.membros", return_value=(["Candidato"], []))
    @patch("src.wikipedia.buscar_artigo")
    @patch("src.wikipedia.avaliar_qualidade_ores", return_value=(None, "timeout"))
    def test_falha_ores_aceita_candidato_com_aviso(self, avaliar, buscar, _membros):
        buscar.return_value = {
            "pageid": 12,
            "titulo": "Candidato",
            "chars": 100,
            "revid": 456,
        }

        with self.assertLogs("src.wikipedia", level="WARNING") as logs:
            artigo = sortear_artigo(
                object(), configuracao(filtro_qualidade={"ativar": True}),
                ["Raiz"], set(), set(), random.Random(1),
            )

        self.assertEqual(artigo["titulo"], "Candidato")
        self.assertIn("aceitando candidato sem filtro", logs.output[0])
        avaliar.assert_called_once()

    @patch("src.wikipedia.membros", return_value=(["Candidato"], []))
    @patch("src.wikipedia.buscar_artigo")
    @patch("src.wikipedia.avaliar_qualidade_ores")
    def test_filtro_ausente_ou_desativado_nao_chama_ores(
        self, avaliar, buscar, _membros
    ):
        buscar.return_value = {
            "pageid": 12,
            "titulo": "Candidato",
            "chars": 100,
            "revid": 456,
        }

        for filtro in (None, {"ativar": False, "classe_minima": "B"}):
            cfg = configuracao()
            if filtro is not None:
                cfg["filtro_qualidade"] = filtro
            artigo = sortear_artigo(
                object(), cfg, ["Raiz"], set(), set(), random.Random(1),
            )
            self.assertEqual(artigo["titulo"], "Candidato")

        avaliar.assert_not_called()

    @patch("src.wikipedia.membros", return_value=(["Candidato"], []))
    @patch("src.wikipedia.buscar_artigo")
    @patch("src.wikipedia.avaliar_qualidade_ores", return_value=(3, None))
    def test_esgota_tentativas_se_todos_os_candidatos_ficam_abaixo(
        self, _avaliar, buscar, _membros
    ):
        buscar.return_value = {
            "pageid": 12,
            "titulo": "Candidato",
            "chars": 100,
            "revid": 456,
        }

        artigo = sortear_artigo(
            object(), configuracao(filtro_qualidade={"ativar": True, "classe_minima": "B"}),
            ["Raiz"], set(), set(), random.Random(1),
        )

        self.assertIsNone(artigo)
        self.assertEqual(buscar.call_count, 2)


if __name__ == "__main__":
    unittest.main()
