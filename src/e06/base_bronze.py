"""Reconstrói a matriz supervisionada da E06 a partir do Bronze municipal da PB."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.etl_municipal.fontes import transferegov_discricionarias as fonte

from .dados import ALVO, CONTAGENS

HORIZONTE = pd.Timedelta(days=365)
CORTE = pd.Timestamp("2024-12-31")
ORIGEM_TREINO = pd.Timestamp("2008-01-01")
INICIO_VALIDACAO = pd.Timestamp("2020-01-01")
INICIO_TESTE = pd.Timestamp("2022-01-01")
IDENTIDADE = ["nr_convenio", "codigo_ibge", "data_assinatura"]
COLUNAS = [
    *IDENTIDADE, "data_previsao", "split", "ano_origem", "modalidade", *CONTAGENS,
    "valor_global_assinatura", ALVO,
]


@dataclass
class BaseReconstruida:
    partes: dict[str, pd.DataFrame]
    prospectivo: pd.DataFrame
    auditoria: dict


def rotular(instrumentos, eventos, corte):
    """Só rotula instrumentos cuja janela inteira terminou no corte declarado."""
    fim = instrumentos["data_assinatura"] + HORIZONTE
    vinculos = eventos.merge(instrumentos[IDENTIDADE], on=["nr_convenio", "codigo_ibge"],
                            validate="many_to_one")
    dias = vinculos["data_desembolso"] - vinculos["data_assinatura"]
    no_prazo = ((dias >= pd.Timedelta(0)) & (dias <= HORIZONTE)
                & vinculos["data_desembolso"].le(corte)
                & vinculos["valor_desembolsado"].gt(0))
    recebidos = vinculos.loc[no_prazo, "nr_convenio"]
    alvo = (~instrumentos["nr_convenio"].isin(recebidos)).astype("boolean")
    return alvo.where(fim.le(corte), pd.NA)


def _acumulado_antes(consultas, datas, valores):
    posicoes = np.searchsorted(datas.to_numpy(dtype="datetime64[ns]"),
                               consultas.to_numpy(dtype="datetime64[ns]"), side="left")
    somas = np.concatenate(([0], np.cumsum(valores)))
    return posicoes, somas[posicoes]


def historico_na_assinatura(instrumentos, eventos, corte):
    """Usa somente maturidades e eventos estritamente anteriores ao dia da assinatura."""
    anteriores = instrumentos.loc[instrumentos[ALVO].notna()].assign(
        maturidade=lambda f: f["data_assinatura"] + HORIZONTE
    ).sort_values("maturidade")
    eventos = eventos.merge(instrumentos[IDENTIDADE], on=["nr_convenio", "codigo_ibge"],
                            validate="many_to_one")
    eventos = eventos.loc[
        eventos["data_desembolso"].ge(eventos["data_assinatura"])
        & eventos["data_desembolso"].le(corte)
        & eventos["valor_desembolsado"].gt(0)
    ].sort_values("data_desembolso")
    maturidades = dict(tuple(anteriores.groupby("codigo_ibge", sort=False)))
    financeiros = dict(tuple(eventos.groupby("codigo_ibge", sort=False)))
    quadros = []
    for municipio, grupo in instrumentos.groupby("codigo_ibge", sort=False):
        m = maturidades.get(municipio, anteriores.iloc[:0])
        e = financeiros.get(municipio, eventos.iloc[:0])
        maduros, atrasados = _acumulado_antes(grupo["data_assinatura"], m["maturidade"],
                                              m[ALVO].to_numpy(dtype=int))
        numero_eventos, centavos = _acumulado_antes(
            grupo["data_assinatura"], e["data_desembolso"],
            np.rint(e["valor_desembolsado"].to_numpy(dtype=float) * 100).astype(np.int64),
        )
        quadros.append(pd.DataFrame(dict(zip(CONTAGENS, (maduros, atrasados, numero_eventos, centavos / 100))),
                                    index=grupo.index))
    return pd.concat(quadros).reindex(instrumentos.index)


def construir(raiz: Path) -> BaseReconstruida:
    """Verifica SHA-256 do extrato Bronze, reutiliza a transformação Silver e congela as linhas."""
    arquivos = fonte.verificar(raiz)
    silver = fonte.transformar(arquivos)
    origem = silver["silver/transferegov_instrumentos"]
    eventos = silver["silver/transferegov_desembolsos"]
    carga = pd.to_datetime(origem["data_carga"].unique(), format="%d/%m/%Y %H:%M:%S")
    if len(carga) != 1 or carga[0].normalize() <= CORTE:
        raise ValueError("A reconstrução exige uma carga única posterior ao corte E06.")
    coorte = origem.loc[origem["data_assinatura"].between(ORIGEM_TREINO, CORTE),
                        [*IDENTIDADE, "modalidade", "valor_global_assinatura"]].copy()
    if coorte.empty or coorte.isna().any().any() or coorte["nr_convenio"].duplicated().any():
        raise ValueError("Coorte Bronze vazia, incompleta ou com instrumentos duplicados.")
    coorte[ALVO] = rotular(coorte, eventos, CORTE)
    coorte = coorte.join(historico_na_assinatura(coorte, eventos, CORTE))
    coorte["ano_origem"] = coorte["data_assinatura"].dt.year
    coorte["data_previsao"] = coorte["data_assinatura"]
    coorte["split"] = np.select(
        [coorte[ALVO].isna(), coorte["data_assinatura"].lt(INICIO_VALIDACAO),
         coorte["data_assinatura"].lt(INICIO_TESTE)],
        ["censored", "train", "validation"], default="test",
    )
    partes = {nome: parte[COLUNAS].reset_index(drop=True)
              for nome, parte in coorte.groupby("split", sort=False)}
    censurados = partes.pop("censored")
    prospectivo = censurados.assign(**{ALVO: rotular(censurados, eventos, carga[0].normalize())})
    auditoria = {
        "carga": carga[0].isoformat(), "corte": CORTE.date().isoformat(),
        "bronze_sha256": {nome: caminho.parent.name for nome, caminho in arquivos.items()},
        "linhas_silver_instrumentos": len(origem), "linhas_silver_desembolsos": len(eventos),
        "linhas": {nome: len(parte) for nome, parte in partes.items()},
        "censurados": len(censurados), "prospectivos_maduros": int(prospectivo[ALVO].notna().sum()),
    }
    return BaseReconstruida(partes, prospectivo, auditoria)


def comparar_pacote(partes, congelado):
    """Compara sem usar o pacote congelado para montar o histórico ou o alvo."""
    relatorio = {}
    for nome, reconstruida in partes.items():
        referencia = congelado[nome]
        chaves = "nr_convenio"
        uniao = reconstruida.merge(referencia, on=chaves, how="outer", indicator=True,
                                   suffixes=("_bronze", "_pacote"), validate="one_to_one")
        pares = uniao.loc[uniao["_merge"].eq("both")]
        divergencias = {}
        for coluna in (coluna for coluna in COLUNAS if coluna != chaves):
            esquerda, direita = (pares[f"{coluna}_{sufixo}"] for sufixo in ("bronze", "pacote"))
            if coluna in {"historico_valor_desembolsado", "valor_global_assinatura"}:
                iguais = np.isclose(esquerda.astype(float), direita.astype(float), rtol=0, atol=0.005)
            else:
                iguais = esquerda.eq(direita).fillna(False)
            divergencias[coluna] = int((~iguais).sum())
        relatorio[nome] = {"n_em_comum": len(pares),
                          "so_bronze": int(uniao["_merge"].eq("left_only").sum()),
                          "so_pacote": int(uniao["_merge"].eq("right_only").sum()),
                          "divergencias": divergencias}
    return relatorio

