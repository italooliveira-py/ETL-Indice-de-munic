"""Utilities for the E04 prova_conceito_infraestrutura.

This module is deliberately independent from the production ETL.  It reads
already generated public outputs and keeps the ObrasGov target separate from
the municipal context used by the experimental baselines.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "dados" / "bruto"
OUTPUT_DIR = ROOT / "output"
BASE_SNAPSHOT = RAW_DIR / "base_municipio_ano_snapshot.csv"
EVENTS_SNAPSHOT = RAW_DIR / "eventos_obrasgov_snapshot.csv"
MANIFEST_PATH = RAW_DIR / "manifesto_prova_conceito_infraestrutura.json"

SCOPE_STATEMENT = (
    "O ObrasGov foi utilizado exclusivamente como fonte experimental para validar "
    "o fluxo supervisionado, em razão da disponibilidade de desfechos observáveis. "
    "A fonte não representa contratos de serviços, programas educacionais, projetos "
    "administrativos ou outras modalidades de execução pública. Portanto, os "
    "resultados desta entrega são restritos a obras e infraestrutura e não constituem "
    "o índice geral proposto pelo projeto."
)

EVENT_SNAPSHOT_COLUMNS = [
    "codigo_ibge", "municipio", "uf", "ano", "ano_cadastro", "ano_inicio_previsto",
    "ano_fim_previsto", "ano_inicio_efetivo", "ano_fim_efetivo",
    "data_observacao_status", "evento_adverso_execucao", "resultado_observavel",
    "projeto_censurado", "id_projeto_investimento", "situacao_atual",
    "data_inicial_prevista", "data_final_prevista", "data_inicial_efetiva",
    "data_final_efetiva", "percentual_execucao", "possui_estudo_viabilidade",
    "quantidade_eventos_paralisacao_cancelamento", "sem_estudo_viabilidade",
    "valor_obra_parada",
]

MODEL_PREDICTORS = [
    "populacao", "pib", "populacao_siconfi", "receita_total_realizada",
    "transferencias_correntes_realizadas", "despesa_total_liquidada",
    "despesa_pessoal_liquidada", "investimentos_liquidados",
    "restos_pagar_processados", "restos_pagar_nao_processados",
    "caixa_equivalentes", "total_contratacoes", "valor_estimado_contratacoes",
    "valor_homologado_contratacoes", "contratacoes_similares",
    "valor_contratacoes_similares", "restos_pagar_total", "pib_per_capita",
    "dependencia_transferencias", "investimento_per_capita",
    "restos_pagar_sobre_receita", "caixa_sobre_receita", "pressao_pessoal_proxy",
    "resultado_orcamentario_proxy",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} sem colunas obrigatórias: {missing}")


def create_snapshots(
    base_source: Path = OUTPUT_DIR / "base_municipio_ano.csv",
    events_source: Path = OUTPUT_DIR / "eventos_obrasgov.csv",
) -> dict:
    """Explicit maintenance operation to create snapshots from existing outputs.

    The notebook never calls this function.  It is intentionally kept as an
    opt-in maintenance operation for refreshing the versioned snapshots.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(base_source, low_memory=False)
    events = pd.read_csv(events_source, low_memory=False)
    _require_columns(base, ("codigo_ibge", "ano"), "base municipal")
    _require_columns(events, EVENT_SNAPSHOT_COLUMNS, "eventos ObrasGov")
    base = base.copy()
    events = events[EVENT_SNAPSHOT_COLUMNS].copy()
    events["evento_adverso_obrasgov"] = events["evento_adverso_execucao"]
    base.to_csv(BASE_SNAPSHOT, index=False)
    events.to_csv(EVENTS_SNAPSHOT, index=False)
    manifest = {
        "name": "prova_conceito_infraestrutura",
        "scope_statement": SCOPE_STATEMENT,
        "snapshot_names": [BASE_SNAPSHOT.name, EVENTS_SNAPSHOT.name],
        "sources": {
            BASE_SNAPSHOT.name: str(base_source.relative_to(ROOT)),
            EVENTS_SNAPSHOT.name: str(events_source.relative_to(ROOT)),
        },
        "rows": {BASE_SNAPSHOT.name: len(base), EVENTS_SNAPSHOT.name: len(events)},
        "columns": {BASE_SNAPSHOT.name: list(base.columns), EVENTS_SNAPSHOT.name: list(events.columns)},
        "sha256": {},
        "keys": {
            BASE_SNAPSHOT.name: ["codigo_ibge", "ano"],
            EVENTS_SNAPSHOT.name: ["id_projeto_investimento"],
        },
        "limitations": [
            "ObrasGov é uma fonte experimental restrita a obras e infraestrutura.",
            "O snapshot não é uma fotografia de contratos de serviços ou programas.",
        ],
    }
    manifest["sha256"] = {
        BASE_SNAPSHOT.name: _sha256(BASE_SNAPSHOT),
        EVENTS_SNAPSHOT.name: _sha256(EVENTS_SNAPSHOT),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validate_snapshots() -> dict:
    """Validate the versioned snapshots, manifest, hashes, and public contract."""
    required = (MANIFEST_PATH, BASE_SNAPSHOT, EVENTS_SNAPSHOT)
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Snapshots versionados ausentes: "
            + ", ".join(missing)
            + ". O fluxo padrão não acessa output/; use create_snapshots() explicitamente "
            "apenas como manutenção quando as fontes locais existirem."
        )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_names = [BASE_SNAPSHOT.name, EVENTS_SNAPSHOT.name]
    if manifest.get("snapshot_names") != expected_names:
        raise ValueError("manifesto com snapshot_names incompatíveis")
    for path in (BASE_SNAPSHOT, EVENTS_SNAPSHOT):
        expected_hash = manifest.get("sha256", {}).get(path.name)
        actual_hash = _sha256(path)
        if expected_hash != actual_hash:
            raise ValueError(f"hash incompatível para {path.name}")

    base = pd.read_csv(BASE_SNAPSHOT, low_memory=False)
    events = pd.read_csv(EVENTS_SNAPSHOT, low_memory=False)
    _require_columns(base, ("codigo_ibge", "ano"), "base municipal")
    _require_columns(events, (*EVENT_SNAPSHOT_COLUMNS, "evento_adverso_obrasgov"), "eventos ObrasGov")
    if len(base) != 1115 or len(events) != 1638:
        raise ValueError(f"cardinalidade incompatível: base={len(base)}, eventos={len(events)}")
    if base[["codigo_ibge", "ano"]].duplicated().any():
        raise ValueError("snapshot municipal possui chave codigo_ibge + ano duplicada")
    identifiers = events["id_projeto_investimento"]
    if identifiers.isna().any() or identifiers.nunique() != 1638:
        raise ValueError("snapshot ObrasGov possui id_projeto_investimento nulo ou duplicado")
    target = events["evento_adverso_obrasgov"]
    counts = {
        "observaveis": int(target.notna().sum()),
        "censurados": int(target.isna().sum()),
        "negativos": int((target == 0).sum()),
        "positivos": int((target == 1).sum()),
    }
    if counts != {"observaveis": 561, "censurados": 1077, "negativos": 508, "positivos": 53}:
        raise ValueError(f"contagens do alvo incompatíveis: {counts}")
    return manifest


def load_snapshots(*, validate: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load versioned snapshots without changing missing-value semantics."""
    if validate:
        validate_snapshots()
    base = pd.read_csv(BASE_SNAPSHOT, low_memory=False)
    events = pd.read_csv(EVENTS_SNAPSHOT, low_memory=False)
    _require_columns(base, ("codigo_ibge", "ano"), "base municipal")
    _require_columns(events, (*EVENT_SNAPSHOT_COLUMNS, "evento_adverso_obrasgov"), "eventos ObrasGov")
    return base, events


def build_ano_ref(events: pd.DataFrame) -> pd.Series:
    """Return the only allowed pre-event context year, or missing."""
    start = pd.to_numeric(events["ano_inicio_previsto"], errors="coerce")
    registration = pd.to_numeric(events["ano_cadastro"], errors="coerce")
    start = start.where(start > 0)
    registration = registration.where(registration > 0)
    return (start.fillna(registration) - 1).astype("Int64")


def preparar_alvo(events: pd.DataFrame) -> pd.DataFrame:
    """Preserve the original target and expose its analytical alias."""
    result = events.copy()
    result["evento_adverso_obrasgov"] = result["evento_adverso_execucao"]
    result["projeto_censurado"] = result["evento_adverso_obrasgov"].isna()
    return result


def build_modeling_frame(
    base: pd.DataFrame,
    events: pd.DataFrame,
    *,
    min_year: int = 2020,
    max_year: int = 2024,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join observed events to the municipal context strictly before the event."""
    events = preparar_alvo(events)
    events = events.copy()
    events["ano_ref"] = build_ano_ref(events)
    if base[["codigo_ibge", "ano"]].duplicated().any():
        raise ValueError("base municipal possui chave codigo_ibge + ano duplicada")
    if events["id_projeto_investimento"].duplicated().any():
        raise ValueError("eventos possuem id_projeto_investimento duplicado")
    available_predictors = [column for column in MODEL_PREDICTORS if column in base.columns]
    context = base[["codigo_ibge", "ano", *available_predictors]].copy()
    joined = events.merge(
        context,
        left_on=["codigo_ibge", "ano_ref"],
        right_on=["codigo_ibge", "ano"],
        how="left",
        indicator=True,
        suffixes=("", "_context"),
    )
    reasons = pd.Series(pd.NA, index=joined.index, dtype="string")
    reasons.loc[joined["id_projeto_investimento"].isna()] = "missing_key"
    reasons.loc[joined["ano_ref"].isna() & reasons.isna()] = "missing_reference_year"
    outside = joined["ano_ref"].notna() & ~joined["ano_ref"].between(min_year, max_year)
    reasons.loc[outside & reasons.isna()] = "outside_window"
    reasons.loc[joined["_merge"].eq("left_only") & reasons.isna()] = "missing_context"
    reasons.loc[joined["evento_adverso_obrasgov"].isna() & reasons.isna()] = "censored_quality"
    joined["exclusion_reason"] = reasons
    exclusions = joined.loc[reasons.notna(), ["id_projeto_investimento", "codigo_ibge", "ano_ref", "exclusion_reason"]].copy()
    exclusions = exclusions.rename(columns={"exclusion_reason": "reason"})
    modeling = joined.loc[reasons.isna()].copy()
    modeling = modeling[[
        "id_projeto_investimento", "codigo_ibge", "ano", "ano_ref",
        "evento_adverso_execucao", "evento_adverso_obrasgov", "projeto_censurado",
        *available_predictors,
    ]]
    return modeling, exclusions


def audit_cohorts(frame: pd.DataFrame) -> pd.DataFrame:
    """Count both target classes by event cohort before freezing a split."""
    required = {"ano", "evento_adverso_obrasgov"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"coortes sem colunas: {sorted(missing)}")
    grouped = frame.groupby("ano")["evento_adverso_obrasgov"]
    result = grouped.agg(
        eventos="size",
        positivos=lambda values: int((values == 1).sum()),
        negativos=lambda values: int((values == 0).sum()),
    )
    result["duas_classes"] = (result["positivos"] > 0) & (result["negativos"] > 0)
    return result.sort_index()


def temporal_split(
    frame: pd.DataFrame,
    *,
    train_until: int = 2022,
    validation_year: int = 2023,
    test_year: int = 2024,
) -> dict[str, pd.DataFrame]:
    """Freeze a chronological split only after checking class support."""
    train = frame.loc[frame["ano"] <= train_until].copy()
    validation = frame.loc[frame["ano"] == validation_year].copy()
    test = frame.loc[frame["ano"] == test_year].copy()
    split = {"train": train, "validation": validation, "test": test}
    for name, part in split.items():
        classes = set(part["evento_adverso_obrasgov"].dropna().astype(int))
        if classes != {0, 1}:
            raise ValueError(f"coorte {name} sem suporte às duas classes: {sorted(classes)}")
    ids = [set(part["id_projeto_investimento"]) for part in split.values()]
    if ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2]:
        raise ValueError("IDs de projeto sobrepostos entre partições temporais")
    return split


def predictor_columns(frame: pd.DataFrame, *, target: str) -> list[str]:
    """Return only the predeclared, target-independent municipal predictors."""
    return [column for column in MODEL_PREDICTORS if column in frame.columns and column != target]


def _numeric_matrix(train: pd.DataFrame, other: pd.DataFrame, target: str) -> tuple[np.ndarray, np.ndarray]:
    columns = [column for column in predictor_columns(train, target=target) if pd.api.types.is_numeric_dtype(train[column])]
    if not columns:
        raise ValueError("baseline_logistico_obras_publicas requer preditores numéricos")
    x_train = train[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    x_other = other[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    medians = np.nanmedian(x_train, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    x_train = np.where(np.isfinite(x_train), x_train, medians)
    x_other = np.where(np.isfinite(x_other), x_other, medians)
    center = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    return (x_train - center) / scale, (x_other - center) / scale


def baseline_trivial_obras_publicas(train: pd.DataFrame, other: pd.DataFrame, *, target: str) -> np.ndarray:
    """Predict the observed positive rate calculated on train only."""
    y = pd.to_numeric(train[target], errors="raise").astype(int)
    return np.repeat(float(y.mean()), len(other))


def baseline_logistico_obras_publicas(
    train: pd.DataFrame,
    other: pd.DataFrame,
    *,
    target: str,
    regularization: float = 0.01,
    iterations: int = 800,
) -> np.ndarray:
    """Small deterministic L2 logistic baseline with train-only imputation."""
    x_train, x_other = _numeric_matrix(train, other, target)
    y = pd.to_numeric(train[target], errors="raise").to_numpy(dtype=float)
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    x_other = np.column_stack([np.ones(len(x_other)), x_other])
    weights = np.zeros(x_train.shape[1], dtype=float)
    for _ in range(iterations):
        logits = np.clip(x_train @ weights, -40, 40)
        probability = 1.0 / (1.0 + np.exp(-logits))
        gradient = (x_train.T @ (probability - y)) / len(y)
        gradient[1:] += regularization * weights[1:]
        weights -= 0.2 * gradient
    return 1.0 / (1.0 + np.exp(-np.clip(x_other @ weights, -40, 40)))


def precision_recall_at_k(y_true: Iterable[int], scores: Iterable[float], *, k_fraction: float = 0.2) -> dict:
    y = np.asarray(list(y_true), dtype=int)
    score = np.asarray(list(scores), dtype=float)
    if len(y) != len(score) or len(y) == 0:
        raise ValueError("y_true e scores precisam ter o mesmo tamanho não vazio")
    k = max(1, int(np.ceil(len(y) * k_fraction)))
    order = np.argsort(-score, kind="mergesort")[:k]
    positives = int(y.sum())
    hits = int(y[order].sum())
    return {
        "k": k,
        "precision_at_k": hits / k,
        "recall_at_k": hits / positives if positives else None,
        "precision_at_k_denominator": k,
        "recall_at_k_denominator": positives,
    }


def avaliar_baseline(y_true: Iterable[int], scores: Iterable[float], *, k_fraction: float = 0.2) -> dict:
    y = np.asarray(list(y_true), dtype=int)
    score = np.asarray(list(scores), dtype=float)
    pred = (score >= 0.5).astype(int)
    tn = int(((y == 0) & (pred == 0)).sum())
    fp = int(((y == 0) & (pred == 1)).sum())
    fn = int(((y == 1) & (pred == 0)).sum())
    tp = int(((y == 1) & (pred == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    k_metrics = precision_recall_at_k(y, score, k_fraction=k_fraction)
    roc_auc = float(roc_auc_score(y, score)) if len(np.unique(y)) == 2 else None
    average_precision = float(average_precision_score(y, score)) if len(np.unique(y)) == 2 else None
    curve_precision, curve_recall, curve_thresholds = precision_recall_curve(y, score)
    result = {
        "n": len(y),
        "positivos_denominator": int(y.sum()),
        "negativos_denominator": int((y == 0).sum()),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "balanced_accuracy": (recall + specificity) / 2,
        "roc_auc": roc_auc,
        "average_precision_score": average_precision,
        "precision_recall_curve": [
            curve_precision.tolist(), curve_recall.tolist(), curve_thresholds.tolist()
        ],
        "confusion_matrix": [[tn, fp], [fn, tp]],
    }
    result.update(k_metrics)
    return result


def diagnostico_operacional_obras_publicas(frame: pd.DataFrame) -> dict:
    """Document the absence of a formal operational rule; never score a model."""
    return {
        "status": "descritivo_nao_preditivo",
        "reason": "sem regra formal aprovada; não usar como preditor ou índice",
        "n": len(frame),
    }


if __name__ == "__main__":
    print(json.dumps(create_snapshots(), ensure_ascii=False, indent=2))
