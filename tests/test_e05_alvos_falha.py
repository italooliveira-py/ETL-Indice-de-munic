"""Regras dos alvos de falha: positivos, negativos e censura nos casos-limite."""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'e05_tempo_desembolso'))
from alvos_falha import construir_alvos, resumo_por_safra

CARGA = pd.Timestamp('2026-07-17')


def instrumento(nr, *, fim, fim_original, situacao='Prestação de Contas Concluída', repasse=100.0):
    return {'nr_convenio': nr, 'codigo_ibge': '2507507', 'modalidade': 'CONVENIO',
            'data_assinatura': pd.Timestamp('2019-01-01'), 'data_fim_vigencia': pd.Timestamp(fim),
            'data_fim_vigencia_original': pd.Timestamp(fim_original), 'situacao': situacao, 'valor_repasse': repasse}


INSTRUMENTOS = pd.DataFrame([
    instrumento('anulado_em_vigencia', fim='2027-01-01', fim_original='2027-01-01', situacao='Convênio Anulado'),
    instrumento('encerrado_ok', fim='2021-01-01', fim_original='2021-01-01'),
    instrumento('em_vigencia_sem_falha', fim='2027-01-01', fim_original='2027-01-01', situacao='Em execução'),
    instrumento('pagou_pouco', fim='2021-01-01', fim_original='2021-01-01'),
    instrumento('pagou_metade', fim='2021-01-01', fim_original='2021-01-01'),
    instrumento('pagou_noventa', fim='2021-01-01', fim_original='2021-01-01'),
    instrumento('prorrogado_366', fim='2022-01-02', fim_original='2021-01-01'),
    instrumento('prorrogado_365', fim='2022-01-01', fim_original='2021-01-01'),
    instrumento('em_vigencia_dentro_do_limite', fim='2027-01-01', fim_original='2026-06-01', situacao='Em execução'),
    instrumento('em_vigencia_alem_do_limite', fim='2028-01-01', fim_original='2026-06-01', situacao='Em execução'),
])
DESEMBOLSOS = pd.DataFrame({'nr_convenio': ['encerrado_ok', 'pagou_pouco', 'pagou_metade', 'pagou_noventa', 'prorrogado_366', 'prorrogado_365'],
                            'valor_desembolsado': [100.0, 49.0, 50.0, 90.0, 100.0, 100.0]})


class Alvos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alvos = construir_alvos(INSTRUMENTOS, DESEMBOLSOS, data_carga=CARGA).set_index('nr_convenio')

    def valor(self, nr, alvo):
        v = self.alvos.loc[nr, alvo]
        return None if pd.isna(v) else int(v)

    def test_falha_contratual_positiva_mesmo_em_vigencia(self):
        self.assertEqual(self.valor('anulado_em_vigencia', 'falha_contratual'), 1)
        self.assertEqual(self.valor('encerrado_ok', 'falha_contratual'), 0)
        self.assertIsNone(self.valor('em_vigencia_sem_falha', 'falha_contratual'))

    def test_nao_pagamento_limite_de_90_e_nao_se_aplica_a_falha_contratual(self):
        self.assertEqual(self.valor('pagou_pouco', 'nao_pagamento'), 1)
        self.assertEqual(self.valor('pagou_metade', 'nao_pagamento'), 1)
        self.assertEqual(self.valor('pagou_noventa', 'nao_pagamento'), 0)
        self.assertIsNone(self.valor('anulado_em_vigencia', 'nao_pagamento'))
        self.assertIsNone(self.valor('em_vigencia_sem_falha', 'nao_pagamento'))

    def test_atraso_grave_limite_de_365_dias_e_censura(self):
        self.assertEqual(self.valor('prorrogado_366', 'atraso_grave'), 1)
        self.assertEqual(self.valor('prorrogado_365', 'atraso_grave'), 0)
        self.assertIsNone(self.valor('em_vigencia_dentro_do_limite', 'atraso_grave'))  # ainda pode ser prorrogado
        self.assertEqual(self.valor('em_vigencia_alem_do_limite', 'atraso_grave'), 1)  # já se sabe

    def test_falha_do_projeto_combina_contratual_e_pagamento(self):
        self.assertEqual(self.valor('anulado_em_vigencia', 'falha_projeto'), 1)
        self.assertEqual(self.valor('pagou_pouco', 'falha_projeto'), 1)
        self.assertEqual(self.valor('encerrado_ok', 'falha_projeto'), 0)
        self.assertIsNone(self.valor('em_vigencia_sem_falha', 'falha_projeto'))

    def test_resumo_separa_observado_e_prevalencia(self):
        resumo = resumo_por_safra(self.alvos.reset_index(), safras=[2019])
        self.assertEqual(resumo.loc[2019, 'instrumentos'], len(INSTRUMENTOS))
        # Três instrumentos em vigência sem falha ficam censurados.
        self.assertAlmostEqual(resumo.loc[2019, 'falha_contratual_observado_%'], round(7 / 10 * 100, 1))

    def test_nr_convenio_duplicado_bloqueia(self):
        with self.assertRaises(ValueError):
            construir_alvos(pd.concat([INSTRUMENTOS, INSTRUMENTOS.iloc[:1]]), DESEMBOLSOS, data_carga=CARGA)


if __name__ == '__main__':
    unittest.main()
