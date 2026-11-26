"""Experimento cruzado: 3 alvos × conjuntos de variáveis × modelos × partições temporais.

Cada alvo é tratado de forma independente. O erro principal é o Brier (erro quadrático da
probabilidade); o ganho é medido como Brier skill score contra duas referências ingênuas:
a prevalência do treino e a taxa por modalidade do treino. ROC-AUC e AP medem ordenação.
Hiperparâmetros fixos e regularizados, definidos antes de ver os resultados: é uma triagem,
não um ajuste fino. Uso: python experimento.py
"""
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from alvos_falha import construir_alvos

SEMENTE = 20261028
RAIZ = Path(__file__).resolve().parents[2]
SILVER = RAIZ / 'data' / 'silver'
SAIDA = RAIZ / 'docs' / 'e05' / 'tempo_desembolso' / 'resultados'
ALVOS = ['falha_contratual', 'nao_pagamento', 'atraso_grave']
# Janela móvel sem o período atípico de 2020–2021 (pandemia; migração das emendas para o Pix).
# O corte de 2022 tem só ~50% de desfechos conhecidos: serve como checagem, com ressalva.
PARTICOES = {
    'teste_2018': {'treino': [2015, 2016, 2017], 'teste': [2018]},
    'teste_2019': {'treino': [2015, 2016, 2017, 2018], 'teste': [2019]},
    'teste_2022': {'treino': [2015, 2016, 2017, 2018, 2019], 'teste': [2022]},
}

# Conjuntos de variáveis, todos conhecidos na assinatura (valores do instrumento seguem o PASS
# condicional do PR #6: a fonte não tem fotografia histórica de cada campo).
NUM_BASICO = ['log_valor_global_assinatura', 'contrapartida_pct', 'log_duracao_original',
              'dias_proposta_ate_assinatura', 'assinado_dezembro', 'origem_emenda', 'emenda_individual', 'emenda_impositiva']
NUM_HISTORICO = ['log_instrumentos_previos', 'log_encerrados_previos', 'taxa_falha_contratual_previa',
                 'taxa_nao_pagamento_previa', 'taxa_atraso_grave_previa']
CONJUNTOS = {
    'V0_modalidade': ([], ['modalidade']),
    'V1_instrumento': (NUM_BASICO, ['modalidade', 'orgao_superior']),
    'V2_instrumento_orgao': (NUM_BASICO, ['modalidade', 'orgao_superior', 'orgao']),
    'V3_instrumento_historico': (NUM_BASICO + NUM_HISTORICO, ['modalidade', 'orgao_superior', 'orgao']),
}

MODELOS = {
    'logistica_l2': lambda: LogisticRegression(C=1.0, max_iter=5000),
    'logistica_l1': lambda: LogisticRegression(C=0.5, l1_ratio=1.0, solver='saga', max_iter=10000),
    'elastic_net': lambda: LogisticRegression(C=0.5, l1_ratio=0.5, solver='saga', max_iter=10000),
    'naive_bayes': lambda: GaussianNB(),
    'knn': lambda: KNeighborsClassifier(n_neighbors=50),
    'arvore': lambda: DecisionTreeClassifier(max_depth=4, min_samples_leaf=30, random_state=SEMENTE),
    'random_forest': lambda: RandomForestClassifier(n_estimators=500, min_samples_leaf=10, n_jobs=-1, random_state=SEMENTE),
    'hist_gb': lambda: HistGradientBoostingClassifier(learning_rate=0.05, max_depth=3, max_iter=300,
                                                      l2_regularization=1.0, random_state=SEMENTE),
    'svc_rbf': lambda: SVC(C=1.0, probability=True, random_state=SEMENTE),
    'mlp': lambda: MLPClassifier(hidden_layer_sizes=(16,), alpha=1.0, solver='lbfgs', max_iter=3000, random_state=SEMENTE),
}


def carregar():
    instrumentos = pd.read_parquet(SILVER / 'transferegov_instrumentos.parquet')
    desembolsos = pd.read_parquet(SILVER / 'transferegov_desembolsos.parquet')
    alvos = construir_alvos(instrumentos, desembolsos)
    base = instrumentos.merge(alvos[['nr_convenio', *ALVOS]], on='nr_convenio', validate='one_to_one')
    base['safra'] = base.data_assinatura.dt.year
    base['log_valor_global_assinatura'] = np.log1p(base.valor_global_assinatura)
    # Contrapartida na assinatura: global na assinatura menos o repasse. O valor_contrapartida
    # atual embute aditivos posteriores (só instrumentos em execução recebem aditivo de valor).
    assinatura = base.valor_global_assinatura.where(base.valor_global_assinatura > 0)
    base['contrapartida_pct'] = ((assinatura - base.valor_repasse) / assinatura).clip(lower=0)
    base['log_duracao_original'] = np.log1p((base.data_fim_vigencia_original - base.data_inicio_vigencia).dt.days.clip(lower=0))
    base['dias_proposta_ate_assinatura'] = (base.data_assinatura - base.data_proposta).dt.days
    base['assinado_dezembro'] = (base.data_assinatura.dt.month == 12).astype(float)
    for coluna in ['origem_emenda', 'emenda_individual', 'emenda_impositiva']:
        base[coluna] = base[coluna].astype(float)
    return adicionar_historico(base)


def adicionar_historico(base):
    """Histórico do município até a véspera da assinatura (todas as safras desde 2008).

    Taxas só com instrumentos cuja vigência terminou antes da data: o desfecho era conhecível.
    Aproximação: a situação é a da data de carga, não a da véspera.
    """
    base = base.sort_values('data_assinatura').reset_index(drop=True)
    colunas = {c: np.full(len(base), np.nan) for c in NUM_HISTORICO}
    for _, grupo in base.groupby('codigo_ibge'):
        assin = grupo.data_assinatura.to_numpy()
        fim = grupo.data_fim_vigencia.to_numpy()
        for pos, linha in zip(grupo.index, range(len(grupo))):
            data = assin[linha]
            previos = assin < data
            encerrados = previos & (fim < data)
            colunas['log_instrumentos_previos'][pos] = np.log1p(previos.sum())
            colunas['log_encerrados_previos'][pos] = np.log1p(encerrados.sum())
            if encerrados.any():
                for alvo in ALVOS:
                    valores = grupo[alvo].to_numpy()[encerrados].astype(float)
                    valores = valores[~np.isnan(valores)]
                    if len(valores):
                        colunas[f'taxa_{alvo}_previa'][pos] = valores.mean()
    for coluna, valores in colunas.items():
        base[coluna] = valores
    return base


def pipeline(modelo, numericas, categoricas, estimador=None):
    partes = [('cat', OneHotEncoder(handle_unknown='infrequent_if_exist', min_frequency=15, sparse_output=False), categoricas)]
    if numericas:
        partes.append(('num', Pipeline([('imputar', SimpleImputer(strategy='median', add_indicator=True)),
                                        ('escalar', StandardScaler())]), numericas))
    return Pipeline([('prep', ColumnTransformer(partes)), ('modelo', estimador if estimador is not None else MODELOS[modelo]())])


def taxa_por_modalidade(treino, outro, alvo):
    taxas = treino.groupby('modalidade')[alvo].mean()
    return outro.modalidade.map(taxas).fillna(treino[alvo].mean()).to_numpy()


def avaliar(y, p, y_treino, p_modalidade):
    brier = brier_score_loss(y, p)
    brier_prior = brier_score_loss(y, np.full(len(y), y_treino.mean()))
    brier_mod = brier_score_loss(y, p_modalidade)
    return {'n': len(y), 'positivos': int(y.sum()), 'prevalencia': y.mean(),
            'roc_auc': roc_auc_score(y, p), 'ap': average_precision_score(y, p),
            'brier': brier, 'log_loss': log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)),
            'bss_vs_prior': 1 - brier / brier_prior, 'bss_vs_modalidade': 1 - brier / brier_mod,
            'roc_auc_modalidade': roc_auc_score(y, p_modalidade)}


def executar():
    warnings.filterwarnings('ignore')
    base = carregar()
    linhas = []
    for particao, anos in PARTICOES.items():
        for alvo in ALVOS:
            observados = base[base[alvo].notna()].copy()
            observados[alvo] = observados[alvo].astype(int)
            treino = observados[observados.safra.isin(anos['treino'])]
            partes = {'teste': observados[observados.safra.isin(anos['teste'])]}
            y_treino = treino[alvo].to_numpy()
            for conjunto, (numericas, categoricas) in CONJUNTOS.items():
                colunas = numericas + categoricas
                for modelo in MODELOS:
                    inicio = time.time()
                    ajustado = pipeline(modelo, numericas, categoricas).fit(treino[colunas], y_treino)
                    for parte, dados in partes.items():
                        p = ajustado.predict_proba(dados[colunas])[:, 1]
                        metr = avaliar(dados[alvo].to_numpy(), p, y_treino, taxa_por_modalidade(treino, dados, alvo))
                        linhas.append({'particao': particao, 'alvo': alvo, 'variaveis': conjunto, 'modelo': modelo,
                                       'avaliacao': parte, 'n_treino': len(treino), 'positivos_treino': int(y_treino.sum()),
                                       'segundos': round(time.time() - inicio, 2), **metr})
                print(f'{particao} {alvo} {conjunto} ok', flush=True)
    resultados = pd.DataFrame(linhas)
    SAIDA.mkdir(exist_ok=True)
    resultados.to_csv(SAIDA / 'experimento_janela_movel.csv', index=False)
    return resultados


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    executar()
