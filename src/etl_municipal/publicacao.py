"""Constrói e publica uma geração validada; CURRENT.json aponta a versão íntegra."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import pandas as pd

from etl_confiabilidade import salvar_json_atomico
from . import __version__
from .core.armazenamento import sha256
from .core.contratos import validar_numerica, validar_painel, validar_tabela, ViolacaoContrato

COLUNAS_OBRAS = {
    'cobertura_obrasgov', 'status_coleta_api', 'status_atribuicao_territorial',
    'status_agregado', 'cobertura_atribuicao', 'valor_observado_total_obras',
    'total_obras', 'obras_paradas', 'valor_obras_paradas', 'percentual_execucao_medio',
    'obras_sem_estudo_viabilidade', 'taxa_obras_paradas',
}
GRUPOS = {
    'ibge': ['populacao', 'pib', 'pib_per_capita'],
    'siconfi': ['populacao_siconfi', 'receita_total_realizada', 'transferencias_correntes_realizadas',
                'despesa_total_liquidada', 'despesa_pessoal_liquidada', 'investimentos_liquidados',
                'restos_pagar_processados', 'restos_pagar_nao_processados', 'caixa_equivalentes',
                'restos_pagar_total', 'dependencia_transferencias', 'investimento_per_capita',
                'restos_pagar_sobre_receita', 'caixa_sobre_receita', 'pressao_pessoal_proxy',
                'resultado_orcamentario_proxy'],
    'pncp': ['total_contratacoes', 'valor_estimado_contratacoes', 'valor_homologado_contratacoes',
             'contratacoes_similares', 'valor_contratacoes_similares'],
    'tse_eleitoral': ['ano_fotografia', 'continuidade_partidaria_pleito', 'ano_eleicao_origem_ciclo',
                       'numero_ano_ciclo_eleitoral', 'numero_ano_gestao_atual',
                       'partido_prefeito_no_pleito_origem', 'origem_gestao', 'status_transicao'],
}


def construir(base, eventos, referencia, territorial=None):
    universo = set(referencia.codigo_ibge)
    validar_tabela(referencia, ['codigo_ibge'], universo, completa=True)
    if len(universo) != 223:
        raise ViolacaoContrato('Publicação PB exige 223 municípios')
    validar_painel(base, universo, list(range(2020, 2025)))
    validar_tabela(eventos, ['id_projeto_investimento'], universo)
    validar_tabela(eventos, ['codigo_ibge', 'id_projeto_investimento'], universo)
    gold = base.drop(columns=list(COLUNAS_OBRAS), errors='ignore').copy()
    # Nomes oficiais corrigem apenas o rótulo, nunca a chave ou o valor medido.
    gold = gold.drop(columns=['municipio', 'uf']).merge(referencia, on='codigo_ibge', validate='many_to_one')
    gold['elegivel_janela_mvp'] = gold.ano.between(2020, 2023)
    # Restrição explícita do MVP: não estimar PIB 2024 nem carregar seu derivado.
    for coluna in ['pib', 'pib_per_capita']:
        if coluna in gold:
            gold.loc[gold.ano == 2024, coluna] = float('nan')
    for fonte, colunas in GRUPOS.items():
        disponiveis = [c for c in colunas if c in gold]
        alguma = gold[disponiveis].notna().any(axis=1)
        todas = gold[disponiveis].notna().all(axis=1)
        gold['status_' + fonte] = 'indisponivel'
        gold.loc[alguma, 'status_' + fonte] = 'parcial'
        gold.loc[todas, 'status_' + fonte] = 'observado'
        cobertura = 'cobertura_' + fonte
        if cobertura in gold:
            gold.loc[alguma & ~gold[cobertura].isin(['completa', 'sem_registros_confirmado']),
                     'status_' + fonte] = 'parcial'
        if fonte == 'pncp':
            gold.loc[gold.ano < 2022, 'status_pncp'] = 'fora_periodo'
    gold['status_pib'] = gold.pib.notna().map({True: 'observado', False: 'indisponivel'})
    gold.loc[gold.ano == 2024, 'status_pib'] = 'fora_periodo'
    for coluna in ['populacao', 'pib', 'total_contratacoes', 'valor_estimado_contratacoes']:
        validar_numerica(gold, coluna)
    gold = gold.sort_values(['codigo_ibge', 'ano']).reset_index(drop=True)
    tabelas = {'gold/base_municipio_ano': gold,
               'gold/base_municipio_ano_mvp': gold[gold.elegivel_janela_mvp].reset_index(drop=True),
               'silver/eventos_obrasgov': eventos.sort_values('id_projeto_investimento').reset_index(drop=True),
               'ref/municipios_pb': referencia.sort_values('codigo_ibge').reset_index(drop=True)}
    auditoria = []
    observacoes = []
    for fonte, colunas in GRUPOS.items():
        existentes = [c for c in colunas if c in gold]
        tabelas['silver/' + fonte] = gold[['codigo_ibge', 'ano', *existentes, 'status_' + fonte]].copy()
        for coluna in existentes:
            status = gold[coluna].notna().map({True: 'observado', False: 'indisponivel'})
            status.loc[gold['status_' + fonte] == 'fora_periodo'] = 'fora_periodo'
            cobertura = 'cobertura_' + fonte
            if cobertura in gold:
                status.loc[gold[coluna].notna() & ~gold[cobertura].isin(['completa', 'sem_registros_confirmado'])] = 'parcial'
            if coluna in ['pib', 'pib_per_capita']:
                status.loc[gold.ano == 2024] = 'fora_periodo'
            if fonte == 'pncp':
                confirmado = ((gold.total_contratacoes == 0) &
                              (gold.cobertura_pncp == 'completa') & (gold[coluna] == 0))
                status.loc[confirmado] = 'sem_registro_confirmado'
            detalhe = gold[['codigo_ibge', 'ano']].copy()
            detalhe['fonte'] = fonte
            detalhe['variavel'] = coluna
            detalhe['valor'] = gold[coluna].astype('string')
            detalhe['status'] = status
            detalhe['data_disponibilidade'] = pd.Series(pd.NA, index=gold.index, dtype='string')
            observacoes.append(detalhe)
            for ano, grupo in gold.groupby('ano'):
                auditoria.append({'fonte': fonte, 'variavel': coluna, 'ano': int(ano),
                                  'municipios': len(grupo), 'observacoes_validas': int(grupo[coluna].notna().sum()),
                                  'cobertura': float(grupo[coluna].notna().mean()),
                                  'data_disponibilidade': None,
                                  'status_temporal': 'pendente_validacao_publicacao'})
    tabelas['gold/auditoria_cobertura'] = pd.DataFrame(auditoria)
    tabelas['silver/observacoes_municipio_ano'] = pd.concat(observacoes, ignore_index=True)
    if territorial is not None:
        validar_tabela(territorial, ['codigo_ibge'], universo, completa=True)
        tabelas['silver/ibge_territorial'] = territorial
        tabelas['gold/base_municipio'] = territorial
    else:
        estatico = referencia.copy()
        estatico['status_ibge_territorial'] = 'indisponivel'
        tabelas['gold/base_municipio'] = estatico
    return tabelas


def _parquet_atomico(quadro, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destino.parent, suffix='.parquet', delete=False) as temp:
        temporario = Path(temp.name)
    try:
        quadro.to_parquet(temporario, index=False, engine='pyarrow', compression='snappy')
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)


def publicar(tabelas, raiz: Path, proveniencia: dict):
    # Identifica a geração pelos bytes Parquet, incluindo tipos e ordem estável.
    conteudos = {nome: quadro.to_parquet(index=False, engine='pyarrow', compression='snappy')
                 for nome, quadro in sorted(tabelas.items())}
    hashes = {nome: sha256(conteudo) for nome, conteudo in conteudos.items()}
    identidade = {'versao_pipeline': __version__, 'hashes': hashes, 'proveniencia': proveniencia}
    versao = sha256(json.dumps(identidade, sort_keys=True).encode())[:20]
    pasta = raiz / 'gold' / 'versoes' / versao
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, conteudo in conteudos.items():
        destino = pasta / (nome + '.parquet')
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists():
            if sha256(destino.read_bytes()) != hashes[nome]:
                raise ViolacaoContrato(f'Geração publicada corrompida: {nome}')
        else:
            with destino.open('xb') as arquivo:
                arquivo.write(conteudo)
    manifesto = {**identidade, 'versao_gold': versao,
                 'linhas': {nome: len(quadro) for nome, quadro in tabelas.items()},
                 'produto': 'indice de contexto municipal para execucao de projetos',
                 'apto_para_treino_temporal': False,
                 'pendencias': ['Datas públicas de disponibilidade das variáveis legadas',
                                'RGF', 'Transferegov', 'MUNIC', 'SINISA', 'MapBiomas',
                                'Bioma por interseção espacial e tipologia territorial']}
    salvar_json_atomico(pasta / 'manifesto.json', manifesto)
    # Atalhos convenientes; consumidores transacionais devem seguir CURRENT.json.
    for nome, quadro in tabelas.items():
        _parquet_atomico(quadro, raiz / (nome + '.parquet'))
    salvar_json_atomico(raiz / 'gold' / 'CURRENT.json',
                       {'versao': versao, 'manifesto': f'versoes/{versao}/manifesto.json'})
    return manifesto
