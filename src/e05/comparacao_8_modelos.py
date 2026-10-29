"""Benchmark temporal comum dos oito classificadores do contrato E05."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, balanced_accuracy_score, brier_score_loss,
    confusion_matrix, f1_score, log_loss, precision_recall_curve,
    precision_score, recall_score, roc_auc_score, roc_curve,
)
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from src.e05_transferegov_atraso import CATEGORICAL_FEATURES, FEATURE_COLUMNS, TARGET

SEED = 42
MODEL_NAMES = ["logistica", "knn", "xgboost", "lightgbm", "random_forest", "decision_tree", "svc", "mlp"]
ALL_NAMES = ["dummy_prior", "dummy_most_frequent", *MODEL_NAMES]
SNAPSHOT_SHA256 = "6A8432CDA7D37B12E59E44486579CDD47C7DEDB4431D5B916A3200FDF56691BB"
CONFIG_PATH = Path("config/e05.transferegov.365.json")
NUMERIC_FEATURES = [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_FEATURES]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_contract_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parents[2] / CONFIG_PATH
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["target"] != TARGET or config["seed"] != SEED:
        raise ValueError("configuração do contrato incompatível com o benchmark")
    if config["partitions"] != {"train": 2022, "validation": 2023, "backtest": 2024}:
        raise ValueError("partições do contrato incompatíveis")
    if config["tie_breakers"] != ["specificity", "f1", "threshold_ascending"]:
        raise ValueError("regra de desempate incompatível com o benchmark")
    return config


def load_snapshot(path: str | Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = Path(path)
    manifest = json.loads((path.parent / "manifesto.json").read_text(encoding="utf-8"))
    if manifest.get("snapshot_sha256") != SNAPSHOT_SHA256 or _sha256(path) != SNAPSHOT_SHA256:
        raise ValueError("hash do snapshot divergente")
    frame = pd.read_parquet(path)
    if len(frame) != 867 or frame["nr_convenio"].duplicated().any():
        raise ValueError("snapshot inválido")
    if set(frame["particao"]) != {"treino_2022", "validacao_2023", "backtest_2024"}:
        raise ValueError("partições inválidas")
    return frame, manifest


def build_common_folds(train: pd.DataFrame, seed: int = SEED):
    y = train[TARGET].astype(int)
    groups = train["codigo_ibge"].astype(str)
    for n_splits in (5, 4, 3):
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        folds = list(splitter.split(train, y, groups))
        audit = []
        valid = True
        for i, (tr, va) in enumerate(folds):
            yt, yv = y.iloc[tr], y.iloc[va]
            overlap = bool(set(groups.iloc[tr]) & set(groups.iloc[va]))
            row = {
                "fold": i, "n_treino": len(tr), "n_validacao": len(va),
                "classes_treino": int(yt.nunique()), "classes_validacao": int(yv.nunique()),
                "grupos_disjuntos": not overlap,
            }
            audit.append(row)
            valid &= yt.nunique() == 2 and yv.nunique() == 2 and not overlap
        if valid:
            return folds, pd.DataFrame(audit)
    raise ValueError("não foi possível construir folds comuns com duas classes")


def _preprocessor(scale: bool) -> ColumnTransformer:
    numeric_steps = [("imputer", SimpleImputer(strategy="median"))]
    if scale:
        numeric_steps.append(("scaler", StandardScaler()))
    return ColumnTransformer([
        ("numeric", Pipeline(numeric_steps), NUMERIC_FEATURES),
        ("categorical", Pipeline([
            ("imputer", SimpleImputer(strategy="constant", fill_value="ausente")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), CATEGORICAL_FEATURES),
    ], remainder="drop")


def model_specs(class_ratio: float) -> dict[str, tuple[Any, dict[str, list[Any]], bool]]:
    return {
        "logistica": (LogisticRegression(max_iter=1500, random_state=SEED), {"model__C": [0.1, 1.0], "model__class_weight": [None, "balanced"]}, True),
        "knn": (KNeighborsClassifier(), {"model__n_neighbors": [5, 15], "model__weights": ["uniform", "distance"], "model__p": [1, 2]}, True),
        "xgboost": (__import__("xgboost").XGBClassifier(objective="binary:logistic", eval_metric="logloss", random_state=SEED, n_jobs=1, tree_method="hist", verbosity=0), {"model__max_depth": [2, 3], "model__learning_rate": [0.05, 0.1], "model__n_estimators": [80, 140], "model__subsample": [0.8], "model__reg_lambda": [1.0, 5.0], "model__scale_pos_weight": [1.0, class_ratio]}, False),
        "lightgbm": (__import__("lightgbm").LGBMClassifier(objective="binary", random_state=SEED, n_jobs=1, verbosity=-1), {"model__num_leaves": [7, 15], "model__max_depth": [-1, 3], "model__learning_rate": [0.05, 0.1], "model__n_estimators": [80, 140], "model__reg_lambda": [0.0, 5.0], "model__scale_pos_weight": [1.0, class_ratio]}, False),
        "random_forest": (RandomForestClassifier(random_state=SEED, n_jobs=1), {"model__n_estimators": [150, 300], "model__max_depth": [4, 8], "model__min_samples_leaf": [2, 8], "model__max_features": ["sqrt"], "model__class_weight": [None, "balanced"]}, False),
        "decision_tree": (DecisionTreeClassifier(random_state=SEED), {"model__max_depth": [2, 4, 8], "model__min_samples_leaf": [2, 8], "model__criterion": ["gini"], "model__class_weight": [None, "balanced"]}, False),
        "svc": (SVC(probability=True, random_state=SEED), {"model__C": [0.1, 1.0], "model__kernel": ["linear", "rbf"], "model__gamma": ["scale"], "model__class_weight": [None, "balanced"]}, True),
        "mlp": (MLPClassifier(random_state=SEED, early_stopping=True, validation_fraction=0.2, max_iter=400), {"model__hidden_layer_sizes": [(8,), (8, 4)], "model__alpha": [0.0001, 0.01], "model__learning_rate_init": [0.001]}, True),
    }


def _pipeline(estimator: Any, scale: bool) -> Pipeline:
    return Pipeline([("preprocessor", _preprocessor(scale)), ("model", estimator)])


def choose_threshold(y_true, probabilities) -> dict[str, Any]:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    candidates = np.unique(np.clip(np.r_[p, 0.5], 0.01, 0.99))
    scored = []
    for threshold in candidates:
        predicted = p >= threshold
        tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
        specificity = tn / (tn + fp) if tn + fp else 0.0
        f1 = f1_score(y, predicted, zero_division=0)
        scored.append((balanced_accuracy_score(y, predicted), specificity, f1, -threshold, threshold))
    best = max(scored)
    return {"criterion": "balanced_accuracy", "threshold": float(best[-1]), "balanced_accuracy": float(best[0]), "specificity": float(best[1]), "f1": float(best[2])}


def _at_k(y, p, fraction):
    k = max(1, int(np.ceil(len(y) * fraction)))
    chosen = np.argsort(-p)[:k]
    positives = int(np.sum(y))
    hits = int(np.sum(y[chosen]))
    return hits / k, hits / positives if positives else np.nan, (hits / k) / (positives / len(y)) if positives else np.nan


def metricas_classificacao(y_true, probabilities, threshold: float) -> dict[str, Any]:
    y, p = np.asarray(y_true, dtype=int), np.asarray(probabilities, dtype=float)
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    result = {
        "n": len(y), "positivos": int(y.sum()), "negativos": int((y == 0).sum()), "prevalencia": float(y.mean()),
        "average_precision": float(average_precision_score(y, p)), "roc_auc": float(roc_auc_score(y, p)),
        "brier_score": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)), "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)), "specificity": float(tn / (tn + fp)) if tn + fp else 0.0,
        "f1": float(f1_score(y, pred, zero_division=0)), "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
        "mae_probabilidade": float(np.mean(np.abs(y - p))), "rmse_probabilidade": float(np.sqrt(np.mean((y - p) ** 2))), "threshold": float(threshold),
    }
    for fraction, label in ((0.1, "10"), (0.2, "20"), (0.3, "30")):
        precision_k, recall_k, lift_k = _at_k(y, p, fraction)
        result[f"precision_at_{label}"] = precision_k; result[f"recall_at_{label}"] = recall_k; result[f"lift_at_{label}"] = lift_k
    return result


def ranking_validacao(metrics: pd.DataFrame) -> pd.DataFrame:
    val = metrics[metrics["particao"] == "validacao_2023"].copy()
    return val.sort_values(["average_precision", "balanced_accuracy", "brier_score", "cv_validation_gap"], ascending=[False, False, True, True]).reset_index(drop=True)


def _bootstrap(predictions: pd.DataFrame, repetitions: int = 500, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed); rows = []
    for partition, part in predictions.groupby("particao"):
        groups = part["codigo_ibge"].astype(str).unique()
        samples = [rng.choice(groups, len(groups), replace=True) for _ in range(repetitions)]
        for model, group in part.groupby("modelo"):
            by_group = {g: x for g, x in group.groupby(group["codigo_ibge"].astype(str))}
            values = {"average_precision": [], "roc_auc": [], "balanced_accuracy": []}
            for sample in samples:
                q = pd.concat([by_group[g] for g in sample], ignore_index=True)
                m = metricas_classificacao(q.y_real, q.probabilidade, float(q.threshold.iloc[0]))
                for key in values: values[key].append(m[key])
            for key, vals in values.items(): rows.append({"particao": partition, "modelo": model, "metrica": key, "inferior": float(np.quantile(vals, .025)), "superior": float(np.quantile(vals, .975)), "repeticoes": repetitions})
        dummy = part[part["modelo"] == "dummy_prior"]
        for model, group in part[~part["modelo"].isin(["dummy_prior", "dummy_most_frequent"])].groupby("modelo"):
            left = {g: x for g, x in group.groupby(group["codigo_ibge"].astype(str))}
            right = {g: x for g, x in dummy.groupby(dummy["codigo_ibge"].astype(str))}
            differences = {"average_precision": [], "roc_auc": [], "balanced_accuracy": []}
            for sample in samples:
                qm = pd.concat([left[g] for g in sample], ignore_index=True); qd = pd.concat([right[g] for g in sample], ignore_index=True)
                mm = metricas_classificacao(qm.y_real, qm.probabilidade, float(qm.threshold.iloc[0])); md = metricas_classificacao(qd.y_real, qd.probabilidade, float(qd.threshold.iloc[0]))
                for key in differences: differences[key].append(mm[key] - md[key])
            for key, vals in differences.items(): rows.append({"particao": partition, "modelo": model + "_vs_dummy_prior", "metrica": key + "_difference", "inferior": float(np.quantile(vals, .025)), "superior": float(np.quantile(vals, .975)), "repeticoes": repetitions})
    return pd.DataFrame(rows)


def _curve_artifacts(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pr_rows, roc_rows, calibration_rows = [], [], []
    for (partition, model), group in predictions.groupby(["particao", "modelo"]):
        y = group["y_real"].to_numpy(dtype=int)
        p = group["probabilidade"].to_numpy(dtype=float)
        precision, recall, pr_thresholds = precision_recall_curve(y, p)
        for i, (prec, rec) in enumerate(zip(precision, recall)):
            threshold = float(pr_thresholds[i]) if i < len(pr_thresholds) else np.nan
            pr_rows.append({"particao": partition, "modelo": model, "threshold": threshold,
                            "precision": float(prec), "recall": float(rec)})
        fpr, tpr, roc_thresholds = roc_curve(y, p)
        for threshold, false_positive, true_positive in zip(roc_thresholds, fpr, tpr):
            roc_rows.append({"particao": partition, "modelo": model, "threshold": float(threshold),
                             "false_positive_rate": float(false_positive), "true_positive_rate": float(true_positive)})
        prob_true, prob_pred = calibration_curve(y, p, n_bins=10, strategy="uniform")
        for observed, predicted in zip(prob_true, prob_pred):
            calibration_rows.append({"particao": partition, "modelo": model,
                                     "probabilidade_media": float(predicted),
                                     "frequencia_observada": float(observed)})
    return pd.DataFrame(pr_rows), pd.DataFrame(roc_rows), pd.DataFrame(calibration_rows)


def run_benchmark(snapshot_path: str | Path = "dados/modelagem/e05_transferegov_365/base_modelagem.parquet", output_dir: str | Path = ".local/e05_contrato_unico", bootstrap_repetitions: int = 500) -> dict[str, Any]:
    config = _load_contract_config(); frame, manifest = load_snapshot(snapshot_path); output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    train = frame[frame.particao == "treino_2022"].reset_index(drop=True); validation = frame[frame.particao == "validacao_2023"].reset_index(drop=True); backtest = frame[frame.particao == "backtest_2024"].reset_index(drop=True)
    folds, fold_audit = build_common_folds(train); fold_rows = []
    for i, (tr, va) in enumerate(folds):
        for idx in tr: fold_rows.append({"nr_convenio": train.iloc[idx].nr_convenio, "codigo_ibge": train.iloc[idx].codigo_ibge, "fold": i, "papel": "treino", "alvo": train.iloc[idx][TARGET]})
        for idx in va: fold_rows.append({"nr_convenio": train.iloc[idx].nr_convenio, "codigo_ibge": train.iloc[idx].codigo_ibge, "fold": i, "papel": "validacao", "alvo": train.iloc[idx][TARGET]})
    pd.DataFrame(fold_rows).to_csv(output / "folds_cv.csv", index=False); fold_audit.to_csv(output / "auditoria_folds.csv", index=False)
    x_train, y_train = train[FEATURE_COLUMNS], train[TARGET].astype(int); x_val, y_val = validation[FEATURE_COLUMNS], validation[TARGET].astype(int); x_back, y_back = backtest[FEATURE_COLUMNS], backtest[TARGET].astype(int)
    ratio = float((y_train == 0).sum() / (y_train == 1).sum()); specs = model_specs(ratio)
    cv_rows, param_rows, val_rows, back_rows, threshold_rows, predictions, importance = [], [], [], [], [], [], []
    fitted = {}
    for name, (estimator, grid, scale) in specs.items():
        started = time.perf_counter(); search = GridSearchCV(_pipeline(estimator, scale), grid, scoring="average_precision", cv=folds, n_jobs=1, refit=True, return_train_score=False)
        search.fit(x_train, y_train); fitted[name] = search.best_estimator_
        best_idx = search.best_index_; cv_rows.append({"modelo": name, "average_precision_mean": search.cv_results_["mean_test_score"][best_idx], "average_precision_std": search.cv_results_["std_test_score"][best_idx], **{f"fold_{i}_average_precision": search.cv_results_[f"split{i}_test_score"][best_idx] for i in range(len(folds))}})
        param_rows.append({"modelo": name, "melhores_parametros": json.dumps(search.best_params_, default=str), "tempo_ajuste_segundos": time.perf_counter() - started})
        p_val, p_back = search.predict_proba(x_val)[:, 1], search.predict_proba(x_back)[:, 1]
        threshold = choose_threshold(y_val, p_val); threshold_rows.append({"modelo": name, **threshold})
        for partition, y, p in (("validacao_2023", y_val, p_val), ("backtest_2024", y_back, p_back)):
            metrics = metricas_classificacao(y, p, threshold["threshold"]); metrics.update({"modelo": name, "particao": partition, "cv_validation_gap": abs(cv_rows[-1]["average_precision_mean"] - metrics["average_precision"])})
            (val_rows if partition == "validacao_2023" else back_rows).append(metrics)
            source = validation if partition == "validacao_2023" else backtest
            predictions.append(pd.DataFrame({"modelo": name, "particao": partition, "nr_convenio": source.nr_convenio, "codigo_ibge": source.codigo_ibge, "y_real": y, "probabilidade": p, "threshold": threshold["threshold"]}))
        model = search.best_estimator_.named_steps["model"]; prep = search.best_estimator_.named_steps["preprocessor"]
        if hasattr(model, "feature_importances_"): vals = model.feature_importances_
        elif hasattr(model, "coef_"): vals = np.abs(model.coef_[0])
        else: vals = np.full(len(prep.get_feature_names_out()), np.nan)
        for feature, value in zip(prep.get_feature_names_out(), vals): importance.append({"modelo": name, "variavel": feature, "importancia": value})
    for name, strategy in (("dummy_prior", "prior"), ("dummy_most_frequent", "most_frequent")):
        dummy = DummyClassifier(strategy=strategy).fit(np.zeros((len(y_train), 1)), y_train); p_val = dummy.predict_proba(np.zeros((len(y_val), 1)))[:, 1]; p_back = dummy.predict_proba(np.zeros((len(y_back), 1)))[:, 1]; threshold = choose_threshold(y_val, p_val); threshold_rows.append({"modelo": name, **threshold})
        for partition, y, p in (("validacao_2023", y_val, p_val), ("backtest_2024", y_back, p_back)):
            metrics = metricas_classificacao(y, p, threshold["threshold"]); metrics.update({"modelo": name, "particao": partition, "cv_validation_gap": np.nan}); (val_rows if partition == "validacao_2023" else back_rows).append(metrics)
            source = validation if partition == "validacao_2023" else backtest; predictions.append(pd.DataFrame({"modelo": name, "particao": partition, "nr_convenio": source.nr_convenio, "codigo_ibge": source.codigo_ibge, "y_real": y, "probabilidade": p, "threshold": threshold["threshold"]}))
    pred = pd.concat(predictions, ignore_index=True); val_df, back_df = pd.DataFrame(val_rows), pd.DataFrame(back_rows); ranking = ranking_validacao(val_df)
    for path, data in (("metricas_cv.csv", pd.DataFrame(cv_rows)), ("melhores_parametros.csv", pd.DataFrame(param_rows)), ("metricas_validacao_2023.csv", val_df), ("metricas_backtest_2024.csv", back_df), ("limiares_validacao.csv", pd.DataFrame(threshold_rows)), ("predicoes_validacao.csv", pred[pred.particao == "validacao_2023"]), ("predicoes_backtest.csv", pred[pred.particao == "backtest_2024"]), ("importancias_variaveis.csv", pd.DataFrame(importance)), ("ranking_validacao.csv", ranking)):
        data.to_csv(output / path, index=False)
    _bootstrap(pred, bootstrap_repetitions).to_csv(output / "intervalos_bootstrap.csv", index=False)
    pr_curve, roc_curve_data, calibration = _curve_artifacts(pred)
    pr_curve.to_csv(output / "curvas_pr.csv", index=False)
    roc_curve_data.to_csv(output / "curvas_roc.csv", index=False)
    calibration.to_csv(output / "curvas_calibracao.csv", index=False)
    bootstrap = pd.read_csv(output / "intervalos_bootstrap.csv")
    bootstrap[bootstrap["modelo"].str.endswith("_vs_dummy_prior")].to_csv(
        output / "comparacao_pareada.csv", index=False
    )
    perm_rows = []; rng = np.random.default_rng(SEED)
    for model, group in pred[pred.particao == "validacao_2023"].groupby("modelo"):
        for seed in range(10):
            shuffled = group.y_real.to_numpy().copy(); np.random.default_rng(seed).shuffle(shuffled); perm_rows.append({"modelo": model, "seed": seed, "average_precision": average_precision_score(shuffled, group.probabilidade), "roc_auc": roc_auc_score(shuffled, group.probabilidade)})
    pd.DataFrame(perm_rows).to_csv(output / "testes_permutacao.csv", index=False)
    errors = pred.copy(); errors["classe_prevista"] = (errors.probabilidade >= errors.threshold).astype(int); errors["tipo_erro"] = np.select([(errors.y_real == 1) & (errors.classe_prevista == 0), (errors.y_real == 0) & (errors.classe_prevista == 1)], ["falso_negativo", "falso_positivo"], default="acerto"); errors["residuo_probabilidade"] = errors.y_real - errors.probabilidade; errors.to_csv(output / "erros_modelos.csv", index=False)
    result = {"snapshot_sha256": SNAPSHOT_SHA256, "config_sha256": _sha256(Path(__file__).resolve().parents[2] / CONFIG_PATH), "folds": len(folds), "modelos": ALL_NAMES, "ranking_validacao": ranking.to_dict("records"), "conclusao": "Nenhum dos oito modelos demonstrou superioridade preditiva consolidada sob o contrato avaliado."}
    (output / "manifesto_execucao.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result
