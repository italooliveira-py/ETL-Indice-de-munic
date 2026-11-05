"""Exportação determinística do painel Gold para consumo analítico/visual."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


NOME_PAINEL = 'painel_municipio_ano_2020_2024'
COLUNAS_ID = ['codigo_ibge', 'municipio', 'uf', 'ano']
COLUNAS_FISCAL = [
    'populacao_siconfi', 'receita_total_realizada',
    'transferencias_correntes_realizadas', 'despesa_total_liquidada',
    'despesa_pessoal_liquidada', 'investimentos_liquidados',
    'restos_pagar_processados', 'restos_pagar_nao_processados',
    'caixa_equivalentes', 'restos_pagar_total', 'dependencia_transferencias',
    'investimento_per_capita', 'restos_pagar_sobre_receita',
    'caixa_sobre_receita', 'pressao_pessoal_proxy', 'resultado_orcamentario_proxy',
]
COLUNAS_CONTRATUAL = [
    'total_contratacoes', 'valor_estimado_contratacoes',
    'valor_homologado_contratacoes', 'contratacoes_similares',
    'valor_contratacoes_similares', 'cobertura_pncp',
]
COLUNAS_INSTITUCIONAL = [
    'pessoal_ativo', 'pessoal_celetista', 'pessoal_comissionado',
    'pessoal_estagiario', 'pessoal_estatutario', 'pessoal_sem_vinculo',
    'proporcao_pessoal_estatutario', 'pessoal_ativo_por_mil_habitantes',
]
COLUNAS_CONTROLE = ['populacao', 'area_km2', 'densidade_demografica']
PREFIXOS_QUALIDADE = ('status_', 'cobertura_')
EXCLUIDAS = {'pib', 'pib_per_capita', 'ano_fotografia', 'elegivel_janela_mvp'}


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _gold_pasta(raiz: Path, versao_gold: str) -> tuple[Path, dict]:
    pasta = raiz / 'gold' / 'versoes' / versao_gold
    manifesto = pasta / 'manifesto.json'
    painel = pasta / 'gold' / 'base_municipio_ano.parquet'
    if not manifesto.exists() or not painel.exists():
        raise FileNotFoundError(f'Versão Gold inexistente ou incompleta: {versao_gold}')
    return pasta, json.loads(manifesto.read_text(encoding='utf-8'))


def _colunas_painel(colunas: list[str]) -> list[str]:
    grupos = COLUNAS_ID + COLUNAS_FISCAL + COLUNAS_CONTRATUAL + COLUNAS_INSTITUCIONAL + COLUNAS_CONTROLE
    qualidade = sorted(c for c in colunas if c.startswith(PREFIXOS_QUALIDADE))
    resultado = [c for c in grupos + qualidade if c in colunas and c not in EXCLUIDAS]
    return list(dict.fromkeys(resultado))


def _metadado_coluna(nome: str) -> dict[str, str | bool]:
    if nome in COLUNAS_ID:
        return {'dimensao': 'identificacao_municipal', 'fonte': 'Gold consolidado', 'unidade': 'identificador' if nome == 'codigo_ibge' else 'texto'}
    if nome in COLUNAS_FISCAL:
        return {'dimensao': 'fiscal_financeira', 'fonte': 'Gold consolidado', 'unidade': 'valor monetario ou indicador fiscal'}
    if nome in COLUNAS_CONTRATUAL:
        return {'dimensao': 'contratual_execucao_recursos', 'fonte': 'Gold consolidado', 'unidade': 'quantidade, valor ou status PNCP'}
    if nome in COLUNAS_INSTITUCIONAL:
        unidade = 'proporcao' if nome.startswith('proporcao_') else ('pessoas por mil habitantes' if 'por_mil' in nome else 'pessoas')
        return {'dimensao': 'capacidade_institucional', 'fonte': 'IBGE MUNIC', 'unidade': unidade}
    if nome in COLUNAS_CONTROLE:
        return {'dimensao': 'controle_territorial', 'fonte': 'Gold consolidado', 'unidade': 'controle territorial'}
    return {'dimensao': 'qualidade_auditoria', 'fonte': 'contrato de qualidade', 'unidade': 'status ou cobertura'}


def _dicionario(quadro: pd.DataFrame, manifesto: dict) -> pd.DataFrame:
    linhas = []
    for nome in quadro.columns:
        meta = _metadado_coluna(nome)
        linhas.append({
            'variavel': nome,
            'rotulo': nome.replace('_', ' '),
            'definicao': f'Variável {nome} conforme o contrato Gold.',
            'dimensao': meta['dimensao'],
            'tipo': str(quadro[nome].dtype),
            'unidade': meta['unidade'],
            'fonte': meta['fonte'],
            'tabela_origem': 'gold/base_municipio_ano',
            'periodicidade': 'anual',
            'edicao_origem': 'MUNIC point-in-time' if nome in COLUNAS_INSTITUCIONAL else '',
            'regra_temporal': 'última informação elegível até 31/12 do ano' if nome in COLUNAS_INSTITUCIONAL else 'ano da observação Gold',
            'significado_zero': 'zero observado; não equivale a nulo',
            'significado_nulo': 'indisponível, não aplicável ou não informado conforme a fonte',
            'cobertura': f'{quadro[nome].notna().mean():.12g}',
            'recomendacao_uso': 'visualização descritiva',
            'limitacao': 'não estabelece causalidade nem imputação',
            'apta_para_visualizacao': True,
            'apta_para_modelagem_temporal': nome in COLUNAS_INSTITUCIONAL,
        })
    return pd.DataFrame(linhas)


def _cobertura(quadro: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    esperado = quadro['codigo_ibge'].nunique()
    for nome in quadro.columns:
        if nome in COLUNAS_ID or nome.startswith(PREFIXOS_QUALIDADE):
            continue
        for ano, grupo in quadro.groupby('ano', sort=True):
            serie = grupo[nome]
            numerica = pd.to_numeric(serie, errors='coerce')
            linhas.append({
                'variavel': nome, 'ano': int(ano), 'municipios_esperados': int(esperado),
                'municipios_observados': int(serie.notna().sum()), 'nulos': int(serie.isna().sum()),
                'zeros': int(numerica.eq(0).sum()), 'cobertura': float(serie.notna().mean()),
                'minimo': None if numerica.dropna().empty else float(numerica.min()),
                'maximo': None if numerica.dropna().empty else float(numerica.max()),
                'status': 'observado' if serie.notna().all() else 'parcial',
                'motivo': 'contrato Gold consolidado',
            })
    return pd.DataFrame(linhas)


def _csv(quadro: pd.DataFrame, caminho: Path) -> None:
    quadro.to_csv(caminho, index=False, sep=';', decimal=',', encoding='utf-8-sig', lineterminator='\n')


def exportar_pacote_visualizacao(raiz: Path, versao_gold: str, destino: Path) -> dict:
    """Exporta um pacote sem depender de CURRENT.json.

    A versão é sempre recebida explicitamente; todos os artefatos são derivados
    apenas do Gold imutável daquela versão.
    """
    raiz, manifesto_gold = Path(raiz), None
    pasta, manifesto_gold = _gold_pasta(raiz, versao_gold)
    quadro = pd.read_parquet(pasta / 'gold' / 'base_municipio_ano.parquet')
    colunas = _colunas_painel(list(quadro.columns))
    quadro = quadro[colunas].copy()
    quadro['codigo_ibge'] = quadro['codigo_ibge'].astype('string').str.zfill(7)
    quadro = quadro.sort_values(['codigo_ibge', 'ano'], kind='mergesort').reset_index(drop=True)
    if quadro['codigo_ibge'].str.len().ne(7).any() or quadro['uf'].dropna().ne('PB').any():
        raise ValueError('Pacote exige códigos IBGE de sete dígitos e somente UF PB')
    if set(quadro['ano']) != set(range(2020, 2025)) or len(quadro) != 1115:
        raise ValueError('Pacote exige exatamente 1.115 linhas nos anos 2020–2024')
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    csv = destino / f'{NOME_PAINEL}.csv'
    parquet = destino / f'{NOME_PAINEL}.parquet'
    _csv(quadro, csv)
    tabela = pa.Table.from_pandas(quadro, preserve_index=False)
    pq.write_table(tabela, parquet, compression='snappy', use_dictionary=False, version='2.6', data_page_version='1.0')
    dicionario = _dicionario(quadro, manifesto_gold)
    cobertura = _cobertura(quadro)
    _csv(dicionario, destino / 'dicionario_variaveis.csv')
    _csv(cobertura, destino / 'cobertura_variaveis.csv')
    arquivos = [csv, parquet, destino / 'dicionario_variaveis.csv', destino / 'cobertura_variaveis.csv']
    manifesto = {
        'nome_pacote': NOME_PAINEL,
        'finalidade': 'pacote analítico determinístico para visualização descritiva',
        'versao_gold': versao_gold,
        'commit_base': manifesto_gold.get('commit_base', '5e8ed87'),
        'periodo': [2020, 2024], 'municipios': int(quadro['codigo_ibge'].nunique()),
        'linhas': int(len(quadro)), 'quantidade_colunas': int(len(quadro.columns)),
        'fontes': sorted({str(x) for x in dicionario['fonte']}),
        'arquivos': {x.name: {'sha256': _sha256(x), 'bytes': x.stat().st_size} for x in arquivos},
        'schema': [{'nome': c, 'dtype': str(quadro[c].dtype)} for c in quadro.columns],
        'ordenacao': ['codigo_ibge', 'ano'], 'csv': {'encoding': 'UTF-8 with BOM', 'separador': ';', 'decimal': ','},
        'versoes_runtime': {'python': '3.12', 'pandas': pd.__version__, 'pyarrow': pa.__version__},
        'regra_point_in_time': 'última informação elegível até 31/12; MUNIC 2024 não entra em 2024',
        'condicao_temporal_munic': manifesto_gold.get('proveniencia', {}).get('condicao_temporal_munic', 'apta_com_ressalva_documentada'),
        'variaveis_excluidas': ['MREG0151', 'MREG0152', 'MREG0153', 'MCUL42', 'score', 'pesos', 'ranking', 'ambientais'],
        'limitacao_originais_munic': 'originais de 2019 e 2021 indisponíveis no FTP consultado; revisões preservadas sem hash original inventado',
        'comando_reproducao': f'venv\\Scripts\\python.exe -m etl_municipal.exportacao_visualizacao --data-dir data --gold-version {versao_gold} --output dados/visualizacao',
        'sem_score_nem_causalidade': True,
    }
    (destino / 'manifesto.json').write_text(json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return manifesto


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--gold-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    resultado = exportar_pacote_visualizacao(args.data_dir, args.gold_version, args.output)
    print(json.dumps(resultado, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
