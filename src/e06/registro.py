"""Registro das rodadas: proveniência, registro.csv (só acrescenta) e aberturas do teste.

Padrão de proveniência copiado de src/e05/__main__.py (commit, hash da base, versões das bibliotecas).
Todo texto é gravado com LF, para os hashes baterem em qualquer máquina.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

from .dados import ROOT

PACOTES = ['pandas', 'numpy', 'scikit-learn', 'pyarrow', 'scipy']


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def escrever_texto(caminho: Path, texto: str):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding='utf-8', newline='\n')


def escrever_csv(quadro: pd.DataFrame, caminho: Path):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    quadro.to_csv(caminho, index=False, encoding='utf-8', lineterminator='\n')


def commit_codigo():
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        sujo = subprocess.check_output(['git', 'status', '--porcelain', '--', 'src/e06', 'config.e06.json'],
                                       cwd=ROOT, text=True).strip()
        return commit + ('+alteracoes_nao_commitadas' if sujo else '')
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'sem_git'


def versoes():
    return {p: importlib.metadata.version(p) for p in PACOTES}


def conferir_lock(config, fora_do_lock=False):
    """Compara as versões instaladas com o lock da equipe; diverge → para, salvo --fora-do-lock."""
    fixadas = {}
    for linha in (ROOT / config['lock']).read_text(encoding='utf-8').splitlines():
        if '==' in linha and not linha.startswith('#'):
            nome, versao = linha.strip().split('==')
            fixadas[nome.lower()] = versao
    diferencas = {p: (v, fixadas.get(p)) for p, v in versoes().items() if fixadas.get(p) not in (None, v)}
    if diferencas and not fora_do_lock:
        raise SystemExit(f'Ambiente fora do lock da equipe {diferencas}. Use o .venv ou --fora-do-lock.')
    return diferencas


def hash_pacote(config):
    manifesto = ROOT / config['pacote'] / 'audit' / 'manifesto.json'
    return sha256(manifesto.read_bytes())


def novo_run_id(experimento, fase):
    return f"{experimento}_{fase}_{datetime.now().strftime('%Y%m%dT%H%M%S')}"


def proveniencia(run_id, config, diferencas_lock):
    return {'run_id': run_id, 'data_hora': datetime.now().isoformat(timespec='seconds'),
            'commit_codigo': commit_codigo(), 'versao_pacote': config['versao_pacote'],
            'hash_pacote': hash_pacote(config), 'python': platform.python_version(),
            'arquitetura': platform.machine(), 'pacotes': versoes(),
            'fora_do_lock': diferencas_lock}


def acrescentar(caminho: Path, linhas):
    """Acrescenta linhas a um CSV sem apagar nada; colunas novas entram no fim."""
    novo = pd.DataFrame(linhas)
    if caminho.exists():
        novo = pd.concat([pd.read_csv(caminho, encoding='utf-8'), novo], ignore_index=True)
    escrever_csv(novo, caminho)


def registrar_abertura_teste(saida: Path, run_id, experimento, previsto_no_plano):
    acrescentar(saida / 'aberturas_teste.csv', [{'run_id': run_id, 'experimento': experimento,
                                                 'data_hora': datetime.now().isoformat(timespec='seconds'),
                                                 'prevista_no_plano': previsto_no_plano}])


def gravar_json(caminho: Path, conteudo):
    escrever_texto(caminho, json.dumps(conteudo, ensure_ascii=False, indent=2, default=str) + '\n')
