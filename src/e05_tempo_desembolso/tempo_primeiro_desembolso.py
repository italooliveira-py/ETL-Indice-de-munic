"""Tempo até o 1º desembolso: modelo de risco em tempo discreto (logística por trimestre).

Por que assim: muitos instrumentos recentes ainda não receberam (censura). Em vez de descartá-los,
cada instrumento vira uma linha por trimestre desde a assinatura enquanto está "em risco"; o alvo
de cada linha é "recebeu o 1º desembolso neste trimestre". A logística estima a chance por
trimestre (hazard) e, encadeando os trimestres, sai a curva de "ainda não recebeu" S(t) de cada
instrumento: probabilidade de receber até 12/18/24 meses e o trimestre mediano previsto.

Saída de risco: 1º desembolso; ou fim da observação = min(data de carga, fim atual da vigência).
Instrumentos anulados nunca recebem: ficam em risco até o fim da vigência, o que faz o modelo
embutir a chance de nunca receber.

Validação temporal por safra (treino em safras antigas, teste na seguinte), contra:
- curva ingênua: só o trimestre (equivale a Kaplan–Meier do treino, sem variáveis);
- curva por modalidade e órgão superior.
Métricas: C-index (ordem de quem recebe antes), Brier nos horizontes de 12/18/24 meses (só
quem não foi censurado antes do horizonte), calibração (previsto médio vs Kaplan–Meier do teste)
e erro mediano em meses do trimestre previsto para quem já recebeu.
Uso: python tempo_primeiro_desembolso.py
"""
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import experimento as e
from alvos_falha import DATA_CARGA

TRIMESTRE = 91
MAX_TRIMESTRES = 20  # 5 anos
HORIZONTES = {'12 meses': 4, '18 meses': 6, '24 meses': 8}
CORTES = {
    'teste_2021': {'treino': [2017, 2018, 2019, 2020], 'teste': [2021]},
    'teste_2022': {'treino': [2017, 2018, 2019, 2020, 2021], 'teste': [2022]},
    'teste_2023': {'treino': [2018, 2019, 2020, 2021, 2022], 'teste': [2023]},
}
NUM, CAT = e.CONJUNTOS['V1_instrumento']
MODELOS = {
    'Ingênuo (só o trimestre)': ([], []),
    'Modalidade + órgão superior': ([], ['modalidade', 'orgao_superior']),
    'Logística V1': (NUM, CAT),
    'V1 + calendário + histórico do município': (NUM + ['log_dias_1o_municipio', 'sem_historico'], CAT + ['trimestre_calendario']),
}


def historico_municipio(b):
    """Mediana (log) dos dias até o 1º desembolso dos instrumentos anteriores do município, só os
    pagos ANTES da data de assinatura (conhecido no dia); vazio se não há nenhum."""
    pagos = b[b.evento].assign(data_1o=lambda d: d.data_assinatura + pd.to_timedelta(d.dias_evento, unit='D'))
    saida = np.full(len(b), np.nan)
    for cod, g in b.groupby('codigo_ibge'):
        p = pagos[pagos.codigo_ibge == cod]
        for pos, data in zip(g.index, g.data_assinatura):
            ant = p[p.data_1o < data]
            if len(ant):
                saida[b.index.get_loc(pos)] = np.log1p(ant.dias_evento.median())
    return saida


def preparar(base, desembolsos):
    primeiro = base.nr_convenio.map(desembolsos[desembolsos.valor_desembolsado > 0].groupby('nr_convenio').data_desembolso.min())
    b = base.copy()
    b['dias_evento'] = (primeiro - b.data_assinatura).dt.days.clip(lower=0)
    fim = np.minimum(b.data_fim_vigencia.fillna(DATA_CARGA), DATA_CARGA)
    b['dias_censura'] = (fim - b.data_assinatura).dt.days.clip(lower=1)
    b['evento'] = b.dias_evento.notna()
    b['tempo'] = np.where(b.evento, b.dias_evento, b.dias_censura)
    b['trimestres'] = np.minimum(np.floor(b.tempo / TRIMESTRE).astype(int) + 1, MAX_TRIMESTRES)
    b['evento'] &= np.floor(b.tempo / TRIMESTRE) < MAX_TRIMESTRES
    b['log_dias_1o_municipio'] = historico_municipio(b)
    b['sem_historico'] = b.log_dias_1o_municipio.isna().astype(float)
    return b


def expandir(b):
    """Uma linha por instrumento × trimestre em risco; y=1 no trimestre do 1º desembolso."""
    idx = np.repeat(b.index.to_numpy(), b.trimestres.to_numpy())
    pp = b.loc[idx].copy()
    pp['trimestre'] = pp.groupby(level=0).cumcount() + 1
    pp['y'] = (pp.evento & (pp.trimestre == pp.trimestres)).astype(int)
    pp['trimestre_calendario'] = _trimestre_calendario(pp.data_assinatura, pp.trimestre)
    return pp.reset_index(drop=True)


def _trimestre_calendario(assinatura, trimestre):
    """Trimestre do ano civil em que cai cada período (sazonalidade da liberação de recursos)."""
    datas = assinatura + pd.to_timedelta((np.asarray(trimestre) - 0.5) * TRIMESTRE, unit='D')
    return 'T' + datas.dt.quarter.astype(str)


def ajustar(pp, num, cat):
    cats = ['trimestre_cat'] + cat
    pp = pp.assign(trimestre_cat=pp.trimestre.astype(str))
    modelo = e.pipeline(None, num, cats, estimador=LogisticRegression(C=1.0, max_iter=5000))
    return modelo.fit(pp[num + cats], pp.y), num, cats


def curvas(ajuste, b):
    """S(t) para t = 1..MAX_TRIMESTRES: probabilidade de ainda não ter recebido ao fim de cada trimestre."""
    modelo, num, cats = ajuste
    grade = b.loc[np.repeat(b.index.to_numpy(), MAX_TRIMESTRES)].copy()
    trimestres = np.tile(np.arange(1, MAX_TRIMESTRES + 1), len(b))
    grade['trimestre_cat'] = trimestres.astype(str)
    grade['trimestre_calendario'] = _trimestre_calendario(grade.data_assinatura.reset_index(drop=True), trimestres).to_numpy()
    h = modelo.predict_proba(grade[num + cats])[:, 1].reshape(len(b), MAX_TRIMESTRES)
    return np.cumprod(1 - h, axis=1)


def kaplan_meier(trimestres, evento):
    s, curva = 1.0, []
    for t in range(1, MAX_TRIMESTRES + 1):
        em_risco = (trimestres >= t).sum()
        eventos = ((trimestres == t) & evento).sum()
        s *= 1 - eventos / em_risco if em_risco else 1
        curva.append(s)
    return np.array(curva)


def c_index(tempo, evento, risco):
    """Harrell: entre pares comparáveis, o de maior risco (receber antes) recebeu antes?"""
    tempo, evento, risco = map(np.asarray, (tempo, evento, risco))
    conc = total = 0.0
    for i in np.where(evento)[0]:
        comparaveis = tempo > tempo[i]
        total += comparaveis.sum()
        conc += (risco[i] > risco[comparaveis]).sum() + 0.5 * (risco[i] == risco[comparaveis]).sum()
    return conc / total


def main():
    warnings.filterwarnings('ignore')
    sys.stdout.reconfigure(encoding='utf-8')
    pd.set_option('display.width', 250)
    base = e.carregar()
    base = base[base.valor_repasse > 0].reset_index(drop=True)
    desemb = pd.read_parquet(e.SILVER / 'transferegov_desembolsos.parquet')
    b = preparar(base, desemb)

    print('##### Kaplan–Meier por safra: % que já recebeu o 1º desembolso até 12/18/24/36 meses')
    km = {s: 1 - kaplan_meier(g.trimestres.to_numpy(), g.evento.to_numpy()) for s, g in b[b.safra.between(2015, 2024)].groupby('safra')}
    print(pd.DataFrame({s: {h: round(c[q - 1] * 100, 1) for h, q in {**HORIZONTES, '36 meses': 12}.items()} for s, c in km.items()}).to_string(), '\n')

    linhas, calib = [], []
    for corte, anos in CORTES.items():
        treino, teste = b[b.safra.isin(anos['treino'])], b[b.safra.isin(anos['teste'])]
        pp = expandir(treino)
        km_teste = 1 - kaplan_meier(teste.trimestres.to_numpy(), teste.evento.to_numpy())
        for nome, (num, cat) in MODELOS.items():
            S = curvas(ajustar(pp, num, cat), teste)
            pago = 1 - S
            linha = {'corte': corte, 'modelo': nome, 'n_teste': len(teste), 'receberam': int(teste.evento.sum()),
                     'c_index': c_index(teste.tempo, teste.evento, pago[:, HORIZONTES['24 meses'] - 1])}
            for h, q in HORIZONTES.items():
                conhecido = teste.evento & (teste.trimestres <= q) | (teste.trimestres > q)
                y = (teste.evento & (teste.trimestres <= q))[conhecido].astype(int).to_numpy()
                linha[f'brier_{h}'] = np.mean((pago[conhecido.to_numpy(), q - 1] - y) ** 2)
                calib.append({'corte': corte, 'modelo': nome, 'horizonte': h,
                              'previsto_%': pago[:, q - 1].mean() * 100, 'kaplan_meier_teste_%': km_teste[q - 1] * 100})
            mediana_prev = (S <= 0.5).argmax(axis=1) + 1
            mediana_prev = np.where((S <= 0.5).any(axis=1), mediana_prev, MAX_TRIMESTRES + 1)
            ok = teste.evento.to_numpy()
            linha['erro_mediano_meses'] = np.median(np.abs(mediana_prev[ok] - teste.trimestres.to_numpy()[ok])) * 3
            linhas.append(linha)
        print(f'{corte} ok', flush=True)

    r = pd.DataFrame(linhas)
    for h in HORIZONTES:
        ingenuo = r[r.modelo == 'Ingênuo (só o trimestre)'].set_index('corte')[f'brier_{h}']
        r[f'reducao_{h}'] = 1 - r[f'brier_{h}'] / r.corte.map(ingenuo)
    print('\n##### Validação temporal: ordem (C-index), redução do Brier vs ingênuo por horizonte, erro em meses')
    print(r[['corte', 'modelo', 'n_teste', 'receberam', 'c_index', *[f'reducao_{h}' for h in HORIZONTES], 'erro_mediano_meses']]
          .round(3).to_string(index=False))
    print('\n##### Calibração: % que recebeu até o horizonte, previsto médio vs Kaplan–Meier do teste')
    print(pd.DataFrame(calib).pivot_table(index=['corte', 'modelo'], columns='horizonte',
                                          values=['previsto_%', 'kaplan_meier_teste_%']).round(1).to_string())
    r.to_csv(e.SAIDA / 'tempo_primeiro_desembolso.csv', index=False)


if __name__ == '__main__':
    main()
