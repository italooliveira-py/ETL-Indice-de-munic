"""Ridge vs lasso vs elastic net no tempo até o 1º desembolso, com município (n pequeno por nível).

Pergunta: a penalização certa resolve o problema dos municípios com poucos instrumentos?
- ridge (L2): encolhe cada município em direção à média (equivale a um efeito aleatório);
- lasso (L1): zera os municípios sem evidência (ficam na média) e mantém só os que se destacam;
- elastic net (L1+L2, metade cada).
Duas formas de tratar os municípios raros:
- agrupar (min_frequency=15 linhas instrumento × trimestre, como no restante do E05);
- sem agrupar (min_frequency=1): só a penalização decide quanto cada município se afasta da média.
C escolhido de forma aninhada (última safra do treino, Brier de 24 meses), mesmos cortes do modelo final.
Uso: python regularizacao_desembolso.py
"""
import sys
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

import experimento as e
import modelo_primeiro_desembolso as m
import tempo_primeiro_desembolso as t

GRADE_C = [0.01, 0.03, 0.1, 0.3, 1.0]
PENALIDADES = {'ridge': 0.0, 'elastic net': 0.5, 'lasso': 1.0}
CONJUNTOS = {
    'porte + fonte': (['porte', 'orgao_superior'], [15]),
    'município + fonte + modalidade': (['municipio', 'orgao_superior', 'modalidade'], [15, 1]),
    'porte + município + fonte + modalidade': (['porte', 'municipio', 'orgao_superior', 'modalidade'], [15, 1]),
}


def ajustar(pp, cat, c, l1_ratio, min_freq):
    cats = ['trimestre_cat'] + cat
    pp = pp.assign(trimestre_cat=pp.trimestre.astype(str))
    if l1_ratio == 0:
        estimador = LogisticRegression(C=c, max_iter=5000)
    else:
        estimador = LogisticRegression(C=c, l1_ratio=l1_ratio, solver='saga', max_iter=3000, tol=1e-3)
    prep = ColumnTransformer([('cat', OneHotEncoder(handle_unknown='infrequent_if_exist', min_frequency=min_freq), cats)])
    modelo = Pipeline([('prep', prep), ('modelo', estimador)]).fit(pp[cats], pp.y)
    return modelo, [], cats


def municipios_ativos(ajuste):
    """Quantos municípios têm coeficiente diferente de zero (afastam-se da média)."""
    modelo = ajuste[0]
    nomes = modelo.named_steps['prep'].get_feature_names_out()
    coef = modelo.named_steps['modelo'].coef_[0]
    mun = np.array(['municipio_' in n for n in nomes])
    return int((np.abs(coef[mun]) > 1e-6).sum()), int(mun.sum())


def main():
    warnings.filterwarnings('ignore')
    sys.stdout.reconfigure(encoding='utf-8')
    pd.set_option('display.width', 250)
    base = e.carregar()
    base = base[base.valor_repasse > 0].reset_index(drop=True)
    b = t.preparar(base, pd.read_parquet(e.SILVER / 'transferegov_desembolsos.parquet'))
    b['municipio'] = b.codigo_ibge.astype(str)
    b = m.adicionar_porte(b)
    print('instrumentos por município (2019–2024):', b[b.safra >= 2019].groupby('municipio').size().describe().round(1).to_dict())

    linhas = []
    for corte, (anos, teste_ano) in {**m.CORTES, 'checagem_2024': m.CHECAGEM}.items():
        pp = t.expandir(b[b.safra.isin(anos)])
        pp_int = t.expandir(b[b.safra.isin(anos[:-1])])
        val, teste = b[b.safra == anos[-1]], b[b.safra == teste_ano]
        S_ref = t.curvas(m.ajustar(pp, [], 1.0), teste)
        brier_ref = m.avaliar(S_ref, teste)['brier_24 meses']
        for conjunto, (cat, freqs) in CONJUNTOS.items():
            for mf in freqs:
                for pen, l1 in PENALIDADES.items():
                    inicio = time.time()
                    notas = {c: m.avaliar(t.curvas(ajustar(pp_int, cat, c, l1, mf), val), val)['brier_24 meses'] for c in GRADE_C}
                    c = min(notas, key=notas.get)
                    aj = ajustar(pp, cat, c, l1, mf)
                    av = m.avaliar(t.curvas(aj, teste), teste)
                    ativos, total = municipios_ativos(aj) if 'municipio' in cat else (np.nan, np.nan)
                    linhas.append({'corte': corte, 'conjunto': conjunto, 'min_freq': mf, 'penalidade': pen, 'C': c,
                                   'c_index': av['c_index'], 'reducao_brier_24m': 1 - av['brier_24 meses'] / brier_ref,
                                   'municipios_ativos': ativos, 'municipios_no_modelo': total})
                    print(f'{corte} | {conjunto} | mf={mf} | {pen} C={c} | C-index {av["c_index"]:.3f} '
                          f'| Brier24 {linhas[-1]["reducao_brier_24m"]:+.1%} | mun {ativos}/{total} ({time.time() - inicio:.0f}s)', flush=True)

    r = pd.DataFrame(linhas)
    r.to_csv(e.SAIDA / 'regularizacao_desembolso.csv', index=False)
    print('\n##### Média dos três cortes')
    print(r.groupby(['conjunto', 'min_freq', 'penalidade'], sort=False)[['c_index', 'reducao_brier_24m', 'municipios_ativos',
                                                                         'municipios_no_modelo']].mean().round(3).to_string())
    print('\n##### Redução do Brier 24m por corte')
    print(r.pivot_table(index=['conjunto', 'min_freq', 'penalidade'], columns='corte', values='reducao_brier_24m', sort=False)
          .round(3).to_string())


if __name__ == '__main__':
    main()
