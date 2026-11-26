"""Triagem mensal sob piso econômico e teto de capacidade, com auditoria de equidade."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Cenario:
    nome: str
    beneficio: float
    custo: float
    capacidade: int

    def __post_init__(self):
        if (not np.isfinite([self.beneficio, self.custo, self.beneficio + self.custo]).all()
                or min(self.beneficio, self.custo) <= 0
                or not isinstance(self.capacidade, int) or self.capacidade < 1):
            raise ValueError("B, C e capacidade devem ser positivos e finitos. A capacidade é inteira.")

    @property
    def limiar(self):
        return self.custo / (self.beneficio + self.custo)


def selecionar_mensal(previsoes: pd.DataFrame, cenario: Cenario):
    """Avalia a expectativa de um sorteio uniforme entre empatados no último escore elegível."""
    quadro = previsoes.copy()
    quadro["mes"] = quadro["data_assinatura"].dt.to_period("M")
    quadro["peso"] = 0.0
    detalhes = []
    for mes, lote in quadro.groupby("mes", sort=True):
        elegiveis = lote.loc[lote["p"].gt(cenario.limiar), "p"]
        if len(elegiveis) > cenario.capacidade:
            corte = float(elegiveis.nlargest(cenario.capacidade).iloc[-1])
            acima = elegiveis.gt(corte)
            empate = elegiveis.eq(corte)
            pesos = acima.astype(float) + empate * ((cenario.capacidade - acima.sum()) / empate.sum())
            restricao = "capacidade"
        else:
            corte = cenario.limiar
            pesos = pd.Series(1.0, index=elegiveis.index)
            excluidos_pelo_piso = len(elegiveis) < len(lote)
            if len(elegiveis) == cenario.capacidade:
                restricao = "ambas" if excluidos_pelo_piso else "capacidade_exata"
            else:
                restricao = "piso_economico" if excluidos_pelo_piso else "volume"
        quadro.loc[pesos.index, "peso"] = pesos
        detalhes.append({"mes": str(mes), "n": len(lote), "elegiveis": len(elegiveis),
                         "vagas": cenario.capacidade, "limiar_efetivo": corte,
                         "restricao": restricao, "revisoes_esperadas": float(pesos.sum())})
    return quadro, detalhes


def contagens(quadro):
    y, peso = quadro["y"], quadro["peso"]
    vp, fp = float((y * peso).sum()), float(((1 - y) * peso).sum())
    fn, vn = float(y.sum() - vp), float((1 - y).sum() - fp)
    revisoes = vp + fp
    return {
        "n": len(quadro), "positivos": int(y.sum()), "revisoes": revisoes,
        "vp": vp, "fp": fp, "fn": fn, "vn": vn,
        "precisao": vp / revisoes if revisoes else np.nan,
        "recall": vp / (vp + fn) if vp + fn else np.nan,
        "taxa_selecao": revisoes / len(quadro),
    }


def avaliar_cenario(previsoes, cenario):
    selecionados, meses = selecionar_mensal(previsoes, cenario)
    medidas = contagens(selecionados)
    medidas["utilidade_normalizada"] = (
        cenario.beneficio * medidas["vp"] - cenario.custo * medidas["fp"]
    )
    return medidas, meses, selecionados


def equidade(selecionados, dimensoes):
    """Mede a cobertura da fila e o erro probabilístico por grupo na mesma coorte."""
    linhas = []
    for dimensao in dimensoes:
        for grupo, parte in selecionados.groupby(dimensao, sort=True, dropna=False):
            linhas.append({
                "dimensao": dimensao, "grupo": grupo, **contagens(parte),
                "observado": parte["y"].mean(), "previsto": parte["p"].mean(),
                "brier": ((parte["p"] - parte["y"]) ** 2).mean(),
            })
    return linhas

