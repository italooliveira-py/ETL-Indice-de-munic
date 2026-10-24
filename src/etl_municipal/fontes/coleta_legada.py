"""Importa uma execução real sem alterar output/ ou seus checkpoints."""
import json
from pathlib import Path
import pandas as pd
from ..core.armazenamento import preservar
from ..core.contratos import ViolacaoContrato


def extrair(diretorio: Path, raiz: Path):
    caminhos = {}
    for nome in ['base_municipio_ano.csv', 'eventos_obrasgov.csv', 'resumo_execucao.json']:
        arquivo = diretorio / nome
        caminhos[nome] = preservar(raiz, 'coleta_legada', nome, arquivo.read_bytes(), arquivo.resolve().as_uri())
    for nome in ['manifesto_coleta.json', 'erros_coleta.csv', 'cobertura_fontes.csv']:
        arquivo = diretorio / nome
        if arquivo.exists():
            caminhos[nome] = preservar(raiz, 'coleta_legada', nome, arquivo.read_bytes(), arquivo.resolve().as_uri())
    return caminhos


def transformar(caminhos):
    resumo = json.loads(caminhos['resumo_execucao.json'].read_text(encoding='utf-8-sig'))
    if resumo.get('smoke_test') or resumo.get('municipios') != 223 or resumo.get('periodo') != [2020, 2024]:
        raise ViolacaoContrato('Publicação exige execução PB completa 2020–2024, fora do smoke')
    base = pd.read_csv(caminhos['base_municipio_ano.csv'], dtype={'codigo_ibge': 'string'})
    try:
        eventos = pd.read_csv(caminhos['eventos_obrasgov.csv'],
                             dtype={'codigo_ibge': 'string', 'id_projeto_investimento': 'string'})
    except pd.errors.EmptyDataError:
        if resumo.get('eventos_obrasgov') != 0:
            raise ViolacaoContrato('Arquivo de eventos vazio contradiz o resumo')
        eventos = pd.DataFrame(columns=['codigo_ibge', 'id_projeto_investimento'])
    if len(base) != resumo.get('linhas_base_municipio_ano') or len(eventos) != resumo.get('eventos_obrasgov'):
        raise ViolacaoContrato('Contagens dos arquivos contradizem o resumo da coleta')
    if 'continuidade_partidaria_pleito' in base:
        base['continuidade_partidaria_pleito'] = base['continuidade_partidaria_pleito'].map(
            lambda v: pd.NA if pd.isna(v) else str(v).lower() == 'true').astype('boolean')
    return base, eventos
