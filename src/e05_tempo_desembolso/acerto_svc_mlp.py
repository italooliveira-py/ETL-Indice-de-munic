"""% de acerto (mesmas medidas de acerto_medias.py) do SVC e do MLP no tempo até o 1º desembolso.

SVC: hiperparâmetros já escolhidos por corte em svc_mlp_desembolso.py (resultados/svc_mlp_desembolso.csv).
MLP: escolha aninhada do alpha com solver lbfgs (média de 3 sementes).
Inclui a largura média da faixa prevista (p25–p75), porque uma faixa larga acerta "de graça".
Uso: python acerto_svc_mlp.py
"""
import ast
import sys
import warnings

import numpy as np
import pandas as pd

import experimento as e
import modelo_primeiro_desembolso as m
import svc_mlp_desembolso as sm
import tempo_primeiro_desembolso as t
from acerto_medias import ABORDAGENS, acertos


def largura_faixa(S):
    return np.mean(m.quantil_trimestre(S, 0.75) - m.quantil_trimestre(S, 0.25)) * 3


def main():
    warnings.filterwarnings('ignore')
    sys.stdout.reconfigure(encoding='utf-8')
    pd.set_option('display.width', 250)
    base = e.carregar()
    base = base[base.valor_repasse > 0].reset_index(drop=True)
    b = t.preparar(base, pd.read_parquet(e.SILVER / 'transferegov_desembolsos.parquet'))
    b['municipio'] = b.codigo_ibge.astype(str)
    b = m.adicionar_porte(b)
    escolhidos = pd.read_csv(e.SAIDA / 'svc_mlp_desembolso.csv').dropna(subset=['params']).set_index(['corte', 'modelo']).params

    linhas = []
    for corte, (anos, teste_ano) in {**m.CORTES, 'checagem_2024': m.CHECAGEM}.items():
        pp = t.expandir(b[b.safra.isin(anos)])
        pp_int = t.expandir(b[b.safra.isin(anos[:-1])])
        val, teste = b[b.safra == anos[-1]], b[b.safra == teste_ano]
        curvas = {}
        for nome, cat in ABORDAGENS.items():
            c = m.escolher_c(b, anos, cat) if cat else 1.0
            curvas[nome] = t.curvas(m.ajustar(pp, cat, c), teste)
        for conjunto, (num, cat) in sm.CONJUNTOS.items():
            params = ast.literal_eval(escolhidos[(corte, f'SVC RBF ({conjunto})')])
            curvas[f'SVC ({conjunto})'] = t.curvas(sm.ajustar('SVC RBF', params, pp, num, cat), teste)
            notas = [m.avaliar(t.curvas(sm.ajustar('MLP', p, pp_int, num, cat), val), val)['brier_24 meses'] for p in sm.GRADES['MLP']]
            melhor = sm.GRADES['MLP'][int(np.argmin(notas))]
            curvas[f'MLP ({conjunto})'] = t.curvas(sm.ajustar('MLP', melhor, pp, num, cat), teste)
        brier_ref = m.avaliar(curvas['Média geral'], teste)['brier_24 meses']
        for nome, S in curvas.items():
            av = m.avaliar(S, teste)
            linhas.append({'corte': corte, 'abordagem': nome, **acertos(S, teste), 'largura_faixa_meses': largura_faixa(S),
                           'c_index': av['c_index'], 'reducao_brier_24m': 1 - av['brier_24 meses'] / brier_ref,
                           'previsto_24m_%': av['previsto_24 meses_%'], 'real_24m_%': av['real_km_24 meses_%']})
        print(f'{corte} ok', flush=True)
    r = pd.DataFrame(linhas)
    r.to_csv(e.SAIDA / 'acerto_svc_mlp.csv', index=False)
    print('\n##### Média dos três cortes')
    print(r.groupby('abordagem', sort=False)[['acerto_prazo_6m_%', 'acerto_faixa_%', 'largura_faixa_meses', 'acerto_24m_%',
                                              'c_index', 'reducao_brier_24m']].mean().round(3).to_string())
    print('\n##### Previsto vs real: % que recebe em 24 meses')
    print(r.pivot_table(index='abordagem', columns='corte', values=['previsto_24m_%', 'real_24m_%'], sort=False).round(1).to_string())


if __name__ == '__main__':
    main()
