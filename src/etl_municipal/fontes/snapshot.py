"""Migração de snapshots, sem apresentá-los como respostas brutas das APIs."""
import io
import json
from pathlib import Path
import pandas as pd
from ..core.armazenamento import preservar, sha256
from ..core.contratos import ViolacaoContrato


def extrair(raiz_projeto: Path, raiz_dados: Path):
    pasta = raiz_projeto / 'dados' / 'bruto'
    manifesto = pasta / 'manifesto_prova_conceito_infraestrutura.json'
    metadados = json.loads(manifesto.read_text(encoding='utf-8'))
    caminhos = {}
    for nome in ['base_municipio_ano_snapshot.csv', 'eventos_obrasgov_snapshot.csv']:
        conteudo = (pasta / nome).read_bytes()
        if sha256(conteudo) != metadados['sha256'][nome]:
            raise ViolacaoContrato(f'Snapshot diverge do manifesto original: {nome}')
        caminhos[nome] = preservar(raiz_dados, 'snapshot_legado', nome, conteudo,
                                   f'repositorio:dados/bruto/{nome}')
    preservar(raiz_dados, 'snapshot_legado', manifesto.name, manifesto.read_bytes(),
              'repositorio:dados/bruto/' + manifesto.name)
    return caminhos


def transformar(caminhos):
    tabelas = [pd.read_csv(io.BytesIO(caminhos[nome].read_bytes()),
                         dtype={'codigo_ibge': 'string', 'id_projeto_investimento': 'string'})
               for nome in ['base_municipio_ano_snapshot.csv', 'eventos_obrasgov_snapshot.csv']]
    base, eventos = tabelas
    if 'continuidade_partidaria_pleito' in base:
        base['continuidade_partidaria_pleito'] = base['continuidade_partidaria_pleito'].map(
            lambda v: pd.NA if pd.isna(v) else str(v).lower() == 'true').astype('boolean')
    return base, eventos
