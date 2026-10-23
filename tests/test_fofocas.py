"""Testes unitários para a coluna de fofocas (Tribunal do Cotidiano - r/AmItheAsshole)."""
import unittest
from unittest.mock import MagicMock, patch

from src.fofocas import (
    FLAIRS_VALIDOS,
    CasoAITA,
    SecaoFofocas,
    buscar_candidatos_reddit,
    buscar_top_comment,
    calcular_scores,
    filtrar_elegiveis,
    gerar_abertura_editorial,
    gerar_bater_do_martelo,
    gerar_ponte_transicao,
    higienizar_markdown_eink,
    obter_secao_fofocas,
    selecionar_dupla_diversa,
    truncar_comentario_sentenca,
    validar_config,
)
from src.itens import item_fofocas


class TestFofocas(unittest.TestCase):
    def setUp(self):
        self.config_padrao = {
            "habilitado": True,
            "titulo_coluna": "Tribunal do Cotidiano",
            "subreddit": "AmItheAsshole",
            "periodo": "week",
            "limite_busca": 100,
            "quantidade_posts": 2,
            "forcar_vereditos_diferentes": True,
            "filtrar_nsfw": False,
            "incluir_top_comment": True,
            "max_palavras_comentario": 140,
            "palavras_min": 150,
            "palavras_max": 750,
            "palavras_ideal_min": 250,
            "palavras_ideal_max": 450,
            "pesos": {"engajamento": 0.45, "polemica": 0.35, "tamanho": 0.20},
            "multiplicadores_flair": {
                "Asshole": 1.35,
                "Everyone Sucks": 1.30,
                "No A-holes here": 1.15,
                "Not the A-hole": 1.00,
            },
        }

    def test_validar_config(self):
        self.assertFalse(validar_config(None)["habilitado"])
        self.assertTrue(validar_config({"habilitado": True})["habilitado"])
        with self.assertRaises(ValueError):
            validar_config({"habilitado": "sim"})
        with self.assertRaises(ValueError):
            validar_config({"quantidade_posts": 0})

    def test_filtragem_elegibilidade(self):
        """Descarta posts sem flair válido, [removed], fora de 150-750 palavras ou já no histórico."""
        texto_ok = "palavra " * 200
        texto_curto = "palavra " * 100
        texto_longo = "palavra " * 800

        candidatos = [
            {"id": "1", "link_flair_text": "Asshole", "selftext": texto_ok, "over_18": False},
            {"id": "2", "link_flair_text": "UPDATE", "selftext": texto_ok, "over_18": False}, # flair inválida
            {"id": "3", "link_flair_text": "Not the A-hole", "selftext": "[removed]", "over_18": False}, # texto removido
            {"id": "4", "link_flair_text": "Not the A-hole", "selftext": texto_curto, "over_18": False}, # curto
            {"id": "5", "link_flair_text": "Everyone Sucks", "selftext": texto_longo, "over_18": False}, # longo
            {"id": "6", "link_flair_text": "No A-holes here", "selftext": texto_ok, "over_18": False}, # já usado
            {"id": "7", "link_flair_text": "Asshole", "selftext": texto_ok, "over_18": True}, # nsfw
        ]
        usados = {"aita_6"}

        # Sem filtro nsfw
        elegiveis = filtrar_elegiveis(candidatos, usados, self.config_padrao)
        ids_elegiveis = [c["id"] for c in elegiveis]
        self.assertEqual(ids_elegiveis, ["1", "7"])

        # Com filtro nsfw
        cfg_nsfw = {**self.config_padrao, "filtrar_nsfw": True}
        elegiveis_nsfw = filtrar_elegiveis(candidatos, usados, cfg_nsfw)
        self.assertEqual([c["id"] for c in elegiveis_nsfw], ["1"])

    def test_multiplicador_veredito_prioriza_raridade(self):
        """Verifica se post Asshole supera Not the A-hole quando o engajamento é ligeiramente inferior."""
        texto = "palavra " * 300 # tamanho ideal
        candidatos = [
            {
                "id": "nta_post",
                "link_flair_text": "Not the A-hole",
                "score": 5000,
                "num_comments": 400,
                "upvote_ratio": 0.95,
                "palavras": 300,
            },
            {
                "id": "yta_post",
                "link_flair_text": "Asshole",
                "score": 4200,
                "num_comments": 1200,
                "upvote_ratio": 0.75,
                "palavras": 300,
            },
        ]
        pontuados = calcular_scores(candidatos, self.config_padrao)
        self.assertEqual(pontuados[0][1]["id"], "yta_post")
        self.assertGreater(pontuados[0][0], pontuados[1][0])

    def test_selecao_diversidade_vereditos(self):
        """Garante que havendo flairs distintas, o segundo selecionado não repete a primeira."""
        pontuados = [
            (0.95, {"id": "1", "link_flair_text": "Asshole", "title": "Post 1"}),
            (0.90, {"id": "2", "link_flair_text": "Asshole", "title": "Post 2"}),
            (0.85, {"id": "3", "link_flair_text": "Not the A-hole", "title": "Post 3"}),
            (0.80, {"id": "4", "link_flair_text": "Everyone Sucks", "title": "Post 4"}),
        ]
        selecionados = selecionar_dupla_diversa(pontuados, quantidade=2, forcar_diversidade=True)
        self.assertEqual(len(selecionados), 2)
        self.assertEqual(selecionados[0]["id"], "1")
        self.assertEqual(selecionados[1]["id"], "3") # pulou o id 2 que tinha flair repetida

        # Fallback se todos tiverem mesma flair
        pontuados_iguais = [
            (0.95, {"id": "1", "link_flair_text": "Asshole"}),
            (0.90, {"id": "2", "link_flair_text": "Asshole"}),
        ]
        fallback = selecionar_dupla_diversa(pontuados_iguais, quantidade=2, forcar_diversidade=True)
        self.assertEqual(len(fallback), 2)
        self.assertEqual(fallback[0]["id"], "1")
        self.assertEqual(fallback[1]["id"], "2")

    def test_extracao_top_comment_ignora_automod(self):
        """Simula resposta JSON com AutoMod pinado e seleciona o primeiro comentário humano."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"data": {"children": []}},
            {
                "data": {
                    "children": [
                        {
                            "kind": "t1",
                            "data": {
                                "author": "AutoModerator",
                                "body": "This is an automated reminder.",
                                "stickied": True,
                                "score": 1,
                            },
                        },
                        {
                            "kind": "t1",
                            "data": {
                                "author": "deleted_user",
                                "body": "[deleted]",
                                "stickied": False,
                                "score": 10,
                            },
                        },
                        {
                            "kind": "t1",
                            "data": {
                                "author": "clever_juror",
                                "body": "YTA. You should have respected their boundaries.",
                                "stickied": False,
                                "score": 1500,
                            },
                        },
                    ]
                }
            },
        ]
        sessao = MagicMock()
        sessao.get.return_value = mock_response

        res = buscar_top_comment(sessao, "/r/AmItheAsshole/comments/123/mock/")
        self.assertIsNotNone(res)
        autor, body, score = res
        self.assertEqual(autor, "clever_juror")
        self.assertEqual(body, "YTA. You should have respected their boundaries.")
        self.assertEqual(score, 1500)

    def test_truncamento_comentario_sentenca(self):
        """Verifica truncamento seguro em fronteira de sentença até 140 palavras."""
        sentenca_1 = "This is the first sentence that sets up the moral problem. " # 10 palavras
        sentenca_2 = "Then comes the second sentence with more details. " # 8 palavras
        sentenca_longa = "Word " * 150 + ". "
        
        # Comentário curto permanece inalterado
        curto = sentenca_1 + sentenca_2
        self.assertEqual(truncar_comentario_sentenca(curto, 140), curto)

        # Comentário longo é truncado na fronteira
        longo = (sentenca_1 * 10) + (sentenca_2 * 10)
        truncado = truncar_comentario_sentenca(longo, 140)
        self.assertTrue(truncado.endswith("[...]"))
        self.assertLessEqual(len(truncado.split()), 142)

    def test_geracao_costura_editorial_pt(self):
        """Verifica se textos em português de abertura, ponte e martelo combinam com os vereditos."""
        # Abertura mista (Inocente + Culpado)
        abertura_mista = gerar_abertura_editorial(["YTA", "NTA"], 2)
        self.assertIn("equilíbrio perfeito do drama humano", abertura_mista)

        # Abertura dupla condenação
        abertura_culpados = gerar_abertura_editorial(["YTA", "ESH"], 2)
        self.assertIn("Semana de tolerância zero", abertura_culpados)

        # Abertura dupla absolvição
        abertura_inocentes = gerar_abertura_editorial(["NTA", "NAH"], 2)
        self.assertIn("Dois casos de tirar o fôlego", abertura_inocentes)

        # Abertura post único
        abertura_unica = gerar_abertura_editorial(["YTA"], 1)
        self.assertIn("Direto dos arquivos morais da internet", abertura_unica)

        # Ponte de transição
        self.assertIn("consciência limpa", gerar_ponte_transicao("NTA"))
        self.assertIn("banco dos réus", gerar_ponte_transicao("YTA"))
        self.assertIn("caos generalizado", gerar_ponte_transicao("ESH"))
        self.assertIn("paz diplomática", gerar_ponte_transicao("NAH"))

        # Bater do martelo: alta controvérsia
        post_polemico = {"upvote_ratio": 0.70, "num_comments": 3000, "score": 1000, "link_flair_text": "Asshole"}
        self.assertIn("audiência brigou nos corredores", gerar_bater_do_martelo(post_polemico, 500))

        # Bater do martelo: condenação com comentário maior que o post
        post_condenacao = {"upvote_ratio": 0.85, "num_comments": 800, "score": 1000, "link_flair_text": "Asshole"}
        self.assertIn("mais aplausos (2500 votos)", gerar_bater_do_martelo(post_condenacao, 2500))

        # Bater do martelo: consenso
        post_consenso = {"upvote_ratio": 0.95, "num_comments": 200, "score": 3000, "link_flair_text": "Not the A-hole"}
        self.assertIn("95% de aprovação", gerar_bater_do_martelo(post_consenso, 1000))

    def test_higienizacao_markdown_eink(self):
        """Verifica higienização com parágrafos limpos e EDIT: em negrito."""
        md = "First paragraph with \u200bzero width space.\n\nEDIT: Added more context.\n\n> Quoted line"
        res = higienizar_markdown_eink(md)
        self.assertNotIn("\u200b", res)
        self.assertIn("<p>First paragraph with zero width space.</p>", res)
        self.assertIn("<strong>EDIT:</strong> Added more context.", res)
        self.assertIn("<blockquote><p>Quoted line</p></blockquote>", res)

    def test_item_fofocas_gera_html_correto(self):
        """Garante que item_fofocas gera estrutura de capítulo contínuo com tags lang=en."""
        caso1 = CasoAITA(
            id="aita_1",
            titulo="AITA for leaving the party early?",
            autor="party_goer",
            corpo_html="<p>I left because I was tired.</p>",
            palavras=250,
            tempo_leitura_min=2,
            score=2500,
            upvote_ratio=0.92,
            num_comments=450,
            flair_original="Not the A-hole",
            veredito_pt="INOCENTE — Livre de Culpa",
            subtitulo_veredito_pt="Absolvido com louvor.",
            comentario_autor="helpful_user",
            comentario_corpo_html="<p>NTA. Your time is your own.</p>",
            comentario_score=1200,
            frase_martelo_pt="Martelo batido por quase unanimidade.",
        )
        secao = SecaoFofocas(
            titulo_coluna="Tribunal do Cotidiano",
            abertura_editorial_pt="Abertura em português.",
            casos=[caso1],
            ponte_transicao_pt=None,
        )
        it = item_fofocas(secao)
        self.assertEqual(it["fonte_id"], "fofocas")
        self.assertEqual(it["titulo"], "Tribunal do Cotidiano")
        self.assertIn('<p class="abertura-coluna"><em>Abertura em português.</em></p>', it["html"])
        self.assertIn('CASO Nº 01 · Depoimento de u/party_goer', it["html"])
        self.assertIn('<div lang="en"><p>I left because I was tired.</p></div>', it["html"])
        self.assertIn('<h4>SENTENÇA DO JÚRI POPULAR</h4>', it["html"])
        self.assertIn('<blockquote lang="en"><p>&ldquo;NTA. Your time is your own.&rdquo;</p></blockquote>', it["html"])
        self.assertIn('INOCENTE — Livre de Culpa', it["html"])

    @patch("time.sleep")
    def test_resiliencia_queda_reddit(self, mock_sleep):
        """Simula falha de conexão na API do Reddit e valida retorno seguro sem exceção."""
        sessao = MagicMock()
        sessao.get.side_effect = Exception("Connection timeout")

        res = buscar_candidatos_reddit(sessao, self.config_padrao)
        self.assertEqual(res, [])

        secao = obter_secao_fofocas(self.config_padrao, [], sessao=sessao)
        self.assertIsNone(secao)


if __name__ == "__main__":
    unittest.main()
