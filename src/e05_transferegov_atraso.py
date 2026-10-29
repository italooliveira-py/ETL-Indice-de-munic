"""Piloto supervisionado Transferegov: atraso até o primeiro desembolso.

Este módulo não altera Bronze/Silver/Gold. A unidade é um instrumento
discricionário e o alvo usa somente a janela financeira de 365 dias após a
assinatura. O adaptador de pré-processamento é substituível pelo pipeline
coletivo quando ele for integrado.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
import hashlib
import json

GOLD_VERSION = "65260a170ee18cd79501"
LOAD_DATE = pd.Timestamp("2026-07-17")
HORIZON_DAYS = 365
TARGET = "risco_atraso_primeiro_desembolso_365d"
TARGET_COLUMNS = {
    "resultado_anulado",
    "resultado_rescindido",
    "resultado_contas_rejeitadas",
    "resultado_prorrogado",
}
LEAKAGE_COLUMNS = TARGET_COLUMNS | {
    "valor_desembolsado",
    "data_primeiro_desembolso",
    "dias_ate_primeiro_desembolso",
    "id_desembolso",
    "qtd_desembolsos",
    "situacao",
    "subsituacao",
    "instrumento_ativo",
    "data_fim_vigencia",
    "data_carga",
    "cnpj_proponente",
    "codigo_ibge",
}
NUMERIC_FEATURES = [
    "valor_global_original",
    "valor_global_assinatura",
    "valor_contrapartida",
    "duracao_original_dias",
    "dias_proposta_ate_assinatura",
]
CATEGORICAL_FEATURES = [
    "modalidade",
    "orgao_superior",
    "orgao",
    "origem_emenda",
    "emenda_individual",
    "emenda_impositiva",
]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _required(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{label}: colunas ausentes: {', '.join(missing)}")


def build_target(
    instrumentos: pd.DataFrame,
    desembolsos: pd.DataFrame,
    data_carga: pd.Timestamp | str = LOAD_DATE,
    horizon_days: int = HORIZON_DAYS,
) -> pd.DataFrame:
    """Constrói o alvo e anexa um relatório de qualidade em ``attrs``."""
    _required(
        instrumentos,
        {"nr_convenio", "data_assinatura"},
        "instrumentos",
    )
    _required(
        desembolsos,
        {"id_desembolso", "nr_convenio", "data_desembolso", "valor_desembolsado"},
        "desembolsos",
    )
    if instrumentos["nr_convenio"].isna().any() or instrumentos["nr_convenio"].duplicated().any():
        raise ValueError("nr_convenio deve ser não nulo e único")
    if desembolsos["id_desembolso"].isna().any():
        raise ValueError("id_desembolso não pode ser nulo")

    out = instrumentos.copy()
    out["data_assinatura"] = pd.to_datetime(out["data_assinatura"], errors="coerce")
    if out["data_assinatura"].isna().any():
        raise ValueError("data_assinatura inválida ou ausente")
    out["data_maturidade"] = out["data_assinatura"] + pd.to_timedelta(horizon_days, unit="D")

    disb = desembolsos.copy()
    duplicate_count = int(disb["id_desembolso"].duplicated().sum())
    disb = disb.drop_duplicates("id_desembolso", keep="first")
    disb["data_desembolso"] = pd.to_datetime(disb["data_desembolso"], errors="coerce")
    linked = disb.merge(
        out[["nr_convenio", "data_assinatura"]],
        on="nr_convenio",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    unmatched = int((linked["_merge"] != "both").sum())
    if unmatched:
        raise ValueError(f"desembolsos sem instrumento correspondente: {unmatched}")
    linked["before_signature"] = linked["data_desembolso"] < linked["data_assinatura"]
    before_signature = int(linked["before_signature"].sum())
    invalid_date = int(linked["data_desembolso"].isna().sum())
    invalid_value = int((pd.to_numeric(linked["valor_desembolsado"], errors="coerce") <= 0).sum())
    valid = linked["data_desembolso"].notna() & linked["valor_desembolsado"].gt(0) & ~linked["before_signature"]
    first = (
        linked.loc[valid]
        .sort_values(["nr_convenio", "data_desembolso", "id_desembolso"])
        .drop_duplicates("nr_convenio", keep="first")[["nr_convenio", "data_desembolso"]]
        .rename(columns={"data_desembolso": "data_primeiro_desembolso"})
    )
    out = out.merge(first, on="nr_convenio", how="left", validate="one_to_one")
    out["dias_ate_primeiro_desembolso"] = (
        out["data_primeiro_desembolso"] - out["data_assinatura"]
    ).dt.days
    cutoff = pd.Timestamp(data_carga)
    out["censurado"] = out["data_maturidade"] > cutoff
    out[TARGET] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    observable = ~out["censurado"]
    out.loc[observable & (out["dias_ate_primeiro_desembolso"] <= horizon_days), TARGET] = 0
    out.loc[
        observable
        & (out["data_primeiro_desembolso"].isna() | (out["dias_ate_primeiro_desembolso"] > horizon_days)),
        TARGET,
    ] = 1
    out["ano_ref"] = out["data_assinatura"].dt.year
    value_columns = [
        column for column in ("valor_global_original", "valor_global_assinatura", "valor_repasse")
        if column in out.columns
    ]
    if value_columns:
        numeric_values = out[value_columns].apply(pd.to_numeric, errors="coerce")
        invalid_instrument_values = int((numeric_values.isna() | numeric_values.le(0)).any(axis=1).sum())
    else:
        invalid_instrument_values = 0
    reasons = pd.Series("censurado_365_incompleto", index=out.index, dtype="object")
    reasons.loc[observable & out["data_primeiro_desembolso"].notna() & out["dias_ate_primeiro_desembolso"].le(horizon_days)] = "desembolso_ate_365"
    reasons.loc[observable & out["data_primeiro_desembolso"].isna()] = "sem_desembolso_ate_365"
    reasons.loc[observable & out["dias_ate_primeiro_desembolso"].gt(horizon_days)] = "desembolso_apos_365"
    out.attrs["report"] = {
        "duplicate_disbursements": duplicate_count,
        "unmatched_disbursements": unmatched,
        "before_signature": before_signature,
        "invalid_disbursement_dates": invalid_date,
        "invalid_disbursement_values": invalid_value,
        "instruments_with_first_disbursement": int(out["data_primeiro_desembolso"].notna().sum()),
        "instruments_without_first_disbursement": int(out["data_primeiro_desembolso"].isna().sum()),
        "unmatched_instruments": int(out["data_primeiro_desembolso"].isna().sum()),
        "invalid_instrument_values": invalid_instrument_values,
        "boundary_365": int((out["dias_ate_primeiro_desembolso"] == horizon_days).sum()),
        "boundary_gt_365": int((out["dias_ate_primeiro_desembolso"] == horizon_days + 1).sum()),
        "reason_counts": reasons.value_counts().to_dict(),
        "observed": int(observable.sum()),
        "censored": int(out["censurado"].sum()),
        "horizon_days": horizon_days,
        "data_carga": cutoff.date().isoformat(),
    }
    return out


def select_predictors(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Deriva somente variáveis conhecidas na assinatura."""
    forbidden = sorted(set(frame.columns) & LEAKAGE_COLUMNS)
    if forbidden:
        raise ValueError(f"campos proibidos presentes na matriz: {', '.join(forbidden)}")
    _required(frame, {"data_assinatura", "data_proposta", "data_fim_vigencia_original"} | set(NUMERIC_FEATURES[:3]) | set(CATEGORICAL_FEATURES), "preditores")
    x = frame.copy()
    x["data_assinatura"] = pd.to_datetime(x["data_assinatura"], errors="coerce")
    x["data_proposta"] = pd.to_datetime(x["data_proposta"], errors="coerce")
    x["data_fim_vigencia_original"] = pd.to_datetime(x["data_fim_vigencia_original"], errors="coerce")
    x["duracao_original_dias"] = (x["data_fim_vigencia_original"] - x["data_assinatura"]).dt.days
    x["dias_proposta_ate_assinatura"] = (x["data_assinatura"] - x["data_proposta"]).dt.days
    features = x[FEATURE_COLUMNS].copy()
    return features, {
        "source": "Transferegov",
        "features": FEATURE_COLUMNS.copy(),
        "excluded": sorted(LEAKAGE_COLUMNS | {"nr_convenio", "id_proposta", "codigo_ibge", "data_assinatura", "data_proposta", "data_fim_vigencia_original", "data_publicacao"}),
        "preprocessing": "ColumnTransformer ajustado somente no treino",
        "integration_point": "substituir pelo pipeline coletivo quando integrado",
    }


def temporal_split(frame: pd.DataFrame) -> dict[int, pd.DataFrame]:
    _required(frame, {"ano_ref", TARGET}, "split temporal")
    result = {year: frame.loc[frame["ano_ref"].eq(year) & frame[TARGET].notna()].copy() for year in (2022, 2023, 2024)}
    for year, part in result.items():
        counts = part[TARGET].astype(int).value_counts()
        if set(counts.index) != {0, 1} or counts.min() < 10:
            raise ValueError(f"coorte {year} sem suporte mínimo: {counts.to_dict()}")
    return result


def make_preprocessor(features: pd.DataFrame) -> ColumnTransformer:
    numeric = [c for c in NUMERIC_FEATURES if c in features.columns]
    categorical = [c for c in CATEGORICAL_FEATURES if c in features.columns]
    return ColumnTransformer(
        [
            ("numeric", Pipeline([("imputer", SimpleImputer(strategy="median"))]), numeric),
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )


def model_registry() -> dict[str, dict[str, Any]]:
    return {
        "xgboost": {
            "estimador": "XGBClassifier",
            "espaco_hiperparametros": {"model__n_estimators": [80, 140], "model__max_depth": [2, 3], "model__learning_rate": [0.05, 0.1]},
            "responsavel": "Ítalo Oliveira",
            "requer_escalonamento": False,
            "aceita_peso_classe": True,
            "status_implementacao": "implementado",
        },
        "lightgbm": {
            "estimador": "LGBMClassifier",
            "espaco_hiperparametros": {"model__n_estimators": [80, 140], "model__num_leaves": [7, 15], "model__learning_rate": [0.05, 0.1]},
            "responsavel": "Ítalo Oliveira",
            "requer_escalonamento": False,
            "aceita_peso_classe": True,
            "status_implementacao": "implementado",
        },
        **{name: {"estimador": None, "espaco_hiperparametros": {}, "responsavel": "pendente", "requer_escalonamento": None, "aceita_peso_classe": None, "status_implementacao": "pendente_integracao"} for name in ("logistica", "knn", "random_forest", "decision_tree", "svc", "mlp")},
    }


def _estimator(name: str):
    if name == "xgboost":
        from xgboost import XGBClassifier

        return XGBClassifier(
            objective="binary:logistic", eval_metric="logloss", random_state=42,
            n_jobs=1, tree_method="hist", verbosity=0,
        )
    if name == "lightgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(objective="binary", random_state=42, n_jobs=1, verbosity=-1)
    raise ValueError(f"modelo não implementado: {name}")


def cv_folds(x: pd.DataFrame, y: pd.Series, groups: pd.Series, n_splits: int = 3):
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)
    folds = list(splitter.split(x, y, groups))
    for train_idx, valid_idx in folds:
        if len(set(y.iloc[train_idx])) < 2 or len(set(y.iloc[valid_idx])) < 2:
            raise ValueError("fold com classe única")
    return folds


def tune_model(name: str, x: pd.DataFrame, y: pd.Series, groups: pd.Series) -> GridSearchCV:
    registry = model_registry()[name]
    pipeline = Pipeline([("preprocessor", make_preprocessor(x)), ("model", _estimator(name))])
    search = GridSearchCV(
        pipeline, registry["espaco_hiperparametros"], scoring="average_precision",
        cv=cv_folds(x, y, groups), n_jobs=1, refit=True, return_train_score=False,
    )
    search.fit(x, y)
    return search


def _at_k(y: np.ndarray, probabilities: np.ndarray, fraction: float = 0.2) -> tuple[float, float]:
    k = max(1, int(np.ceil(len(y) * fraction)))
    selected = np.argsort(-probabilities)[:k]
    positives = int(y.sum())
    hits = int(y[selected].sum())
    return hits / k, hits / positives if positives else float("nan")


def classification_metrics(y_true, probabilities, threshold: float = 0.5, k_fraction: float = 0.2) -> dict[str, Any]:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    predicted = (p >= threshold).astype(int)
    precision_k, recall_k = _at_k(y, p, k_fraction)
    at_k = {fraction: _at_k(y, p, fraction) for fraction in (0.1, 0.2, 0.3)}
    matrix = confusion_matrix(y, predicted, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    prevalence = float(y.mean()) if len(y) else float("nan")
    ap = float(average_precision_score(y, p))
    lift_rows = []
    order = np.argsort(-p)
    for decile, indices in enumerate(np.array_split(order, 10), start=1):
        if len(indices):
            precision = float(y[indices].mean())
            lift_rows.append({"decil": decile, "n": int(len(indices)), "positivos": int(y[indices].sum()), "precision": precision, "lift": precision / prevalence if prevalence else float("nan")})
    result = {
        "n": int(len(y)), "positives": int(y.sum()), "negatives": int((y == 0).sum()),
        "prevalence": prevalence,
        "average_precision": ap,
        "average_precision_gain_absolute": ap - prevalence,
        "average_precision_gain_relative": (ap / prevalence - 1.0) if prevalence else float("nan"),
        "balanced_accuracy": float(balanced_accuracy_score(y, predicted)),
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "f1": float(f1_score(y, predicted, zero_division=0)),
        "specificity": float(tn / (tn + fp)) if (tn + fp) else float("nan"),
        "precision_at_k": float(precision_k), "recall_at_k": float(recall_k),
        "precision_at_10": float(at_k[0.1][0]), "recall_at_10": float(at_k[0.1][1]),
        "precision_at_20": float(at_k[0.2][0]), "recall_at_20": float(at_k[0.2][1]),
        "precision_at_30": float(at_k[0.3][0]), "recall_at_30": float(at_k[0.3][1]),
        "lift_by_decile": lift_rows,
        "brier_score": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "confusion_matrix": matrix.tolist(),
        "threshold": float(threshold), "k_fraction": float(k_fraction),
    }
    result["roc_auc"] = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")
    return result


def choose_threshold(y_true, probabilities, return_audit: bool = False):
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    candidates = np.unique(np.clip(np.r_[p, 0.5], 0.01, 0.99))
    scores = [(balanced_accuracy_score(y, p >= t), -t, t) for t in candidates]
    threshold = float(max(scores)[2])
    if not return_audit:
        return threshold
    predicted = p >= threshold
    matrix = confusion_matrix(y, predicted, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    return {
        "criterion": "balanced_accuracy",
        "threshold": threshold,
        "balanced_accuracy": float(max(scores)[0]),
        "predicted_positive": int(predicted.sum()),
        "predicted_negative": int((~predicted).sum()),
        "sensitivity": float(tp / (tp + fn)) if (tp + fn) else float("nan"),
        "specificity": float(tn / (tn + fp)) if (tn + fp) else float("nan"),
        "false_positive_rate": float(fp / (fp + tn)) if (fp + tn) else float("nan"),
        "false_negative_rate": float(fn / (fn + tp)) if (fn + tp) else float("nan"),
        "confusion_matrix": matrix.tolist(),
    }


def permutation_sanity(y_true, probabilities, seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    y = np.asarray(y_true, dtype=int).copy()
    rng.shuffle(y)
    ap = float(average_precision_score(y, probabilities))
    return {
        "seed": int(seed),
        "average_precision": ap,
        "average_precision_gain_absolute": ap - float(y.mean()),
        "roc_auc": float(roc_auc_score(y, probabilities)) if len(np.unique(y)) == 2 else float("nan"),
        "prevalence": float(y.mean()),
    }


def fit_baselines(x_train: pd.DataFrame, y_train: pd.Series) -> dict[str, Pipeline]:
    """Retorna apenas baselines de auditoria, sem substituir XGBoost/LightGBM."""
    return {
        "dummy_prior": Pipeline([("model", DummyClassifier(strategy="prior"))]).fit(x_train, y_train),
        "dummy_most_frequent": Pipeline([("model", DummyClassifier(strategy="most_frequent"))]).fit(x_train, y_train),
        "logistica": Pipeline([
            ("preprocessor", make_preprocessor(x_train)),
            ("model", LogisticRegression(max_iter=1000, random_state=42)),
        ]).fit(x_train, y_train),
    }


def diagnose_errors(frame: pd.DataFrame, probabilities, threshold: float, model: str) -> pd.DataFrame:
    out = frame[[c for c in ("nr_convenio", "codigo_ibge", "ano_ref", TARGET, "dias_ate_primeiro_desembolso") if c in frame]].copy()
    out["probabilidade"] = np.asarray(probabilities, dtype=float)
    out["classe_prevista"] = (out["probabilidade"] >= threshold).astype(int)
    out["threshold"] = float(threshold)
    out["tipo_erro"] = np.select(
        [(out[TARGET] == 0) & (out["classe_prevista"] == 1), (out[TARGET] == 1) & (out["classe_prevista"] == 0)],
        ["falso_positivo", "falso_negativo"], default="acerto",
    )
    out["residuo_probabilidade"] = out[TARGET].astype(float) - out["probabilidade"]
    out["modelo"] = model
    return out


def frozen_paths(data_root: str | Path) -> dict[str, Path]:
    root_input = Path(data_root)
    gold_root = root_input if root_input.name.lower() == "gold" else root_input / "gold"
    root = gold_root / "versoes" / GOLD_VERSION
    if not (root / "manifesto.json").exists():
        raise FileNotFoundError(f"geração Gold congelada ausente: {root}")
    return {
        "instrumentos": root / "silver" / "transferegov_instrumentos.parquet",
        "desembolsos": root / "silver" / "transferegov_desembolsos.parquet",
        "cnpj_ibge": root / "ref" / "transferegov_cnpj_municipio.parquet",
        "manifesto": root / "manifesto.json",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_frozen_tables(data_root: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Lê diretamente a versão congelada e confere os hashes publicados."""
    paths = frozen_paths(data_root)
    manifest = json.loads(paths["manifesto"].read_text(encoding="utf-8"))
    if manifest.get("versao_gold") != GOLD_VERSION:
        raise ValueError("manifesto Gold não corresponde à versão congelada")
    for relative, expected in manifest.get("hashes", {}).items():
        if relative in {"silver/transferegov_instrumentos", "silver/transferegov_desembolsos"}:
            path = paths["instrumentos"] if relative.endswith("instrumentos") else paths["desembolsos"]
            if _sha256(path) != expected:
                raise ValueError(f"hash divergente: {relative}")
    instrumentos = pd.read_parquet(paths["instrumentos"])
    desembolsos = pd.read_parquet(paths["desembolsos"])
    return instrumentos, desembolsos, manifest
