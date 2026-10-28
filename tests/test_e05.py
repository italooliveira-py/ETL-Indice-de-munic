"""Contrato do alvo, corte temporal, contexto disponível e limites de estimação."""
import tempfile
import unittest
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.e05.dados import (rotular, particoes, adicionar_contexto, PREDITORES,
                           NUMERICAS, CATEGORICAS)
from src.e05.experimento import (criar_pipeline, treinar, probabilidade_positiva,
                                metricas, folds_temporais, intervalos_cluster, executar)
from src.e05.__main__ import ler_base
from src.etl_municipal.core.armazenamento import sha256
from unittest.mock import patch


def instrumentos(datas):
    return pd.DataFrame({'nr_convenio': [str(i) for i in range(len(datas))],
                         'codigo_ibge': '2507507', 'data_assinatura': pd.to_datetime(datas),
                         'modalidade': 'Convênio', 'orgao_superior': 'Órgão público',
                         'valor_global_assinatura': 1000.0})


def desembolsos(dados):
    return pd.DataFrame(dados, columns=['id_desembolso', 'nr_convenio', 'codigo_ibge',
                                      'data_desembolso', 'valor_desembolsado']).assign(
        data_desembolso=lambda q: pd.to_datetime(q.data_desembolso))


class TestAlvo90Dias(unittest.TestCase):
    def test_primeiro_repasse_janela_inclusiva_e_ausencia(self):
        base = instrumentos(['2022-01-01'] * 5)
        d = desembolsos([
            ('d0', '0', '2507507', '2022-01-01', 10),
            ('d1', '1', '2507507', '2022-04-01', 10),  # dia 90
            ('d2', '2', '2507507', '2022-04-02', 10),
            ('d3', '3', '2507507', '2022-01-02', 0),
        ])
        resultado = rotular(base, d, '2026-07-17')
        self.assertEqual(resultado.sem_repasse_90d.tolist(), [0, 0, 1, 1, 1])

    def test_seguimento_incompleto_nao_e_classe_1(self):
        resultado = rotular(instrumentos(['2026-07-01']), desembolsos([]), '2026-07-17')
        self.assertTrue(pd.isna(resultado.sem_repasse_90d.iloc[0]))
        self.assertEqual(resultado.motivo_exclusao.iloc[0], 'seguimento_90d_incompleto')

    def test_repasse_anterior_a_assinatura_excluido(self):
        d = desembolsos([('d', '0', '2507507', '2021-12-31', 10)])
        resultado = rotular(instrumentos(['2022-01-01']), d, '2026-07-17')
        self.assertEqual(resultado.motivo_exclusao.iloc[0], 'repasse_anterior_assinatura')
        self.assertTrue(pd.isna(resultado.sem_repasse_90d.iloc[0]))

    def test_duplicidade_de_evento_bloqueia(self):
        d = desembolsos([('d', '0', '2507507', '2022-01-02', 10)] * 2)
        with self.assertRaises(ValueError):
            rotular(instrumentos(['2022-01-01']), d, '2026-07-17')

    def test_cortes_usam_maturidade_e_ano_de_assinatura(self):
        q = particoes(rotular(instrumentos(['2022-01-01', '2022-12-31', '2023-01-01',
                                           '2023-12-31', '2024-01-01']), desembolsos([]), '2026-07-17'))
        self.assertEqual(q.treino_validacao.tolist(), [True, False, False, False, False])
        self.assertEqual(q.validacao.tolist(), [False, False, True, False, False])
        self.assertEqual(q.treino_final.tolist(), [True, True, True, False, False])
        self.assertEqual(q.teste.tolist(), [False, False, False, False, True])


class TestContexto(unittest.TestCase):
    def test_dados_depois_da_assinatura_nao_entram(self):
        ins = instrumentos(['2022-06-01'])
        coh = particoes(rotular(ins, desembolsos([]), '2026-07-17'))
        hist = pd.concat([ins, instrumentos(['2022-05-01', '2023-01-01'])], ignore_index=True)
        ibge = pd.DataFrame({'codigo_ibge': ['2507507'] * 4,
                             'variavel': ['populacao_ibge', 'pib_pc_ibge'] * 2,
                             'ano_referencia': [2021, 2019, 2022, 2021], 'valor': [100, 10, 9999, 9999],
                             'data_disponibilidade': pd.to_datetime(['2021-08-27', '2021-12-17', '2023-06-28', '2023-12-15'])})
        dca = pd.DataFrame({'codigo_ibge': ['2507507'] * 2, 'ano': [2020, 2021],
                            'data_envio': pd.to_datetime(['2021-04-30', '2022-07-01'], utc=True),
                            'receita_liquida': [1000, 99999], 'convenios_uniao': [100, 999]})
        rgf = pd.DataFrame({'codigo_ibge': ['2507507'] * 2, 'ano': [2020, 2021],
                            'data_envio': pd.to_datetime(['2021-01-30', '2022-07-01'], utc=True),
                            'razao_declarada': [50, 99]})
        ds = desembolsos([('antes', 'h', '2507507', '2022-05-01', 100),
                          ('mesmo_dia', '0', '2507507', '2022-06-01', 1000),
                          ('futuro', 'h', '2507507', '2023-01-01', 99999)])
        pix = pd.DataFrame({'codigo_ibge': ['2507507'], 'data_emissao_ob': pd.to_datetime(['2022-05-01']), 'valor_pago': [50]})
        q = adicionar_contexto(coh, hist, ds, pix, ibge, dca, rgf).iloc[0]
        self.assertAlmostEqual(q.log_populacao_ibge, np.log1p(100))
        self.assertAlmostEqual(q.log_desembolso_365d_percap, np.log1p(1))
        self.assertEqual(q.historico_assinados_365d, 1)
        self.assertEqual(q.pessoal_rgf_pct, 50)
        self.assertAlmostEqual(q.dependencia_convenios_uniao, 0.1)
        self.assertEqual(q.ano_ref_dca, 2020)
        self.assertEqual(q.ano_ref_populacao_ibge, 2021)

    def test_lista_preditores_nao_contem_resultado_identificador_ou_ano_futuro(self):
        proibidas = {'nr_convenio', 'codigo_ibge', 'sem_repasse_90d', 'situacao', 'ano_coorte',
                     'valor_desembolsado', 'primeiro_repasse', 'qtd_prorrogacoes'}
        self.assertFalse(proibidas.intersection(PREDITORES))
        self.assertEqual(len(PREDITORES), 12)


def matriz(n=20, unica=True):
    q = pd.DataFrame({c: np.arange(n, dtype=float) for c in NUMERICAS})
    for c in CATEGORICAS:
        q[c] = 'categoria'
    q['sem_repasse_90d'] = 1 if unica else np.arange(n) % 2
    q['nr_convenio'] = [str(i) for i in range(n)]
    q['codigo_ibge'] = '2507507'
    q['data_assinatura'] = pd.Timestamp('2022-01-01')
    q['fim_horizonte'] = q.data_assinatura + pd.Timedelta(days=90)
    return q


CONFIG = {'random_state': 42, 'origens_cv': ['2022-07-01', '2022-08-01', '2022-09-01'],
          'limiar_classificacao': 0.5, 'bootstrap_municipios': 20}


class TestExperimento(unittest.TestCase):
    def test_base_versionada_e_usada_sem_preparacao_local(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            pasta = raiz / 'dados/modelagem/e05'
            pasta.mkdir(parents=True)
            pd.DataFrame({'teste': [1, 2]}).to_parquet(pasta / 'base_modelagem.parquet', index=False)
            meta = {'sha256_dataset': sha256((pasta / 'base_modelagem.parquet').read_bytes())}
            (pasta / 'manifesto_base.json').write_text(json.dumps(meta))
            with patch('src.e05.__main__.ROOT', raiz):
                dados, manifesto = ler_base(raiz / 'output/e05')
            self.assertEqual(dados.teste.tolist(), [1, 2])
            self.assertEqual(manifesto, meta)

    def test_base_alterada_nao_e_aceita_pelo_manifesto(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            pd.DataFrame({'teste': [1]}).to_parquet(pasta / 'base_modelagem.parquet', index=False)
            (pasta / 'manifesto_base.json').write_text(json.dumps({'sha256_dataset': 'invalido'}))
            with self.assertRaises(ValueError):
                ler_base(pasta)

    def test_logistica_classe_unica_e_inestimavel_sem_fabricar_numeros(self):
        modelo, meta = treinar('logistica', matriz(), CONFIG)
        self.assertIsNone(modelo)
        self.assertEqual(meta['status'], 'nao_estimavel_treino_classe_unica')

    def test_arvore_classe_unica_probabilidade_positiva_correta(self):
        modelo, meta = treinar('arvore', matriz(), CONFIG)
        self.assertEqual(meta['status'], 'degenerado_treino_classe_unica')
        np.testing.assert_array_equal(probabilidade_positiva(modelo, matriz()[PREDITORES]), np.ones(20))

    def test_metricas_constantes_com_duas_classes_nao_sao_boa_discriminacao(self):
        q = metricas([0, 1, 1, 1], [1, 1, 1, 1])
        self.assertEqual(q['acuracia_balanceada'], 0.5)
        self.assertEqual(q['roc_auc'], 0.5)
        self.assertEqual(q['acuracia'], 0.75)

    def test_validacao_classe_unica_nao_publica_auc_ou_balanced_accuracy_enganosas(self):
        q = metricas([1, 1, 1], [1, 1, 1])
        self.assertIsNone(q['roc_auc'])
        self.assertIsNone(q['acuracia_balanceada'])

    def test_folds_sem_suporte_nao_viram_kfold_aleatorio(self):
        folds, auditoria = folds_temporais(matriz(), CONFIG['origens_cv'])
        self.assertEqual(folds, [])
        self.assertFalse(auditoria.valido.any())

    def test_logistica_com_duas_classes_e_ajustavel(self):
        modelo, meta = treinar('logistica', matriz(unica=False), CONFIG)
        self.assertEqual(meta['status'], 'estimado')
        self.assertEqual(set(modelo.classes_), {0, 1})

    def test_bootstrap_recusa_falsa_precisao_com_unico_controle(self):
        q = pd.DataFrame({'modelo': ['trivial'] * 4, 'codigo_ibge': ['2507507'] * 4,
                           'y_real': [0, 1, 1, 1], 'probabilidade': [1.] * 4})
        intervalos, meta = intervalos_cluster(q)
        self.assertTrue(intervalos.empty)
        self.assertIn('inferior_a_10', meta['status'])

    def test_execucao_preserva_mesmos_ids_e_nao_substitui_logistica(self):
        q = matriz()
        q['treino_validacao'] = np.arange(20) < 8
        q['validacao'] = (np.arange(20) >= 8) & (np.arange(20) < 12)
        q['treino_final'] = np.arange(20) < 12
        q['teste'] = np.arange(20) >= 12
        q.loc[12, 'sem_repasse_90d'] = 0
        with tempfile.TemporaryDirectory() as temp:
            resultado, m, p = executar(q, CONFIG, Path(temp))
            self.assertEqual(resultado['status_conclusao'], 'inviavel_discriminacao_treino_classe_unica')
            self.assertEqual(set(p.modelo), {'trivial', 'arvore', 'floresta'})
            ids = p.groupby('modelo').nr_convenio.apply(set)
            self.assertTrue(all(i == ids.iloc[0] for i in ids))
            logistica = m[(m.particao == 'teste_2024') & (m.modelo == 'logistica')].iloc[0]
            self.assertTrue(pd.isna(logistica.roc_auc))
            self.assertFalse((Path(temp) / 'logistica.joblib').exists())


if __name__ == '__main__':
    unittest.main()
