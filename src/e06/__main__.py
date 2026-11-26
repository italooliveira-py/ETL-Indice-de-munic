"""Comando único do E06.

    python -m src.e06 --fase escolha --experimento A0      grade e escolha, sem tocar no teste
    python -m src.e06 --fase teste --experimento A0        teste com as escolhas já commitadas
    python -m src.e06 --fase prospectivo --experimento A0  as mesmas escolhas nos censurados de 2024
    python -m src.e06 --replicacao A0                      compara as duas últimas rodadas de teste
"""
from __future__ import annotations

import argparse
import json
import subprocess
import warnings

import pandas as pd

from . import dados as d
from . import experimento as x
from . import registro as r
from .relatorio import figuras

warnings.filterwarnings('ignore', category=FutureWarning)


def _janela_treino(partes, faixa):
    treino = partes['train']
    return treino[treino.ano_origem.between(*faixa)].reset_index(drop=True)


def _pasta_escolhas(prov, saida, config):
    # Ensaios (--fora-do-lock) guardam as escolhas na própria saída, longe das oficiais.
    return saida / 'escolhas' if prov['ensaio'] else d.ROOT / config['escolhas']


def _modelos(experimento, config, pasta):
    if experimento['modelos'] == 'todos':
        return list(config['grades'])
    escolhas = json.loads((pasta / 'A0.json').read_text(encoding='utf-8'))
    notas = {m: v['brier_escolha'] for m, v in escolhas['conjuntos']['M1_plus'].items() if m not in x.BASELINES}
    return list(x.BASELINES) + list(dict.fromkeys(sorted(notas, key=notas.get)[:2] + ['logistica']))


def _linha(prov, nome_exp, conjunto, modelo, params, particao, valores):
    return {'run_id': prov['run_id'], 'data_hora': prov['data_hora'], 'commit_codigo': prov['commit_codigo'],
            'versao_pacote': prov['versao_pacote'], 'hash_pacote': prov['hash_pacote'],
            'fora_do_lock': bool(prov['fora_do_lock']), 'experimento': nome_exp, 'conjunto': conjunto,
            'modelo': modelo, 'hiperparametros': json.dumps(params, sort_keys=True), 'semente': prov['semente'],
            'particao': particao, **valores}


def _previsoes(base, conjunto, modelo, particao, p):
    return base[['nr_convenio', 'codigo_ibge', 'ano_origem', 'modalidade']].assign(
        particao=particao, conjunto=conjunto, modelo=modelo, y=base[d.ALVO].to_numpy(), p=p)


def _avaliacao(y, p, codigos, prevalencia, limiares, config, sorteio):
    return {**x.metricas(y, p, prevalencia), **x.intervalos_cluster(y, p, codigos, prevalencia, sorteio),
            **x.decisoes(y, p, limiares, config['capacidades'])}


def fase_escolha(nome_exp, config, partes, prov, saida):
    exp = config['experimentos'][nome_exp]
    treino, validacao = _janela_treino(partes, exp['treino']), partes['validation']
    prevalencia = float(treino[d.ALVO].mean())
    janelas = x.janelas_tempo(treino, exp['anos_cv']) if exp['escolha'] == 'cv_tempo' else None
    sorteio = x.sorteios_municipios(validacao.codigo_ibge.to_numpy(), config['bootstrap'], config['semente'])
    escolhas = {'experimento': nome_exp, 'run_id': prov['run_id'], 'escolha': exp['escolha'],
                'prevalencia_treino': prevalencia, 'conjuntos': {}}
    grade, registro, previsoes, robustez = [], [], [], []
    for conjunto in exp['conjuntos']:
        colunas = config['conjuntos'][conjunto]
        escolhas['conjuntos'][conjunto] = {}
        for modelo in _modelos(exp, config, _pasta_escolhas(prov, saida, config)):
            notas = x.avaliar_grade(modelo, colunas, config, treino, validacao, janelas)
            grade += [{**n, 'conjunto': conjunto, 'hiperparametros': json.dumps(n['hiperparametros'])} for n in notas]
            melhor = min(notas, key=lambda n: n['brier_escolha'])
            params = melhor['hiperparametros']
            if janelas is None:
                ajuste = x.criar_pipeline(modelo, params, colunas, config).fit(treino[x.entrada(colunas)], treino[d.ALVO])
                y, p = validacao[d.ALVO].to_numpy(), x.prever(ajuste, validacao[x.entrada(colunas)])
                particao, codigos = 'validacao', validacao.codigo_ibge
                previsoes.append(_previsoes(validacao, conjunto, modelo, particao, p))
            else:
                y, p = x.previsoes_janelas(modelo, params, colunas, config, treino, janelas)
                particao, codigos = 'janelas_tempo', None
            limiar = x.limiar_f1(y, p)
            limiares = {'f1': limiar, 'prevalencia': prevalencia}
            valores = ({**x.metricas(y, p, prevalencia), **x.decisoes(y, p, limiares, config['capacidades'])}
                       if codigos is None else _avaliacao(y, p, codigos, prevalencia, limiares, config, sorteio))
            registro.append(_linha(prov, nome_exp, conjunto, modelo, params, particao, valores))
            escolhas['conjuntos'][conjunto][modelo] = {'hiperparametros': params,
                                                      'brier_escolha': melhor['brier_escolha'], 'limiar_f1': limiar}
            if exp.get('robustez_cv') and modelo not in x.BASELINES:
                notas_cv = x.avaliar_grade(modelo, colunas, config, treino, janelas=x.janelas_tempo(treino, exp['robustez_cv']))
                params_cv = min(notas_cv, key=lambda n: n['brier_escolha'])['hiperparametros']
                robustez.append({'conjunto': conjunto, 'modelo': modelo, 'escolha_validacao': json.dumps(params),
                                 'escolha_janelas': json.dumps(params_cv), 'mesma_escolha': params_cv == params,
                                 'brier_validacao_escolha_janelas': next(n['brier_escolha'] for n in notas
                                                                          if n['hiperparametros'] == params_cv),
                                 'brier_validacao_escolha_oficial': melhor['brier_escolha']})
            print(f'{nome_exp} {conjunto} {modelo}: {params} Brier {melhor["brier_escolha"]:.4f}', flush=True)
    r.acrescentar(saida / 'registro.csv', registro)
    r.escrever_csv(pd.DataFrame(grade), saida / 'grades' / f'{prov["run_id"]}.csv')
    if previsoes:
        pd.concat(previsoes).to_parquet(saida / 'previsoes' / f'{prov["run_id"]}.parquet', index=False)
    if robustez:
        r.escrever_csv(pd.DataFrame(robustez), saida / 'robustez' / f'{prov["run_id"]}.csv')
    destino = _pasta_escolhas(prov, saida, config) / f'{nome_exp}.json'
    r.gravar_json(destino, escolhas)
    print(f'Escolhas em {destino}. Faça o commit antes de abrir o teste.')


def _escolhas_congeladas(nome_exp, prov, saida, config):
    if prov['ensaio']:
        return json.loads((saida / 'escolhas' / f'{nome_exp}.json').read_text(encoding='utf-8'))
    caminho = f"{config['escolhas']}/{nome_exp}.json"
    rastreado = subprocess.run(['git', 'ls-files', '--error-unmatch', caminho], cwd=d.ROOT, capture_output=True).returncode == 0
    limpo = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', caminho], cwd=d.ROOT).returncode == 0
    if not (rastreado and limpo):
        raise SystemExit(f'{caminho} não está commitado: faça o commit das escolhas antes de abrir o teste.')
    return json.loads((d.ROOT / caminho).read_text(encoding='utf-8'))


def _aplicar(nome_exp, config, escolhas, ajustes, avaliado, grupos, prov, saida, titulo=None):
    """Ajusta cada escolha congelada em cada base de `ajustes` e avalia em `avaliado`."""
    prevalencia = escolhas['prevalencia_treino']
    sorteio = x.sorteios_municipios(avaliado.codigo_ibge.to_numpy(), config['bootstrap'], config['semente'])
    y = avaliado[d.ALVO].to_numpy()
    registro, previsoes, calib, erros = [], [], [], []
    for conjunto, modelos in escolhas['conjuntos'].items():
        colunas = config['conjuntos'][conjunto]
        for particao, base in ajustes:
            for modelo, esc in modelos.items():
                params = esc['hiperparametros']
                ajuste = x.criar_pipeline(modelo, params, colunas, config).fit(base[x.entrada(colunas)], base[d.ALVO])
                p = x.prever(ajuste, avaliado[x.entrada(colunas)])
                limiares = {'f1': esc['limiar_f1'], 'prevalencia': prevalencia}
                registro.append(_linha(prov, nome_exp, conjunto, modelo, params, particao,
                                       _avaliacao(y, p, avaliado.codigo_ibge, prevalencia, limiares, config, sorteio)))
                previsoes.append(_previsoes(avaliado, conjunto, modelo, particao, p))
                rotulo = dict(conjunto=conjunto, modelo=modelo, particao=particao)
                calib.append(x.calibracao(y, p).assign(tipo='decil', **rotulo))
                if 'ano' in grupos:
                    calib.append(x.calibracao(y, p, grupos['ano']).assign(tipo='ano', **rotulo))
                erros.append(x.erros_por_grupo(y, p, grupos, prevalencia).assign(**rotulo))
                print(f'{nome_exp} {particao} {conjunto} {modelo}: Brier skill {registro[-1]["brier_skill"]:+.3f} '
                      f'ROC {registro[-1]["roc_auc"]:.3f}', flush=True)
            if titulo and particao == ajustes[0][0]:
                parte = pd.concat(previsoes)
                parte = parte[(parte.conjunto == conjunto) & (parte.particao == particao)]
                figuras(parte, {m: e['limiar_f1'] for m, e in modelos.items()},
                        saida / 'figuras' / prov['run_id'] / conjunto, f'{nome_exp} {conjunto} — {titulo}')
    r.acrescentar(saida / 'registro.csv', registro)
    pd.concat(previsoes).to_parquet(saida / 'previsoes' / f'{prov["run_id"]}.parquet', index=False)
    r.escrever_csv(pd.concat(calib), saida / 'calibracao' / f'{prov["run_id"]}.csv')
    r.escrever_csv(pd.concat(erros), saida / 'erros' / f'{prov["run_id"]}.csv')


def _grupos(base, config):
    return {'modalidade': base.modalidade.to_numpy(), 'porte': d.porte(base.codigo_ibge, config).to_numpy(),
            'experiencia': d.experiencia(base.historico_instrumentos_maduros).to_numpy()}


def fase_teste(nome_exp, config, partes, prov, saida):
    escolhas = _escolhas_congeladas(nome_exp, prov, saida, config)
    exp = config['experimentos'][nome_exp]
    r.registrar_abertura_teste(saida, prov['run_id'], nome_exp, not prov['ensaio'])
    treino, teste = _janela_treino(partes, exp['treino']), partes['test']
    ajustes = [('teste', treino)]
    if exp.get('refit_treino_validacao'):
        ajustes.append(('teste_refit_treino_validacao', pd.concat([treino, partes['validation']], ignore_index=True)))
    grupos = {'ano': teste.ano_origem.to_numpy(), **_grupos(teste, config)}
    _aplicar(nome_exp, config, escolhas, ajustes, teste, grupos, prov, saida, 'teste 2022–2023')


def fase_prospectivo(nome_exp, config, partes, prov, saida):
    """Seção 9 do plano: censurados de 2024 com desfecho apurado pelos desembolsos do Silver."""
    escolhas = _escolhas_congeladas(nome_exp, prov, saida, config)
    teste = partes['test']
    concordancia = float((d.rotular_por_desembolsos(teste, config) == teste[d.ALVO].to_numpy()).mean())
    if concordancia < 1:
        raise SystemExit(f'A regra de rótulo pelo Silver não reproduz o pacote no teste ({concordancia:.1%}).')
    alvo = d.carregar_censurados(config)
    alvo[d.ALVO] = d.rotular_por_desembolsos(alvo, config)
    r.registrar_abertura_teste(saida, prov['run_id'], f'{nome_exp}_prospectivo_2024', not prov['ensaio'])
    treino = _janela_treino(partes, config['experimentos'][nome_exp]['treino'])
    _aplicar(nome_exp, config, escolhas, [('prospectivo_2024', treino)], alvo, _grupos(alvo, config), prov, saida)


def replicacao(nome_exp, saida):
    aberturas = pd.read_csv(saida / 'aberturas_teste.csv')
    ids = aberturas[aberturas.experimento == nome_exp].run_id.tolist()[-2:]
    if len(ids) < 2:
        raise SystemExit('São necessárias duas rodadas de teste para comparar.')
    a, b = (pd.read_parquet(saida / 'previsoes' / f'{i}.parquet') for i in ids)
    junto = a.merge(b, on=['nr_convenio', 'conjunto', 'modelo', 'particao'], suffixes=('_1', '_2'), validate='one_to_one')
    junto['diferenca'] = (junto.p_1 - junto.p_2).abs()
    resumo = junto.groupby(['conjunto', 'modelo', 'particao']).diferenca.max().reset_index()
    resumo['identico'] = resumo.diferenca <= 1e-9
    r.escrever_csv(resumo, saida / 'replicacao' / f'{ids[0]}__{ids[1]}.csv')
    print(resumo.to_string(index=False))
    print('REPLICACAO OK' if resumo.identico.all() and len(junto) == len(a) == len(b) else 'REPLICACAO DIVERGENTE')


def main():
    parser = argparse.ArgumentParser(prog='python -m src.e06')
    parser.add_argument('--fase', choices=['escolha', 'teste', 'prospectivo'])
    parser.add_argument('--experimento')
    parser.add_argument('--todos', action='store_true')
    parser.add_argument('--replicacao')
    parser.add_argument('--fora-do-lock', action='store_true')
    parser.add_argument('--config', default=str(d.ROOT / 'config.e06.json'))
    args = parser.parse_args()
    config = d.ler_config(args.config)
    saida = d.ROOT / config['saida']
    if args.replicacao:
        return replicacao(args.replicacao, saida)
    diferencas = r.conferir_lock(config, args.fora_do_lock)
    if args.fora_do_lock:
        saida = saida.parent / (saida.name + '_fora_do_lock')
    (saida / 'previsoes').mkdir(parents=True, exist_ok=True)
    print('Pacote:', d.verificar_pacote(config))
    partes = d.carregar(config)
    fases = {'escolha': fase_escolha, 'teste': fase_teste, 'prospectivo': fase_prospectivo}
    for nome_exp in (list(config['experimentos']) if args.todos else [args.experimento]):
        prov = {**r.proveniencia(r.novo_run_id(nome_exp, args.fase), config, diferencas),
                'semente': config['semente'], 'ensaio': args.fora_do_lock}
        r.gravar_json(saida / 'proveniencia' / f'{prov["run_id"]}.json', prov)
        fases[args.fase](nome_exp, config, partes, prov, saida)


if __name__ == '__main__':
    main()
