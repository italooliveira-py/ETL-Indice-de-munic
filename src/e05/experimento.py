"""Avaliação temporal honesta; classe única não é corrigida com dados artificiais."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
                             brier_score_loss, confusion_matrix, f1_score, log_loss,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier
from threadpoolctl import threadpool_limits

from .dados import CATEGORICAS, NUMERICAS, PREDITORES

NOMES = {
    'trivial': 'Baseline trivial (prevalência do treino)',
    'logistica': 'Baseline operacional (Regressão Logística)',
    'arvore': 'Decision Tree Classifier',
    'floresta': 'Random Forest Classifier',
}


def limpar_x(x, numericas=NUMERICAS, categoricas=CATEGORICAS):
    x = x[list(numericas) + list(categoricas)].copy()
    for coluna in numericas:
        x[coluna] = pd.to_numeric(x[coluna], errors='raise').astype(float)
        if np.isinf(x[coluna]).any():
            raise ValueError('Preditor infinito: ' + coluna)
    for coluna in categoricas:
        x[coluna] = x[coluna].astype(object).where(x[coluna].notna(), np.nan)
    return x


def criar_pipeline(nome, seed=42, numericas=None, categoricas=None, parametros=None):
    numericas = NUMERICAS if numericas is None else numericas
    categoricas = CATEGORICAS if categoricas is None else categoricas
    numerico = [('imputar', SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True))]
    if nome == 'logistica':
        numerico.append(('escala', StandardScaler()))
    preparo = ColumnTransformer([
        ('numericas', Pipeline(numerico), numericas),
        ('categoricas', Pipeline([
            ('imputar', SimpleImputer(strategy='constant', fill_value='ausente', keep_empty_features=True)),
            ('codificar', OneHotEncoder(handle_unknown='infrequent_if_exist', min_frequency=5, sparse_output=False)),
        ]), categoricas),
    ])
    modelos = {
        'trivial': DummyClassifier(strategy='prior'),
        'logistica': LogisticRegression(C=1.0, max_iter=2000, random_state=seed),
        'arvore': DecisionTreeClassifier(
            max_depth=3, min_samples_leaf=10, random_state=seed),
        'floresta': RandomForestClassifier(n_estimators=300, max_depth=5, min_samples_leaf=10,
                                           max_features=0.7, random_state=seed, n_jobs=2),
    }
    if parametros:
        modelos[nome].set_params(**parametros.get(nome, {}))
    return Pipeline([('limpar', FunctionTransformer(limpar_x, validate=False,
                       kw_args={'numericas': numericas, 'categoricas': categoricas})),
                     ('preparo', preparo), ('modelo', modelos[nome])])


def probabilidade_positiva(modelo, x):
    """Não presume duas colunas de probabilidade quando o ajuste tem classe única."""
    probabilidades = modelo.predict_proba(x)
    classes = modelo.classes_
    posicoes = np.flatnonzero(classes == 1)
    return probabilidades[:, posicoes[0]] if len(posicoes) else np.zeros(len(x))


def metricas(y, probabilidades, limiar=0.5):
    y, p = np.asarray(y, dtype=int), np.asarray(probabilidades, dtype=float)
    if len(y) == 0 or len(y) != len(p) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('Alvo/probabilidades inválidos')
    duas = set(y) == {0, 1}
    pred = (p >= limiar).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        'n': len(y), 'classe_0': int((y == 0).sum()), 'classe_1': int(y.sum()),
        'prevalencia': float(y.mean()), 'acuracia': float(accuracy_score(y, pred)),
        'acuracia_balanceada': float(balanced_accuracy_score(y, pred)) if duas else None,
        'roc_auc': float(roc_auc_score(y, p)) if duas else None,
        'average_precision': float(average_precision_score(y, p)) if duas else None,
        'precision': float(precision_score(y, pred, zero_division=0)),
        'recall': float(recall_score(y, pred, zero_division=0)),
        'f1': float(f1_score(y, pred, zero_division=0)),
        'brier': float(brier_score_loss(y, p)),
        'mae_probabilidade': float(np.mean(np.abs(y - p))),
        'rmse_probabilidade': float(np.sqrt(brier_score_loss(y, p))),
        'log_loss': float(log_loss(y, p, labels=[0, 1])),
        'tn': int(tn), 'fp': int(fp), 'fn': int(fn), 'tp': int(tp),
        'suporte_duas_classes': duas,
    }


def folds_temporais(treino, origens, minimo_treino=30, minimo_validacao=10, minimo_classe=5,
                    alvo='sem_repasse_90d'):
    folds, auditoria = [], []
    for origem in origens:
        inicio = pd.Timestamp(origem)
        fim = inicio + pd.offsets.MonthBegin(1)
        t = np.flatnonzero((treino.data_assinatura < inicio) & (treino.fim_horizonte < inicio))
        v = np.flatnonzero((treino.data_assinatura >= inicio) & (treino.data_assinatura < fim))
        cont_t = treino.iloc[t][alvo].value_counts()
        cont_v = treino.iloc[v][alvo].value_counts()
        valido = len(t) >= minimo_treino and len(v) >= minimo_validacao
        valido = valido and all(cont_t.get(c, 0) >= minimo_classe and cont_v.get(c, 0) >= minimo_classe for c in (0, 1))
        auditoria.append(dict(origem=origem, n_treino=len(t), n_validacao=len(v),
                              treino_0=int(cont_t.get(0, 0)), treino_1=int(cont_t.get(1, 0)),
                              validacao_0=int(cont_v.get(0, 0)), validacao_1=int(cont_v.get(1, 0)), valido=valido))
        if valido:
            folds.append((t, v))
    return folds, pd.DataFrame(auditoria)


def treinar(nome, treino, config, folds=()):
    if treino.empty:
        return None, {'status': 'nao_estimavel_treino_vazio'}
    alvo = config.get('alvo', 'sem_repasse_90d')
    preditores = config.get('numericas', NUMERICAS) + config.get('categoricas', CATEGORICAS)
    y = treino[alvo].astype(int)
    if nome == 'logistica' and y.nunique() < 2:
        return None, {'status': 'nao_estimavel_treino_classe_unica',
                      'motivo': 'Regressão Logística exige exemplos das duas classes; não houve substituição por Dummy.'}
    modelo = criar_pipeline(nome, config['random_state'], config.get('numericas'),
                            config.get('categoricas'), config.get('parametros_modelos'))
    ajuste = {'status': 'estimado', 'busca': 'nao_aplicavel_baseline'}
    if nome in ('arvore', 'floresta'):
        if y.nunique() < 2:
            ajuste = {'status': 'degenerado_treino_classe_unica', 'busca': 'bloqueada_sem_duas_classes',
                      'motivo': 'A árvore ajusta uma folha constante; isso não demonstra aprendizagem discriminativa.'}
        elif config.get('busca_hiperparametros') is False:
            ajuste['busca'] = 'configuracao_conservadora_predefinida'
        elif len(folds) < 2:
            ajuste['busca'] = 'defaults_conservadores_menos_de_dois_folds_validos'
        else:
            grade = ({'modelo__max_depth': [3, 5, 8], 'modelo__min_samples_leaf': [5, 10, 20]}
                     if nome == 'arvore' else
                     {'modelo__max_depth': [5, 10], 'modelo__min_samples_leaf': [5, 10, 20]})
            busca = GridSearchCV(modelo, grade, cv=folds, scoring='average_precision', refit=True,
                                 n_jobs=1, error_score='raise')
            busca.fit(treino[preditores], y)
            return busca.best_estimator_, {**ajuste, 'busca': 'cv_temporal_com_purga',
                                          'melhores_parametros': busca.best_params_, 'ap_cv': float(busca.best_score_)}
    modelo.fit(treino[preditores], y)
    return modelo, ajuste


def intervalos_cluster(predicoes, repeticoes=1000, seed=42):
    """Predições fixas e municípios como unidades; não simula outros anos de teste."""
    if predicoes.empty:
        return pd.DataFrame(), {'status': 'sem_predicoes'}
    referencia = predicoes[predicoes.modelo == 'trivial']
    suporte = referencia.y_real.value_counts()
    if min(suporte.get(0, 0), suporte.get(1, 0)) < 10:
        return pd.DataFrame(), {'status': 'nao_estimado_suporte_minoritario_inferior_a_10',
                                'motivo': 'Evita intervalos aparentemente precisos com pouquíssimos exemplos de uma classe.'}
    ids = referencia.codigo_ibge.unique()
    rng, linhas = np.random.default_rng(seed), []
    sorteios = [rng.choice(ids, len(ids), replace=True) for _ in range(repeticoes)]
    for nome, grupo in predicoes.groupby('modelo'):
        # Reamostrar índices evita milhares de concatenações de DataFrames no notebook.
        codigos = grupo.codigo_ibge.to_numpy()
        por_codigo = {c: np.flatnonzero(codigos == c) for c in ids}
        y = grupo.y_real.to_numpy(dtype=int)
        p = grupo.probabilidade.to_numpy(dtype=float)
        valores = []
        for sorteio in sorteios:
            indices = np.concatenate([por_codigo[c] for c in sorteio])
            yy, pp = y[indices], p[indices]
            positivos = yy == 1
            if positivos.any() and (~positivos).any():
                previsto = pp >= 0.5
                valores.append({'acuracia_balanceada': float((previsto[positivos].mean() + (~previsto[~positivos]).mean()) / 2),
                                'roc_auc': float(roc_auc_score(yy, pp)),
                                'average_precision': float(average_precision_score(yy, pp))})
        for metrica in ('acuracia_balanceada', 'roc_auc', 'average_precision'):
            valores_m = [v[metrica] for v in valores]
            if valores_m:
                linhas.append(dict(modelo=nome, metrica=metrica, inferior=np.quantile(valores_m, .025),
                                   superior=np.quantile(valores_m, .975), reamostragens_validas=len(valores_m)))
    return pd.DataFrame(linhas), {'status': 'condicional_ao_teste_2024_e_ajustes_fixos', 'repeticoes': repeticoes}


def executar(base, config, destino: Path):
    destino.mkdir(parents=True, exist_ok=True)
    treino = base[base.treino_validacao].reset_index(drop=True)
    validacao = base[base.validacao].reset_index(drop=True)
    final = base[base.treino_final].reset_index(drop=True)
    teste = base[base.teste].reset_index(drop=True)
    alvo = config.get('alvo', 'sem_repasse_90d')
    id_col = config.get('coluna_id', 'nr_convenio')
    data_col = config.get('coluna_data', 'data_assinatura')
    preditores = config.get('numericas', NUMERICAS) + config.get('categoricas', CATEGORICAS)
    if teste.empty or set(final[id_col]) & set(teste[id_col]):
        raise ValueError('Teste vazio ou instrumentos sobrepostos ao treino final')
    if config.get('tipo_cv') == 'grupos_municipais_no_treino':
        folds = list(StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=config['random_state']).split(
            treino, treino[alvo], treino.codigo_ibge))
        folds = [(t, v) for t, v in folds if treino.iloc[t][alvo].nunique() == 2 and treino.iloc[v][alvo].nunique() == 2]
        auditoria_cv = pd.DataFrame([{'fold': i, 'n_treino': len(t), 'n_validacao': len(v),
                                      'grupos_disjuntos': not bool(set(treino.iloc[t].codigo_ibge) & set(treino.iloc[v].codigo_ibge))}
                                     for i, (t, v) in enumerate(folds)])
    else:
        folds, auditoria_cv = folds_temporais(treino, config['origens_cv'], alvo=alvo)
    auditoria_cv.to_csv(destino / 'auditoria_cv.csv', index=False)
    linhas, predicoes, ajustes, metricas_cv = [], [], {}, []
    with threadpool_limits(limits=2):
        for nome in NOMES:
            modelo, ajuste = treinar(nome, treino, config, folds)
            ajustes[nome] = {'desenvolvimento': ajuste}
            if config.get('tipo_cv') == 'grupos_municipais_no_treino' and modelo is not None:
                for i, (t, v) in enumerate(folds):
                    estimador_cv = clone(modelo).fit(treino.iloc[t][preditores], treino.iloc[t][alvo].astype(int))
                    pcv = probabilidade_positiva(estimador_cv, treino.iloc[v][preditores])
                    metricas_cv.append({'modelo': nome, 'fold': i, **metricas(treino.iloc[v][alvo], pcv)})
            if modelo is not None and len(validacao):
                p = probabilidade_positiva(modelo, validacao[preditores])
                linhas.append({'modelo': nome, 'nome': NOMES[nome], 'particao': 'validacao_2023',
                               'status_ajuste': ajuste['status'], **metricas(validacao[alvo], p)})
            # Todos os métodos usam exatamente os mesmos instrumentos elegíveis na refit e no teste.
            if modelo is not None:
                modelo_final = clone(modelo).fit(final[preditores], final[alvo].astype(int))
                ajuste_final = 'degenerado_treino_classe_unica' if final[alvo].nunique() < 2 and nome != 'trivial' else 'estimado'
            else:
                modelo_final, meta_final = treinar(nome, final, config)
                ajuste_final = meta_final['status']
            ajustes[nome]['ajuste_final'] = ajuste_final
            if modelo_final is None:
                # Um modelo antigo não pode parecer válido depois de um ajuste não estimável.
                (destino / (nome + '.joblib')).unlink(missing_ok=True)
                linhas.append({'modelo': nome, 'nome': NOMES[nome], 'particao': 'teste_2024',
                               'status_ajuste': ajuste_final, 'n': len(teste),
                               'classe_0': int((teste[alvo] == 0).sum()), 'classe_1': int((teste[alvo] == 1).sum()),
                               'acuracia_balanceada': None, 'roc_auc': None, 'average_precision': None})
                continue
            p = probabilidade_positiva(modelo_final, teste[preditores])
            linhas.append({'modelo': nome, 'nome': NOMES[nome], 'particao': 'teste_2024',
                           'status_ajuste': ajuste_final, **metricas(teste[alvo], p, config['limiar_classificacao'])})
            df = teste[[id_col, 'codigo_ibge', data_col, alvo]].rename(columns={alvo: 'y_real'})
            df['modelo'], df['probabilidade'] = nome, p
            df['y_previsto'] = (p >= config['limiar_classificacao']).astype(int)
            predicoes.append(df)
            joblib.dump(modelo_final, destino / (nome + '.joblib'))
    metricas_df = pd.DataFrame(linhas)
    if not config.get('erros_probabilidade', False):
        metricas_df = metricas_df.drop(columns=['mae_probabilidade', 'rmse_probabilidade'], errors='ignore')
    pd.DataFrame(metricas_cv).to_csv(destino / 'metricas_cv.csv', index=False)
    preds = pd.concat(predicoes, ignore_index=True) if predicoes else pd.DataFrame()
    intervalos, meta_intervalos = intervalos_cluster(preds, config['bootstrap_municipios'], config['random_state'])
    metricas_df.to_csv(destino / 'metricas.csv', index=False, encoding='utf-8-sig')
    metricas_df[metricas_df.particao == 'teste_2024'].to_csv(destino / 'quadro_comparacao_jorge.csv', index=False, encoding='utf-8-sig')
    preds.to_csv(destino / 'predicoes_teste_2024.csv', index=False, encoding='utf-8-sig')
    intervalos.to_csv(destino / 'intervalos_cluster.csv', index=False)
    resultados = {
        'configuracao': config, 'ajustes': ajustes, 'intervalos': meta_intervalos,
        'classes_por_particao': {nome: {'n': len(parte), 'classe_0': int((parte[alvo] == 0).sum()),
                                        'classe_1': int((parte[alvo] == 1).sum())}
                                 for nome, parte in [('treino_2022_validacao', treino), ('validacao_2023', validacao),
                                                     ('treino_final_2022_2023', final), ('teste_2024', teste)]},
        'candidato_validado': None,
        'status_conclusao': 'inviavel_discriminacao_treino_classe_unica' if final[alvo].nunique() < 2 else 'benchmark_retrospectivo_executado',
        'nota': 'Acurácia elevada com classe dominante não demonstra previsão útil de risco. Métrica ausente não foi inventada.',
    }
    if validacao[alvo].nunique() == 2 and final[alvo].nunique() == 2:
        candidatos = metricas_df[(metricas_df.particao == 'validacao_2023') & metricas_df.modelo.isin(['arvore', 'floresta'])]
        if len(candidatos):
            resultados['candidato_validado'] = candidatos.sort_values(['average_precision', 'modelo'], ascending=[False, True]).modelo.iloc[0]
        referencias = metricas_df[metricas_df.particao == 'validacao_2023'].dropna(subset=['average_precision'])
        if len(referencias):
            melhor = referencias.sort_values(['average_precision', 'modelo'], ascending=[False, True]).iloc[0]
            resultados['referencia_por_ap_validacao'] = melhor.modelo
            resultados['substituicao_baseline_justificada_na_validacao'] = bool(melhor.modelo in ['arvore', 'floresta'])
    elif final[alvo].nunique() == 2:
        resultados['status_conclusao'] = 'sem_validacao_discriminativa_classe_unica_2023'
    (destino / 'resultados.json').write_text(json.dumps(resultados, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return resultados, metricas_df, preds
