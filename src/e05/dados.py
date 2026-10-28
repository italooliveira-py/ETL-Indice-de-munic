"""Coorte por instrumento e contexto anterior à assinatura; não altera o ETL legado."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.etl_municipal.core.armazenamento import preservar, sha256
from src.etl_municipal.core.contratos import ViolacaoContrato
from src.etl_municipal.core.http import obter_json
from src.etl_municipal.fontes import transferegov_discricionarias as disc
from src.etl_municipal.fontes import transferegov_especiais as esp
from src.etl_municipal.fontes import siconfi
from src.etl_municipal.fontes import snapshot

ROOT = Path(__file__).resolve().parents[2]
NUMERICAS = [
    'log_valor_assinatura', 'log_populacao_ibge', 'log_pib_pc_ibge',
    'historico_assinados_365d', 'log_desembolso_365d_percap', 'log_pix_365d_percap',
    'log_receita_dca_percap', 'dependencia_convenios_uniao', 'pessoal_rgf_pct',
]
CATEGORICAS = ['modalidade', 'orgao_superior', 'mes_assinatura']
PREDITORES = NUMERICAS + CATEGORICAS
FONTES_PUBLICACAO = {
    'pop_2021': ('2021-08-27', 'https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2021/'),
    'pop_2022': ('2023-06-28', 'https://www.ibge.gov.br/novo-portal-destaques.html?destaque=37016'),
    'pop_2024': ('2024-08-29', 'https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html'),
    'pib_2019': ('2021-12-17', 'https://www.ibge.gov.br/estatisticas/economicas/contas-nacionais/9088-produto-interno-bruto-dos-municipios.html?edicao=32575'),
    'pib_2020': ('2022-12-16', 'https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/35890-pandemia-derruba-o-pib-dos-grandes-centros-urbanos-em-2020'),
    'pib_2021': ('2023-12-15', 'https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/38683-pib-dos-municipios-mostra-que-economia-do-pais-continuou-a-se-desconcentrar-em-2021'),
}


def preparar_ibge(sessao, raiz: Path, *, offline=False):
    """Completa 2019 para ter PIB disponível já em janeiro/2022; restante é reaproveitado."""
    indice = raiz / 'ref/ibge_e05_bronze.json'
    caminhos = json.loads(indice.read_text(encoding='utf-8')) if indice.exists() else {}
    for nome, agregado, variavel in [('pib_2019', 5938, 37), ('pop_2019', 6579, 9324)]:
        if nome in caminhos:
            p = raiz / caminhos[nome]
            if not p.exists() or sha256(p.read_bytes()) != p.parent.name:
                raise ViolacaoContrato('Bronze IBGE E05 corrompido')
            continue
        if offline:
            raise ViolacaoContrato('Falta Bronze IBGE 2019 para a E05; executar preparar-dados sem --offline')
        url = (f'https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}/periodos/2019/'
               f'variaveis/{variavel}?localidades=N6[N3[25]]')
        _, conteudo = obter_json(sessao, url, {'max_tentativas': 4, 'timeout_segundos': 90})
        p = preservar(raiz, 'ibge_e05', nome + '.json', conteudo, url)
        caminhos[nome] = p.relative_to(raiz).as_posix()
        from etl_confiabilidade import salvar_json_atomico
        salvar_json_atomico(indice, caminhos)
    return {k: raiz / v for k, v in caminhos.items()}


def _serie_sidra(caminho, variavel, multiplicador=1):
    dados = json.loads(caminho.read_bytes())
    if len(dados) != 1 or str(dados[0].get('id')) != str(variavel):
        raise ViolacaoContrato('Variável IBGE inesperada')
    if variavel == 37 and 'mil' not in dados[0].get('unidade', '').lower():
        raise ViolacaoContrato('Unidade do PIB não é mil reais')
    linhas = [{'codigo_ibge': str(s['localidade']['id']),
               'valor': pd.to_numeric(s['serie'].get('2019'), errors='coerce') * multiplicador}
              for r in dados[0]['resultados'] for s in r['series']]
    quadro = pd.DataFrame(linhas)
    if (len(quadro) != 223 or quadro.codigo_ibge.duplicated().any() or not quadro.codigo_ibge.str.fullmatch(r'25\d{5}').all()
            or quadro.valor.isna().any() or (quadro.valor <= 0).any()):
        raise ViolacaoContrato('IBGE 2019 incompleto, duplicado ou inválido')
    return quadro.set_index('codigo_ibge').valor


def contexto_ibge(base, caminhos):
    """Disponibilidade por divulgação, não pelo ano de referência; versões atuais podem conter revisões."""
    linhas = []
    pib19, pop19 = _serie_sidra(caminhos['pib_2019'], 37, 1000), _serie_sidra(caminhos['pop_2019'], 9324)
    for codigo in pib19.index:
        linhas.append(dict(codigo_ibge=codigo, variavel='pib_pc_ibge', ano_referencia=2019,
                           valor=pib19[codigo] / pop19[codigo], data_disponibilidade=FONTES_PUBLICACAO['pib_2019'][0]))
    for ano in (2021, 2022, 2024):
        for r in base[(base.ano == ano) & base.populacao.notna()].itertuples():
            linhas.append(dict(codigo_ibge=r.codigo_ibge, variavel='populacao_ibge', ano_referencia=ano,
                               valor=r.populacao, data_disponibilidade=FONTES_PUBLICACAO[f'pop_{ano}'][0]))
    for ano in (2020, 2021):
        for r in base[(base.ano == ano) & base.pib.notna() & (base.populacao > 0)].itertuples():
            linhas.append(dict(codigo_ibge=r.codigo_ibge, variavel='pib_pc_ibge', ano_referencia=ano,
                               valor=r.pib / r.populacao, data_disponibilidade=FONTES_PUBLICACAO[f'pib_{ano}'][0]))
    quadro = pd.DataFrame(linhas)
    quadro['data_disponibilidade'] = pd.to_datetime(quadro.data_disponibilidade)
    return quadro


def rotular(instrumentos, desembolsos, data_carga, horizonte=90):
    """Alvo binário explícito; falta de seguimento não equivale à ausência de repasse."""
    if instrumentos.nr_convenio.isna().any() or instrumentos.nr_convenio.duplicated().any():
        raise ViolacaoContrato('Instrumentos com chave nula ou duplicada')
    if desembolsos.id_desembolso.duplicated().any():
        raise ViolacaoContrato('Desembolsos duplicados')
    base = instrumentos.copy()
    base['data_assinatura'] = pd.to_datetime(base.data_assinatura).dt.normalize()
    positivos = desembolsos[desembolsos.valor_desembolsado > 0].copy()
    positivos['data_desembolso'] = pd.to_datetime(positivos.data_desembolso).dt.normalize()
    primeiro = positivos.groupby('nr_convenio').data_desembolso.min()
    base['primeiro_repasse'] = base.nr_convenio.map(primeiro)
    base['fim_horizonte'] = base.data_assinatura + pd.to_timedelta(horizonte, unit='D')
    base['ano_coorte'] = base.data_assinatura.dt.year.astype('Int64')
    base['motivo_exclusao'] = pd.Series(pd.NA, index=base.index, dtype='string')
    base.loc[base.data_assinatura.isna(), 'motivo_exclusao'] = 'assinatura_ausente'
    base.loc[base.primeiro_repasse < base.data_assinatura, 'motivo_exclusao'] = 'repasse_anterior_assinatura'
    base.loc[base.fim_horizonte >= pd.Timestamp(data_carga).normalize(), 'motivo_exclusao'] = 'seguimento_90d_incompleto'
    base['sem_repasse_90d'] = (base.primeiro_repasse.isna() | (base.primeiro_repasse > base.fim_horizonte)).astype('Int64')
    base.loc[base.motivo_exclusao.notna(), 'sem_repasse_90d'] = pd.NA
    return base


def particoes(base, corte_validacao='2023-01-01', corte_teste='2024-01-01'):
    base = base.copy()
    elegivel = base.motivo_exclusao.isna()
    base['treino_validacao'] = elegivel & (base.ano_coorte == 2022) & (base.fim_horizonte < pd.Timestamp(corte_validacao))
    base['validacao'] = elegivel & (base.ano_coorte == 2023) & (base.fim_horizonte < pd.Timestamp(corte_teste))
    base['treino_final'] = elegivel & base.ano_coorte.isin([2022, 2023]) & (base.fim_horizonte < pd.Timestamp(corte_teste))
    base['teste'] = elegivel & (base.ano_coorte == 2024)
    base['exclusao_temporal'] = elegivel & base.ano_coorte.isin([2022, 2023]) & ~base.treino_final
    return base


def _anterior(tabela, codigo, corte, coluna_data):
    return tabela[(tabela.codigo_ibge == codigo) & (tabela[coluna_data] < corte)]


def adicionar_contexto(coorte, instrumentos, desembolsos, pagamentos_pix, ibge, dca, rgf,
                       coluna_corte='data_assinatura'):
    """Poucos mecanismos pré-declarados; nenhum campo de estado atual entra em X."""
    base = coorte.copy()
    for quadro in (dca, rgf):
        quadro['data_disponibilidade'] = pd.to_datetime(quadro.data_envio, utc=True).dt.tz_convert(None)
    registros = []
    for r in base.itertuples():
        codigo, corte = r.codigo_ibge, getattr(r, coluna_corte)
        linha = {'nr_convenio': r.nr_convenio, 'modalidade': r.modalidade,
                 'orgao_superior': r.orgao_superior, 'mes_assinatura': str(corte.month),
                 'log_valor_assinatura': np.log1p(r.valor_global_assinatura) if pd.notna(r.valor_global_assinatura) else np.nan}
        contexto = _anterior(ibge, codigo, corte, 'data_disponibilidade')
        valores = {}
        for var in ['populacao_ibge', 'pib_pc_ibge']:
            antes = contexto[contexto.variavel == var].sort_values('data_disponibilidade')
            ultimo = antes.iloc[-1] if len(antes) else None
            valores[var] = ultimo.valor if ultimo is not None else np.nan
            linha['log_' + var] = np.log1p(valores[var])
            linha['disponibilidade_' + var] = ultimo.data_disponibilidade if ultimo is not None else pd.NaT
            linha['ano_ref_' + var] = int(ultimo.ano_referencia) if ultimo is not None else pd.NA
        pop = valores['populacao_ibge']
        inicio = corte - pd.Timedelta(days=365)
        anteriores = _anterior(instrumentos, codigo, corte, 'data_assinatura')
        linha['historico_assinados_365d'] = int((anteriores.data_assinatura >= inicio).sum())
        for tabela, data, valor, destino in [
            (desembolsos, 'data_desembolso', 'valor_desembolsado', 'log_desembolso_365d_percap'),
            (pagamentos_pix, 'data_emissao_ob', 'valor_pago', 'log_pix_365d_percap'),
        ]:
            antes = _anterior(tabela, codigo, corte, data)
            janela = antes[(antes[data] >= inicio) & (antes[valor] > 0)]
            linha[destino] = np.log1p(janela[valor].sum() / pop) if pop > 0 else np.nan
        for tabela, fonte in [(dca, 'dca'), (rgf, 'rgf')]:
            antes = _anterior(tabela, codigo, corte, 'data_disponibilidade')
            antes = antes[antes.ano < corte.year].sort_values(['ano', 'data_disponibilidade'])
            ultimo = antes.iloc[-1] if len(antes) else None
            linha['disponibilidade_' + fonte] = ultimo.data_disponibilidade if ultimo is not None else pd.NaT
            linha['ano_ref_' + fonte] = int(ultimo.ano) if ultimo is not None else pd.NA
            if fonte == 'dca':
                receita = ultimo.receita_liquida if ultimo is not None else np.nan
                linha['log_receita_dca_percap'] = np.log1p(receita / pop) if pop > 0 and receita > 0 else np.nan
                linha['dependencia_convenios_uniao'] = ultimo.convenios_uniao / receita if ultimo is not None and receita > 0 else np.nan
            else:
                linha['pessoal_rgf_pct'] = ultimo.razao_declarada if ultimo is not None else np.nan
        registros.append(linha)
    resultado = base.merge(pd.DataFrame(registros), on='nr_convenio', validate='one_to_one', suffixes=('_auditoria', ''))
    for coluna in resultado.filter(like='disponibilidade_'):
        if (resultado[coluna] >= resultado[coluna_corte]).any():
            raise ViolacaoContrato(f'Informação posterior à assinatura: {coluna}')
    return resultado


def construir_base(raiz, caminhos_ibge):
    caminhos_disc, caminhos_esp, caminhos_siconfi = disc.verificar(raiz), esp.verificar(raiz), siconfi.verificar(raiz)
    d = disc.transformar(caminhos_disc)
    e = esp.transformar(caminhos_esp, d['ref/transferegov_cnpj_municipio'])
    instrumentos, desembolsos = d['silver/transferegov_instrumentos'], d['silver/transferegov_desembolsos']
    carga = instrumentos.data_carga.iloc[0]
    coorte = particoes(rotular(instrumentos, desembolsos, carga))
    coorte = coorte[coorte.ano_coorte.isin([2022, 2023, 2024])].copy()
    # Revalida os arquivos contra o manifesto original, antes de reaproveitar o contexto.
    snapshot.extrair(ROOT, raiz)
    base = pd.read_csv(ROOT / 'dados/bruto/base_municipio_ano_snapshot.csv', dtype={'codigo_ibge': 'string'})
    ibge = contexto_ibge(base, caminhos_ibge)
    fiscais = {**siconfi.transformar_dca(caminhos_siconfi), **siconfi.transformar_rgf(caminhos_siconfi)}
    resultado = adicionar_contexto(coorte, instrumentos, desembolsos, e['silver/transferegov_especiais_pagamentos'],
                                  ibge, fiscais['silver/siconfi_dca_receita_municipio'], fiscais['silver/siconfi_rgf_pessoal'])
    insumos = {**{'disc/' + k: v for k, v in caminhos_disc.items()}, **{'ibge/' + k: v for k, v in caminhos_ibge.items()}}
    for fonte, caminhos in [('especiais', caminhos_esp), ('siconfi', caminhos_siconfi)]:
        for k, lista in caminhos.items():
            for i, p in enumerate(lista if isinstance(lista, list) else [lista]):
                insumos[f'{fonte}/{k}/{i}'] = p
    manifesto = {'data_carga_transferegov': carga, 'hashes_bronze': {k: sha256(p.read_bytes()) for k, p in sorted(insumos.items())},
                 'hash_snapshot_contexto': sha256((ROOT / 'dados/bruto/base_municipio_ano_snapshot.csv').read_bytes()),
                 'fontes_disponibilidade_ibge': FONTES_PUBLICACAO, 'preditores': PREDITORES,
                 'nota_revisoes': 'Datas de eventos/divulgação controladas; valores públicos atuais podem ter revisões não reconstruíveis.'}
    return resultado, manifesto
