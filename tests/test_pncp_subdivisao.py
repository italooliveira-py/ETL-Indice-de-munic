import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import etl_primario as etl
import etl_confiabilidade as seguro
from test_checkpoint1 import compra, pagina, resposta


class SubdivisaoPncp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for nome, pasta in (("RAW_DIR", "raw"), ("OUTPUT_DIR", "output")):
            remendo = patch.object(etl, nome, self.root / pasta)
            remendo.start()
            self.addCleanup(remendo.stop)
        self.config = {
            "pncp_max_tentativas": 1,
            "pncp_intervalo_requisicoes_segundos": 0,
            "pncp_backoff_base_segundos": 0,
            "pncp_tamanho_pagina": 50,
        }
        self.sessao = Mock(spec=requests.Session)

    def coletar(self, inicio=date(2023, 10, 1), fim=date(2023, 12, 31)):
        self.assertTrue(hasattr(etl, "coletar_janela_pncp"), "Função de subdivisão ainda ausente")
        return etl.coletar_janela_pncp(
            self.sessao, self.config, "PB", {"uf": "PB"}, inicio, fim, 6, {}
        )

    def test_trimestre_400_duas_metades_completas(self):
        self.sessao.get.side_effect = [
            resposta(400, {"message": "intervalo muito amplo"}),
            resposta(dados=pagina([compra("esquerda")])),
            resposta(dados=pagina([compra("direita")])),
        ]
        resultado = self.coletar()
        self.assertEqual(resultado["situacao"], "completa")
        self.assertEqual(len(resultado["dados"]), 2)
        self.assertEqual(resultado["janelas_filhas"], ["2023-10-01/2023-11-15", "2023-11-16/2023-12-31"])
        intervalos = [(c.kwargs["params"]["dataInicial"], c.kwargs["params"]["dataFinal"])
                      for c in self.sessao.get.call_args_list]
        self.assertEqual(intervalos, [("20231001", "20231231"), ("20231001", "20231115"),
                                     ("20231116", "20231231")])

    def test_filha_vazia_e_filha_com_dados_completam_pai(self):
        self.sessao.get.side_effect = [resposta(400), resposta(204), resposta(dados=pagina([compra()]))]
        resultado = self.coletar()
        self.assertEqual(resultado["situacao"], "completa")
        self.assertEqual(len(resultado["dados"]), 1)

    def test_filha_com_falha_deixa_pai_parcial(self):
        self.sessao.get.side_effect = [resposta(400), resposta(dados=pagina([compra()])), resposta(400)]
        resultado = self.coletar(date(2023, 10, 1), date(2023, 10, 2))
        self.assertEqual(resultado["situacao"], "parcial")
        self.assertEqual(len(resultado["dados"]), 1)
        self.assertIn("HTTP permanente 400", resultado["erro_final"])

    def test_um_dia_400_encerra_e_preserva_corpo_truncado(self):
        self.sessao.get.return_value = resposta(400, {"message": "x" * 2000})
        resultado = self.coletar(date(2023, 10, 1), date(2023, 10, 1))
        self.assertEqual(resultado["situacao"], "falhou")
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertIn("message", resultado["erro_final"])
        self.assertLessEqual(len(resultado["erro_final"]), 800)

    def test_duplicados_entre_filhas_sao_deduplicados(self):
        self.sessao.get.side_effect = [resposta(400), resposta(dados=pagina([compra("igual")])),
                                      resposta(dados=pagina([compra("igual"), compra("distinto")]))]
        resultado = self.coletar()
        self.assertEqual(resultado["registros_antes_deduplicacao"], 3)
        self.assertEqual(resultado["registros_apos_deduplicacao"], 2)
        self.assertEqual({x["numeroControlePNCP"] for x in resultado["dados"]}, {"igual", "distinto"})

    def test_resume_reutiliza_checkpoints_das_filhas(self):
        self.sessao.get.side_effect = [resposta(400), resposta(dados=pagina([compra("a")])),
                                      resposta(dados=pagina([compra("b")]))]
        self.coletar()
        self.sessao.get.reset_mock()
        self.sessao.get.side_effect = [resposta(400)]
        resultado = self.coletar()
        self.assertEqual(self.sessao.get.call_count, 1)
        self.assertEqual(resultado["situacao"], "completa")
        self.assertEqual(len(resultado["dados"]), 2)

    def test_parcial_nao_publica_zero_no_agregado(self):
        config = {
            **self.config,
            "municipios": [{"codigo_ibge": "2507507", "nome": "João Pessoa", "uf": "PB"}],
            "escopo": {"tipo": "uf", "ufs": ["PB"]},
            "ano_inicial": 2023,
            "ano_final": 2023,
            "pncp_janela_meses": 12,
            "pncp_modalidades": [6],
        }
        self.sessao.get.side_effect = [resposta(400), resposta(204), resposta(400)]
        _, agregado = etl.coletar_pncp(self.sessao, config, [])
        self.assertEqual(agregado.iloc[0].cobertura_pncp, "parcial")
        self.assertTrue(agregado.iloc[0].total_contratacoes is None)

    def test_total_declarado_inconsistente_deixa_filha_parcial(self):
        esquerda = {**pagina([compra("a")], total=2), "totalRegistros": 3}
        segunda = {**pagina([compra("b")], total=2, numero=2), "totalRegistros": 3}
        self.sessao.get.side_effect = [resposta(400), resposta(dados=esquerda), resposta(dados=segunda),
                                      resposta(dados=pagina([compra("c")]))]
        resultado = self.coletar()
        self.assertEqual(resultado["situacao"], "parcial")
        self.assertIn("soma das páginas", resultado["erro_final"])

    def test_manifesto_pai_registra_rastreabilidade(self):
        self.sessao.get.side_effect = [resposta(400), resposta(dados=pagina([compra("a")])),
                                      resposta(dados=pagina([compra("b")]))]
        self.coletar()
        manifesto = json.loads((etl.OUTPUT_DIR / "manifesto_coleta.json").read_text(encoding="utf-8"))
        pai = next(r for r in manifesto if r["periodo"] == "2023-10-01/2023-12-31")
        self.assertEqual(pai["situacao"], "completa")
        self.assertEqual(pai["registros_antes_deduplicacao"], 2)
        self.assertEqual(pai["registros_apos_deduplicacao"], 2)
        self.assertEqual(len(pai["janelas_filhas"]), 2)

    def test_contagem_bruta_inclui_duplicatas_na_mesma_filha(self):
        self.sessao.get.return_value = resposta(dados=pagina([compra("igual"), compra("igual")]))
        resultado = self.coletar(date(2023, 10, 1), date(2023, 10, 1))
        self.assertEqual(resultado["registros_antes_deduplicacao"], 2)
        self.assertEqual(resultado["registros_apos_deduplicacao"], 1)

    def test_refresh_interrompido_nao_mistura_geracoes_das_filhas(self):
        self.sessao.get.side_effect = [resposta(400), resposta(dados=pagina([compra("old-left")])),
                                      resposta(dados=pagina([compra("old-right")]))]
        self.coletar()
        self.config["_refresh_fontes"] = ["pncp"]
        self.sessao.get.side_effect = [
            resposta(400),
            resposta(dados=pagina([compra("new-left-1")], 2)),
            KeyboardInterrupt(),
        ]
        with self.assertRaises(KeyboardInterrupt):
            self.coletar()
        self.config.pop("_refresh_fontes")
        self.sessao.get.side_effect = [
            resposta(400),
            resposta(dados=pagina([compra("new-left-2")], 2, 2)),
            resposta(dados=pagina([compra("new-right")])),
        ]
        resultado = self.coletar()
        self.assertEqual(
            {item["numeroControlePNCP"] for item in resultado["dados"]},
            {"new-left-1", "new-left-2", "new-right"},
        )

    def test_interrupcao_em_filha_atualiza_manifesto_pai(self):
        self.sessao.get.side_effect = [resposta(400), resposta(dados=pagina([compra("a")])), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.coletar()
        manifesto = json.loads((etl.OUTPUT_DIR / "manifesto_coleta.json").read_text(encoding="utf-8"))
        pai = next(r for r in manifesto if r["periodo"] == "2023-10-01/2023-12-31")
        self.assertEqual(pai["situacao"], "parcial")
        self.assertEqual(pai["erro_final"], "Interrompido por Ctrl+C durante subdivisão")
        self.assertEqual(len(pai["janelas_filhas"]), 2)
        self.assertGreaterEqual(pai["paginas_concluidas"], 1)

    def test_resume_reutiliza_marcador_de_geracao_da_versao_anterior(self):
        inicio, fim = date(2023, 10, 1), date(2023, 12, 31)
        chave_historica = f"PB-{inicio}-{fim}-6-50"
        pasta_geracao = seguro.geracao_cache(etl.RAW_DIR / "pncp", chave_historica, refresh=True)
        nome = "PB_20231001_20231231_modalidade_06_tamanho_50_pagina_0001.json"
        seguro.salvar_json_atomico(pasta_geracao / nome, pagina([compra("geracao-vigente")]))
        seguro.salvar_json_atomico(etl.RAW_DIR / "pncp" / "pages" / nome, pagina([compra("legado")]))
        resultado = self.coletar(inicio, fim)
        self.sessao.get.assert_not_called()
        self.assertEqual(
            [item["numeroControlePNCP"] for item in resultado["dados"]],
            ["geracao-vigente"],
        )


if __name__ == "__main__":
    unittest.main()
