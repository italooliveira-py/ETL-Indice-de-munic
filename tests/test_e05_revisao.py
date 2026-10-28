"""Revisão E05: continuidade da E04, alvos separados e métricas corretas."""
import unittest
import numpy as np
import pandas as pd

from src.e05.revisao import base_180, configuracoes
from src.e05.experimento import criar_pipeline, metricas, treinar
from src.e05.dados import NUMERICAS, CATEGORICAS


class RevisaoE05(unittest.TestCase):
    def test_180_nao_altera_o_rotulo_90_e_inclui_dia_limite(self):
        inicio = pd.Timestamp('2022-01-01')
        q = pd.DataFrame({'data_assinatura': [inicio] * 4,
                          'primeiro_repasse': [inicio + pd.to_timedelta(x, unit='D') for x in [90, 180, 181]] + [pd.NaT],
                          'data_carga': ['17/07/2026 06:30:47'] * 4,
                          'ano_coorte': [2022] * 4, 'motivo_exclusao': pd.Series([pd.NA] * 4, dtype='string'),
                          'sem_repasse_90d': [0, 1, 1, 1]})
        resultado = base_180(q)
        self.assertEqual(resultado.sem_repasse_180d.tolist(), [0, 0, 1, 1])
        self.assertEqual(q.sem_repasse_90d.tolist(), [0, 1, 1, 1])
        self.assertNotIn('sem_repasse_180d', q)

    def test_corte_180_dias_retira_rotulo_nao_observavel_em_janeiro(self):
        q = pd.DataFrame({'data_assinatura': pd.to_datetime(['2023-06-01', '2023-12-01']),
                          'primeiro_repasse': [pd.NaT, pd.NaT], 'data_carga': ['17/07/2026 06:30:47'] * 2,
                          'ano_coorte': [2023, 2023], 'motivo_exclusao': pd.Series([pd.NA] * 2, dtype='string')})
        r = base_180(q)
        self.assertEqual(r.treino_final.tolist(), [True, False])

    def test_mae_e_rmse_probabilidade_sao_diagnosticos_numericos(self):
        y, p = np.array([0, 1, 0, 1]), np.array([.1, .8, .3, .9])
        m = metricas(y, p)
        self.assertAlmostEqual(m['mae_probabilidade'], np.abs(y-p).mean())
        self.assertAlmostEqual(m['rmse_probabilidade'] ** 2, m['brier'])

    def test_alvo_principal_e_allowlist_nao_sao_trocados_por_indice(self):
        cfg = configuracoes()
        c = cfg['principal']
        self.assertEqual(c['alvo'], 'evento_adverso_obrasgov')
        self.assertEqual(cfg['secundario']['alvo'], 'sem_repasse_180d')
        self.assertNotIn(c['alvo'], c['numericas'])
        self.assertNotIn('codigo_ibge', c['numericas'])
        self.assertEqual(len(c['numericas']), 8)
        self.assertEqual(c['random_state'], 42)
        self.assertFalse(c['busca_hiperparametros'])

    def test_pipeline_numerico_sem_categorias_e_alvo_configurado(self):
        c = configuracoes()['principal']
        q = pd.DataFrame({coluna: np.arange(30, dtype=float) for coluna in c['numericas']})
        q[c['alvo']] = np.arange(30) % 2
        modelo, meta = treinar('arvore', q, c)
        self.assertEqual(meta['busca'], 'configuracao_conservadora_predefinida')
        self.assertEqual(set(modelo.classes_), {0, 1})
        self.assertEqual(modelo.named_steps['limpar'].transform(q).columns.tolist(), c['numericas'])

    def test_snapshot_principal_tem_as_coortes_e_publicacao_anterior(self):
        from src.e05.revisao import carregar
        bases, m = carregar()
        q = bases['principal']
        self.assertEqual(q.groupby('ano').size().to_dict(), {2022: 127, 2023: 121, 2024: 110})
        self.assertEqual(int(q.evento_adverso_obrasgov.sum()), 28)
        for coluna in q.filter(like='disponibilidade_'):
            self.assertFalse((q[coluna] >= q.data_corte).any())
        self.assertEqual(m['diagnostico']['contextos_futuros_e04_nao_reutilizados'], 21)


if __name__ == '__main__':
    unittest.main()
