"""Treina e avalia Regressão Logística e KNN na coorte ObrasGov congelada."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, balanced_accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import k_nearest_neighbors, regressao_logistica


ROOT = Path(__file__).resolve().parents[2]
MODELOS = {
    "regressao_logistica": ("Regressão Logística", regressao_logistica.criar, regressao_logistica.GRADE),
    "k_nearest_neighbors": ("K-Nearest Neighbors", k_nearest_neighbors.criar, k_nearest_neighbors.GRADE),
}


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def carregar(base_path: Path, particoes_path: Path, config: dict) -> pd.DataFrame:
    """Carrega somente os snapshots esperados e confere os cortes temporais."""
    if sha256(base_path) != config["sha256_base"]:
        raise ValueError("Hash da base ObrasGov divergente.")
    if sha256(particoes_path) != config["sha256_particoes"]:
        raise ValueError("Hash do CSV de partições ObrasGov divergente.")
    base, cortes = pd.read_parquet(base_path), pd.read_csv(particoes_path)
    id_col, alvo = config["coluna_id"], config["alvo"]
    flags = list(config["particoes"].values())
    obrigatorias = {id_col, alvo, config["coluna_grupo"], *flags, *config["preditores_numericos"]}
    ausentes = sorted(obrigatorias - set(base.columns))
    if ausentes:
        raise ValueError("Colunas ausentes: " + ", ".join(ausentes))
    esquerda = base[[id_col, *flags]].copy().astype({id_col: str})
    direita = cortes[[id_col, *flags]].copy().astype({id_col: str})
    comparacao = esquerda.merge(direita, on=id_col, how="outer", suffixes=("_base", "_csv"), indicator=True)
    if not comparacao["_merge"].eq("both").all():
        raise ValueError("IDs da base e do CSV de partições divergem.")
    if any(not comparacao[f"{flag}_base"].eq(comparacao[f"{flag}_csv"]).all() for flag in flags):
        raise ValueError("Flags de partição divergentes entre base e CSV.")
    return base


def criar_pipeline(nome: str, config: dict) -> Pipeline:
    """Mantém imputação e escala dentro do ajuste para impedir vazamento."""
    preparo = ColumnTransformer([
        ("numericas", Pipeline([
            ("imputar", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("escalar", StandardScaler()),
        ]), config["preditores_numericos"]),
    ], remainder="drop")
    _, fabrica, _ = MODELOS[nome]
    return Pipeline([("preparo", preparo), ("modelo", fabrica(config["random_state"]))])


def metricas(y: pd.Series, probabilidade: np.ndarray, limiar: float) -> dict:
    y = y.astype(int).to_numpy()
    prevista = (probabilidade >= limiar).astype(int)
    return {
        "n": len(y), "classe_0": int((y == 0).sum()), "classe_1": int((y == 1).sum()),
        "acuracia_balanceada": float(balanced_accuracy_score(y, prevista)),
        "roc_auc": float(roc_auc_score(y, probabilidade)),
        "average_precision": float(average_precision_score(y, probabilidade)),
        "f1": float(f1_score(y, prevista, zero_division=0)),
    }


def folds_cv(x: pd.DataFrame, y: pd.Series, grupos: pd.Series, seed: int):
    divisao = StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=seed)
    folds = list(divisao.split(x, y, grupos))
    validos = [(t, v) for t, v in folds if y.iloc[t].nunique() == 2 and y.iloc[v].nunique() == 2]
    if len(validos) < 2:
        raise ValueError("Menos de dois folds municipais com ambas as classes.")
    return validos


def executar(base: pd.DataFrame, config: dict, destino: Path) -> pd.DataFrame:
    destino.mkdir(parents=True, exist_ok=True)
    alvo, grupo = config["alvo"], config["coluna_grupo"]
    features, partes = config["preditores_numericos"], config["particoes"]
    desenvolvimento = base.loc[base[partes["treino"]]].reset_index(drop=True)
    validacao = base.loc[base[partes["validacao"]]].reset_index(drop=True)
    final = base.loc[base[partes["treino_final"]]].reset_index(drop=True)
    teste = base.loc[base[partes["teste"]]].reset_index(drop=True)
    if any(quadro[alvo].nunique() != 2 for quadro in (desenvolvimento, validacao, final, teste)):
        raise ValueError("Toda partição deve conter as duas classes para esta execução.")
    folds = folds_cv(desenvolvimento[features], desenvolvimento[alvo].astype(int), desenvolvimento[grupo], config["random_state"])
    linhas, auditoria = [], {"folds_cv": len(folds), "modelos": {}}
    for chave, (nome, fabrica, grade) in MODELOS.items():
        busca = GridSearchCV(criar_pipeline(chave, config), grade, scoring="average_precision", cv=folds, n_jobs=1, refit=True)
        busca.fit(desenvolvimento[features], desenvolvimento[alvo].astype(int))
        melhor = busca.best_estimator_
        prob_validacao = melhor.predict_proba(validacao[features])[:, list(melhor.classes_).index(1)]
        linhas.append({"modelo": chave, "nome": nome, "particao": "validacao_2023", "status_ajuste": "estimado",
                       **metricas(validacao[alvo], prob_validacao, config["limiar_classificacao"])})
        melhor.fit(final[features], final[alvo].astype(int))
        prob_teste = melhor.predict_proba(teste[features])[:, list(melhor.classes_).index(1)]
        linhas.append({"modelo": chave, "nome": nome, "particao": "teste_2024", "status_ajuste": "estimado",
                       **metricas(teste[alvo], prob_teste, config["limiar_classificacao"])})
        pd.DataFrame({config["coluna_id"]: teste[config["coluna_id"]], "y_real": teste[alvo],
                      "probabilidade": prob_teste, "y_previsto": (prob_teste >= config["limiar_classificacao"]).astype(int)}).to_csv(
                          destino / f"predicoes_{chave}_teste_2024.csv", index=False, encoding="utf-8-sig")
        joblib.dump(melhor, destino / f"{chave}.joblib")
        auditoria["modelos"][chave] = {"melhores_parametros": busca.best_params_, "ap_cv": float(busca.best_score_)}
    tabela = pd.DataFrame(linhas)
    tabela.to_csv(destino / "metricas.csv", index=False, encoding="utf-8-sig")
    tabela[tabela.particao.eq("teste_2024")].to_csv(destino / "quadro_comparacao_2024.csv", index=False, encoding="utf-8-sig")
    (destino / "auditoria_execucao.json").write_text(json.dumps(auditoria, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tabela


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "dados/modelagem/e05_revisao/principal.parquet")
    parser.add_argument("--particoes", type=Path, default=ROOT / "dados/modelagem/e05_revisao/principal_particoes.csv")
    parser.add_argument("--config", type=Path, default=ROOT / "config.modelos_obrasgov.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/modelos_obrasgov")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(executar(carregar(args.base, args.particoes, config), config, args.output_dir).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
