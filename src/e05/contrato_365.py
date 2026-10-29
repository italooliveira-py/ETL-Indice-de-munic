"""Preparação auditável do snapshot comum do contrato Transferegov 365d."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.e05_transferegov_atraso import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    GOLD_VERSION,
    TARGET,
    build_target,
    load_frozen_tables,
    select_predictors,
)

CONFIG_PATH = Path("config/e05.transferegov.365.json")
EXPECTED_MANIFEST_SHA256 = "28E24585431DC29B0DA53B10FD0811B91A02BA79BD00484EA6297D9ABB84F5B5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _code_sha256(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for relative in ("src/e05/contrato_365.py", "src/e05_transferegov_atraso.py"):
        path = repo_root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest().upper()


def _particao(ano: pd.Series) -> pd.Series:
    return ano.map({2022: "treino_2022", 2023: "validacao_2023", 2024: "backtest_2024"}).astype("string")


def build_snapshot(gold_root: str | Path, output_dir: str | Path, *, generated_at: str | None = None) -> dict[str, Any]:
    """Lê o Gold externo, cria o snapshot comum e grava somente artefatos derivados."""
    gold_root = Path(gold_root)
    output_dir = Path(output_dir)
    instrumentos, desembolsos, gold_manifest = load_frozen_tables(gold_root)
    manifest_path = gold_root / "versoes" / GOLD_VERSION / "manifesto.json"
    if _sha256(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("hash do manifesto Gold divergente")
    target = build_target(instrumentos, desembolsos, data_carga="2026-07-17")
    report = target.attrs.get("report", {})
    if report.get("before_signature", 0):
        raise ValueError("há desembolsos anteriores à assinatura")
    target = target[target["ano_ref"].isin([2022, 2023, 2024]) & target[TARGET].notna()].copy()
    if len(target) != 867:
        raise ValueError(f"snapshot esperado com 867 linhas; encontrado {len(target)}")
    counts = target.groupby("ano_ref")[TARGET].value_counts().to_dict()
    expected = {(2022, 0): 28, (2022, 1): 211, (2023, 0): 77, (2023, 1): 309, (2024, 0): 30, (2024, 1): 212}
    if counts != expected:
        raise ValueError(f"classes divergentes: {counts}")
    source_columns = [
        "data_assinatura", "data_proposta", "data_fim_vigencia_original",
        "valor_global_original", "valor_global_assinatura", "valor_contrapartida",
        *CATEGORICAL_FEATURES,
    ]
    source = target[source_columns].copy()
    features, audit = select_predictors(source)
    out = pd.DataFrame({
        "nr_convenio": target["nr_convenio"].astype("string"),
        "codigo_ibge": target["codigo_ibge"].astype("string") if "codigo_ibge" in target else pd.NA,
        "ano_coorte": target["ano_ref"].astype("int64"),
        "data_assinatura": target["data_assinatura"],
        TARGET: target[TARGET].astype("Int64"),
        "censurado": target["censurado"].astype(bool),
        "particao": _particao(target["ano_ref"]),
        "data_primeiro_desembolso": target["data_primeiro_desembolso"],
        "dias_ate_primeiro_desembolso": target["dias_ate_primeiro_desembolso"].astype("Int64"),
    })
    for column in FEATURE_COLUMNS:
        out[column] = features[column].to_numpy()
    if out["nr_convenio"].duplicated().any() or out["censurado"].any():
        raise ValueError("snapshot contém duplicidade ou censura")
    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = output_dir / "base_modelagem.parquet"
    part_path = output_dir / "particoes.csv"
    pred_path = output_dir / "preditores.csv"
    manifest_out = output_dir / "manifesto.json"
    out.to_parquet(base_path, index=False)
    out[["nr_convenio", "codigo_ibge", "ano_coorte", "data_assinatura", TARGET, "particao"]].to_csv(part_path, index=False)
    pd.DataFrame({"preditor": FEATURE_COLUMNS, "tipo": ["numerica"] * 5 + ["categorica"] * 6}).to_csv(pred_path, index=False)
    manifest = {
        "contrato": "e05_transferegov_365",
        "gold_version": GOLD_VERSION,
        "gold_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "gold_load_date": "17/07/2026 06:30:47",
        "rows": int(len(out)),
        "columns": int(len(out.columns)),
        "snapshot_sha256": _sha256(base_path),
        "config_sha256": _sha256(Path(__file__).resolve().parents[2] / CONFIG_PATH),
        "code_sha256": _code_sha256(Path(__file__).resolve().parents[2]),
        "partitions": out["particao"].value_counts().sort_index().to_dict(),
        "classes": {str(k): int(v) for k, v in out[TARGET].value_counts().sort_index().items()},
        "cohorts": {str(k): {str(c): int(n) for c, n in g[TARGET].value_counts().sort_index().items()} for k, g in out.groupby("ano_coorte")},
        "predictors": FEATURE_COLUMNS,
        "audit": {**audit, "target_report": report},
        "source_scope": "Transferegov only; ObrasGov excluded",
        "generated_at": generated_at or pd.Timestamp.utcnow().isoformat(),
    }
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest
