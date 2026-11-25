"""Verify the final E06 package without training or network access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
EXPECTED = {"train": 3711, "validation": 1023, "test": 625}


def verify() -> dict:
    manifest = json.loads((ROOT / "audit" / "manifesto.json").read_text(encoding="utf-8"))
    mismatches = []
    for relative, expected in manifest["hashes"].items():
        path = ROOT / relative
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            mismatches.append(relative)
    if mismatches:
        raise SystemExit(f"hash mismatch: {mismatches}")
    features = json.loads((ROOT / "data" / "feature_sets.json").read_text(encoding="utf-8"))
    frames = {name: pd.read_parquet(ROOT / "data" / f"{name}.parquet") for name in EXPECTED}
    combined = pd.concat(frames.values(), ignore_index=True)
    if any(len(frame) != EXPECTED[name] for name, frame in frames.items()):
        raise SystemExit("partition cardinality mismatch")
    if combined.nr_convenio.duplicated().any() or combined.y_1_sem_desembolso_365.isna().any():
        raise SystemExit("duplicate IDs or null target")
    if not set(features["M1_plus"]).issubset(combined.columns):
        raise SystemExit("M1+ schema mismatch")
    if set(combined.nr_convenio) & set(pd.read_parquet(ROOT / "data" / "censored.parquet").nr_convenio):
        raise SystemExit("censored overlap")
    result = {"status": "OK", "rows": len(combined), "municipios": int(combined.codigo_ibge.nunique()), "target_nulls": 0, "hash_mismatches": 0, "training_executed": False}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    verify()
