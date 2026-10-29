"""SVC e MLP (modelos do Jorge no E05) no alvo de tempo até o 1º desembolso.

Mesma formulação dos outros modelos: uma linha por instrumento × trimestre em que ainda aguardava;
o classificador estima "recebe neste trimestre?" e as chances encadeadas dão a curva S(t).
Mesmos cortes, métricas e protocolo de escolha (hiperparâmetros escolhidos pelo Brier de 24 meses
na última safra do treino, sem tocar no teste).

Dois conjuntos de entrada, além do trimestre desde a assinatura:
- porte + fonte: o mesmo do modelo final (comparação direta do algoritmo);
- rico: porte + fonte + modalidade + atributos numéricos do instrumento (V1), para dar aos modelos
  não lineares a chance de achar interações que a logística não acha.
O MLP é a média de 3 sementes. O SVC usa probabilidade de Platt (probability=True).
Uso: python svc_mlp_desembolso.py
"""
import sys
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC

import experimento as e
import modelo_primeiro_desembolso as m
import tempo_primeiro_desembolso as t

SEMENTES_MLP = 3
CONJUNTOS = {
    'porte + fonte': ([], ['porte', 'orgao_superior']),
    'rico (porte + fonte + modalidade + V1)': (t.NUM, ['porte', 'orgao_superior', 'modalidade']),
}
GRADES = {
    'SVC RBF': [{'C': 0.3}, {'C': 1.0}],
    'MLP': [{'alpha': 1.0}, {'alpha': 10.0}],
}


class Media:
    """Média das probabilidades de vários pipelines já ajustados (sementes do MLP)."""

    def __init__(self, modelos):
        self.modelos = modelos

    def predict_proba(self, x):
        return np.mean([mod.predict_proba(x) for mod in self.modelos], axis=0)


def ajustar(nome, params, pp, num, cat):
    cats = ['trimestre_cat'] + cat
    pp = pp.assign(trimestre_cat=pp.trimestre.astype(str))
    if nome == 'SVC RBF':
        fabricas = [SVC(probability=True, gamma='scale', random_state=e.SEMENTE, **params)]
    else:
        # lbfgs, como no restante do E05: com adam + early stopping a rede superestimou o recebimento
        # (previa ~90% em 24 meses contra 51–72% reais).
        fabricas = [MLPClassifier(hidden_layer_sizes=(8,), solver='lbfgs', max_iter=2000,
                                  random_state=e.SEMENTE + s, **params) for s in range(SEMENTES_MLP)]
    ajustados = [e.pipeline(None, num, cats, estimador=f).fit(pp[num + cats], pp.y) for f in fabricas]
    return Media(ajustados), num, cats


def main():
    warnings.filterwarnings('ignore')
    sys.stdout.reconfigure(encoding='utf-8')
    pd.set_option('display.width', 250)
    base = e.carregar()
    base = base[base.valor_repasse > 0].reset_index(drop=True)
    b = t.preparar(base, pd.read_parquet(e.SILVER / 'transferegov_desembolsos.parquet'))
    b['municipio'] = b.codigo_ibge.astype(str)
    b = m.adicionar_porte(b)

    linhas = []
    for corte, (anos, teste_ano) in {**m.CORTES, 'checagem_2024': m.CHECAGEM}.items():
        pp = t.expandir(b[b.safra.isin(anos)])
        pp_int = t.expandir(b[b.safra.isin(anos[:-1])])
        val, teste = b[b.safra == anos[-1]], b[b.safra == teste_ano]
        for nome, grade in GRADES.items():
            for conjunto, (num, cat) in CONJUNTOS.items():
                inicio = time.time()
                notas = [m.avaliar(t.curvas(ajustar(nome, p, pp_int, num, cat), val), val)['brier_24 meses'] for p in grade]
                melhor = grade[int(np.argmin(notas))]
                S = t.curvas(ajustar(nome, melhor, pp, num, cat), teste)
                linhas.append({'corte': corte, 'modelo': f'{nome} ({conjunto})', 'params': str(melhor), **m.avaliar(S, teste)})
                print(f'{corte} {nome} {conjunto} {melhor} ({time.time() - inicio:.0f}s, {len(pp)} linhas)', flush=True)

    novos = pd.DataFrame(linhas)
    anteriores = pd.read_csv(e.SAIDA / 'modelo_1o_desembolso_validacao.csv')
    r = pd.concat([anteriores.drop(columns=[c for c in anteriores if c.startswith('reducao_')]), novos], ignore_index=True)
    for h in t.HORIZONTES:
        ref = r[r.modelo.str.startswith('Média simples')].set_index('corte')[f'brier_{h}']
        r[f'reducao_{h}'] = 1 - r[f'brier_{h}'] / r.corte.map(ref)
    r.to_csv(e.SAIDA / 'svc_mlp_desembolso.csv', index=False)

    cols = ['c_index', *[f'reducao_{h}' for h in t.HORIZONTES], 'erro_mediano_meses', 'dentro_faixa_p25_p75_%']
    print('\n##### Por corte')
    print(r[['corte', 'modelo', *cols]].round(3).to_string(index=False))
    print('\n##### Média dos três cortes')
    print(r.groupby('modelo', sort=False)[cols].mean().round(3).to_string())
    print('\n##### Calibração em 24 meses: previsto vs real (Kaplan–Meier)')
    print(r.pivot_table(index='modelo', columns='corte', values=['previsto_24 meses_%', 'real_km_24 meses_%'], sort=False)
          .round(1).to_string())


if __name__ == '__main__':
    main()
