import unittest

import numpy as np
import pandas as pd

from src.e06 import base_bronze, dados, experimento, operacao


class TestBaseBronze(unittest.TestCase):
    def setUp(self):
        self.instrumentos = pd.DataFrame({
            "nr_convenio": ["a", "b", "c", "d"],
            "codigo_ibge": ["pb"] * 4,
            "data_assinatura": pd.to_datetime(["2020-01-01", "2020-01-01", "2020-12-31", "2021-01-01"]),
        })
        self.eventos = pd.DataFrame({
            "nr_convenio": ["a", "b", "b", "c"], "codigo_ibge": ["pb"] * 4,
            "data_desembolso": pd.to_datetime(["2020-12-31", "2019-12-31", "2021-01-01", "2020-12-31"]),
            "valor_desembolsado": [10.0, 100.0, 10.0, 50.0],
        })

    def test_horizonte_inclusivo_corte_e_censura(self):
        alvo = base_bronze.rotular(self.instrumentos, self.eventos, pd.Timestamp("2020-12-31"))
        self.assertEqual(alvo.iloc[:2].tolist(), [False, True])
        self.assertTrue(alvo.iloc[2:].isna().all())

    def test_historico_exclui_evento_e_maturidade_do_proprio_dia(self):
        corte = pd.Timestamp("2021-12-31")
        instrumentos = self.instrumentos.assign(**{
            dados.ALVO: base_bronze.rotular(self.instrumentos, self.eventos, corte)
        })
        historico = base_bronze.historico_na_assinatura(instrumentos, self.eventos, corte)
        np.testing.assert_allclose(historico.loc[2, dados.CONTAGENS].astype(float), [0, 0, 0, 0])
        np.testing.assert_allclose(historico.loc[3, dados.CONTAGENS].astype(float), [2, 1, 2, 60])


class TestOperacaoMensal(unittest.TestCase):
    def test_teto_mensal_empates_e_piso_estrito_independem_da_ordem(self):
        dados_teste = pd.DataFrame({
            "data_assinatura": pd.to_datetime(["2023-01-04"] * 4 + ["2023-02-01"] * 3),
            "p": [0.9, 0.8, 0.8, 0.5, 0.7, 0.5, 0.1],
            "y": [1, 1, 0, 1, 1, 0, 0],
        })
        cenario = operacao.Cenario("teste", 1, 1, 2)
        resumo, meses, selecionados = operacao.avaliar_cenario(dados_teste, cenario)
        invertido, _, _ = operacao.avaliar_cenario(dados_teste.iloc[::-1], cenario)
        self.assertEqual(resumo, invertido)
        self.assertEqual(resumo["vp"], 2.5)
        self.assertEqual(resumo["revisoes"], 3)
        self.assertEqual(resumo["utilidade_normalizada"], 2)
        self.assertEqual([m["restricao"] for m in meses], ["capacidade", "piso_economico"])
        self.assertEqual(selecionados.loc[selecionados["p"].eq(0.5), "peso"].sum(), 0)

    def test_rejeita_parametros_invalidos(self):
        for valores in [(np.nan, 1, 2), (1, 0, 2), (1, 1, 0)]:
            with self.subTest(valores=valores), self.assertRaises(ValueError):
                operacao.Cenario("invalido", *valores)

    def test_logistica_l1_usa_penalizacao_declarada(self):
        modelo = experimento.criar_pipeline("logistica", {"C": 1.0, "l1_ratio": 1.0},
                                             ["modalidade"], dados.ler_config())
        self.assertEqual(modelo.named_steps["modelo"].penalty, "elasticnet")

