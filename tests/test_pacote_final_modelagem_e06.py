import unittest

import pandas as pd

from src.etl_municipal.analitico.pacote_final_modelagem_e06 import (
    M1_FEATURES,
    M1_PLUS_FEATURES,
    audit_signature_value,
    validate_final_frames,
)


class PacoteFinalModelagemTest(unittest.TestCase):
    def test_m1_e_m1_plus_tem_mesmos_ids_e_particoes(self):
        frame = pd.DataFrame({
            "nr_convenio": ["a", "b"], "codigo_ibge": [1, 2], "split": ["train", "test"],
            "y_1_sem_desembolso_365": [True, False],
            "valor_global_assinatura": [10.0, 20.0],
        })
        for feature in M1_FEATURES:
            frame[feature] = 1
        self.assertTrue(validate_final_frames(frame))
        self.assertEqual(len(M1_FEATURES), 6)
        self.assertEqual(M1_PLUS_FEATURES[-1], "valor_global_assinatura")

    def test_valor_assinatura_rejeita_nulo_zero_negativo(self):
        result = audit_signature_value(pd.Series([1.0, 2.0, 3.0]))
        self.assertEqual(result["nulos"], 0)
        self.assertEqual(result["zeros"], 0)
        self.assertEqual(result["negativos"], 0)

    def test_final_rejeita_duplicidade_e_alvo_nulo(self):
        frame = pd.DataFrame({
            "nr_convenio": ["a", "a"], "codigo_ibge": [1, 1], "split": ["train", "train"],
            "y_1_sem_desembolso_365": [True, None], "valor_global_assinatura": [1.0, 1.0],
        })
        with self.assertRaises(ValueError):
            validate_final_frames(frame)


if __name__ == "__main__":
    unittest.main()
