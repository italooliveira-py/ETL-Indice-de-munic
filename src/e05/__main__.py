"""CLI reproduzível: coleta mínima complementar, base congelada e experimento E05."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

import pandas as pd
import requests

from src.etl_municipal.core.armazenamento import sha256
from .dados import ROOT, PREDITORES, preparar_ibge, construir_base
from .experimento import executar
from .relatorio import figuras, consolidar


def ler_base(pasta):
    # O snapshot público versionado permite reproduzir o notebook sem nova coleta.
    if not (pasta / 'manifesto_base.json').exists() and pasta.resolve() == (ROOT / 'output/e05').resolve():
        pasta = ROOT / 'dados/modelagem/e05'
    manifesto = json.loads((pasta / 'manifesto_base.json').read_text(encoding='utf-8'))
    caminho = pasta / 'base_modelagem.parquet'
    if sha256(caminho.read_bytes()) != manifesto['sha256_dataset']:
        raise ValueError('Base congelada diverge do manifesto')
    return pd.read_parquet(caminho), manifesto


def executar_notebook(caminho, pasta_output):
    """Kernel local e intérprete explícito, compartilhados entre versões do experimento."""
    import os
    import sys
    import nbformat
    from nbclient import NotebookClient
    from jupyter_client.manager import AsyncKernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    pasta_output.mkdir(parents=True, exist_ok=True)
    kernels = pasta_output.resolve() / '.kernels'
    pasta_kernel = kernels / 'e05'
    pasta_kernel.mkdir(parents=True, exist_ok=True)
    (pasta_kernel / 'kernel.json').write_text(json.dumps({
        'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
        'display_name': 'Python E05 local', 'language': 'python'}), encoding='utf-8')
    gestor = AsyncKernelManager(kernel_name='e05', kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernels)]),
                                 connection_file=str(pasta_output.resolve() / '.conexao_kernel.json'))
    nb = nbformat.read(caminho, as_version=4)
    cliente = NotebookClient(nb, km=gestor, timeout=600, resources={'metadata': {'path': str(ROOT)}})
    cliente.execute(cleanup_kc=True, env={**os.environ, 'E05_OUTPUT_DIR': str(pasta_output.resolve())})
    nbformat.write(nb, caminho)
    return caminho


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('acao', choices=['preparar-dados', 'executar', 'notebook', 'executar-notebook'])
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output/e05')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / 'config.e05.json').read_text(encoding='utf-8'))
    if config['horizonte_dias'] != 90 or config['alvo'] != 'sem_repasse_90d':
        raise ValueError('Esta versão implementa exclusivamente o alvo binário de 90 dias; mudar o contrato exige outra versão')
    if args.acao == 'preparar-dados':
        with requests.Session() as sessao:
            caminhos = preparar_ibge(sessao, args.data_dir, offline=args.offline)
        base, manifesto = construir_base(args.data_dir, caminhos)
        base.to_parquet(args.output_dir / 'base_modelagem.parquet', index=False)
        manifesto['sha256_dataset'] = sha256((args.output_dir / 'base_modelagem.parquet').read_bytes())
        manifesto['configuracao'] = config
        manifesto['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        manifesto['implementacao_hash'] = {p.name: sha256(p.read_bytes()) for p in sorted((ROOT / 'src/e05').glob('*.py'))}
        manifesto['ambiente'] = {'python': platform.python_version(), 'arquitetura': platform.machine(),
                                 'pacotes': {p: importlib.metadata.version(p) for p in ['pandas', 'numpy', 'scikit-learn', 'pyarrow']}}
        (args.output_dir / 'manifesto_base.json').write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        base[['nr_convenio', 'codigo_ibge', 'ano_coorte', 'data_assinatura', 'fim_horizonte', 'sem_repasse_90d',
              'treino_validacao', 'validacao', 'treino_final', 'teste', 'motivo_exclusao', 'exclusao_temporal']].to_csv(
                  args.output_dir / 'particoes.csv', index=False)
        print('Base congelada:', len(base), 'instrumentos; hash', manifesto['sha256_dataset'])
        return 0
    if args.acao == 'notebook':
        from .notebook import criar
        print(criar(ROOT))
        return 0
    if args.acao == 'executar-notebook':
        caminho = ROOT / 'notebooks/02_E05_classificacao_risco_municipal.ipynb'
        executar_notebook(caminho, args.output_dir)
        print('Notebook executado, sem células com erro:', caminho)
        return 0
    base, manifesto = ler_base(args.output_dir)
    if manifesto['configuracao'] != config:
        raise ValueError('Configuração mudou depois de congelar a base; preparar nova versão dos dados')
    resultados, metricas, predicoes = executar(base, config, args.output_dir / 'experimento')
    resultados['proveniencia'] = {'sha256_dataset': manifesto['sha256_dataset'], 'commit_base': manifesto['commit'],
                                  'ambiente': manifesto['ambiente'], 'data_carga': manifesto['data_carga_transferegov'],
                                  'hash_implementacao': manifesto['implementacao_hash']}
    (args.output_dir / 'experimento/resultados.json').write_text(json.dumps(resultados, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    figuras(predicoes, args.output_dir / 'figuras')
    consolidar(base, resultados, metricas, ROOT / 'docs/e05')
    print(metricas[metricas.particao == 'teste_2024'][['modelo', 'acuracia_balanceada', 'roc_auc', 'status_ajuste']].to_string(index=False))
    print('Conclusão:', resultados['status_conclusao'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
