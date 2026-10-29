"""Em quantos % dos casos cada abordagem acerta o prazo até o 1º desembolso.

Três abordagens, todas aprendidas só com as safras anteriores ao ano de teste (2019 em diante):
- média geral: a curva média de todos os instrumentos;
- média por ministério: a curva média de cada órgão superior;
- modelo final: curva por porte do município e ministério.
Três formas de "acertar", nos cortes 2022, 2023 e 2024:
- prazo: o 1º desembolso real caiu a até ±6 meses do prazo mediano previsto (só quem já recebeu);
- faixa: caiu dentro da faixa provável prevista (p25–p75) (só quem já recebeu);
- 24 meses: acertou se recebe ou não em até 24 meses (prevê "sim" quando a chance é ≥ 50%;
  só quem já tem o desfecho de 24 meses conhecido).
Uso: python acerto_medias.py
"""
import sys
import warnings

import numpy as np
import pandas as pd

import experimento as e
import modelo_primeiro_desembolso as m
import tempo_primeiro_desembolso as t

ABORDAGENS = {'Média geral': [], 'Média por ministério': ['orgao_superior'], 'Modelo final (porte + ministério)': m.CATEGORICAS}


def acertos(S, teste):
    ok = teste.evento.to_numpy()
    real = teste.trimestres.to_numpy()
    mediana = m.quantil_trimestre(S, 0.5)
    p25, p75 = m.quantil_trimestre(S, 0.25), m.quantil_trimestre(S, 0.75)
    conhecido = (teste.evento & (teste.trimestres <= 8)) | (teste.trimestres > 8)
    recebeu_24 = (teste.evento & (teste.trimestres <= 8)).to_numpy()[conhecido.to_numpy()]
    preve_24 = (1 - S[:, 7] >= 0.5)[conhecido.to_numpy()]
    return {'n_receberam': int(ok.sum()),
            'acerto_prazo_6m_%': (np.abs(mediana[ok] - real[ok]) <= 2).mean() * 100,
            'acerto_faixa_%': ((real[ok] >= p25[ok]) & (real[ok] <= p75[ok])).mean() * 100,
            'n_24m': int(conhecido.sum()), 'acerto_24m_%': (recebeu_24 == preve_24).mean() * 100,
            'preve_sim_24m_%': preve_24.mean() * 100, 'real_sim_24m_%': recebeu_24.mean() * 100}


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
        teste = b[b.safra == teste_ano]
        for nome, cat in ABORDAGENS.items():
            c = m.escolher_c(b, anos, cat) if cat else 1.0
            linhas.append({'corte': corte, 'abordagem': nome, **acertos(t.curvas(m.ajustar(pp, cat, c), teste), teste)})
    r = pd.DataFrame(linhas)
    print('##### Por corte')
    print(r.round(1).to_string(index=False))
    print('\n##### Média dos três cortes')
    print(r.groupby('abordagem', sort=False)[['acerto_prazo_6m_%', 'acerto_faixa_%', 'acerto_24m_%']].mean().round(1).to_string())
    r.to_csv(e.SAIDA / 'acerto_medias.csv', index=False)


if __name__ == '__main__':
    main()
