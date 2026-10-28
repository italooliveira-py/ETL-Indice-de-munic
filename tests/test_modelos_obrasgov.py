"""Contratos de reprodução da Regressão Logística e KNN no ObrasGov."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.modelos_obrasgov.executar_modelos import ROOT, carregar, criar_pipeline, executar


class TestModelosObrasGov(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config.modelos_obrasgov.json").read_text(encoding="utf-8"))
        cls.base = carregar(
            ROOT / "dados/modelagem/e05_revisao/principal.parquet",
            ROOT / "dados/modelagem/e05_revisao/principal_particoes.csv",
            cls.config,
        )

    def test_snapshot_e_particoes_tem_classes_nos_tres_anos(self):
        self.assertEqual(len(self.base), 358)
        for flag in self.config["particoes"].values():
            self.assertEqual(set(self.base.loc[self.base[flag], self.config["alvo"]]), {0.0, 1.0})

    def test_pipelines_incluem_imputacao_e_escala_no_treino(self):
        for nome in ("regressao_logistica", "k_nearest_neighbors"):
            pipeline = criar_pipeline(nome, self.config)
            preparo = pipeline.named_steps["preparo"].transformers[0][1].named_steps
            self.assertIn("imputar", preparo)
            self.assertIn("escalar", preparo)

    def test_execucao_gera_metricas_e_modelos_reproduziveis(self):
        with tempfile.TemporaryDirectory() as temp:
            tabela = executar(self.base, self.config, Path(temp))
            self.assertEqual(len(tabela), 4)
            self.assertTrue(tabela["status_ajuste"].eq("estimado").all())
            self.assertTrue(np.isfinite(tabela["roc_auc"]).all())
            self.assertTrue((Path(temp) / "regressao_logistica.joblib").exists())
            self.assertTrue((Path(temp) / "k_nearest_neighbors.joblib").exists())


if __name__ == "__main__":
    unittest.main()
