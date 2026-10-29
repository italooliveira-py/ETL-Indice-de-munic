"""Modelo final: tempo até o 1º desembolso, curva média por porte do município e fonte do recurso.

Alvo: em cada trimestre desde a assinatura, enquanto o instrumento ainda não recebeu, "recebe o
1º desembolso neste trimestre?" (0/1). Encadeando os trimestres sai a curva S(t) = chance de
ainda não ter recebido, e dela: P(receber até 12/18/24 meses), mediana e faixa (p25–p75) do prazo.
Variáveis: trimestre desde a assinatura (curva de base), porte do município (faixa de população,
IBGE) e órgão superior (fonte do recurso). É, na prática, uma média ajustada por porte e fonte:
venceu pela navalha de Occam o modelo com município e modalidade, que tinha o mesmo desempenho.
Regime recente: safras 2019 em diante. Regularização (C) escolhida na última safra do treino de
cada corte, sem tocar no teste.

Saídas em resultados/: modelo_1o_desembolso_validacao.csv, _referencia.csv, _municipios.csv, _pendentes.csv
Uso: python modelo_primeiro_desembolso.py
"""
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import experimento as e
import tempo_primeiro_desembolso as t
from alvos_falha import DATA_CARGA, SITUACOES_FALHA

CATEGORICAS = ['porte', 'orgao_superior']
COMPARACAO = ['municipio', 'orgao_superior', 'modalidade']
FAIXAS_PORTE = [0, 10_000, 20_000, 50_000, 100_000, np.inf]
ROTULOS_PORTE = ['até 10 mil', '10–20 mil', '20–50 mil', '50–100 mil', 'acima de 100 mil']
GRADE_C = [0.03, 0.1, 0.3, 1.0]
CORTES = {'teste_2022': ([2019, 2020, 2021], 2022), 'teste_2023': ([2019, 2020, 2021, 2022], 2023)}
CHECAGEM = ([2019, 2020, 2021, 2022, 2023], 2024)
FINAL = [2019, 2020, 2021, 2022, 2023, 2024]
MUNICIPIOS = {'2512101': 'Pombal', '2507507': 'João Pessoa', '2504009': 'Campina Grande',
              '2510808': 'Patos', '2503704': 'Cajazeiras', '2516201': 'Sousa'}
FONTE_REFERENCIA = 'MINISTERIO DAS CIDADES'


def adicionar_porte(b):
    """Faixa de população do município pela população mais recente no Silver do IBGE."""
    ibge = pd.read_parquet(e.SILVER / 'ibge.parquet').dropna(subset=['populacao']).sort_values('ano')
    populacao = ibge.groupby(ibge.codigo_ibge.astype(str)).populacao.last()
    b = b.copy()
    b['populacao'] = b.municipio.map(populacao)
    b['porte'] = pd.cut(b.populacao, FAIXAS_PORTE, labels=ROTULOS_PORTE).astype(str)
    return b


def ajustar(pp, cat, c):
    cats = ['trimestre_cat'] + cat
    pp = pp.assign(trimestre_cat=pp.trimestre.astype(str))
    modelo = e.pipeline(None, [], cats, estimador=LogisticRegression(C=c, max_iter=5000))
    return modelo.fit(pp[cats], pp.y), [], cats


def quantil_trimestre(S, nivel):
    """Primeiro trimestre em que a chance de já ter recebido passa de `nivel` (21 = depois de 5 anos)."""
    passou = (1 - S) >= nivel
    return np.where(passou.any(axis=1), passou.argmax(axis=1) + 1, t.MAX_TRIMESTRES + 1)


def avaliar(S, teste):
    pago = 1 - S
    saida = {'n': len(teste), 'receberam': int(teste.evento.sum()),
             'c_index': t.c_index(teste.tempo, teste.evento, pago[:, 7])}
    km = 1 - t.kaplan_meier(teste.trimestres.to_numpy(), teste.evento.to_numpy())
    for h, q in t.HORIZONTES.items():
        conhecido = ((teste.evento & (teste.trimestres <= q)) | (teste.trimestres > q)).to_numpy()
        y = (teste.evento & (teste.trimestres <= q)).to_numpy()[conhecido].astype(int)
        saida[f'brier_{h}'] = np.mean((pago[conhecido, q - 1] - y) ** 2)
        saida[f'previsto_{h}_%'] = pago[:, q - 1].mean() * 100
        saida[f'real_km_{h}_%'] = km[q - 1] * 100
    ok = teste.evento.to_numpy()
    real = teste.trimestres.to_numpy()[ok]
    mediana = quantil_trimestre(S, 0.5)[ok]
    p25, p75 = quantil_trimestre(S, 0.25)[ok], quantil_trimestre(S, 0.75)[ok]
    saida['erro_mediano_meses'] = np.median(np.abs(mediana - real)) * 3
    saida['dentro_faixa_p25_p75_%'] = ((real >= p25) & (real <= p75)).mean() * 100
    return saida


def escolher_c(b, anos, cat):
    pp = t.expandir(b[b.safra.isin(anos[:-1])])
    val = b[b.safra == anos[-1]]
    notas = {c: avaliar(t.curvas(ajustar(pp, cat, c), val), val)['brier_24 meses'] for c in GRADE_C}
    return min(notas, key=notas.get)


def validar(b):
    linhas = []
    for corte, (anos, teste_ano) in {**CORTES, 'checagem_2024': CHECAGEM}.items():
        pp = t.expandir(b[b.safra.isin(anos)])
        teste = b[b.safra == teste_ano]
        variantes = (('Média simples (só o tempo)', []), ('Média por porte', ['porte']),
                     ('Final: média por porte e fonte', CATEGORICAS),
                     ('Comparação: município + fonte + modalidade', COMPARACAO))
        for nome, cat in variantes:
            c = escolher_c(b, anos, cat) if cat else 1.0
            linhas.append({'corte': corte, 'modelo': nome, 'C': c, **avaliar(t.curvas(ajustar(pp, cat, c), teste), teste)})
        print(f'{corte} ok', flush=True)
    r = pd.DataFrame(linhas)
    for h in t.HORIZONTES:
        ref = r[r.modelo.str.startswith('Média simples')].set_index('corte')[f'brier_{h}']
        r[f'reducao_{h}'] = 1 - r[f'brier_{h}'] / r.corte.map(ref)
    return r


def curva_anulacao(b):
    """Falha final entre os que ainda não tinham recebido até cada trimestre (safras maduras 2015–2019)."""
    m = b[b.safra.between(2015, 2019) & b.falha_contratual.notna()]
    return {q: m[~(m.evento & (m.trimestres <= q))].falha_contratual.astype(float).mean() for q in range(0, t.MAX_TRIMESTRES + 1)}


def _resumir_curva(S):
    return pd.DataFrame({'receber_12m_%': (1 - S[:, 3]) * 100, 'receber_24m_%': (1 - S[:, 7]) * 100,
                         'mediana_meses': quantil_trimestre(S, 0.5) * 3,
                         'faixa_p25_p75_meses': [f'{a * 3}–{z * 3}' for a, z in zip(quantil_trimestre(S, .25), quantil_trimestre(S, .75))]})


def aplicar(b, c):
    recentes = b[b.safra.isin(FINAL)]
    ajuste = ajustar(t.expandir(recentes), CATEGORICAS, c)

    # Régua de referência: porte × fonte (fontes com ≥ 30 instrumentos no período).
    fontes = recentes.orgao_superior.value_counts()
    fontes = fontes[fontes >= 30].index
    grade = pd.MultiIndex.from_product([ROTULOS_PORTE, fontes], names=['porte', 'orgao_superior']).to_frame(index=False).assign(data_assinatura=pd.Timestamp('2025-01-01'))
    referencia = pd.concat([grade, _resumir_curva(t.curvas(ajuste, grade))], axis=1)

    # Municípios selecionados: porte e curva para um instrumento da fonte de referência.
    municipios = recentes.groupby('municipio').agg(n=('nr_convenio', 'size'), populacao=('populacao', 'first'),
                                                   porte=('porte', 'first')).reset_index()
    municipios = municipios.assign(orgao_superior=FONTE_REFERENCIA, data_assinatura=pd.Timestamp('2025-01-01'))
    municipios = pd.concat([municipios, _resumir_curva(t.curvas(ajuste, municipios))], axis=1)
    hist = recentes[recentes.evento].groupby('municipio').dias_evento.median() / 30.4
    municipios['mediana_real_meses'] = municipios.municipio.map(hist).round(0)

    # Pendentes hoje: ainda sem desembolso, sem falha e com vigência ativa na data de carga.
    pend = b[~b.evento & ~b.situacao.isin(SITUACOES_FALHA) & (b.data_fim_vigencia > DATA_CARGA) & (b.safra >= 2019)].copy()
    pend['idade_trim'] = np.clip(((DATA_CARGA - pend.data_assinatura).dt.days // t.TRIMESTRE).astype(int), 0, t.MAX_TRIMESTRES - 4)
    Sp = np.hstack([np.ones((len(pend), 1)), t.curvas(ajuste, pend)])
    i = pend.idade_trim.to_numpy()
    linhas = np.arange(len(pend))
    pend['receber_prox_6m_%'] = (1 - Sp[linhas, i + 2] / Sp[linhas, i]) * 100
    pend['receber_prox_12m_%'] = (1 - Sp[linhas, i + 4] / Sp[linhas, i]) * 100
    pend['anulacao_historica_%'] = pend.idade_trim.map(curva_anulacao(b)) * 100
    pend['idade_meses'] = ((DATA_CARGA - pend.data_assinatura).dt.days / 30.4).round(0)
    return referencia, municipios, pend


def main():
    warnings.filterwarnings('ignore')
    sys.stdout.reconfigure(encoding='utf-8')
    pd.set_option('display.width', 250)
    base = e.carregar()
    base = base[base.valor_repasse > 0].reset_index(drop=True)
    b = t.preparar(base, pd.read_parquet(e.SILVER / 'transferegov_desembolsos.parquet'))
    b['municipio'] = b.codigo_ibge.astype(str)
    b = adicionar_porte(b)

    r = validar(b)
    cols = ['corte', 'modelo', 'C', 'n', 'receberam', 'c_index', *[f'reducao_{h}' for h in t.HORIZONTES],
            'erro_mediano_meses', 'dentro_faixa_p25_p75_%']
    print('\n##### Validação temporal')
    print(r[cols].round(3).to_string(index=False))
    print('\n##### Média dos três cortes')
    print(r.groupby('modelo', sort=False)[['c_index', *[f'reducao_{h}' for h in t.HORIZONTES], 'erro_mediano_meses',
                                           'dentro_faixa_p25_p75_%']].mean().round(3).to_string())
    print('\n##### Calibração: % que recebeu até o horizonte, previsto vs real (Kaplan–Meier)')
    print(r[['corte', 'modelo', *[f'{k}_{h}_%' for h in t.HORIZONTES for k in ('previsto', 'real_km')]]].round(1).to_string(index=False))
    r.to_csv(e.SAIDA / 'modelo_1o_desembolso_validacao.csv', index=False)

    c_final = r[(r.corte == 'teste_2023') & r.modelo.str.startswith('Final')].C.iloc[0]
    referencia, municipios, pend = aplicar(b, c_final)
    referencia.to_csv(e.SAIDA / 'modelo_1o_desembolso_referencia.csv', index=False)
    municipios.to_csv(e.SAIDA / 'modelo_1o_desembolso_municipios.csv', index=False)
    pend.to_csv(e.SAIDA / 'modelo_1o_desembolso_pendentes.csv', index=False)

    print(f'\n##### Régua de referência: porte × fonte (C = {c_final})')
    ref = referencia.assign(fonte=referencia.orgao_superior.str[:32])
    print(ref.pivot(index='fonte', columns='porte', values='mediana_meses')[ROTULOS_PORTE].to_string())
    print('\n% que recebe em 24 meses')
    print(ref.pivot(index='fonte', columns='porte', values='receber_24m_%')[ROTULOS_PORTE].round(0).to_string())

    print(f'\n##### Municípios selecionados (fonte: {FONTE_REFERENCIA})')
    sel = municipios[municipios.municipio.isin(MUNICIPIOS)].assign(nome=lambda d: d.municipio.map(MUNICIPIOS))
    print(sel[['nome', 'populacao', 'porte', 'n', 'receber_12m_%', 'receber_24m_%', 'mediana_meses', 'faixa_p25_p75_meses',
               'mediana_real_meses']].round(1).to_string(index=False))

    print('\n##### Pendentes hoje (sem desembolso, vigentes) nos municípios selecionados')
    ps = pend[pend.municipio.isin(MUNICIPIOS)].assign(nome=lambda d: d.municipio.map(MUNICIPIOS),
                                                      orgao=lambda d: d.orgao_superior.str[:30], modal=lambda d: d.modalidade.str[:12])
    print(ps.sort_values(['nome', 'idade_meses'])[['nome', 'nr_convenio', 'safra', 'modal', 'orgao', 'valor_repasse', 'idade_meses',
                                                   'receber_prox_6m_%', 'receber_prox_12m_%', 'anulacao_historica_%']]
          .round(1).to_string(index=False))
    print(f'\nTotal de pendentes na PB: {len(pend)}')


if __name__ == '__main__':
    main()
