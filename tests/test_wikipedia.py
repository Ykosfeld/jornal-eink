import random
import unittest
from unittest.mock import patch

from src.qualidade import FiltroQualidade, avaliar_qualidade
from src.wikipedia import buscar_artigo, limpar_html, sortear_artigo


class Resposta:
    def __init__(self, dados, status_code=200, headers=None):
        self.dados = dados
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self.dados


class SessaoFalsa:
    def __init__(self, resposta=None, erro=None):
        self.resposta = resposta
        self.erro = erro
        self.chamadas = []

    def get(self, url, params=None, timeout=None):
        self.chamadas.append(("get", url, params, timeout))
        return self.resposta

    def post(self, url, **kwargs):
        self.chamadas.append(("post", url, kwargs))
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
        self.assertEqual(corpo.count("<mn>5</mn>"), 1)

    def test_buscar_artigo_retorna_id_da_revisao_atual(self):
        sessao = SessaoFalsa(Resposta({"query": {"pages": [{
            "pageid": 12, "title": "Artigo redirecionado",
            "fullurl": "https://pt.wikipedia.org/wiki/Artigo_redirecionado",
            "extract": "<p>Texto do artigo com conteúdo suficiente.</p>",
            "revisions": [{"revid": 456}],
        }]}}))
        artigo = buscar_artigo(sessao, configuracao(), "Artigo")
        self.assertEqual(artigo["revid"], 456)

    def test_liftwing_envia_post_e_interpreta_classe_por_nome(self):
        sessao = SessaoFalsa(Resposta({"ptwiki": {"scores": {"456": {
            "articlequality": {"score": {"prediction": "B"}}
        }}}}))
        classe, erro = avaliar_qualidade(
            sessao, 456, {"modelo": "ptwiki-articlequality", "timeout": 7},
        )
        self.assertEqual((classe, erro), (4, None))
        metodo, url, kwargs = sessao.chamadas[0]
        self.assertEqual(metodo, "post")
        self.assertTrue(url.endswith("/ptwiki-articlequality:predict"))
        self.assertEqual(kwargs["json"], {"rev_id": 456})
        self.assertEqual(kwargs["timeout"], 7)

    @patch("src.wikipedia.membros", return_value=(["Candidato"], []))
    @patch("src.wikipedia.buscar_artigo")
    @patch("src.qualidade.avaliar_qualidade", side_effect=[(3, None), (4, None)])
    def test_rejeita_classe_inferior_e_tenta_outro_candidato(
        self, avaliar, buscar, _membros
    ):
        buscar.return_value = {"pageid": 12, "titulo": "Candidato", "chars": 100, "revid": 456}
        artigo = sortear_artigo(
            object(), configuracao(filtro_qualidade={"ativar": True, "classe_minima": "B"}),
            ["Raiz"], set(), set(), random.Random(1),
        )
        self.assertEqual(artigo["titulo"], "Candidato")
        self.assertEqual(avaliar.call_count, 2)

    def test_disjuntor_para_de_fazer_requisicoes(self):
        class Falha:
            def post(self, *args, **kwargs):
                self.chamadas += 1
                raise TimeoutError("falha")

            chamadas = 0

        sessao = Falha()
        filtro = FiltroQualidade({"filtro_qualidade": {
            "ativar": True, "falhas_consecutivas_max": 2,
        }})
        art = {"titulo": "A", "revid": 1}
        with patch("src.qualidade.avaliar_qualidade", return_value=(None, "timeout")):
            self.assertTrue(filtro.aceitavel(sessao, art))
            self.assertTrue(filtro.aceitavel(sessao, {"titulo": "B", "revid": 2}))
            self.assertTrue(filtro.aceitavel(sessao, {"titulo": "C", "revid": 3}))
        self.assertTrue(filtro.disjuntor_acionado)
        self.assertEqual(filtro.sem_filtro, ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
