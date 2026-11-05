"""Normalização isolada da MUNIC; não realiza coleta nem publica Gold."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from . import munic_catalogo


CORRIGIDAS_OFICIAIS = frozenset({'MREG0151', 'MREG0152', 'MREG0153', 'MCUL42'})


ESTADOS = frozenset({
    'observado', 'nao_informado', 'nao_se_aplica', 'resposta_negativa',
    'ausente_na_edicao', 'edicao_indisponivel', 'resposta_invalida', 'fora_periodo',
})


def _normalizar_valor(valor):
    if pd.isna(valor) or (isinstance(valor, str) and not valor.strip()):
        return None, 'nao_informado'
    texto = str(valor).strip().upper()
    if texto in {'NAO SE APLICA', 'N/A', 'NA'}:
        return None, 'nao_se_aplica'
    if texto in {'NAO', 'NÃO'}:
        return None, 'resposta_negativa'
    try:
        numero = float(str(valor).replace(',', '.'))
    except (TypeError, ValueError):
        return None, 'resposta_invalida'
    if not math.isfinite(numero) or numero < 0:
        return None, 'resposta_invalida'
    return int(numero) if numero.is_integer() else numero, 'observado'


def normalizar_observacoes(bruto: pd.DataFrame, edicao: int, referencia=None) -> pd.DataFrame:
    """Normaliza um fixture/extração longa e preserva o estado de cada resposta."""
    exigidas = {'codigo_ibge', 'municipio', 'uf', 'bloco', 'codigo_original', 'valor_original'}
    ausentes = exigidas - set(bruto.columns)
    if ausentes:
        raise ValueError(f'Colunas MUNIC ausentes: {sorted(ausentes)}')
    linhas = []
    for registro in bruto.to_dict('records'):
        codigo = str(registro['codigo_ibge']).strip()
        if len(codigo) != 7 or not codigo.isdigit() or registro['uf'] != 'PB':
            raise ValueError(f'Código MUNIC inválido ou fora da PB: {codigo}')
        definicao = munic_catalogo.definicao(edicao, registro['bloco'], registro['codigo_original'])
        valor, estado = _normalizar_valor(registro['valor_original'])
        linhas.append({
            'codigo_ibge': codigo,
            'municipio': registro['municipio'],
            'uf': registro['uf'],
            'ano_edicao_munic': int(edicao),
            'variavel': definicao['variavel'],
            'valor_original': registro['valor_original'],
            'valor_normalizado': valor,
            'tipo': definicao['tipo'],
            'unidade': definicao['unidade'],
            'status_observacao': estado,
            'codigo_original': registro['codigo_original'],
            'bloco_origem': registro['bloco'],
            'comparabilidade': definicao['comparabilidade'],
            'regra_harmonizacao': 'catalogo_versionado_por_edicao_bloco_codigo',
        })
    resultado = pd.DataFrame(linhas)
    if not set(resultado.status_observacao.dropna()) <= ESTADOS:
        raise ValueError('Estado MUNIC fora do contrato')
    return resultado


def ler_recursos_humanos(caminho, edicao: int) -> pd.DataFrame:
    """Lê o bloco oficial de RH usando códigos do dicionário, não posição de coluna."""
    quadro = pd.read_excel(caminho, sheet_name='Recursos humanos', dtype=object)
    por_nome = {str(col).strip().upper(): col for col in quadro.columns}
    codmun_col = next((col for chave, col in por_nome.items() if chave == 'CODMUN'), None)
    uf_col = next((col for chave, col in por_nome.items() if chave in {'UF', 'SIGLA UF'}), None)
    mun_col = next((col for chave, col in por_nome.items() if chave in {'MUN', 'NOME MUNIC'}), None)
    if not all((codmun_col, uf_col, mun_col)):
        raise ValueError('Leiaute MUNIC RH sem identificação municipal completa')
    codigos = munic_catalogo._CATALOGO.get('mapas_rh', {}).get(str(int(edicao)), {})
    colunas = {codigo: por_nome.get(codigo.upper()) for codigo in codigos}
    if any(coluna is None for coluna in colunas.values()):
        raise ValueError(f'Leiaute MUNIC RH {edicao} sem códigos catalogados: {colunas}')
    linhas = []
    for registro in quadro.to_dict('records'):
        uf_original = str(registro[uf_col]).strip().upper()
        if uf_original not in {'PB', 'PARAIBA', 'PARAÍBA'}:
            continue
        uf = 'PB'
        for codigo, coluna in colunas.items():
            linhas.append({
                'codigo_ibge': str(registro[codmun_col]).strip().split('.')[0],
                'municipio': registro[mun_col], 'uf': uf, 'bloco': 'recursos_humanos',
                'codigo_original': codigo, 'valor_original': registro[coluna],
            })
    return normalizar_observacoes(pd.DataFrame(linhas), int(edicao), referencia='arquivo_oficial')


def construir_silver_munic_versionado(
    observacoes: pd.DataFrame,
    *,
    versao_base: str,
    data_publicacao: str,
    arquivo_origem: str,
    sha256_origem: str,
) -> dict[str, pd.DataFrame]:
    """Adiciona proveniência de uma versão sem substituir outra versão existente."""
    if not versao_base or len(sha256_origem) != 64:
        raise ValueError('Versão e SHA-256 MUNIC são obrigatórios')
    if observacoes.empty:
        raise ValueError('Silver MUNIC não pode ser construído sem observações')
    quadro = observacoes.copy()
    quadro['versao_base'] = versao_base
    quadro['data_publicacao'] = pd.Timestamp(data_publicacao)
    quadro['data_disponibilidade'] = quadro['data_publicacao']
    quadro['data_publicacao_versao'] = quadro['data_publicacao']
    quadro['data_publicacao_edicao_original'] = quadro['data_publicacao']
    quadro['data_publicacao_arquivo_fisico'] = quadro['data_publicacao']
    quadro['data_disponibilidade_variavel'] = quadro['data_publicacao']
    quadro['versao_arquivo_fisico'] = versao_base
    quadro['status_afetada_errata'] = 'indeterminada'
    quadro['evidencia_disponibilidade_variavel'] = 'publicacao_oficial_da_edicao'
    quadro['precisao_data_disponibilidade'] = 'dia'
    quadro['arquivo_origem'] = arquivo_origem
    quadro['sha256_origem'] = sha256_origem
    quadro['status_temporal'] = 'disponivel_a_partir_da_publicacao'
    quadro.attrs['chave'] = ['codigo_ibge', 'ano_edicao_munic', 'versao_base', 'variavel']

    status = quadro.groupby(['codigo_ibge', 'municipio', 'uf', 'ano_edicao_munic', 'versao_base'], as_index=False).agg(
        status_resposta=('status_observacao', lambda serie: 'observado' if (serie == 'observado').any() else serie.iloc[0]),
        data_publicacao=('data_publicacao', 'first'),
        data_disponibilidade=('data_disponibilidade', 'first'),
        arquivo_origem=('arquivo_origem', 'first'),
        sha256_origem=('sha256_origem', 'first'),
        status_temporal=('status_temporal', 'first'),
    )
    status['data_publicacao_original'] = status['data_publicacao']
    status['data_publicacao_versao'] = status['data_publicacao']
    status['comparabilidade'] = 'catalogo_versionado'
    status.attrs['chave'] = ['codigo_ibge', 'ano_edicao_munic', 'versao_base']
    return {
        'silver/munic_observacoes_versao': quadro,
        'silver/munic_municipio_edicao_versao': status,
    }


def construir_silver_munic(raiz: Path) -> dict[str, pd.DataFrame]:
    """Lê o Bronze MUNIC persistente e produz Silver versionado e adotado."""
    from . import munic

    indice = json.loads((Path(raiz) / 'ref' / 'munic_bronze.json').read_text(encoding='utf-8'))
    versoes, edicoes = [], []
    for ano, meta in sorted(indice['edicoes'].items(), key=lambda par: int(par[0])):
        caminho = Path(raiz) / meta['arquivo']
        observacoes = ler_recursos_humanos(caminho, int(ano))
        tabelas = construir_silver_munic_versionado(
            observacoes,
            versao_base=meta['versao_base'],
            data_publicacao=meta['data_publicacao_versao'],
            arquivo_origem=meta['arquivo'],
            sha256_origem=meta['sha256'],
        )
        obs = tabelas['silver/munic_observacoes_versao']
        obs['data_publicacao_original'] = pd.Timestamp(meta['data_publicacao'])
        obs['data_publicacao_versao'] = pd.Timestamp(meta['data_publicacao_versao'])
        obs['data_publicacao_edicao_original'] = pd.Timestamp(meta['data_publicacao'])
        obs['data_publicacao_arquivo_fisico'] = pd.Timestamp(meta['data_publicacao_versao'])
        obs['versao_arquivo_fisico'] = meta['versao_base']
        corrigidas = set((meta.get('escopo_correcao_oficial') or '').split(',')) - {''}
        afetada = obs['codigo_original'].isin(corrigidas)
        obs['data_disponibilidade_variavel'] = obs['data_publicacao_versao']
        obs['data_disponibilidade_temporal'] = obs['data_disponibilidade_variavel']
        obs['status_afetada_errata'] = 'afetada'
        obs['status_temporal'] = 'indisponivel_antes_da_revisao'
        obs['motivo_temporal'] = 'variavel_corrigida_em_substituicao_oficial'
        obs['evidencia_disponibilidade_variavel'] = meta.get('url_nota_oficial') or 'nota_oficial_ibge'
        obs['precisao_data_disponibilidade'] = 'dia'
        nao_afetada = ~afetada
        obs.loc[nao_afetada, 'data_disponibilidade_variavel'] = obs.loc[nao_afetada, 'data_publicacao_original']
        obs.loc[nao_afetada, 'data_disponibilidade_temporal'] = obs.loc[nao_afetada, 'data_publicacao_original']
        obs.loc[nao_afetada, 'status_afetada_errata'] = 'nao_afetada'
        obs.loc[nao_afetada, 'status_temporal'] = 'apta_com_ressalva_documentada'
        obs.loc[nao_afetada, 'motivo_temporal'] = 'variavel_nao_listada_na_nota_de_correcao'
        obs.loc[nao_afetada, 'evidencia_disponibilidade_variavel'] = (
            'nota_oficial_ibge_delimita_correcao_a_' + (meta.get('escopo_correcao_oficial') or '').lower()
        )
        obs.loc[nao_afetada, 'precisao_data_disponibilidade'] = 'condicional_por_escopo_de_errata'
        obs['status_versao'] = meta['status_versao']
        obs['original_disponivel'] = meta['original_disponivel']
        obs['original_bytes_disponiveis'] = meta['original_bytes_disponiveis']
        obs['escopo_correcao_oficial'] = meta.get('escopo_correcao_oficial')
        obs['url_nota_oficial'] = meta.get('url_nota_oficial')
        versoes.append(obs)
        edicao = tabelas['silver/munic_municipio_edicao_versao']
        edicao['versao_adotada'] = meta['versao_base']
        edicao['data_publicacao_original'] = pd.Timestamp(meta['data_publicacao'])
        edicao['data_publicacao_versao'] = pd.Timestamp(meta['data_publicacao_versao'])
        edicao['data_disponibilidade_adotada'] = pd.Timestamp(meta['data_publicacao'])
        edicao['motivo_selecao_versao'] = 'revisao_oficial_atualmente_disponivel_com_nota_de_correcao'
        edicao['sha256_origem'] = meta['sha256']
        edicoes.append(edicao)
    observacoes = pd.concat(versoes, ignore_index=True)
    observacoes['valor_original'] = observacoes['valor_original'].astype('string')
    edicao = pd.concat(edicoes, ignore_index=True)
    observacoes.attrs['chave'] = ['codigo_ibge', 'ano_edicao_munic', 'versao_base', 'variavel']
    edicao.attrs['chave'] = ['codigo_ibge', 'ano_edicao_munic', 'versao_base']
    adotadas = observacoes.copy()
    adotadas['versao_adotada'] = adotadas['versao_base']
    adotadas['motivo_selecao_versao'] = 'versao_oficial_atualmente_disponivel'
    adotadas.attrs['chave'] = ['codigo_ibge', 'ano_edicao_munic', 'variavel']
    analitica_edicao = edicao.drop(columns=['versao_base']).drop_duplicates(
        ['codigo_ibge', 'ano_edicao_munic']
    )
    analitica_edicao.attrs['chave'] = ['codigo_ibge', 'ano_edicao_munic']
    return {
        'silver/munic_observacoes_versao': observacoes,
        'silver/munic_municipio_edicao_versao': edicao,
        'silver/munic_observacoes': adotadas,
        'silver/munic_municipio_edicao': analitica_edicao,
    }


def construir_painel_munic(
    observacoes_versao: pd.DataFrame, *, anos=range(2020, 2025), populacao: pd.DataFrame | None = None
) -> dict[str, pd.DataFrame]:
    """Seleciona, por variável, a versão MUNIC mais recente disponível no corte anual."""
    exigidas = {
        'codigo_ibge', 'municipio', 'uf', 'ano_edicao_munic', 'variavel', 'valor_publicado',
        'versao_base', 'data_publicacao', 'data_publicacao_original', 'arquivo_origem',
        'sha256_origem', 'status_observacao',
    }
    ausentes = exigidas - set(observacoes_versao.columns)
    if ausentes:
        raise ValueError(f'Colunas MUNIC versionadas ausentes: {sorted(ausentes)}')
    origem = observacoes_versao.copy()
    origem['data_publicacao'] = pd.to_datetime(origem['data_publicacao'])
    origem['data_publicacao_original'] = pd.to_datetime(origem['data_publicacao_original'])
    origem['_data_corte'] = pd.to_datetime(origem.get('data_disponibilidade_temporal', origem['data_publicacao']))
    linhas = []
    for ano in anos:
        corte = pd.Timestamp(year=int(ano), month=12, day=31)
        elegiveis = origem[origem._data_corte <= corte]
        if elegiveis.empty:
            continue
        escolhidas = (elegiveis.sort_values('_data_corte')
                      .drop_duplicates(['codigo_ibge', 'variavel'], keep='last'))
        for registro in escolhidas.to_dict('records'):
            status_temporal = registro.get('status_temporal')
            if pd.isna(status_temporal):
                status_temporal = {
                    'nao_afetada': 'apta_com_ressalva_documentada',
                    'afetada': 'indisponivel_antes_da_revisao',
                }.get(registro.get('status_afetada_errata'), 'elegivel_no_corte')
            regra_temporal = registro.get('regra_temporal')
            if pd.isna(regra_temporal):
                regra_temporal = 'ultima_versao_publicada_ate_31_de_dezembro'
            precisao_data = registro.get('precisao_data_disponibilidade')
            if pd.isna(precisao_data):
                precisao_data = 'dia'
            registro.update({
                'ano_fotografia': int(ano),
                'ano_edicao_origem': int(registro['ano_edicao_munic']),
                'versao_origem': registro['versao_base'],
                'data_disponibilidade_adotada': registro['_data_corte'],
                'precisao_data_disponibilidade': precisao_data,
                'defasagem_edicao': int(ano) - int(registro['ano_edicao_munic']),
                'status_temporal': status_temporal,
                'regra_temporal': regra_temporal,
            })
            linhas.append(registro)
    longo = pd.DataFrame(linhas)
    if longo.empty:
        longo = pd.DataFrame(columns=sorted(exigidas | {
            'ano_fotografia', 'ano_edicao_origem', 'versao_origem', 'data_disponibilidade_adotada',
            'precisao_data_disponibilidade', 'defasagem_edicao', 'status_temporal', 'regra_temporal',
        }))
    longo = longo.rename(columns={'valor_publicado': 'valor_publicado'})
    longo.attrs['chave'] = ['codigo_ibge', 'ano_fotografia', 'variavel']
    auditoria = longo.copy()
    auditoria.attrs['chave'] = ['codigo_ibge', 'ano_fotografia', 'variavel']
    auditoria.attrs['tipo_tabela'] = 'auditoria'
    auditoria.attrs['uso_analitico'] = False
    longo = longo[~longo['variavel'].isin(CORRIGIDAS_OFICIAIS)].copy()
    longo.attrs['tipo_tabela'] = 'analitica'
    longo.attrs['uso_analitico'] = True
    if not longo.empty:
        largo = longo.pivot_table(
            index=['codigo_ibge', 'municipio', 'uf', 'ano_fotografia'],
            columns='variavel', values='valor_publicado', aggfunc='first',
        ).reset_index()
    else:
        largo = pd.DataFrame(columns=['codigo_ibge', 'municipio', 'uf', 'ano_fotografia'])
    if not largo.empty:
        largo = largo.drop(columns=[col for col in CORRIGIDAS_OFICIAIS if col in largo.columns], errors='ignore')
        if {'pessoal_estatutario', 'pessoal_ativo'} <= set(largo.columns):
            largo['proporcao_pessoal_estatutario'] = (
                largo['pessoal_estatutario'] / largo['pessoal_ativo'].where(largo['pessoal_ativo'] > 0)
            )
        if populacao is not None:
            pop = populacao[['codigo_ibge', 'ano_fotografia', 'populacao']].copy()
            pop['codigo_ibge'] = pop['codigo_ibge'].astype(str)
            largo = largo.merge(pop, on=['codigo_ibge', 'ano_fotografia'], how='left', validate='one_to_one')
            valido = largo['populacao'].notna() & (largo['populacao'] > 0)
            largo['pessoal_ativo_por_mil_habitantes'] = pd.NA
            if 'pessoal_ativo' in largo:
                largo.loc[valido, 'pessoal_ativo_por_mil_habitantes'] = (
                    largo.loc[valido, 'pessoal_ativo'] / largo.loc[valido, 'populacao'] * 1000
                )
            largo['status_denominador_populacao'] = 'denominador_indisponivel'
            largo.loc[valido, 'status_denominador_populacao'] = 'denominador_temporalmente_valido'
    largo.attrs['chave'] = ['codigo_ibge', 'ano_fotografia']
    longo.attrs['chave'] = ['codigo_ibge', 'ano_fotografia', 'variavel']
    return {
        'gold/munic_capacidade_institucional_ano': largo,
        'gold/munic_disponibilidade_variavel': longo,
        'gold/munic_auditoria_disponibilidade_variavel': auditoria,
    }
