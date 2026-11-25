"""Reconstrução temporal analítica do Transferegov, sem efeitos operacionais."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config" / "transferegov_historico_temporal.v0.json"
CONTRACT_VERSION = "transferegov-historico-temporal-v0.1.2"


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _semantic_hash(frame: pd.DataFrame, keys: list[str]) -> str:
    value = frame.copy()
    value = value.sort_index(axis=1)
    ordered_keys = [key for key in keys if key in value.columns]
    if ordered_keys:
        value = value.sort_values(ordered_keys, kind="mergesort")
    value = value.reset_index(drop=True)
    return _digest_bytes(pd.util.hash_pandas_object(value, index=False).values.tobytes())


def load_config(path: str | Path | None = None) -> tuple[dict[str, Any], str]:
    config_path = Path(path) if path else DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"configuração temporal ausente: {config_path}")
    raw = config_path.read_bytes()
    config = json.loads(raw.decode("utf-8"))
    required = {"versao_contrato", "periodo", "corte_anual", "maturidade_dias", "regra_dia_365", "regra_dia_366", "modalidades", "faixas_denominador", "metodos_sensibilidade", "parametros_sensibilidade"}
    if not required.issubset(config):
        raise ValueError("configuração temporal incompleta")
    if config["versao_contrato"] != CONTRACT_VERSION or config["periodo"] != [2020, 2024] or config["maturidade_dias"] != 365:
        raise ValueError("configuração temporal divergente do contrato")
    expected_methods = ["taxa_bruta", "taxa_minimo_configurado", "taxa_beta_binomial", "taxa_shrinkage_estadual"]
    if config["metodos_sensibilidade"] != expected_methods:
        raise ValueError("metodos de sensibilidade divergentes do contrato")
    params = config["parametros_sensibilidade"]
    if set(params) != {"minimo_denominador", "beta_alpha", "beta_beta", "shrinkage_k"}:
        raise ValueError("parametros de sensibilidade incompletos")
    if any(float(params[key]) < 0 for key in params) or params["minimo_denominador"] < 1:
        raise ValueError("parametros de sensibilidade invalidos")
    bands = config["faixas_denominador"]
    if not bands or any("nome" not in b or "minimo" not in b or "maximo" not in b for b in bands):
        raise ValueError("faixas de denominador devem ter nome, minimo e maximo")
    digest = _digest_bytes(raw)
    config["_raw_sha256"] = digest
    return config, digest


def _band_series(values: pd.Series, config: dict[str, Any]) -> pd.Series:
    bands = config["faixas_denominador"]
    labels = [b["nome"] for b in bands]
    edges = [-0.5] + [b["maximo"] + 0.5 for b in bands[:-1]] + [float("inf")]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True)


def context_year_for_signature(signature_date: pd.Timestamp, target_year: int) -> int | None:
    if pd.isna(signature_date):
        return None
    if signature_date.year in (target_year - 1, target_year):
        return target_year - 1
    return None


def _as_text(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = frame.copy()
    for column in columns:
        if column in frame:
            frame[column] = frame[column].astype("string")
    return frame


def _parse_date(frame: pd.DataFrame, column: str, *, required: bool = False) -> pd.Series:
    values = pd.to_datetime(frame[column], errors="coerce")
    if required and values.isna().any():
        raise ValueError(f"datas inválidas em {column}")
    return values


def _canonical_instruments(instruments: pd.DataFrame) -> pd.DataFrame:
    out = _as_text(instruments, ["nr_convenio", "id_proposta", "codigo_ibge", "cnpj_proponente"])
    if "nr_convenio" not in out or out["nr_convenio"].isna().any() or out["nr_convenio"].str.strip().eq("").any() or out["nr_convenio"].duplicated().any():
        raise ValueError("instrumentos com identificador ausente ou duplicado")
    if "data_assinatura" not in out:
        raise ValueError("instrumentos sem data_assinatura")
    out["assinatura"] = _parse_date(out, "data_assinatura")
    out["estado_base"] = out["assinatura"].notna().map({True: "disponivel", False: "indisponivel_sem_assinatura"})
    out["codigo_ibge"] = out.get("codigo_ibge", pd.Series(index=out.index, dtype="string")).astype("string")
    if out["codigo_ibge"].isna().any() or ~out["codigo_ibge"].str.fullmatch(r"25\d{5}").all():
        raise ValueError("código IBGE inválido ou fora da PB")
    out["motivo_estado_base"] = out["estado_base"].map({"indisponivel_sem_assinatura": "data_assinatura_ausente"}).fillna(pd.NA)
    return out


def _canonical_events(instruments: pd.DataFrame, disbursements: pd.DataFrame) -> pd.DataFrame:
    if disbursements.empty:
        return pd.DataFrame(columns=["nr_convenio", "id_desembolso", "codigo_ibge", "data_evento", "valor", "posicao_cronologica", "primeiro_desembolso"])
    out = _as_text(disbursements, ["id_desembolso", "nr_convenio", "codigo_ibge"])
    if "codigo_ibge" not in out:
        out["codigo_ibge"] = pd.Series(pd.NA, index=out.index, dtype="string")
    if "id_desembolso" not in out or out["id_desembolso"].isna().any() or out["id_desembolso"].str.strip().eq("").any() or out["id_desembolso"].duplicated().any():
        raise ValueError("desembolsos com id duplicado")
    if out["nr_convenio"].isna().any() or out["nr_convenio"].str.strip().eq("").any():
        raise ValueError("desembolso sem nr_convenio")
    if not set(out["nr_convenio"].dropna()).issubset(set(instruments["nr_convenio"].dropna())):
        raise ValueError("desembolso órfão")
    out["data_evento"] = _parse_date(out, "data_desembolso", required=True)
    out["valor"] = pd.to_numeric(out["valor_desembolsado"], errors="coerce")
    if out["valor"].lt(0).any() or out["valor"].isna().any():
        raise ValueError("valor de desembolso negativo ou inválido")
    out = out[out["valor"].gt(0)].copy()
    signed = instruments[["nr_convenio", "assinatura"]]
    out = out.merge(signed, on="nr_convenio", how="left", validate="many_to_one")
    if (out["data_evento"] < out["assinatura"]).any():
        raise ValueError("desembolso anterior à assinatura")
    instrument_codes = instruments.set_index("nr_convenio")["codigo_ibge"]
    expected = out["nr_convenio"].map(instrument_codes)
    provided = out["codigo_ibge"]
    if provided.notna().any() and (provided.notna() & provided.ne(expected)).any():
        raise ValueError("código IBGE do desembolso diverge do instrumento")
    out["codigo_ibge"] = provided.fillna(expected)
    out = out.sort_values(["nr_convenio", "data_evento", "id_desembolso"], kind="mergesort")
    out["posicao_cronologica"] = out.groupby("nr_convenio").cumcount() + 1
    out["primeiro_desembolso"] = out["posicao_cronologica"].eq(1)
    return out[["nr_convenio", "id_desembolso", "codigo_ibge", "data_evento", "valor", "posicao_cronologica", "primeiro_desembolso"]]


def _instrument_snapshots(instruments: pd.DataFrame, events: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    years = range(config["periodo"][0], config["periodo"][1] + 1)
    first = events[events["primeiro_desembolso"]].groupby("nr_convenio", as_index=False)["data_evento"].min().rename(columns={"data_evento": "primeiro_desembolso_completo"})
    base = instruments.merge(first, on="nr_convenio", how="left")
    rows: list[pd.DataFrame] = []
    for year in years:
        cut = pd.Timestamp(year=year, month=12, day=31)
        current = base[base["assinatura"].notna() & base["assinatura"].le(cut)].copy()
        current["ano"] = year
        current["data_corte"] = cut
        current["data_maturidade_365"] = current["assinatura"] + pd.to_timedelta(config["maturidade_dias"], unit="D")
        observed = current["primeiro_desembolso_completo"].where(current["primeiro_desembolso_completo"].le(cut))
        current["primeiro_desembolso_observado_ate_corte"] = observed
        current["dias_ate_primeiro_desembolso_observado"] = (observed - current["assinatura"]).dt.days
        current["evento_sem_desembolso_positivo_ate_365d"] = pd.Series(pd.NA, index=current.index, dtype="boolean")
        current["motivo_censura"] = pd.NA
        current["status_temporal"] = "apta_data_evento"
        before_cut = current["primeiro_desembolso_observado_ate_corte"].notna()
        mature = current["data_maturidade_365"].le(cut)
        current["estado_maturidade"] = "censurado_365_incompleto"
        current.loc[mature & before_cut & current["dias_ate_primeiro_desembolso_observado"].le(365), "estado_maturidade"] = "no_prazo_365"
        current.loc[mature & before_cut & current["dias_ate_primeiro_desembolso_observado"].gt(365), "estado_maturidade"] = "atrasado_apos_365"
        current.loc[mature & ~before_cut, "estado_maturidade"] = "sem_desembolso_ate_maturidade"
        current.loc[current["estado_maturidade"].eq("censurado_365_incompleto"), "motivo_censura"] = "maturidade_posterior_ao_corte"
        current.loc[current["estado_maturidade"].eq("no_prazo_365"), "evento_sem_desembolso_positivo_ate_365d"] = False
        current.loc[current["estado_maturidade"].isin(["atrasado_apos_365", "sem_desembolso_ate_maturidade"]), "evento_sem_desembolso_positivo_ate_365d"] = True
        current["desfecho_365"] = current["evento_sem_desembolso_positivo_ate_365d"]
        rows.append(current)
    result = pd.concat(rows, ignore_index=True)
    result = result.drop(columns=["primeiro_desembolso_completo"], errors="ignore")
    result["desfecho_365"] = result["desfecho_365"].astype("boolean")
    result["versao_contrato"] = CONTRACT_VERSION
    return result


def _validate_special(frame: pd.DataFrame, kind: str, identifier: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = _as_text(frame, [identifier, "codigo_ibge", "cnpj_beneficiario", "id_plano_acao", "id_empenho", "id_dh", "id_op_ob"])
    if identifier not in out or out[identifier].isna().any() or out[identifier].str.strip().eq("").any() or out[identifier].duplicated().any():
        raise ValueError(f"{kind} com identificador ausente ou duplicado")
    if "codigo_ibge" not in out or out["codigo_ibge"].isna().any() or ~out["codigo_ibge"].str.fullmatch(r"25\d{5}").all():
        raise ValueError(f"{kind} com código IBGE inválido")
    date_columns = [c for c in out.columns if c.startswith("data_")]
    for column in date_columns:
        parsed = pd.to_datetime(out[column], errors="coerce")
        if parsed.isna().any() and out[column].notna().any():
            raise ValueError(f"{kind} com data inválida")
    value_columns = [c for c in out.columns if c.startswith("valor_")]
    for column in value_columns:
        values = pd.to_numeric(out[column], errors="coerce")
        if values.isna().any() or values.lt(0).any():
            raise ValueError(f"{kind} com valor inválido")
    out["modalidade"] = "especial"
    out["tipo_evento"] = kind
    out["id_evento"] = out[identifier]
    date_candidates = [c for c in out.columns if c.startswith("data_")]
    out["data_evento"] = pd.to_datetime(out[date_candidates[0]], errors="coerce") if date_candidates else pd.NaT
    return out


def _aggregate(snapshots: pd.DataFrame, municipalities: pd.DataFrame, config: dict[str, Any], coverage_complete: bool) -> pd.DataFrame:
    muni = _as_text(municipalities, ["codigo_ibge"])[["codigo_ibge"]].drop_duplicates() if not municipalities.empty else snapshots[["codigo_ibge"]].drop_duplicates()
    muni["codigo_ibge"] = muni["codigo_ibge"].astype("string")
    years = pd.DataFrame({"ano": list(range(config["periodo"][0], config["periodo"][1] + 1))})
    grid = muni.assign(_key=1).merge(years.assign(_key=1), on="_key").drop(columns="_key")
    s = snapshots.copy()
    s["instrumentos_maduros"] = s["data_maturidade_365"].le(s["data_corte"])
    s["no_prazo"] = s["estado_maturidade"].eq("no_prazo_365")
    s["atrasados"] = s["estado_maturidade"].eq("atrasado_apos_365") | s["estado_maturidade"].eq("sem_desembolso_ate_maturidade")
    s["censurados"] = s["estado_maturidade"].eq("censurado_365_incompleto")
    grouped = s.groupby(["codigo_ibge", "ano"], as_index=False).agg(instrumentos_elegiveis=("nr_convenio", "nunique"), instrumentos_maduros=("instrumentos_maduros", "sum"), no_prazo_365=("no_prazo", "sum"), atrasados_365=("atrasados", "sum"), censurados_365=("censurados", "sum"), instrumentos_assinados_coorte=("nr_convenio", lambda x: int((s.loc[x.index, "assinatura"].dt.year == s.loc[x.index, "ano"]).sum())))
    s["ano_assinatura"] = s["assinatura"].dt.year

    def summarize(selection: pd.DataFrame, suffix: str) -> pd.DataFrame:
        if selection.empty:
            return pd.DataFrame(columns=["codigo_ibge", "ano", f"denominador_maduro{suffix}", f"atrasados_365{suffix}", f"censurados_365{suffix}"])
        return selection.groupby(["codigo_ibge", "ano"], as_index=False).agg(**{
            f"denominador_maduro{suffix}": ("instrumentos_maduros", "sum"),
            f"atrasados_365{suffix}": ("atrasados", "sum"),
            f"censurados_365{suffix}": ("censurados", "sum"),
        })

    cohort = summarize(s[s["ano_assinatura"] == s["ano"]], "_coorte")
    window = s[s["ano_assinatura"].between(s["ano"] - 2, s["ano"])].copy()
    window = summarize(window, "_janela_3a")
    out = grid.merge(grouped, on=["codigo_ibge", "ano"], how="left")
    out = out.merge(cohort, on=["codigo_ibge", "ano"], how="left").merge(window, on=["codigo_ibge", "ano"], how="left")
    counts = ["instrumentos_elegiveis", "instrumentos_maduros", "no_prazo_365", "atrasados_365", "censurados_365", "instrumentos_assinados_coorte"]
    for c in counts:
        if coverage_complete:
            out[c] = out[c].fillna(0).astype("int64")
        else:
            out[c] = out[c].astype("Float64")
    out["denominador_maduro"] = out["instrumentos_maduros"]
    out["taxa_atraso_365_acumulada"] = out["atrasados_365"].div(out["denominador_maduro"].where(out["denominador_maduro"].gt(0)))
    for c in ["denominador_maduro_coorte", "atrasados_365_coorte", "censurados_365_coorte", "denominador_maduro_janela_3a", "atrasados_365_janela_3a", "censurados_365_janela_3a"]:
        if coverage_complete:
            out[c] = out[c].fillna(0).astype("int64")
        else:
            out[c] = out[c].astype("Float64")
    out["taxa_atraso_365_coorte"] = out["atrasados_365_coorte"].div(out["denominador_maduro_coorte"].where(out["denominador_maduro_coorte"].gt(0)))
    out["taxa_atraso_365_janela_3a"] = out["atrasados_365_janela_3a"].div(out["denominador_maduro_janela_3a"].where(out["denominador_maduro_janela_3a"].gt(0)))
    out["status_cobertura"] = "confirmada" if coverage_complete else "incompleta"
    out["motivo_cobertura"] = pd.NA if coverage_complete else "contrato_de_cobertura_nao_confirmado"
    out["cobertura"] = out["denominador_maduro"].gt(0) if coverage_complete else pd.NA
    return out.sort_values(["codigo_ibge", "ano"]).reset_index(drop=True)


def build_temporal_package(instruments: pd.DataFrame, disbursements: pd.DataFrame, special_plans: pd.DataFrame, special_empenhos: pd.DataFrame, special_payments: pd.DataFrame, municipalities: pd.DataFrame, config: dict[str, Any], gold_version: str, gold_manifest_sha: str, coverage_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    inst = _canonical_instruments(instruments)
    events = _canonical_events(inst, disbursements)
    snapshots = _instrument_snapshots(inst, events, config)
    plans = _validate_special(special_plans, "plano", "id_plano_acao")
    empenhos = _validate_special(special_empenhos, "empenho", "id_empenho")
    payments = _validate_special(special_payments, "pagamento", "id_op_ob")
    if not empenhos.empty and "id_plano_acao" in empenhos and not set(empenhos["id_plano_acao"]).issubset(set(plans.get("id_plano_acao", pd.Series(dtype="string")))):
        raise ValueError("empenho especial referencia plano inexistente")
    if not payments.empty and "id_empenho" in payments and not set(payments["id_empenho"]).issubset(set(empenhos.get("id_empenho", pd.Series(dtype="string")))):
        raise ValueError("pagamento especial referencia empenho inexistente")
    specials = pd.concat([plans, empenhos, payments], ignore_index=True, sort=False)
    if not specials.empty:
        specials = specials.sort_values(["tipo_evento", "id_evento", "codigo_ibge", "data_evento"], kind="mergesort").reset_index(drop=True)
    coverage_complete = bool(coverage_contract and all(coverage_contract.get(k, False) for k in ("universo_municipal_completo", "artefato_completo", "modalidade_coberta", "consulta_confirmada")))
    annual = _aggregate(snapshots, municipalities, config, coverage_complete)
    sensitivity = annual[["codigo_ibge", "ano", "denominador_maduro", "atrasados_365", "taxa_atraso_365_acumulada"]].copy()
    sensitivity["taxa_bruta"] = sensitivity["taxa_atraso_365_acumulada"]
    params = config["parametros_sensibilidade"]
    minimum = params["minimo_denominador"]
    alpha = params["beta_alpha"]
    beta = params["beta_beta"]
    k = params["shrinkage_k"]
    sensitivity["taxa_minimo_configurado"] = sensitivity["taxa_bruta"].where(sensitivity["denominador_maduro"].ge(minimum))
    sensitivity["taxa_beta_binomial"] = (sensitivity["atrasados_365"] + alpha) / (sensitivity["denominador_maduro"] + alpha + beta)
    totals = sensitivity.groupby("ano")[["atrasados_365", "denominador_maduro"]].sum()
    state = totals["atrasados_365"].div(totals["denominador_maduro"].where(totals["denominador_maduro"].gt(0))).rename("media_estadual")
    sensitivity = sensitivity.join(state, on="ano")
    sensitivity["taxa_shrinkage_estadual"] = ((sensitivity["denominador_maduro"] / (sensitivity["denominador_maduro"] + k)) * sensitivity["taxa_bruta"] + (k / (sensitivity["denominador_maduro"] + k)) * sensitivity["media_estadual"]).where(sensitivity["denominador_maduro"].gt(0))
    sensitivity["faixa_denominador"] = _band_series(sensitivity["denominador_maduro"], config)
    sensitivity["rank_taxa_bruta"] = sensitivity.groupby("ano")["taxa_bruta"].rank(method="average", ascending=False)
    for method in ["taxa_bruta", "taxa_minimo_configurado", "taxa_beta_binomial", "taxa_shrinkage_estadual"]:
        rank_col = f"rank_{method}"
        sensitivity[rank_col] = sensitivity.groupby("ano")[method].rank(method="average", ascending=False)
        sensitivity[f"municipios_incluidos_{method}"] = sensitivity.groupby("ano")[method].transform("count")
        sensitivity[f"municipios_excluidos_{method}"] = sensitivity.groupby("ano")[method].transform("size") - sensitivity[f"municipios_incluidos_{method}"]
        sensitivity[f"diferenca_absoluta_{method}"] = (sensitivity[method] - sensitivity["taxa_bruta"]).abs()
        sensitivity[f"variacao_posicao_{method}"] = sensitivity[rank_col] - sensitivity["rank_taxa_bruta"]
        sensitivity[f"quantidade_posicoes_alteradas_{method}"] = pd.Series(0, index=sensitivity.index, dtype="Int64")
        sensitivity[f"percentual_posicoes_alteradas_{method}"] = pd.Series(pd.NA, index=sensitivity.index, dtype="Float64")
        for year, group in sensitivity.groupby("ano"):
            valid = group[["rank_taxa_bruta", rank_col]].dropna()
            changed = int((valid["rank_taxa_bruta"] != valid[rank_col]).sum()) if method != "taxa_bruta" else 0
            sensitivity.loc[group.index, f"quantidade_posicoes_alteradas_{method}"] = changed
            sensitivity.loc[group.index, f"percentual_posicoes_alteradas_{method}"] = (changed / len(valid) * 100) if len(valid) else pd.NA
        spearman = {}
        for year, group in sensitivity.groupby("ano"):
            spearman[year] = group["taxa_bruta"].corr(group[method], method="spearman")
        sensitivity[f"spearman_{method}_vs_bruta"] = sensitivity["ano"].map(spearman)
    method_summary = {}
    for method in ["taxa_bruta", "taxa_minimo_configurado", "taxa_beta_binomial", "taxa_shrinkage_estadual"]:
        method_summary[method] = {}
        for year, group in sensitivity.groupby("ano"):
            valid = group[method].notna()
            method_summary[method][str(year)] = {
                "municipios_incluidos": int(valid.sum()),
                "municipios_excluidos": int((~valid).sum()),
                "spearman_vs_bruta": None if sensitivity.loc[valid.index[valid], method].nunique() < 2 else float(group["taxa_bruta"].corr(group[method], method="spearman")),
            }
    audit = inst[inst["estado_base"].ne("disponivel")].copy()
    payload = {"instrumentos": snapshots, "instrumentos_auditoria": audit, "eventos_financeiros": events, "especiais": specials, "municipio_ano_historico": annual, "censura_municipio_ano": annual[["codigo_ibge", "ano", "censurados_365", "cobertura"]].copy(), "sensibilidade_maturidade": sensitivity, "elegibilidade_variaveis": pd.DataFrame([{"variavel": "historico_desembolso_365", "status": "apta_data_evento"}, {"variavel": "situacao_atual", "status": "indisponivel"}])}
    semantic_config = {k: v for k, v in config.items() if k != "_raw_sha256"}
    cfg_digest = _digest_bytes(json.dumps(semantic_config, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    input_hashes = {
        "instrumentos": _semantic_hash(instruments, ["nr_convenio", "codigo_ibge"]),
        "desembolsos": _semantic_hash(disbursements, ["nr_convenio", "id_desembolso"]),
        "planos": _semantic_hash(special_plans, ["id_plano_acao"]),
        "empenhos": _semantic_hash(special_empenhos, ["id_empenho"]),
        "pagamentos": _semantic_hash(special_payments, ["id_op_ob"]),
        "universo_municipal": _semantic_hash(municipalities, ["codigo_ibge"]),
        "configuracao": cfg_digest,
    }
    version_material = json.dumps({"gold_version": gold_version, "gold_manifest_sha": gold_manifest_sha, "contract": CONTRACT_VERSION, "config": cfg_digest, "maturity": config["maturidade_dias"]}, sort_keys=True).encode("utf-8")
    payload["metadata"] = {
        "versao_analitica": _digest_bytes(version_material)[:20],
        "gold_version": gold_version,
        "gold_manifest_sha": gold_manifest_sha,
        "config_sha256": cfg_digest,
        "config_raw_sha256": config.get("_raw_sha256"),
        "versao_contrato": CONTRACT_VERSION,
        "periodo": config["periodo"],
        "cortes": "31/12 de cada ano",
        "modalidades": config["modalidades"],
        "regras_maturidade": {"dias": config["maturidade_dias"], "dia_365": config["regra_dia_365"], "dia_366": config["regra_dia_366"], "valor": "> 0"},
        "formulas": {"taxa_atraso_365": "atrasados_365 / denominador_maduro", "beta_binomial": f"(atrasados + {alpha}) / (maduros + {alpha} + {beta})", "shrinkage": f"n/(n+{k})*taxa + {k}/(n+{k})*media_estadual"},
        "parametros_sensibilidade": config["parametros_sensibilidade"],
        "aptidao": "descritiva; não preditiva",
        "aptidao_tabelas": {"instrumentos": "descritiva_temporal", "eventos_financeiros": "descritiva_temporal", "especiais": "descritiva_temporal", "municipio_ano_historico": "descritiva_nao_preditiva", "sensibilidade_maturidade": "diagnostica"},
        "hashes_entradas_semanticos": input_hashes,
        "contrato_cobertura": coverage_contract or {},
        "definicao_coorte": "instrumentos cuja data_assinatura pertence ao ano de referência",
        "definicao_janela_3a": "instrumentos assinados entre ano-2 e ano, avaliados somente se maduros no corte",
        "cobertura_por_ano_visao": {
            str(year): {
                "status": str(group["status_cobertura"].iloc[0]),
                "linhas": int(len(group)),
                "municipios_com_cobertura": int(group["cobertura"].astype("boolean").fillna(False).sum()),
            }
            for year, group in annual.groupby("ano")
        },
        "censurados_por_ano": annual.groupby("ano")["censurados_365"].sum(min_count=1).to_dict(),
        "distribuicao_denominadores": {f"{ano}:{denominador}": int(total) for (ano, denominador), total in annual.groupby(["ano", "denominador_maduro"], dropna=False).size().items()},
        "sensibilidade_por_metodo_ano": method_summary,
        "chaves_tabelas": {
            "instrumentos": ["nr_convenio", "ano"],
            "eventos_financeiros": ["id_desembolso"],
            "especiais": ["tipo_evento", "id_evento"],
            "municipio_ano_historico": ["codigo_ibge", "ano"],
            "censura_municipio_ano": ["codigo_ibge", "ano"],
            "sensibilidade_maturidade": ["codigo_ibge", "ano"],
        },
    }
    return payload


def _write_temporal_package_contents(package: dict[str, Any], destination: str | Path) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    hashes = {}
    sort_keys = {
        "instrumentos_auditoria": ["codigo_ibge", "nr_convenio"],
        "instrumentos": ["codigo_ibge", "ano", "nr_convenio"],
        "eventos_financeiros": ["codigo_ibge", "nr_convenio", "data_evento", "id_desembolso"],
        "especiais": ["tipo_evento", "id_evento", "codigo_ibge", "data_evento"],
        "municipio_ano_historico": ["codigo_ibge", "ano"],
        "censura_municipio_ano": ["codigo_ibge", "ano"],
        "sensibilidade_maturidade": ["codigo_ibge", "ano"],
    }
    for name in ["instrumentos", "instrumentos_auditoria", "eventos_financeiros", "especiais", "municipio_ano_historico", "censura_municipio_ano", "sensibilidade_maturidade"]:
        path = root / f"{name}.parquet"
        frame = package[name].copy()
        keys = [k for k in sort_keys[name] if k in frame.columns]
        if keys:
            frame = frame.sort_values(keys, kind="mergesort").reset_index(drop=True)
        frame.sort_index(axis=1).to_parquet(path, index=False)
        hashes[name] = _digest_bytes(path.read_bytes())
    package["elegibilidade_variaveis"].to_csv(root / "elegibilidade_variaveis.csv", index=False, encoding="utf-8")
    hashes["elegibilidade_variaveis"] = _digest_bytes((root / "elegibilidade_variaveis.csv").read_bytes())
    manifest = {**package["metadata"], "hashes_saidas": hashes, "linhas": {name: int(len(package[name])) for name in hashes}, "tempo_execucao_segundos": round(time.perf_counter() - started, 6), "aptidao_descritiva": True, "aptidao_preditiva": False, "caminhos_absolutos": False}
    (root / "manifesto.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return manifest


def write_temporal_package(package: dict[str, Any], destination: str | Path) -> dict[str, Any]:
    root = Path(destination)
    existing_manifest_path = root / "manifesto.json"
    if existing_manifest_path.exists():
        with tempfile.TemporaryDirectory() as temporary:
            candidate = _write_temporal_package_contents(package, temporary)
            existing = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
            if existing.get("hashes_saidas") != candidate.get("hashes_saidas"):
                raise ValueError("versão analítica existente diverge; sobrescrita bloqueada")
            return existing
    return _write_temporal_package_contents(package, root)


def write_versioned_temporal_package(package: dict[str, Any], analytic_root: str | Path) -> Path:
    destination = Path(analytic_root) / "versoes" / package["metadata"]["versao_analitica"]
    write_temporal_package(package, destination)
    return destination
