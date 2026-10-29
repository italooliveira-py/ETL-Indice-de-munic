import os
import unittest

import pandas as pd


class TestAlvoAtrasoDesembolso(unittest.TestCase):
    def setUp(self):
        self.instrumentos = pd.DataFrame(
            {
                "nr_convenio": ["i1", "i2", "i3", "i4", "i5", "i6"],
                "id_proposta": ["p1", "p2", "p3", "p4", "p5", "p6"],
                "codigo_ibge": ["1", "1", "2", "2", "3", "3"],
                "data_assinatura": pd.to_datetime(
                    ["2022-01-01", "2022-01-01", "2022-01-01", "2022-01-01", "2024-01-01", "2024-01-01"]
                ),
                "data_proposta": pd.to_datetime(
                    ["2021-12-01", "2021-12-01", "2021-12-01", "2021-12-01", "2023-12-01", "2023-12-01"]
                ),
                "data_fim_vigencia_original": pd.to_datetime(
                    ["2023-01-01"] * 4 + ["2025-01-01"] * 2
                ),
                "valor_global_original": [100.0] * 6,
                "valor_global_assinatura": [100.0] * 6,
                "valor_contrapartida": [10.0] * 6,
                "modalidade": ["CONVENIO"] * 6,
                "orgao_superior": ["A"] * 6,
                "orgao": ["B"] * 6,
                "origem_emenda": [False] * 6,
                "emenda_individual": [False] * 6,
                "emenda_impositiva": [False] * 6,
            }
        )
        self.desembolsos = pd.DataFrame(
            {
                "id_desembolso": ["d1", "d2", "d3", "d4", "d5", "d6", "d6"],
                "nr_convenio": ["i1", "i2", "i3", "i4", "i5", "i6", "i6"],
                "data_desembolso": pd.to_datetime(
                    ["2022-01-01", "2023-01-02", "2022-12-31", "2023-01-02", "2024-12-31", "2025-01-02", "2025-01-02"]
                ),
                "valor_desembolsado": [1.0] * 7,
            }
        )

    def test_classifies_same_365th_and_366th_day(self):
        from src.e05_transferegov_atraso import build_target

        result = build_target(self.instrumentos, self.desembolsos, pd.Timestamp("2026-07-17"))
        by_id = result.set_index("nr_convenio")
        self.assertEqual(by_id.loc["i1", "risco_atraso_primeiro_desembolso_365d"], 0)
        self.assertEqual(by_id.loc["i2", "risco_atraso_primeiro_desembolso_365d"], 1)
        self.assertEqual(by_id.loc["i3", "risco_atraso_primeiro_desembolso_365d"], 0)
        self.assertEqual(by_id.loc["i4", "risco_atraso_primeiro_desembolso_365d"], 1)
        self.assertEqual(by_id.loc["i5", "risco_atraso_primeiro_desembolso_365d"], 0)
        self.assertEqual(by_id.loc["i6", "risco_atraso_primeiro_desembolso_365d"], 1)

    def test_deduplicates_official_disbursement_id_and_reports_anomalies(self):
        from src.e05_transferegov_atraso import build_target

        result = build_target(self.instrumentos, self.desembolsos, pd.Timestamp("2026-07-17"))
        self.assertEqual(result["nr_convenio"].nunique(), len(result))
        self.assertEqual(result.attrs["report"]["duplicate_disbursements"], 1)
        self.assertEqual(result.attrs["report"]["before_signature"], 0)

    def test_censors_instrument_without_365_days(self):
        from src.e05_transferegov_atraso import build_target

        result = build_target(self.instrumentos, self.desembolsos, pd.Timestamp("2024-06-01"))
        row = result.set_index("nr_convenio").loc["i5"]
        self.assertTrue(row["censurado"])
        self.assertTrue(pd.isna(row["risco_atraso_primeiro_desembolso_365d"]))


class TestContratoPreditores(unittest.TestCase):
    def test_rejects_outcome_and_disbursement_columns(self):
        from src.e05_transferegov_atraso import select_predictors

        frame = pd.DataFrame(
            {
                "nr_convenio": ["i1"],
                "data_assinatura": pd.to_datetime(["2022-01-01"]),
                "valor_global_original": [1.0],
                "resultado_anulado": [False],
                "valor_desembolsado": [1.0],
            }
        )
        with self.assertRaises(ValueError):
            select_predictors(frame)

    def test_builds_explicit_features_without_identifiers_or_targets(self):
        from src.e05_transferegov_atraso import select_predictors

        frame = pd.DataFrame(
            {
                "nr_convenio": ["i1"],
                "data_assinatura": pd.to_datetime(["2022-01-01"]),
                "data_proposta": pd.to_datetime(["2021-12-01"]),
                "data_fim_vigencia_original": pd.to_datetime(["2023-01-01"]),
                "valor_global_original": [1.0],
                "valor_global_assinatura": [1.0],
                "valor_contrapartida": [0.1],
                "modalidade": ["CONVENIO"],
                "orgao_superior": ["A"],
                "orgao": ["B"],
                "origem_emenda": [False],
                "emenda_individual": [False],
                "emenda_impositiva": [False],
                "risco_atraso_primeiro_desembolso_365d": [0],
            }
        )
        features, metadata = select_predictors(frame)
        self.assertNotIn("nr_convenio", features.columns)
        self.assertNotIn("risco_atraso_primeiro_desembolso_365d", features.columns)
        self.assertEqual(metadata["source"], "Transferegov")


class TestValidacaoEModelos(unittest.TestCase):
    def test_frozen_version_is_explicit(self):
        from src.e05_transferegov_atraso import GOLD_VERSION, frozen_paths

        if not os.getenv("E05_GOLD_ROOT"):
            self.skipTest("integração externa não executada: E05_GOLD_ROOT ausente")
        paths = frozen_paths(os.environ["E05_GOLD_ROOT"])
        self.assertEqual(GOLD_VERSION, "65260a170ee18cd79501")
        self.assertIn(GOLD_VERSION, str(paths["manifesto"]))

    def test_temporal_split_requires_two_classes_and_ten_each(self):
        from src.e05_transferegov_atraso import temporal_split

        from src.e05_transferegov_atraso import TARGET

        frame = pd.DataFrame(
            {"ano_ref": [2022] * 20 + [2023] * 20 + [2024] * 20, TARGET: [0, 1] * 30, "codigo_ibge": [str(i % 5) for i in range(60)]}
        )
        splits = temporal_split(frame)
        self.assertEqual([len(splits[y]) for y in (2022, 2023, 2024)], [20, 20, 20])

    def test_model_registry_has_only_two_implemented_models(self):
        from src.e05_transferegov_atraso import model_registry

        registry = model_registry()
        self.assertEqual(registry["xgboost"]["status_implementacao"], "implementado")
        self.assertEqual(registry["lightgbm"]["status_implementacao"], "implementado")
        for name in ("logistica", "knn", "random_forest", "decision_tree", "svc", "mlp"):
            self.assertEqual(registry[name]["status_implementacao"], "pendente_integracao")

    def test_threshold_and_error_diagnostic_are_auditable(self):
        from src.e05_transferegov_atraso import TARGET, choose_threshold, diagnose_errors

        frame = pd.DataFrame({"nr_convenio": ["i1", "i2"], TARGET: [0, 1], "ano_ref": [2023, 2023]})
        threshold = choose_threshold(frame[TARGET], [0.2, 0.8])
        diagnostic = diagnose_errors(frame, [0.8, 0.1], threshold, "xgboost")
        self.assertIn("falso_positivo", diagnostic.tipo_erro.tolist())
        self.assertIn("falso_negativo", diagnostic.tipo_erro.tolist())
        self.assertIn("residuo_probabilidade", diagnostic.columns)

    def test_metrics_include_average_precision_calibration_and_at_k(self):
        from src.e05_transferegov_atraso import classification_metrics

        metrics = classification_metrics([0, 1, 1, 0], [0.1, 0.8, 0.6, 0.2], threshold=0.5)
        for key in (
            "average_precision", "average_precision_gain_absolute",
            "average_precision_gain_relative", "specificity", "brier_score",
            "log_loss", "precision_at_10", "recall_at_10", "precision_at_20",
            "recall_at_20", "precision_at_30", "recall_at_30", "lift_by_decile",
            "confusion_matrix",
        ):
            self.assertIn(key, metrics)

    def test_threshold_audit_uses_balanced_accuracy_as_primary_criterion(self):
        from src.e05_transferegov_atraso import choose_threshold

        result = choose_threshold([0, 0, 1, 1], [0.1, 0.4, 0.6, 0.9], return_audit=True)
        self.assertEqual(result["criterion"], "balanced_accuracy")
        self.assertAlmostEqual(result["threshold"], 0.5)

    def test_target_report_records_reconciliation_and_boundary_counts(self):
        from src.e05_transferegov_atraso import build_target

        instrumentos = pd.DataFrame({"nr_convenio": ["i1"], "data_assinatura": pd.to_datetime(["2022-01-01"])})
        desembolsos = pd.DataFrame({
            "id_desembolso": ["d1"], "nr_convenio": ["i1"],
            "data_desembolso": pd.to_datetime(["2023-01-01"]), "valor_desembolsado": [1.0],
        })
        result = build_target(instrumentos, desembolsos, pd.Timestamp("2026-07-17"))
        report = result.attrs["report"]
        for key in ("unmatched_instruments", "boundary_365", "boundary_gt_365", "reason_counts"):
            self.assertIn(key, report)

    def test_permuted_target_is_auditable(self):
        from src.e05_transferegov_atraso import permutation_sanity

        result = permutation_sanity([0, 1, 0, 1, 0, 1], [0.1, 0.9, 0.2, 0.8, 0.3, 0.7], seed=42)
        self.assertIn("average_precision", result)
        self.assertIn("roc_auc", result)
        self.assertEqual(result["seed"], 42)

    def test_folds_do_not_overlap_municipal_groups(self):
        from src.e05_transferegov_atraso import cv_folds

        x = pd.DataFrame({"x": range(12)})
        y = pd.Series([0, 1] * 6)
        groups = pd.Series(["a", "a", "b", "b", "c", "c", "d", "d", "e", "e", "f", "f"])
        for train, valid in cv_folds(x, y, groups, n_splits=3):
            self.assertTrue(set(groups.iloc[train]).isdisjoint(set(groups.iloc[valid])))
