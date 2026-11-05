"""Alvos de falha de instrumentos do Transferegov, com censura explícita.

Unidade: instrumento assinado (Silver `transferegov_instrumentos`). Cada alvo vale 1, 0 ou
ausente (censurado), e a regra de censura respeita o que já era conhecível na data de carga:

- falha contratual: anulado, rescindido ou cancelado. Positivo assim que ocorre; negativo só
  depois do fim da vigência sem falha; antes disso, censurado. Contas rejeitadas ficam de fora
  (4 casos em 2015–2024, quase sempre ainda em análise).
- não pagamento: com a vigência encerrada e sem falha contratual, menos de 90% do repasse
  desembolsado (execução financeira incompleta; com 50% o evento era raro demais: 56 casos em
  2015–2019, contra 104 com 90%). Antes do fim da vigência, censurado; com falha contratual, não se aplica.
- atraso grave: vigência atual mais de 365 dias além da original. Positivo assim que a
  vigência é estendida além do limite (a prorrogação só ocorre antes do término, PC 33/2023);
  negativo só se a vigência já terminou dentro do limite; senão, censurado.
- falha do projeto: falha contratual ou não pagamento — o projeto não se realizou.

Situação, vigência e valores vêm da fotografia da data de carga: servem para o alvo, nunca
como preditores.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DATA_CARGA = pd.Timestamp('2026-07-17')
SITUACOES_FALHA = ('Convênio Anulado', 'Convênio Rescindido', 'Cancelado')
LIMITE_EXECUCAO = 0.9
LIMITE_ATRASO_DIAS = 365
ALVOS = ('falha_contratual', 'nao_pagamento', 'atraso_grave', 'falha_projeto')


def _binario(positivo, negativo) -> pd.Series:
    """1, 0 ou ausente; positivo prevalece sobre negativo."""
    alvo = pd.Series(pd.NA, index=positivo.index, dtype='Int64')
    alvo[negativo.fillna(False)] = 0
    alvo[positivo.fillna(False)] = 1
    return alvo


def construir_alvos(instrumentos: pd.DataFrame, desembolsos: pd.DataFrame, *,
                    data_carga: pd.Timestamp = DATA_CARGA) -> pd.DataFrame:
    """Um registro por instrumento com os quatro alvos e os insumos de cada regra."""
    if instrumentos.nr_convenio.duplicated().any():
        raise ValueError('nr_convenio duplicado')
    pago = desembolsos.groupby('nr_convenio').valor_desembolsado.sum()
    base = instrumentos[['nr_convenio', 'codigo_ibge', 'modalidade', 'data_assinatura', 'data_fim_vigencia',
                         'data_fim_vigencia_original', 'situacao', 'valor_repasse']].copy()
    base['safra'] = base.data_assinatura.dt.year
    base['total_desembolsado'] = base.nr_convenio.map(pago).fillna(0.0)
    base['taxa_execucao_financeira'] = base.total_desembolsado / base.valor_repasse.where(base.valor_repasse > 0)
    base['vigencia_encerrada'] = base.data_fim_vigencia < data_carga
    base['prorrogacao_dias'] = (base.data_fim_vigencia - base.data_fim_vigencia_original).dt.days

    falhou = base.situacao.isin(SITUACOES_FALHA)
    base['falha_contratual'] = _binario(falhou, base.vigencia_encerrada & ~falhou)

    aplicavel = base.vigencia_encerrada & ~falhou & base.taxa_execucao_financeira.notna()
    base['nao_pagamento'] = _binario(aplicavel & (base.taxa_execucao_financeira < LIMITE_EXECUCAO),
                                     aplicavel & (base.taxa_execucao_financeira >= LIMITE_EXECUCAO))

    limite = base.data_fim_vigencia_original + pd.Timedelta(days=LIMITE_ATRASO_DIAS)
    base['atraso_grave'] = _binario(base.data_fim_vigencia > limite,
                                    (base.data_fim_vigencia <= limite) & base.vigencia_encerrada)

    contratual, pagamento = base.falha_contratual, base.nao_pagamento
    base['falha_projeto'] = _binario((contratual == 1) | (pagamento == 1),
                                     (contratual == 0) & (pagamento == 0))
    return base


def resumo_por_safra(alvos: pd.DataFrame, safras=range(2015, 2025)) -> pd.DataFrame:
    """Instrumentos, % observado (não censurado) e prevalência entre os observados, por alvo."""
    recorte = alvos[alvos.safra.isin(list(safras))]
    linhas = {'instrumentos': recorte.groupby('safra').size()}
    for alvo in ALVOS:
        observado = recorte[alvo].notna()
        linhas[f'{alvo}_observado_%'] = observado.groupby(recorte.safra).mean().mul(100).round(1)
        linhas[f'{alvo}_prevalencia_%'] = (recorte[alvo].astype(float).groupby(recorte.safra).mean().mul(100).round(1))
    return pd.DataFrame(linhas)


def baseline_ingenua(alvos: pd.DataFrame, particoes: dict[str, list[int]]) -> pd.DataFrame:
    """Prevalência do treino aplicada adiante (prior) e taxa por modalidade no treino."""
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    linhas = []
    treino = alvos[alvos.safra.isin(particoes['treino'])]
    for alvo in ALVOS:
        obs_treino = treino[treino[alvo].notna()]
        prior = float(obs_treino[alvo].astype(float).mean())
        por_modalidade = obs_treino.groupby('modalidade')[alvo].apply(lambda s: s.astype(float).mean())
        for parte in ('validacao', 'teste'):
            dados = alvos[alvos.safra.isin(particoes[parte]) & alvos[alvo].notna()]
            y = dados[alvo].astype(int).to_numpy()
            escores_modalidade = dados.modalidade.map(por_modalidade).fillna(prior).to_numpy()
            linhas.append({
                'alvo': alvo, 'particao': parte, 'n': len(y), 'positivos': int(y.sum()),
                'prevalencia': round(float(y.mean()), 3), 'prior_treino': round(prior, 3),
                'brier_prior': round(brier_score_loss(y, np.full(len(y), prior)), 3),
                'roc_auc_modalidade': round(roc_auc_score(y, escores_modalidade), 3) if 0 < y.sum() < len(y) else None,
                'ap_modalidade': round(average_precision_score(y, escores_modalidade), 3) if y.sum() else None,
            })
    return pd.DataFrame(linhas)
