"""Funcoes puras para os indices experimentais de contexto municipal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FISCAL_COMPONENTS = (
    ("dependencia_transferencias", False),
    ("restos_pagar_sobre_receita", False),
    ("caixa_sobre_receita", True),
    ("pressao_pessoal_proxy", False),
    ("resultado_orcamentario_proxy", True),
)
INSTITUTIONAL_COMPONENTS = (
    ("proporcao_pessoal_estatutario", True),
    ("proporcao_pessoal_comissionado", False),
    ("proporcao_pessoal_sem_vinculo", False),
)
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "indice_contexto_municipal.v0.json"


def load_config(path: str | Path = CONFIG_PATH) -> tuple[dict[str, Any], str]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"configuracao ausente: {config_path}")
    raw = config_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("configuracao invalida") from exc
    required = {"versao_metodologia_indice", "fiscal", "institucional", "pncp", "temporalidade"}
    if not required.issubset(config):
        raise ValueError("configuracao sem campos obrigatorios")
    expected_fiscal = {name: ("inversa" if inverse else "direta") for name, inverse in FISCAL_COMPONENTS}
    expected_institutional = {name: ("inversa" if inverse else "direta") for name, inverse in INSTITUTIONAL_COMPONENTS}
    actual_fiscal = {k: v.get("direcao") for k, v in config["fiscal"]["componentes"].items()}
    actual_institutional = {k: v.get("direcao") for k, v in config["institucional"]["componentes"].items()}
    if actual_fiscal != expected_fiscal or actual_institutional != expected_institutional:
        raise ValueError("configuracao divergente das direcoes aprovadas")
    if config["fiscal"].get("min_componentes_validos") != 4 or config["institucional"].get("min_componentes_validos") != 2:
        raise ValueError("configuracao divergente dos minimos aprovados")
    if config["pncp"].get("periodo") != [2022, 2024] or config["pncp"].get("pesos") != {"intensidade_geral": 0.5, "similaridade": 0.5}:
        raise ValueError("configuracao PNCP divergente")
    return config, digest


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    den = den.where(den > 0)
    result = num / den
    return result.replace([np.inf, -np.inf], np.nan)


def derive_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Deriva componentes sem converter ausencia, invalidade ou nao aplicabilidade em zero."""
    out = frame.copy()
    receita = pd.to_numeric(out["receita_total_realizada"], errors="coerce")
    out["dependencia_transferencias"] = _safe_ratio(out["transferencias_correntes_realizadas"], receita)
    out["restos_pagar_sobre_receita"] = _safe_ratio(out["restos_pagar_total"], receita)
    out["caixa_sobre_receita"] = _safe_ratio(out["caixa_equivalentes"], receita)
    out["pressao_pessoal_proxy"] = _safe_ratio(out["despesa_pessoal_liquidada"], receita)
    out["resultado_orcamentario_proxy"] = _safe_ratio(
        receita - pd.to_numeric(out["despesa_total_liquidada"], errors="coerce"), receita
    )

    pessoal = pd.to_numeric(out["pessoal_ativo"], errors="coerce")
    out["proporcao_pessoal_estatutario"] = _safe_ratio(out["pessoal_estatutario"], pessoal)
    out["proporcao_pessoal_comissionado"] = _safe_ratio(out["pessoal_comissionado"], pessoal)
    out["proporcao_pessoal_sem_vinculo"] = _safe_ratio(out["pessoal_sem_vinculo"], pessoal)

    populacao = pd.to_numeric(out["populacao"], errors="coerce")
    populacao = populacao.where(populacao > 0)
    total_contratacoes = pd.to_numeric(out["total_contratacoes"], errors="coerce")
    out["contratacoes_por_mil_habitantes"] = (
        total_contratacoes / populacao * 1000
    ).replace([np.inf, -np.inf], np.nan)
    out["exposicao_contratual_sobre_receita"] = _safe_ratio(
        out["valor_estimado_contratacoes"], receita
    )
    total = total_contratacoes.where(total_contratacoes > 0)
    similar = _safe_ratio(out["contratacoes_similares"], total)
    total_raw = total_contratacoes
    similar_raw = pd.to_numeric(out["contratacoes_similares"], errors="coerce")
    estimated_raw = pd.to_numeric(out["valor_estimado_contratacoes"], errors="coerce")
    invalid_institutional = {
        name: ~pd.to_numeric(out[name], errors="coerce").between(0, 1)
        for name in ("proporcao_pessoal_estatutario", "proporcao_pessoal_comissionado", "proporcao_pessoal_sem_vinculo")
    }
    for name, invalid in invalid_institutional.items():
        out.loc[invalid, name] = np.nan
        out[f"motivo_invalidade_{name}"] = pd.Series(pd.NA, index=out.index, dtype="string")
        out.loc[invalid, f"motivo_invalidade_{name}"] = "fora_do_dominio_0_1"
    out.loc[total_raw < 0, "contratacoes_por_mil_habitantes"] = np.nan
    out.loc[estimated_raw < 0, "exposicao_contratual_sobre_receita"] = np.nan
    invalid_similar = (similar_raw < 0) | (similar_raw > total_raw)
    out["proporcao_contratacoes_similares"] = similar.where(~invalid_similar & similar.between(0, 1))
    out["motivo_invalidade_pncp"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out.loc[total_raw < 0, "motivo_invalidade_pncp"] = "total_contratacoes_negativo"
    out.loc[estimated_raw < 0, "motivo_invalidade_pncp"] = "valor_estimado_negativo"
    out.loc[invalid_similar, "motivo_invalidade_pncp"] = "similares_fora_do_total"
    return out


def winsorize_annual(
    frame: pd.DataFrame, value_col: str, year_col: str
) -> tuple[pd.DataFrame, dict[Any, dict[str, Any]]]:
    out = frame.copy()
    target = f"{value_col}_winsorized"
    out[target] = out[value_col]
    metadata: dict[Any, dict[str, Any]] = {}
    for year, idx in out.groupby(year_col, sort=True).groups.items():
        values = pd.to_numeric(out.loc[idx, value_col], errors="coerce")
        valid = values.dropna()
        if valid.empty:
            metadata[year] = {"method": "linear", "lower": None, "upper": None, "below": 0, "above": 0}
            continue
        lower = float(valid.quantile(0.01, interpolation="linear"))
        upper = float(valid.quantile(0.99, interpolation="linear"))
        metadata[year] = {
            "method": "linear",
            "lower": lower,
            "upper": upper,
            "below": int((valid < lower).sum()),
            "above": int((valid > upper).sum()),
        }
        out.loc[idx, target] = values.clip(lower=lower, upper=upper)
    return out, metadata


def annual_percentile(
    frame: pd.DataFrame, value_col: str, year_col: str, *, inverse: bool = False
) -> pd.DataFrame:
    out = frame.copy()
    target = f"{value_col}_percentile"
    out[target] = np.nan
    for _, idx in out.groupby(year_col, sort=True).groups.items():
        values = pd.to_numeric(out.loc[idx, value_col], errors="coerce")
        valid = values.dropna()
        if valid.empty:
            continue
        if len(valid) == 1:
            scores = pd.Series(50.0, index=valid.index)
        else:
            ranks = valid.rank(method="average")
            scores = (ranks - 1) / (len(valid) - 1) * 100
        if inverse:
            scores = 100 - scores
        out.loc[scores.index, target] = scores
    return out


def annual_band(
    frame: pd.DataFrame, value_col: str, year_col: str
) -> tuple[pd.DataFrame, dict[Any, dict[str, Any]]]:
    out = frame.copy()
    target = f"{value_col}_faixa"
    out[target] = pd.Series(pd.NA, index=out.index, dtype="string")
    metadata: dict[Any, dict[str, Any]] = {}
    for year, idx in out.groupby(year_col, sort=True).groups.items():
        values = pd.to_numeric(out.loc[idx, value_col], errors="coerce")
        valid = values.dropna()
        if valid.nunique() < 4:
            metadata[year] = {"reason": "valores_distintos_insuficientes", "distinct": int(valid.nunique())}
            continue
        q1, q2, q3 = (float(valid.quantile(q, interpolation="linear")) for q in (0.25, 0.5, 0.75))
        metadata[year] = {"q1": q1, "q2": q2, "q3": q3, "distinct": int(valid.nunique())}
        labels = pd.Series(index=valid.index, dtype="string")
        labels.loc[valid <= q1] = "baixo"
        labels.loc[(valid > q1) & (valid <= q2)] = "moderado"
        labels.loc[(valid > q2) & (valid <= q3)] = "alto"
        labels.loc[valid > q3] = "muito_alto"
        out.loc[labels.index, target] = labels
        metadata[year]["contagens_faixa"] = labels.value_counts().to_dict()
    return out, metadata


def _aggregate_percentiles(
    frame: pd.DataFrame,
    components: tuple[tuple[str, bool], ...],
    year_col: str,
    prefix: str,
    minimum: int,
) -> pd.DataFrame:
    out = frame.copy()
    percentile_cols = []
    for name, inverse in components:
        clipped, _ = winsorize_annual(out, name, year_col)
        clipped = annual_percentile(clipped, f"{name}_winsorized", year_col, inverse=inverse)
        col = f"{name}_percentile"
        out[col] = clipped[f"{name}_winsorized_percentile"]
        percentile_cols.append(col)
    count_col = f"quantidade_componentes_{prefix}_validos"
    coverage_col = f"cobertura_{prefix}"
    out[count_col] = out[percentile_cols].notna().sum(axis=1)
    out[coverage_col] = out[count_col] / len(components)
    out[f"indice_{prefix}"] = out[percentile_cols].mean(axis=1).where(out[count_col] >= minimum)
    return out


def compute_indices(frame: pd.DataFrame, year_col: str = "ano", config_path: str | Path = CONFIG_PATH) -> pd.DataFrame:
    """Calcula os quatro produtos aprovados e metadados por municipio-ano."""
    config, config_sha256 = load_config(config_path)
    out = frame.copy()
    if "cobertura_pncp" in out:
        out["cobertura_pncp_fonte"] = out["cobertura_pncp"]
    if "status_pncp" in out:
        out["status_cobertura_pncp_fonte"] = out["status_pncp"]
    out = derive_components(out)
    fiscal_components = tuple((name, config["fiscal"]["componentes"][name]["direcao"] == "inversa") for name in config["fiscal"]["componentes"])
    institutional_components = tuple((name, config["institucional"]["componentes"][name]["direcao"] == "inversa") for name in config["institucional"]["componentes"])
    out = _aggregate_percentiles(out, fiscal_components, year_col, "fiscais", config["fiscal"]["min_componentes_validos"])
    out = out.rename(columns={
        "quantidade_componentes_fiscais_validos": "quantidade_componentes_fiscais_validos",
        "cobertura_fiscais": "cobertura_fiscal",
        "indice_fiscais": "indice_vulnerabilidade_fiscal",
    })
    out = _aggregate_percentiles(out, institutional_components, year_col, "institucionais", config["institucional"]["min_componentes_validos"])
    out = out.rename(columns={
        "cobertura_institucionais": "cobertura_institucional",
        "indice_institucionais": "indice_estrutura_vinculos_institucionais",
    })
    out["quantidade_dimensoes_estruturais_validas"] = out[
        ["indice_vulnerabilidade_fiscal", "indice_estrutura_vinculos_institucionais"]
    ].notna().sum(axis=1)
    out["cobertura_contexto_estrutural"] = out["quantidade_dimensoes_estruturais_validas"] / 2
    out["indice_contexto_estrutural_municipal"] = out[
        ["indice_vulnerabilidade_fiscal", "indice_estrutura_vinculos_institucionais"]
    ].mean(axis=1).where(out["quantidade_dimensoes_estruturais_validas"] == 2)

    pncp_start, pncp_end = config["pncp"]["periodo"]
    pncp_period = out[year_col].between(pncp_start, pncp_end)
    source_coverage = out.get("cobertura_pncp_fonte", pd.Series(pd.NA, index=out.index))
    complete_source = source_coverage.eq("completa")
    valid_pncp = pncp_period & complete_source
    for name in ("contratacoes_por_mil_habitantes", "exposicao_contratual_sobre_receita"):
        out.loc[~valid_pncp, name] = np.nan
        out[f"log1p_{name}"] = np.log1p(out[name].where(out[name] >= 0))
    general = []
    for name in ("contratacoes_por_mil_habitantes", "exposicao_contratual_sobre_receita"):
        clipped, _ = winsorize_annual(out, f"log1p_{name}", year_col)
        scored = annual_percentile(clipped, f"log1p_{name}_winsorized", year_col)
        col = f"percentil_pncp_{name}"
        out[col] = scored[f"log1p_{name}_winsorized_percentile"]
        general.append(col)
    out["subindice_intensidade_geral_pncp"] = out[general].mean(axis=1).where(valid_pncp)
    out.loc[~valid_pncp, "proporcao_contratacoes_similares"] = np.nan
    similar = winsorize_annual(out, "proporcao_contratacoes_similares", year_col)[0]
    similar = annual_percentile(similar, "proporcao_contratacoes_similares_winsorized", year_col)
    out["subindice_similaridade_pncp"] = similar["proporcao_contratacoes_similares_winsorized_percentile"].where(valid_pncp)
    out["status_similaridade_pncp"] = pd.Series(pd.NA, index=out.index, dtype="string")
    zero_complete = (pd.to_numeric(out["total_contratacoes"], errors="coerce") == 0) & complete_source & pncp_period
    out.loc[zero_complete, "status_similaridade_pncp"] = "nao_aplicavel_sem_contratacoes"
    out["quantidade_componentes_pncp_validos"] = out[[*general, "subindice_similaridade_pncp"]].notna().sum(axis=1)
    out["cobertura_indice_pncp"] = out["quantidade_componentes_pncp_validos"] / 3
    out["indice_intensidade_contratual_pncp"] = (
        0.5 * out["subindice_intensidade_geral_pncp"] + 0.5 * out["subindice_similaridade_pncp"]
    ).where(out["subindice_intensidade_geral_pncp"].notna() & out["subindice_similaridade_pncp"].notna())
    out["status_pncp_indice"] = np.where(pncp_period, np.where(valid_pncp, "calculado", "indisponivel_cobertura_pncp"), "fora_periodo_configurado")
    out["historico_execucao_transferegov"] = np.nan
    out["status_historico_execucao"] = "indisponivel_dados_transferegov"
    out["ano_referencia_indice"] = out[year_col]
    out["data_corte_indice"] = pd.to_datetime(out[year_col].astype(str) + "-12-31")
    out["status_temporal_indice"] = "descritivo_retrospectivo"
    out["motivo_status_temporal"] = "fotografia_anual_com_fontes_disponibilizadas_apos_o_corte"
    out["apto_analise_descritiva"] = True
    out["apto_predicao_point_in_time"] = False
    out["justificativa_temporal"] = "produto_descritivo_relativo_sem_uso_preditivo"
    out.attrs["config_sha256"] = config_sha256
    band_map = {
        "indice_vulnerabilidade_fiscal": "faixa_vulnerabilidade_fiscal",
        "indice_estrutura_vinculos_institucionais": "faixa_estrutura_vinculos_institucionais",
        "indice_contexto_estrutural_municipal": "faixa_contexto_estrutural",
        "indice_intensidade_contratual_pncp": "faixa_intensidade_contratual_pncp",
    }
    for index_col, band_col in band_map.items():
        band_frame, _ = annual_band(out, index_col, year_col)
        out[band_col] = band_frame[f"{index_col}_faixa"]
    return out


def institutional_sensitivity(frame: pd.DataFrame, year_col: str = "ano") -> pd.DataFrame:
    rows = []
    names = [name for name, _ in INSTITUTIONAL_COMPONENTS]
    for year, group in frame.groupby(year_col, sort=True):
        values = group[names].apply(pd.to_numeric, errors="coerce")
        complete = values.mean(axis=1)
        no_stat = values.drop(columns=["proporcao_pessoal_estatutario"]).mean(axis=1)
        no_sem = values.drop(columns=["proporcao_pessoal_sem_vinculo"]).mean(axis=1)
        rows.append({
            "ano": year,
            "correlacao_estatutario_comissionado": values["proporcao_pessoal_estatutario"].corr(values["proporcao_pessoal_comissionado"], method="spearman"),
            "correlacao_estatutario_sem_vinculo": values["proporcao_pessoal_estatutario"].corr(values["proporcao_pessoal_sem_vinculo"], method="spearman"),
            "correlacao_comissionado_sem_vinculo": values["proporcao_pessoal_comissionado"].corr(values["proporcao_pessoal_sem_vinculo"], method="spearman"),
            "spearman_completa_sem_estatutarios": complete.corr(no_stat, method="spearman"),
            "spearman_completa_sem_sem_vinculo": complete.corr(no_sem, method="spearman"),
            "municipios_mudaram_faixa_sem_estatutarios": int((complete.rank(pct=True) - no_stat.rank(pct=True)).abs().gt(0.25).sum()),
            "municipios_mudaram_faixa_sem_sem_vinculo": int((complete.rank(pct=True) - no_sem.rank(pct=True)).abs().gt(0.25).sum()),
            "percentual_mudaram_faixa_sem_estatutarios": float((complete.rank(pct=True) - no_stat.rank(pct=True)).abs().gt(0.25).mean() * 100),
            "percentual_mudaram_faixa_sem_sem_vinculo": float((complete.rank(pct=True) - no_sem.rank(pct=True)).abs().gt(0.25).mean() * 100),
        })
    return pd.DataFrame(rows)


def build_manifest(frame: pd.DataFrame, input_sha256: str, config_path: str | Path = CONFIG_PATH, final_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    config, config_sha256 = load_config(config_path)
    winsor = {}
    components = [x[0] for x in FISCAL_COMPONENTS + INSTITUTIONAL_COMPONENTS]
    for component in components:
        _, meta = winsorize_annual(frame, component, "ano")
        winsor[component] = {str(k): v for k, v in meta.items()}
    bands = {}
    for col in ("indice_vulnerabilidade_fiscal", "indice_estrutura_vinculos_institucionais", "indice_contexto_estrutural_municipal", "indice_intensidade_contratual_pncp"):
        _, meta = annual_band(frame, col, "ano")
        bands[col] = {str(k): v for k, v in meta.items()}
    manifest = {
        "versao_metodologia_indice": "indice-contexto-municipal-v0",
        "input_sha256": input_sha256,
        "config_sha256": config_sha256,
        "rows": int(len(frame)),
        "municipios": int(frame["codigo_ibge"].nunique()) if "codigo_ibge" in frame else None,
        "anos": sorted(int(x) for x in frame["ano_referencia_indice"].dropna().unique()),
        "aptos": {"analise_descritiva": True, "predicao_point_in_time": False},
        "formulas_direcoes": {"fiscal": config["fiscal"]["componentes"], "institucional": config["institucional"]["componentes"]},
        "pesos": config["pncp"]["pesos"],
        "periodos": {"indice_estrutural": [2020, 2024], "indice_intensidade_contratual_pncp": config["pncp"]["periodo"]},
        "limites_p1_p99": winsor,
        "limites_faixas": bands,
        "cobertura_por_ano": frame.groupby("ano")[['cobertura_fiscal', 'cobertura_institucional', 'cobertura_indice_pncp']].mean().round(6).to_dict(orient="index"),
        "hashes_finais": final_hashes or {},
        "sem_historico_execucao_transferegov": True,
    }
    return manifest


def export_indices(frame: pd.DataFrame, input_sha256: str, output_dir: str | Path) -> dict[str, str]:
    """Exporta somente artefatos analiticos proprios, em ordem deterministica."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    sort_cols = [c for c in ("codigo_ibge", "ano_referencia_indice") if c in frame.columns]
    out = frame.sort_values(sort_cols, kind="mergesort") if sort_cols else frame.copy()
    out = out.reindex(sorted(out.columns), axis=1)
    csv_path = root / "indices_contexto_municipal.csv"
    parquet_path = root / "indices_contexto_municipal.parquet"
    manifest_path = root / "manifesto_indices_contexto.json"
    sensitivity_path = root / "sensibilidade_institucional.csv"
    out.to_csv(csv_path, sep=";", index=False, encoding="utf-8")
    out.to_parquet(parquet_path, index=False)
    sensitivity = institutional_sensitivity(out)
    sensitivity.to_csv(sensitivity_path, sep=";", index=False, encoding="utf-8")
    final_hashes = {
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "parquet_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(build_manifest(out, input_sha256, final_hashes=final_hashes), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        **final_hashes,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "sensitivity_sha256": hashlib.sha256(sensitivity_path.read_bytes()).hexdigest(),
    }
