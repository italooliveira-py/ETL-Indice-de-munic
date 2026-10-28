"""E05 v2: evento adverso ObrasGov como principal; repasse 180d como sensibilidade."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd

from src.e04_baseline_obras_publicas import load_snapshots, build_modeling_frame
from src.etl_municipal.core.armazenamento import sha256
from src.etl_municipal.fontes import siconfi
from src.etl_municipal.fontes import transferegov_discricionarias as disc
from src.etl_municipal.fontes import transferegov_especiais as esp
from .dados import ROOT, adicionar_contexto, contexto_ibge, particoes, preparar_ibge
from .experimento import executar
from .relatorio import figuras

PASTA_DADOS = ROOT / 'dados/modelagem/e05_revisao'
PASTA_DOCS = ROOT / 'docs/e05/revisao_v2'
PASTA_OUTPUT = ROOT / 'output/e05_revisao'


def configuracoes():
    c = json.loads((ROOT / 'config.e05.revisao.json').read_text(encoding='utf-8'))
    comuns = {k: v for k, v in c.items() if k not in ['principal', 'secundario']}
    return {n: {**comuns, **c[n]} for n in ['principal', 'secundario']}


def base_180(base):
    """Deriva uma nova versão sem modificar a base ou o rótulo de 90 dias."""
    q = base.copy()
    q['fim_horizonte'] = q.data_assinatura + pd.to_timedelta(180, unit='D')
    carga = pd.to_datetime(q.data_carga.iloc[0], dayfirst=True).normalize()
    q['motivo_exclusao'] = q.motivo_exclusao.mask(q.motivo_exclusao.eq('seguimento_90d_incompleto'))
    q.loc[q.fim_horizonte >= carga, 'motivo_exclusao'] = 'seguimento_180d_incompleto'
    q['sem_repasse_180d'] = (q.primeiro_repasse.isna() | (q.primeiro_repasse > q.fim_horizonte)).astype('Int64')
    q.loc[q.motivo_exclusao.notna(), 'sem_repasse_180d'] = pd.NA
    return particoes(q)


def preparar(raiz_dados=ROOT / 'data'):
    import requests
    cfg = configuracoes()
    base_mun, eventos = load_snapshots()
    elegiveis, exclusoes = build_modeling_frame(base_mun, eventos)
    # Usa os mesmos IDs e desfechos da E04, sem reaproveitar X ou sua data potencialmente futura.
    meta = elegiveis[['id_projeto_investimento', 'codigo_ibge', 'ano', 'ano_ref', 'evento_adverso_obrasgov']].copy()
    meta['data_corte'] = pd.to_datetime(meta.ano.astype(str) + '-01-01')
    meta['contexto_e04_posterior_coorte'] = meta.ano_ref >= meta.ano
    d = disc.transformar(disc.verificar(raiz_dados))
    e = esp.transformar(esp.verificar(raiz_dados), d['ref/transferegov_cnpj_municipio'])
    s = siconfi.verificar(raiz_dados)
    dca = siconfi.transformar_dca(s)['silver/siconfi_dca_receita_municipio']
    rgf = siconfi.transformar_rgf(s)['silver/siconfi_rgf_pessoal']
    caminhos_ibge = preparar_ibge(requests.Session(), raiz_dados, offline=True)
    ibge = contexto_ibge(base_mun, caminhos_ibge)
    # A interface de contexto é compartilhada; o alias do ID é interno e não vira preditor.
    entradas = meta.rename(columns={'id_projeto_investimento': 'nr_convenio'}).assign(
        modalidade=pd.NA, orgao_superior=pd.NA, valor_global_assinatura=np.nan)
    enriquecida = adicionar_contexto(entradas, d['silver/transferegov_instrumentos'],
        d['silver/transferegov_desembolsos'], e['silver/transferegov_especiais_pagamentos'],
        ibge, dca, rgf, coluna_corte='data_corte')
    enriquecida = enriquecida.rename(columns={'nr_convenio': 'id_projeto_investimento'})
    for novo, antigo in [('populacao_ibge', 'log_populacao_ibge'), ('pib_pc_ibge', 'log_pib_pc_ibge'),
                          ('desembolso_365d_percap', 'log_desembolso_365d_percap'),
                          ('pix_365d_percap', 'log_pix_365d_percap'), ('receita_dca_percap', 'log_receita_dca_percap')]:
        enriquecida[novo] = np.expm1(enriquecida[antigo])
    colunas = ['id_projeto_investimento', 'codigo_ibge', 'ano', 'ano_ref', 'data_corte',
                'evento_adverso_obrasgov', 'contexto_e04_posterior_coorte', *cfg['principal']['numericas']]
    colunas += [c for c in enriquecida if c.startswith(('disponibilidade_', 'ano_ref_'))]
    principal = enriquecida[colunas].copy()
    principal['treino_validacao'] = principal.ano == 2022
    principal['validacao'] = principal.ano == 2023
    principal['treino_final'] = principal.ano.isin([2022, 2023])
    principal['teste'] = principal.ano == 2024
    secundario = base_180(pd.read_parquet(ROOT / 'dados/modelagem/e05/base_modelagem.parquet'))
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for nome, q in [('principal', principal), ('secundario', secundario)]:
        p = PASTA_DADOS / (nome + '.parquet')
        q.to_parquet(p, index=False)
        hashes[nome] = sha256(p.read_bytes())
        chave = cfg[nome]['coluna_id']
        q[[chave, 'codigo_ibge', cfg[nome]['coluna_data'], cfg[nome]['alvo'],
           'treino_validacao', 'validacao', 'treino_final', 'teste']].to_csv(PASTA_DADOS / (nome + '_particoes.csv'), index=False)
    manifesto = {'versao': '2.0.0', 'data': '2026-10-28', 'hashes': hashes, 'configuracoes': cfg,
        'codigo': {p.name: sha256(p.read_bytes()) for p in (ROOT / 'src/e05').glob('*.py')},
        'fontes': {'E04_manifesto': sha256((ROOT / 'dados/bruto/manifesto_prova_conceito_infraestrutura.json').read_bytes()),
                   'E05_v1_manifesto': sha256((ROOT / 'dados/modelagem/e05/manifesto_base.json').read_bytes()),
                   'siconfi_indice': sha256((raiz_dados / 'ref/siconfi_bronze.json').read_bytes())},
        'ambiente': {'python': platform.python_version(), 'pacotes': {p: importlib.metadata.version(p) for p in ['numpy', 'pandas', 'scikit-learn', 'pyarrow']}},
        'diagnostico': {'coorte_e04_preservada': len(principal), 'contextos_futuros_e04_nao_reutilizados': int(meta.contexto_e04_posterior_coorte.sum()),
                       'censurados_excluidos_no_universo_e04': int(eventos.evento_adverso_execucao.isna().sum())},
        'limites': ['Rotulos ObrasGov sao estados observados no snapshot; datas de ocorrencia/publicacao nao recuperaveis para todos.',
                    'Benchmark retrospectivo condicionado a obras com resultado observado, nao estimativa prospectiva para todas as obras.',
                    'Ano de cadastro define coorte. Contexto congelado antes de 01/01 desse ano, sem usar inicio previsto posterior.',
                    'Teste 2024 ja consultado na E04; nao e validacao externa inedita.',
                    'Campos fiscais de versoes retificadas e datas de registro publico limitam a reconstrucao historica exata.']}
    (PASTA_DADOS / 'manifesto.json').write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifesto


def carregar():
    m = json.loads((PASTA_DADOS / 'manifesto.json').read_text(encoding='utf-8'))
    if configuracoes() != m['configuracoes']:
        raise ValueError('Configuração alterada; reconstruir e versionar a base da revisão')
    bases = {}
    for nome, hash_esperado in m['hashes'].items():
        p = PASTA_DADOS / (nome + '.parquet')
        if sha256(p.read_bytes()) != hash_esperado:
            raise ValueError('Snapshot da revisão alterado: ' + nome)
        bases[nome] = pd.read_parquet(p)
    return bases, m


def rodar(destino=PASTA_OUTPUT):
    bases, manifesto = carregar()
    cfg = configuracoes()
    todas, resultados = [], {}
    for nome, base in bases.items():
        resultado, tabela, pred = executar(base, cfg[nome], destino / nome)
        resultado['limites'] = manifesto['limites'] if nome == 'principal' else [
            'Janela 180d nao equivale a evento adverso de execucao.',
            'Suporte insuficiente da classe minoritaria; nao usar resultado para escolher o alvo apos olhar o teste.']
        resultados[nome] = resultado
        tabela['analise'] = nome
        todas.append(tabela)
        figuras(pred, destino / nome / 'figuras', titulo='Teste 2024 — ' + cfg[nome]['alvo'])
    tabela = pd.concat(todas, ignore_index=True)
    if destino.resolve() == PASTA_OUTPUT.resolve():
        PASTA_DOCS.mkdir(parents=True, exist_ok=True)
        tabela.to_csv(PASTA_DOCS / 'metricas.csv', index=False, encoding='utf-8-sig')
        tabela[tabela.particao == 'teste_2024'].to_csv(PASTA_DOCS / 'quadro_comparacao_2024.csv', index=False, encoding='utf-8-sig')
        resumo = {'versao': '2.0.0', 'data': '2026-10-28', 'analises': resultados,
                  'hashes_datasets': manifesto['hashes'], 'diagnostico': manifesto['diagnostico'],
                  'fontes_referencias': ['Desafios e Oportunidades para o Desenvolvimento Regional (artigo, pp. 5–6 e 12–15)',
                                         'Predição de Fatores de Risco na Execução de Obras Públicas (apresentação E04, pp. 2–10)',
                                         'E04_equipe01_dados_baseline_atualizado.docx']}
        (PASTA_DOCS / 'resultados.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return resultados, tabela


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acao', choices=['preparar', 'executar', 'notebook', 'executar-notebook'])
    args = parser.parse_args()
    if args.acao == 'preparar':
        print(json.dumps(preparar()['diagnostico'], ensure_ascii=False))
    elif args.acao == 'executar':
        _, tabela = rodar()
        print(tabela[tabela.particao == 'teste_2024'][['analise', 'modelo', 'acuracia_balanceada', 'roc_auc', 'average_precision']].to_string(index=False))
    elif args.acao == 'notebook':
        from .revisao_notebook import criar
        print(criar())
    else:
        from .__main__ import executar_notebook
        caminho = ROOT / 'notebooks/03_E05_benchmark_risco_obras_180dias.ipynb'
        print(executar_notebook(caminho, PASTA_OUTPUT))


if __name__ == '__main__':
    main()
