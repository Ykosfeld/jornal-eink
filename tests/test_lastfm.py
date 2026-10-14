import datetime as dt
import os
import unittest
from unittest.mock import patch

import requests

from src.lastfm import (
    _avaliar_candidato_bilingue,
    _eh_artigo_musical,
    _eh_musica_classica,
    _titulos_candidatos,
    interpretar_recenttracks,
    priorizar_artigos_musica,
    validar_config,
)
from src.pipeline import coletar_curiosidades


def fake_track(artist, name="Track", album="Album", uts=1728900000, now_playing=False):
    item = {
        "artist": {"#text": artist},
        "name": name,
        "album": {"#text": album},
        "url": f"https://www.last.fm/music/{artist}/_/{name}",
    }
    if now_playing:
        item["@attr"] = {"nowplaying": "true"}
    else:
        item["date"] = {"uts": str(uts), "#text": "date"}
    return item


def artigo(titulo, pageid, revid=100, chars=2000, lang="pt"):
    return {
        "titulo": titulo,
        "pageid": pageid,
        "revid": revid,
        "chars": chars,
        "url": f"https://{lang}.wikipedia.org/wiki/{titulo.replace(' ', '_')}",
        "html": f"<p>{titulo} é uma banda de rock e música clássica.</p>",
        "imagem": None,
        "lang": lang,
    }


class Resposta:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")
        return None


class SessaoMock:
    def __init__(self, data):
        self.data = data

    def get(self, url, params=None, timeout=None):
        return Resposta(self.data)


class SessaoIndisponivel:
    def get(self, url, params=None, timeout=None):
        raise requests.ConnectionError("falha de conexão")


class LastFmTests(unittest.TestCase):
    def test_validar_config_padroes_e_validacoes(self):
        cfg = validar_config({})
        self.assertFalse(cfg["ativar"])
        self.assertEqual(cfg["janela_dias"], 7)
        self.assertEqual(cfg["max_itens"], 10)
        self.assertEqual(cfg["temas"], ["Música", "Música clássica"])

        # Quando ativa, exige usuario e api_key
        with self.assertRaisesRegex(ValueError, "usuario é obrigatório"):
            validar_config({"ativar": True, "api_key": "chave"})

        with self.assertRaisesRegex(ValueError, "api_key.*é obrigatória"):
            validar_config({"ativar": True, "usuario": "usuario"})

        # Variável de ambiente preenche api_key
        with patch.dict(os.environ, {"LASTFM_API_KEY": "chave_env"}):
            valida = validar_config({"ativar": True, "usuario": "user"})
            self.assertEqual(valida["api_key"], "chave_env")

        # Inteiros positivos
        with self.assertRaisesRegex(ValueError, "janela_dias"):
            validar_config({"janela_dias": -1})
        with self.assertRaisesRegex(ValueError, "max_itens"):
            validar_config({"max_itens": 0})
        with self.assertRaisesRegex(ValueError, "temas deve ser uma lista"):
            validar_config({"temas": []})

    def test_interpretar_recenttracks_agrega_ordena_e_filtra_janela(self):
        hoje = dt.date(2026, 10, 14)
        inicio_ts = int(dt.datetime(2026, 10, 8, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp())
        ts_antigo = inicio_ts - 1000
        ts_recente_1 = inicio_ts + 10000
        ts_recente_2 = inicio_ts + 20000

        tracks = [
            fake_track("Radiohead", "Airbag", "OK Computer", ts_recente_1),
            fake_track("Radiohead", "Paranoid Android", "OK Computer", ts_recente_2),
            fake_track("Radiohead", "15 Step", "In Rainbows", ts_recente_1),
            fake_track("David Bowie", "Heroes", "Heroes", ts_recente_2),
            fake_track("David Bowie", "Heroes", "Heroes", ts_recente_2),
            fake_track("Artista Antigo", "Old Song", "Old Album", ts_antigo),
            fake_track("Artista NowPlaying", "Current Song", "Current Album", now_playing=True),
        ]
        dados = {"recenttracks": {"track": tracks}}

        artistas = interpretar_recenttracks(dados, hoje, janela_dias=7, max_itens=5)

        nomes = [a["nome"] for a in artistas]
        self.assertIn("Radiohead", nomes)
        self.assertIn("David Bowie", nomes)
        self.assertIn("Artista NowPlaying", nomes)
        self.assertNotIn("Artista Antigo", nomes)

        radiohead = next(a for a in artistas if a["nome"] == "Radiohead")
        self.assertEqual(radiohead["scrobbles"], 3)
        self.assertEqual(len(radiohead["albuns"]), 2)
        self.assertEqual(radiohead["albuns"]["ok computer"]["scrobbles"], 2)

        # Radiohead tem 3 scrobbles, David Bowie tem 2 -> Radiohead primeiro
        self.assertEqual(artistas[0]["nome"], "Radiohead")

    def test_interpretar_trata_track_como_dicionario_unico_e_ignora_invalidos(self):
        hoje = dt.date(2026, 10, 14)
        inicio_ts = int(dt.datetime(2026, 10, 8, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp())
        dados = {"recenttracks": {"track": fake_track("Solo", uts=inicio_ts + 500)}}

        artistas = interpretar_recenttracks(dados, hoje, janela_dias=7)
        self.assertEqual(len(artistas), 1)
        self.assertEqual(artistas[0]["nome"], "Solo")

        # Dados malformados geram aviso e não explodem
        with self.assertLogs("src.lastfm", level="WARNING"):
            artistas_inv = interpretar_recenttracks(
                {"recenttracks": {"track": [{"name": "No Artist"}, {"artist": {"#text": "Sem Data"}}]}},
                hoje,
            )
            self.assertEqual(len(artistas_inv), 0)

    @patch("src.lastfm.api")
    def test_titulos_candidatos_inclui_sufixos_e_busca(self, mock_api):
        mock_api.return_value = {"query": {"search": [{"title": "Hit de Busca"}]}}
        candidatos = _titulos_candidatos(
            object(), {"lang": "pt"}, "Radiohead", "artista",
        )
        self.assertIn("Radiohead", candidatos)
        self.assertIn("Radiohead (banda)", candidatos)
        self.assertIn("Hit de Busca", candidatos)

    def test_deteccao_artigo_musical_e_musica_classica(self):
        art_rock = artigo("Radiohead", 1)
        art_rock["html"] = "<p>Radiohead é uma banda britânica de rock alternativo.</p>"
        self.assertTrue(_eh_artigo_musical(art_rock, ["Categoria:Bandas de rock"]))
        self.assertFalse(_eh_musica_classica(art_rock, ["Categoria:Bandas de rock"]))

        art_chopin = artigo("Frédéric Chopin", 2)
        art_chopin["html"] = "<p>Frédéric Chopin foi um proeminente compositor clássico e pianista.</p>"
        self.assertTrue(_eh_artigo_musical(art_chopin, ["Categoria:Compositores clássicos"]))
        self.assertTrue(_eh_musica_classica(art_chopin, ["Categoria:Compositores da era clássica"]))

        art_outro = artigo("Outro Assunto", 3)
        art_outro["html"] = "<p>Este é um artigo sobre culinária.</p>"
        self.assertFalse(_eh_artigo_musical(art_outro, ["Categoria:Culinária"]))

    @patch("src.lastfm.avaliar_qualidade")
    @patch("src.lastfm.artigo_aceitavel", return_value=True)
    @patch("src.lastfm._obter_categorias", return_value=["Categoria:Músicos"])
    @patch("src.lastfm.buscar_artigo")
    @patch("src.lastfm._titulos_candidatos")
    def test_busca_bilingue_equilibrio_qualidade_e_caracteres(
        self, mock_titulos, mock_buscar, mock_cats, mock_aceitavel, mock_qualidade
    ):
        mock_titulos.side_effect = lambda s, w, t, tp, a: [t]
        art_pt = artigo("David Bowie", 10, chars=2500, lang="pt")
        art_en = artigo("David Bowie", 20, chars=3000, lang="en")

        def fake_buscar(sessao, wcfg, titulo):
            return art_pt if wcfg["lang"] == "pt" else art_en

        mock_buscar.side_effect = fake_buscar
        # Ambas classes iguais (3): pt ganha pelo bônus de idioma (+1000)
        mock_qualidade.return_value = (3, None)

        class FiltroMock:
            ativo = True
            disjuntor_acionado = False
            config = {}

        filtro = FiltroMock()
        cfg_base = {"wikipedia": {"max_caracteres": 15000}}
        fmcfg = {"peso_classe": 2000, "bonus_idioma_pt": 1000}
        escolhido, _ = _avaliar_candidato_bilingue(
            object(), cfg_base, "David Bowie", "artista", "David Bowie",
            set(), set(), filtro, fmcfg,
        )
        self.assertEqual(escolhido["lang"], "pt")

        # Se en tiver qualidade significativamente superior (FA = 6 vs Start = 2), en ganha
        def fake_qualidade(sessao, revid, cfg):
            return (2, None) if "ptwiki" in cfg["modelo"] else (6, None)

        mock_qualidade.side_effect = fake_qualidade
        escolhido_superior, _ = _avaliar_candidato_bilingue(
            object(), cfg_base, "David Bowie", "artista", "David Bowie",
            set(), set(), filtro, fmcfg,
        )
        self.assertEqual(escolhido_superior["lang"], "en")

    @patch("src.lastfm._avaliar_candidato_bilingue")
    @patch("src.lastfm.coletar_scrobbles")
    def test_priorizar_artigos_musica_separa_musica_e_classica(
        self, mock_scrobbles, mock_avaliar
    ):
        hoje = dt.date(2026, 10, 14)
        ts = int(dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc).timestamp())
        mock_scrobbles.return_value = {
            "recenttracks": {
                "track": [
                    fake_track("Frédéric Chopin", "Nocturne", "Nocturnes", ts),
                    fake_track("Radiohead", "Karma Police", "OK Computer", ts),
                ]
            }
        }

        art_chopin = {**artigo("Frédéric Chopin", 1), "lang": "pt"}
        art_radiohead = {**artigo("Radiohead", 2), "lang": "en"}

        def fake_avaliar(sessao, cfg, termo, tipo, artista, us_t, us_ids, fq, fmcfg):
            if artista == "Frédéric Chopin":
                return art_chopin, True  # é clássica
            if artista == "Radiohead":
                return art_radiohead, False  # não é clássica
            return None, False

        mock_avaliar.side_effect = fake_avaliar

        cfg = {
            "personalizacao_cultural": {
                "ativar": True,
                "lastfm": {
                    "ativar": True,
                    "usuario": "ykosfeld",
                    "api_key": "fakekey",
                    "temas": ["Música", "Música clássica"],
                },
            },
            "wikipedia": {"min_caracteres": 300},
        }

        res, motivo = priorizar_artigos_musica(
            object(), cfg, set(), set(), hoje, temas_alvo=["Música", "Música clássica"]
        )

        self.assertEqual(motivo, "")
        self.assertIn("Música", res)
        self.assertIn("Música clássica", res)
        self.assertEqual(res["Música clássica"]["titulo"], "Frédéric Chopin")
        self.assertEqual(res["Música"]["titulo"], "Radiohead")
        self.assertIn("passarinho vermelho", res["Música"]["nota"])
        self.assertIn("Last.fm · Radiohead", res["Música"]["caminho"])

    @patch("src.lastfm._avaliar_candidato_bilingue")
    @patch("src.lastfm.coletar_scrobbles")
    def test_artista_em_usados_tenta_album_e_faixa(
        self, mock_scrobbles, mock_avaliar
    ):
        hoje = dt.date(2026, 10, 14)
        ts = int(dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc).timestamp())
        mock_scrobbles.return_value = {
            "recenttracks": {
                "track": [
                    fake_track("Radiohead", "Karma Police", "OK Computer", ts),
                ]
            }
        }

        art_album = {**artigo("OK Computer", 10), "lang": "pt"}

        def fake_avaliar(sessao, cfg, termo, tipo, artista, us_t, us_ids, fq, fmcfg):
            # Artista "Radiohead" já está em usados_ids, então o chamador passa para o álbum
            if tipo == "álbum":
                return art_album, False
            return None, False

        mock_avaliar.side_effect = fake_avaliar

        cfg = {
            "personalizacao_cultural": {
                "ativar": True,
                "lastfm": {
                    "ativar": True,
                    "usuario": "ykosfeld",
                    "api_key": "fakekey",
                },
            },
            "wikipedia": {"min_caracteres": 300},
        }

        res, motivo = priorizar_artigos_musica(
            object(), cfg, {"Radiohead"}, {1}, hoje, temas_alvo=["Música"]
        )

        self.assertEqual(motivo, "")
        self.assertEqual(res["Música"]["titulo"], "OK Computer")
        self.assertIn("(álbum)", res["Música"]["caminho"])

    def test_falha_de_rede_retorna_fallback_sem_excecao(self):
        cfg = {
            "personalizacao_cultural": {
                "ativar": True,
                "lastfm": {
                    "ativar": True,
                    "usuario": "ykosfeld",
                    "api_key": "fakekey",
                },
            },
            "wikipedia": {"min_caracteres": 300},
        }
        with self.assertLogs("src.lastfm", level="WARNING"):
            res, motivo = priorizar_artigos_musica(
                SessaoIndisponivel(), cfg, set(), set(), dt.date(2026, 10, 14), temas_alvo=["Música"]
            )
        self.assertEqual(res, {})
        self.assertEqual(motivo, "falha ao consultar Last.fm")

    @patch("src.pipeline.sortear_artigo")
    def test_pipeline_usa_artigo_priorizado_do_lastfm(self, mock_sortear):
        art_musica = {
            **artigo("Radiohead", 42),
            "caminho": "Last.fm · Radiohead (artista)",
            "nota": "Um passarinho vermelho me contou que você andou ouvindo bastante isso ultimamente.",
        }
        cfg = {
            "wikipedia": {
                "api": "https://pt.wikipedia.org/w/api.php",
                "max_caracteres": 1000,
                "min_caracteres": 300,
            },
            "imagens": {"ativar": False},
            "temas": {"Música": []},
        }
        artigos, novos, pulados = coletar_curiosidades(
            object(), cfg, set(), set(), object(), dt.date(2026, 10, 14),
            priorizados={"Música": art_musica},
        )
        mock_sortear.assert_not_called()
        self.assertEqual(artigos[0][1]["titulo"], "Radiohead")
        self.assertEqual(novos[0]["pageid"], 42)
        self.assertEqual(novos[0]["tema"], "Música")


if __name__ == "__main__":
    unittest.main()
