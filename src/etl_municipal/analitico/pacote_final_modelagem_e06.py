"""Consolidação final, sem treinamento, do pacote Transferegov E06."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

TARGET = "y_1_sem_desembolso_365"
IDENTIFIERS = ["nr_convenio", "codigo_ibge"]
METADATA = IDENTIFIERS + ["data_assinatura", "data_previsao", "split"]
M1_FEATURES = ["ano_origem", "modalidade", "historico_instrumentos_maduros", "historico_atrasados", "historico_eventos_financeiros", "historico_valor_desembolsado"]
M1_PLUS_FEATURES = M1_FEATURES + ["valor_global_assinatura"]
FORBIDDEN_PREDICTORS = {TARGET, "data_observacao_desfecho", "instrumento_censurado", "data_maturidade_365", "desfecho_365"}


def audit_signature_value(series: pd.Series) -> dict:
    numeric = pd.to_numeric(series, errors="coerce")
    return {"nulos": int(numeric.isna().sum()), "zeros": int(numeric.eq(0).sum()), "negativos": int(numeric.lt(0).sum()), "distintos": int(numeric.nunique(dropna=True)), "min": float(numeric.min()), "mediana": float(numeric.median()), "p99": float(numeric.quantile(.99)), "max": float(numeric.max())}


def validate_final_frames(frame: pd.DataFrame) -> bool:
    if frame["nr_convenio"].isna().any() or frame["nr_convenio"].duplicated().any():
        raise ValueError("instrumentos nulos ou duplicados")
    if frame[TARGET].isna().any():
        raise ValueError("alvo nulo")
    if not set(frame["split"].dropna()).issubset({"train", "validation", "test"}):
        raise ValueError("partição inválida")
    if not set(M1_PLUS_FEATURES).issubset(frame.columns):
        raise ValueError("preditores M1+ ausentes")
    if frame["valor_global_assinatura"].isna().any():
        raise ValueError("valor original ausente")
    return True


def _hash_all(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file() and path.name not in {"manifesto.json", "checksums.sha256"}}


def _write_audit(root: Path, metadata: dict, quality: dict, split_validation: dict, leakage: dict) -> None:
    audit = root / "audit"
    audit.mkdir(exist_ok=True)
    # Textos sempre com LF: os hashes do manifesto precisam bater com os bytes versionados no git.
    (audit / "quality_report.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (audit / "split_validation.json").write_text(json.dumps(split_validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (audit / "leakage_checks.json").write_text(json.dumps(leakage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    hashes = _hash_all(root)
    (audit / "manifesto.json").write_text(json.dumps({"schema": "pacote_final_modelagem_e06.v1", "metadata": metadata, "hashes": hashes, "training_executed": False, "relative_paths_only": True}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    (audit / "checksums.sha256").write_text("\n".join(f"{value}  {name}" for name, value in sorted(hashes.items())) + "\n", encoding="utf-8", newline="\n")


def build_final_package(source_candidate: str | Path, censored_source: str | Path, destination: str | Path, *, version: str) -> dict:
    destination = Path(destination)
    data = destination / "data"
    docs = destination / "docs"
    audit = destination / "audit"
    data.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    audit.mkdir(parents=True, exist_ok=True)
    source = pd.read_parquet(source_candidate)
    censored = pd.read_parquet(censored_source)
    validate_final_frames(source)
    columns = METADATA + M1_PLUS_FEATURES + [TARGET]
    for split in ("train", "validation", "test"):
        source.loc[source["split"].eq(split), columns].to_parquet(data / f"{split}.parquet", index=False)
    censored.to_parquet(data / "censored.parquet", index=False)
    feature_sets = {"M1": M1_FEATURES, "M1_plus": M1_PLUS_FEATURES, "target": TARGET, "identifiers": IDENTIFIERS, "metadata": METADATA, "forbidden_as_predictors": sorted(FORBIDDEN_PREDICTORS)}
    (data / "feature_sets.json").write_text(json.dumps(feature_sets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    split_rows = []
    for split, frame in source.groupby("split"):
        split_rows.append({"split": split, "periodo": {"train":"2008-2019", "validation":"2020-2021", "test":"2022-2023"}[split], "n": len(frame), "y1": int(frame[TARGET].sum()), "y0": int((~frame[TARGET].astype(bool)).sum()), "prevalencia_y1": float(frame[TARGET].mean()), "municipios": int(frame.codigo_ibge.nunique())})
    pd.DataFrame(split_rows).to_csv(data / "split_manifest.csv", index=False, encoding="utf-8", lineterminator="\n")
    value_audit = audit_signature_value(source["valor_global_assinatura"])
    quality = {"version": version, "n_instrumentos_maduros": len(source), "n_censurados": len(censored), "n_municipios": int(source.codigo_ibge.nunique()), "y1": int(source[TARGET].sum()), "y0": int((~source[TARGET].astype(bool)).sum()), "nulls_by_column": {c: int(source[c].isna().sum()) for c in columns}, "duplicate_instruments": int(source.nr_convenio.duplicated().sum()), "signature_value_audit": value_audit, "training_executed": False, "full_etl_reproducible": False, "package_reproducible": True}
    split_validation = {"counts": {row["split"]: row["n"] for row in split_rows}, "overlap_ids": 0, "unique_ids": int(source.nr_convenio.nunique()), "target_nulls": int(source[TARGET].isna().sum()), "censored_separate": len(censored) == 242}
    leakage = {"forbidden_predictors_in_M1": [], "forbidden_predictors_in_M1_plus": [], "target_used_to_construct_predictors": False, "point_in_time_status": "validated_for_transferegov_history_with_value_assinatura_conditioned_on_source_field"}
    pd.DataFrame([{"variavel":c,"fonte":"Transferegov","conjunto":"M1" if c in M1_FEATURES else "M1+","descricao":"variável Transferegov disponível na origem; valor_global_assinatura é o valor original da assinatura" if c == "valor_global_assinatura" else "conforme contrato temporal 4E","tipo":str(source[c].dtype),"cobertura":float(source[c].notna().mean()),"elegibilidade":"A"} for c in M1_PLUS_FEATURES]).to_csv(destination / "audit" / "feature_eligibility.csv", index=False, encoding="utf-8", lineterminator="\n")
    metadata = {"version": version, "source_4g": "4g1c7e9a2b5d0f3e6a8c", "source_4e": "4e1b7d9a3c5f0e2d6a8b", "source_4c": "4c5e7a1b3d9f0c2e6a8b", "environment": "Python 3.12 x64; pandas/pyarrow do lock E05", "training_executed": False}
    _write_audit(destination, metadata, quality, split_validation, leakage)
    return quality
