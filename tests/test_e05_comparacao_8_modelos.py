import unittest

import numpy as np
import pandas as pd

from src.e05.comparacao_8_modelos import (
    MODEL_NAMES,
    build_common_folds,
    choose_threshold,
    metricas_classificacao,
    ranking_validacao,
)


class Comparacao8Modelos(unittest.TestCase):
    def test_folds_comuns_separam_municipios_e_classes(self):
        frame = pd.DataFrame({
            "codigo_ibge": [str(i % 20) for i in range(40)],
            "risco_atraso_primeiro_desembolso_365d": [0, 1] * 20,
            "nr_convenio": [str(i) for i in range(40)],
        })
        folds, audit = build_common_folds(frame)
        self.assertGreaterEqual(len(folds), 3)
        self.assertTrue((audit["classes_treino"] == 2).all())
        self.assertTrue((audit["classes_validacao"] == 2).all())
        self.assertTrue(audit["grupos_disjuntos"].all())

    def test_limiar_prioriza_balanced_accuracy_e_desempata(self):
        result = choose_threshold([0, 1, 0, 1], [0.1, 0.6, 0.4, 0.9])
        self.assertEqual(result["criterion"], "balanced_accuracy")
        self.assertGreaterEqual(result["threshold"], 0.01)
        self.assertLessEqual(result["threshold"], 0.99)

    def test_metricas_calculam_especificidade_e_at_k(self):
        result = metricas_classificacao([0, 1, 0, 1], [0.1, 0.8, 0.2, 0.7], 0.5)
        self.assertEqual(result["tn"], 2)
        self.assertEqual(result["tp"], 2)
        self.assertEqual(result["specificity"], 1.0)
        self.assertIn("precision_at_10", result)
        self.assertIn("recall_at_30", result)

    def test_ranking_usa_ap_da_validacao_e_nao_backtest(self):
        rows = []
        for model, ap in zip(MODEL_NAMES, np.linspace(0.1, 0.9, len(MODEL_NAMES))):
            rows.append({"modelo": model, "particao": "validacao_2023", "average_precision": ap, "balanced_accuracy": 0.5, "brier_score": 0.5, "cv_validation_gap": 0.1})
            rows.append({"modelo": model, "particao": "backtest_2024", "average_precision": 1 - ap, "balanced_accuracy": 0.9, "brier_score": 0.1, "cv_validation_gap": 0.1})
        ranking = ranking_validacao(pd.DataFrame(rows))
        self.assertEqual(ranking.iloc[0]["modelo"], MODEL_NAMES[-1])


if __name__ == "__main__":
    unittest.main()
