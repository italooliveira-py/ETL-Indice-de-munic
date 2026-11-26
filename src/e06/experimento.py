"""Pipelines, grades, janelas no tempo, métricas e bootstrap por município do E06.

Reaproveitado da E05 (src/e05/experimento.py, main de 25/11/2026), copiado e não importado:
- NOMES e a estrutura de criar_pipeline (nomes dos modelos iguais aos da equipe);
- folds_temporais: o treino de cada janela só tem desfechos conhecidos no início da validação;
- intervalos_cluster: bootstrap com municípios inteiros como unidade, aqui com o Brier incluído.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from .dados import ALVO, CONTAGENS, DERIVADAS, EM_LOG, DerivadasHistorico

NOMES = {
    'trivial': 'Baseline trivial (prevalência do treino)',
    'modalidade': 'Baseline por modalidade (taxa do treino)',
    'logistica': 'Regressão logística regularizada',
    'arvore': 'Decision Tree Classifier',
    'floresta': 'Random Forest Classifier',
    'gb': 'Gradient Boosting (HistGB)',
    'svc': 'SVC (RBF)',
    'mlp': 'MLP (média de 3 sementes)',
}
BASELINES = ('trivial', 'modalidade')
COM_ESCALA = ('logistica', 'svc', 'mlp')


class TaxaPorModalidade(BaseEstimator, ClassifierMixin):
    """Baseline operacional: a taxa de Y=1 de cada modalidade no treino."""

    def fit(self, x, y):
        y = pd.Series(np.asarray(y), index=x.index)
        self.geral_ = float(y.mean())
        self.taxas_ = y.groupby(x['modalidade']).mean().to_dict()
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, x):
        p = x['modalidade'].map(self.taxas_).fillna(self.geral_).to_numpy(dtype=float)
        return np.column_stack([1 - p, p])


class MediaSementes(BaseEstimator, ClassifierMixin):
    """Média das probabilidades do mesmo estimador ajustado com várias sementes."""

    def __init__(self, estimador=None, sementes=(0, 1, 2)):
        self.estimador = estimador
        self.sementes = sementes

    def fit(self, x, y):
        self.modelos_ = [clone(self.estimador).set_params(random_state=s).fit(x, y) for s in self.sementes]
        self.classes_ = self.modelos_[0].classes_
        return self

    def predict_proba(self, x):
        return np.mean([m.predict_proba(x) for m in self.modelos_], axis=0)


def expandir_grade(grade):
    if isinstance(grade, list):
        return grade
    chaves = list(grade)
    return [dict(zip(chaves, valores)) for valores in itertools.product(*(grade[c] for c in chaves))]


def _estimador(nome, params, config):
    s = config['semente']
    if nome == 'trivial':
        return DummyClassifier(strategy='prior')
    if nome == 'logistica':
        l1 = params['l1_ratio']
        if l1 == 0:
            return LogisticRegression(C=params['C'], max_iter=5000, random_state=s)
        return LogisticRegression(C=params['C'], penalty='elasticnet', l1_ratio=l1,
                                  solver='saga', max_iter=10000, random_state=s)
    if nome == 'arvore':
        return DecisionTreeClassifier(random_state=s, **params)
    if nome == 'floresta':
        return RandomForestClassifier(n_estimators=500, n_jobs=-1, random_state=s, **params)
    if nome == 'gb':
        return HistGradientBoostingClassifier(max_iter=300, early_stopping=True, validation_fraction=0.1,
                                              n_iter_no_change=20, random_state=s, **params)
    if nome == 'svc':
        return SVC(kernel='rbf', gamma='scale', probability=True, random_state=s, **params)
    if nome == 'mlp':
        base = MLPClassifier(hidden_layer_sizes=tuple(params['hidden_layer_sizes']), alpha=params['alpha'],
                             solver='lbfgs', max_iter=2000)
        return MediaSementes(base, sementes=tuple(s + k for k in config['sementes_mlp']))
    raise ValueError(nome)


def entrada(colunas):
    """Colunas brutas que o pipeline recebe: as derivadas nascem dentro dele, a partir das contagens."""
    brutas = [c for c in colunas if c not in DERIVADAS]
    if len(brutas) < len(colunas):
        brutas += [c for c in CONTAGENS if c not in brutas]
    return brutas


def criar_pipeline(nome, params, colunas, config):
    if nome == 'modalidade':
        return Pipeline([('modelo', TaxaPorModalidade())])
    escala = nome in COM_ESCALA
    em_log = [c for c in colunas if c in EM_LOG]
    categoricas = [c for c in colunas if c == 'modalidade']
    numericas = [c for c in colunas if c not in em_log and c not in categoricas]
    log_passos = [('log', FunctionTransformer(np.log1p, feature_names_out='one-to-one'))]
    if escala:
        log_passos.append(('escala', StandardScaler()))
    partes = [('log', Pipeline(log_passos), em_log),
              ('num', StandardScaler() if escala else 'passthrough', numericas),
              ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categoricas)]
    preparo = ColumnTransformer([p for p in partes if p[2]])
    return Pipeline([('derivadas', DerivadasHistorico(config['suavizacao_historico'])),
                     ('preparo', preparo), ('modelo', _estimador(nome, params, config))])


def prever(modelo, x):
    return modelo.predict_proba(x)[:, 1]


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def janelas_tempo(treino, anos, maturidade_dias=365):
    """Para validar o ano V, treina só com instrumentos cujo desfecho de 365 dias já era conhecido
    em 01/01 de V (regra de folds_temporais da E05: fim_horizonte < início da validação)."""
    janelas = []
    for ano in anos:
        inicio = pd.Timestamp(f'{ano}-01-01')
        fim_horizonte = treino.data_assinatura + pd.to_timedelta(maturidade_dias, unit='D')
        t = np.flatnonzero(fim_horizonte < inicio)
        v = np.flatnonzero(treino.ano_origem == ano)
        janelas.append((ano, t, v))
    return janelas


def avaliar_grade(nome, colunas, config, treino, validacao=None, janelas=None):
    """Brier de cada combinação da grade, na validação oficial ou na média das janelas no tempo."""
    linhas = []
    for params in expandir_grade(config['grades'][nome]):
        if janelas is None:
            m = criar_pipeline(nome, params, colunas, config).fit(treino[entrada(colunas)], treino[ALVO])
            nota = brier(validacao[ALVO], prever(m, validacao[entrada(colunas)]))
        else:
            notas = []
            for _, t, v in janelas:
                tt, vv = treino.iloc[t], treino.iloc[v]
                m = criar_pipeline(nome, params, colunas, config).fit(tt[entrada(colunas)], tt[ALVO])
                notas.append(brier(vv[ALVO], prever(m, vv[entrada(colunas)])))
            nota = float(np.mean(notas))
        linhas.append({'modelo': nome, 'hiperparametros': params, 'brier_escolha': nota})
    return linhas


def previsoes_janelas(nome, params, colunas, config, treino, janelas):
    """Probabilidades fora da amostra nas janelas (usadas para o limiar quando não há validação)."""
    ys, ps = [], []
    for _, t, v in janelas:
        tt, vv = treino.iloc[t], treino.iloc[v]
        m = criar_pipeline(nome, params, colunas, config).fit(tt[entrada(colunas)], tt[ALVO])
        ys.append(vv[ALVO].to_numpy())
        ps.append(prever(m, vv[entrada(colunas)]))
    return np.concatenate(ys), np.concatenate(ps)


def metricas(y, p, prevalencia_treino):
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    b = brier(y, p)
    ref = brier(y, np.full(len(y), prevalencia_treino))
    duas = len(np.unique(y)) == 2
    return {'n': len(y), 'prevalencia': float(y.mean()), 'previsto_medio': float(p.mean()),
            'brier': b, 'brier_skill': 1 - b / ref,
            'log_loss': float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])),
            'roc_auc': float(roc_auc_score(y, p)) if duas else np.nan,
            'pr_auc_y1': float(average_precision_score(y, p)) if duas else np.nan,
            'pr_auc_y0': float(average_precision_score(1 - y, 1 - p)) if duas else np.nan}


def _resumo_matriz(vp, fp, fn, vn):
    precisao = vp / (vp + fp) if vp + fp else np.nan
    recall = vp / (vp + fn) if vp + fn else np.nan
    f1 = 2 * precisao * recall / (precisao + recall) if vp else 0.0
    return {'precisao': precisao, 'recall': recall, 'f1': f1, 'vp': vp, 'fp': fp, 'fn': fn, 'vn': vn}


def matriz_limiar(y, p, limiar):
    y, marcado = np.asarray(y, dtype=int), np.asarray(p) >= limiar
    return _resumo_matriz(int((marcado & (y == 1)).sum()), int((marcado & (y == 0)).sum()),
                          int((~marcado & (y == 1)).sum()), int((~marcado & (y == 0)).sum()))


def matriz_capacidade(y, p, fracao):
    """Marca os `fracao` de maior risco. Empates na fronteira entram na proporção que falta (valor
    esperado de um sorteio), para o resultado não depender da ordem do arquivo."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    k = fracao * len(p)
    grupos = pd.DataFrame({'y': y, 'p': p}).groupby('p').y.agg(['size', 'sum']).sort_index(ascending=False)
    restante, vp = k, 0.0
    for n, soma in zip(grupos['size'], grupos['sum']):
        pega = min(restante, n)
        vp += pega * soma / n
        restante -= pega
        if restante <= 0:
            break
    fn = y.sum() - vp
    return _resumo_matriz(vp, k - vp, fn, len(p) - k - fn)


def limiar_f1(y, p):
    """Limiar que maximiza o F1 de Y=1, entre os quantis das probabilidades."""
    candidatos = np.unique(np.quantile(p, np.linspace(0, 1, 201)))
    notas = [matriz_limiar(y, p, c)['f1'] for c in candidatos]
    return float(candidatos[int(np.argmax(notas))])


def decisoes(y, p, limiares, capacidades):
    """Matriz de confusão por limiar (nome → valor) e por capacidade (fração dos de maior risco)."""
    saida = {}
    for nome, limiar in limiares.items():
        saida[f'limiar_{nome}'] = limiar
        saida.update({f'{k}_{nome}': v for k, v in matriz_limiar(y, p, limiar).items()})
    for fracao in capacidades:
        rotulo = f'top{int(round(fracao * 100))}'
        saida.update({f'{k}_{rotulo}': v for k, v in matriz_capacidade(y, p, fracao).items()})
    return saida


def sorteios_municipios(codigos, repeticoes, semente):
    ids = np.unique(codigos)
    rng = np.random.default_rng(semente)
    return ids, [rng.choice(ids, len(ids), replace=True) for _ in range(repeticoes)]


def intervalos_cluster(y, p, codigos, prevalencia_treino, sorteio):
    """IC de 95% reamostrando municípios inteiros (as mesmas reamostragens para todos os modelos)."""
    ids, sorteios = sorteio
    y, p, codigos = np.asarray(y, dtype=int), np.asarray(p, dtype=float), np.asarray(codigos)
    por_codigo = {c: np.flatnonzero(codigos == c) for c in ids}
    valores = {k: [] for k in ('brier', 'brier_skill', 'roc_auc', 'pr_auc_y1', 'pr_auc_y0')}
    for s in sorteios:
        idx = np.concatenate([por_codigo[c] for c in s])
        yy, pp = y[idx], p[idx]
        b = brier(yy, pp)
        valores['brier'].append(b)
        valores['brier_skill'].append(1 - b / brier(yy, np.full(len(yy), prevalencia_treino)))
        if 0 < yy.sum() < len(yy):
            valores['roc_auc'].append(roc_auc_score(yy, pp))
            valores['pr_auc_y1'].append(average_precision_score(yy, pp))
            valores['pr_auc_y0'].append(average_precision_score(1 - yy, 1 - pp))
    saida = {}
    for k, v in valores.items():
        saida[f'ic95_inf_{k}'] = float(np.quantile(v, 0.025)) if v else np.nan
        saida[f'ic95_sup_{k}'] = float(np.quantile(v, 0.975)) if v else np.nan
    return saida


def calibracao(y, p, grupos=None, bins=10):
    """Previsto médio contra real por decil de probabilidade (ou por grupo, quando informado)."""
    quadro = pd.DataFrame({'y': np.asarray(y, dtype=int), 'p': np.asarray(p, dtype=float)})
    if grupos is None:
        quadro['grupo'] = pd.qcut(quadro.p.rank(method='first'), bins, labels=False) + 1
    else:
        quadro['grupo'] = np.asarray(grupos)
    return quadro.groupby('grupo').agg(n=('y', 'size'), previsto=('p', 'mean'), real=('y', 'mean')).reset_index()


def erros_por_grupo(y, p, grupos, prevalencia_treino):
    linhas = []
    quadro = pd.DataFrame({'y': np.asarray(y, dtype=int), 'p': np.asarray(p, dtype=float)})
    for dimensao, valores in grupos.items():
        quadro['g'] = np.asarray(valores)
        for valor, parte in quadro.groupby('g'):
            m = metricas(parte.y, parte.p, prevalencia_treino)
            linhas.append({'dimensao': dimensao, 'grupo': valor, **m})
    return pd.DataFrame(linhas)
