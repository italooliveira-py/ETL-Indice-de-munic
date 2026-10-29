import os
import unittest
from pathlib import Path

import pandas as pd

from src.e05_transferegov_atraso import (
    TARGET,
    build_target,
    load_frozen_tables,
    select_predictors,
    temporal_split,
)
from src.e05.contrato_365 import build_snapshot


def instrumentos_fixture():
    return pd.DataFrame(
        {
            "nr_convenio": ["a", "b", "c", "d"],
            "data_assinatura": pd.to_datetime(["2022-01-01"] * 4),
            "data_proposta": pd.to_datetime(["2021-12-01"] * 4),
            "data_fim_vigencia_original": pd.to_datetime(["2023-01-01"] * 4),
            "valor_global_original": [100.0] * 4,
            "valor_global_assinatura": [100.0] * 4,
            "valor_contrapartida": [10.0] * 4,
            "modalidade": ["A"] * 4,
            "orgao_superior": ["O"] * 4,
            "orgao": ["G"] * 4,
            "origem_emenda": [False] * 4,
            "emenda_individual": [False] * 4,
            "emenda_impositiva": [False] * 4,
        }
    )


class Contrato365(unittest.TestCase):
    def test_dia_365_e_classe_0_e_dia_366_e_classe_1(self):
        ins = instrumentos_fixture().iloc[:2].copy()
        des = pd.DataFrame(
            {
                "id_desembolso": [1, 2],
                "nr_convenio": ["a", "b"],
                "data_desembolso": pd.to_datetime(["2023-01-01", "2023-01-02"]),
                "valor_desembolsado": [1.0, 1.0],
            }
        )
        out = build_target(ins, des, data_carga="2024-01-01")
        self.assertEqual(out[TARGET].tolist(), [0, 1])

    def test_zero_nao_e_primeiro_desembolso(self):
        ins = instrumentos_fixture().iloc[:1].copy()
        des = pd.DataFrame(
            {
                "id_desembolso": [1, 2],
                "nr_convenio": ["a", "a"],
                "data_desembolso": pd.to_datetime(["2022-02-01", "2022-03-01"]),
                "valor_desembolsado": [0.0, 5.0],
            }
        )
        out = build_target(ins, des, data_carga="2024-01-01")
        self.assertEqual(out.loc[0, TARGET], 0)
        self.assertEqual(out.loc[0, "data_primeiro_desembolso"], pd.Timestamp("2022-03-01"))

    def test_censura_nao_vira_classe_1(self):
        ins = instrumentos_fixture().iloc[:1].copy()
        des = pd.DataFrame(columns=["id_desembolso", "nr_convenio", "data_desembolso", "valor_desembolsado"])
        out = build_target(ins, des, data_carga="2022-12-31")
        self.assertTrue(out.loc[0, "censurado"])
        self.assertTrue(pd.isna(out.loc[0, TARGET]))

    def test_duplicidade_de_instrumento_bloqueia(self):
        ins = pd.concat([instrumentos_fixture().iloc[:1], instrumentos_fixture().iloc[:1]], ignore_index=True)
        with self.assertRaises(ValueError):
            build_target(ins, pd.DataFrame(columns=["id_desembolso", "nr_convenio", "data_desembolso", "valor_desembolsado"]))

    def test_split_temporal_exige_as_tres_coortes(self):
        ins = pd.concat([instrumentos_fixture()] * 15, ignore_index=True)
        ins["nr_convenio"] = [str(i) for i in range(len(ins))]
        ins["data_assinatura"] = pd.to_datetime(["2022-01-01"] * 20 + ["2023-01-01"] * 20 + ["2024-01-01"] * 20)
        des = pd.DataFrame(
            {
                "id_desembolso": range(30),
                "nr_convenio": ins["nr_convenio"].iloc[[*range(0, 10), *range(20, 30), *range(40, 50)]],
                "data_desembolso": pd.to_datetime(["2022-02-01"] * 10 + ["2023-02-01"] * 10 + ["2024-02-01"] * 10),
                "valor_desembolsado": [1.0] * 30,
            }
        )
        out = build_target(ins, des, data_carga="2026-01-01")
        parts = temporal_split(out)
        self.assertEqual(set(parts), {2022, 2023, 2024})

    def test_preditores_excluem_identificadores_e_desfechos(self):
        frame = instrumentos_fixture()
        features, audit = select_predictors(frame)
        self.assertEqual(list(features.columns), audit["features"])
        self.assertNotIn("nr_convenio", features)
        self.assertNotIn("codigo_ibge", features)
        self.assertNotIn(TARGET, features)


class GoldIntegration(unittest.TestCase):
    @unittest.skipUnless(os.getenv("E05_GOLD_ROOT"), "E05_GOLD_ROOT ausente: integração externa do Gold não executada")
    def test_snapshot_gold_tem_867_linhas_e_coortes(self):
        root = Path(os.environ["E05_GOLD_ROOT"])
        instrumentos, desembolsos, _ = load_frozen_tables(root)
        out = build_target(instrumentos, desembolsos, data_carga="2026-07-17")
        out = out[out["ano_ref"].isin([2022, 2023, 2024]) & out[TARGET].notna()]
        self.assertEqual(len(out), 867)
        self.assertEqual(
            out.groupby("ano_ref")[TARGET].value_counts().to_dict(),
            {(2022, 0): 28, (2022, 1): 211, (2023, 0): 77, (2023, 1): 309, (2024, 0): 30, (2024, 1): 212},
        )

    @unittest.skipUnless(os.getenv("E05_GOLD_ROOT"), "E05_GOLD_ROOT ausente: integração externa do Gold não executada")
    def test_build_snapshot_grava_867_linhas_e_manifesto(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = build_snapshot(os.environ["E05_GOLD_ROOT"], Path(tmp), generated_at="2026-10-29T00:00:00Z")
            self.assertEqual(result["rows"], 867)
            self.assertTrue(result["config_sha256"])
            self.assertTrue(result["code_sha256"])
            self.assertTrue((Path(tmp) / "base_modelagem.parquet").exists())
            self.assertTrue((Path(tmp) / "manifesto.json").exists())


if __name__ == "__main__":
    unittest.main()
