"""Quadros do RESULTADOS_E06 a partir do registro e das previsões salvas, sem treinar de novo.

Uso: python -m src.e06.resumo [--publicar]
--publicar copia as saídas para dados/modelagem/e06 (com manifesto de hashes) e as figuras para docs/e06.
"""
from __future__ import annotations

import argparse
import json
import shutil

import pandas as pd

from . import experimento as x
from .dados import ROOT, ler_config
from .registro import escrever_csv, gravar_json, sha256
from .relatorio import figura_matrizes


def capacidades(previsoes, fracoes):
    linhas = []
    for chave, g in previsoes.groupby(['experimento', 'conjunto', 'modelo', 'particao']):
        linha = dict(zip(['experimento', 'conjunto', 'modelo', 'particao'], chave), prevalencia=g.y.mean())
        for f in fracoes:
            m = x.matriz_capacidade(g.y, g.p, f)
            linha[f'precisao_top{int(round(f * 100))}'] = m['precisao']
            linha[f'recall_top{int(round(f * 100))}'] = m['recall']
        linhas.append(linha)
    return pd.DataFrame(linhas)


def matrizes_tres_limiares(previsoes, escolhas, fracao=0.2):
    linhas = []
    for (conjunto, modelo), g in previsoes.groupby(['conjunto', 'modelo'], sort=False):
        esc = escolhas['conjuntos'][conjunto][modelo]
        tipos = {'F1 na validação': x.matriz_limiar(g.y, g.p, esc['limiar_f1']),
                 'prevalência do treino': x.matriz_limiar(g.y, g.p, escolhas['prevalencia_treino']),
                 f'capacidade {int(fracao * 100)}%': x.matriz_capacidade(g.y, g.p, fracao)}
        linhas += [{'conjunto': conjunto, 'modelo': modelo, 'limiar_tipo': t, **m} for t, m in tipos.items()]
    return pd.DataFrame(linhas)


PUBLICADOS = ['registro.csv', 'aberturas_teste.csv', 'previsoes.parquet', 'grades.csv', 'erros.csv',
              'calibracao.csv', 'robustez.csv', 'replicacao.csv', 'proveniencia.json',
              'registro_oficial_teste.csv', 'quadro_validacao.csv', 'capacidade_esperada.csv',
              'matrizes_tres_limiares.csv', 'calibracao_por_ano_A0.csv']


def publicar(config, saida, oficiais):
    destino = ROOT / 'dados' / 'modelagem' / 'e06'
    for nome in PUBLICADOS:
        shutil.copy2(saida / nome, destino / nome)
    figuras = ROOT / 'docs' / 'e06' / 'figuras'
    shutil.copytree(saida / 'figuras' / 'resumo', figuras, dirs_exist_ok=True)
    shutil.copytree(saida / 'figuras' / oficiais['A0'], figuras / 'A0_teste', dirs_exist_ok=True)
    arquivos = sorted(p for p in destino.rglob('*') if p.is_file() and p.name != 'manifesto.json')
    gravar_json(destino / 'manifesto.json', {'versao_pacote': config['versao_pacote'],
                                              'hashes': {p.relative_to(destino).as_posix(): sha256(p.read_bytes())
                                                         for p in arquivos}})


def main():
    parser = argparse.ArgumentParser(prog='python -m src.e06.resumo')
    parser.add_argument('--publicar', action='store_true')
    args = parser.parse_args()
    config = ler_config()
    saida = ROOT / config['saida']
    aberturas = pd.read_csv(saida / 'aberturas_teste.csv')
    # A primeira abertura de cada experimento previsto no plano é a leitura oficial.
    oficiais = aberturas[aberturas.prevista_no_plano].groupby('experimento').run_id.first()
    previsoes = pd.read_parquet(saida / 'previsoes.parquet')
    previsoes = previsoes[previsoes.run_id.isin(oficiais.values)].assign(
        experimento=lambda q: q.run_id.map({rid: exp for exp, rid in oficiais.items()}))
    escrever_csv(capacidades(previsoes, config['capacidades']), saida / 'capacidade_esperada.csv')

    registro = pd.read_csv(saida / 'registro.csv')
    escrever_csv(registro[registro.run_id.isin(oficiais.values)], saida / 'registro_oficial_teste.csv')
    escolha = registro[registro.run_id.str.contains('_escolha_') & ~registro.fora_do_lock.astype(bool)]
    ultima = escolha.groupby('experimento').run_id.max()
    escrever_csv(escolha[escolha.run_id.isin(ultima.values)], saida / 'quadro_validacao.csv')

    escolhas_a0 = json.loads((ROOT / config['escolhas'] / 'A0.json').read_text(encoding='utf-8'))
    teste_a0 = previsoes[(previsoes.experimento == 'A0') & (previsoes.particao == 'teste')]
    matrizes = matrizes_tres_limiares(teste_a0, escolhas_a0)
    escrever_csv(matrizes, saida / 'matrizes_tres_limiares.csv')
    figura_matrizes(matrizes, saida / 'figuras' / 'resumo')

    calib = pd.read_csv(saida / 'calibracao.csv')
    calib = calib[(calib.run_id == oficiais['A0']) & (calib.tipo == 'ano') & (calib.particao == 'teste')]
    escrever_csv(calib, saida / 'calibracao_por_ano_A0.csv')
    if args.publicar:
        publicar(config, saida, oficiais)


if __name__ == '__main__':
    main()
