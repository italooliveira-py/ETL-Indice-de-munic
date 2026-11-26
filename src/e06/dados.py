"""Carga do pacote E06 verificado, variáveis derivadas do histórico e grupos para leitura de erros."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

ROOT = Path(__file__).resolve().parents[2]
ALVO = 'y_1_sem_desembolso_365'
PARTICOES = ('train', 'validation', 'test')
CONTAGENS = ['historico_instrumentos_maduros', 'historico_atrasados', 'historico_eventos_financeiros',
             'historico_valor_desembolsado']
DERIVADAS = ['taxa_atraso_hist', 'sem_historico', 'valor_medio_evento']
# Cauda longa: entram em log1p dentro do pipeline.
EM_LOG = CONTAGENS + ['valor_global_assinatura', 'valor_medio_evento']
FAIXAS_PORTE = [0, 10_000, 20_000, 50_000, 100_000, np.inf]
ROTULOS_PORTE = ['até 10 mil', '10–20 mil', '20–50 mil', '50–100 mil', 'acima de 100 mil']


def ler_config(caminho=ROOT / 'config.e06.json'):
    return json.loads(Path(caminho).read_text(encoding='utf-8'))


def verificar_pacote(config):
    """Roda o verify_package.py do próprio pacote; qualquer divergência de hash interrompe."""
    pasta = ROOT / config['pacote']
    saida = subprocess.run([sys.executable, 'verify_package.py'], cwd=pasta, capture_output=True, text=True)
    if saida.returncode != 0:
        raise SystemExit(f'Pacote não verificado: {saida.stdout.strip()} {saida.stderr.strip()}')
    return json.loads(saida.stdout.strip().splitlines()[-1])


def carregar(config):
    pasta = ROOT / config['pacote'] / 'data'
    partes = {p: pd.read_parquet(pasta / f'{p}.parquet') for p in PARTICOES}
    for nome, parte in partes.items():
        parte[ALVO] = parte[ALVO].astype(int)
        parte['modalidade'] = parte['modalidade'].astype(str)
        parte['codigo_ibge'] = parte['codigo_ibge'].astype(str)
    return partes


class DerivadasHistorico(BaseEstimator, TransformerMixin):
    """Acrescenta a taxa de atraso suavizada, a marca de município novo e o valor médio por evento.

    Só a prevalência do treino é aprendida no fit; o resto é calculado linha a linha a partir das
    contagens do próprio instrumento, que o pacote já congela na data de assinatura.
    """

    def __init__(self, suavizacao=5.0):
        self.suavizacao = suavizacao

    def fit(self, x, y=None):
        self.prevalencia_ = float(np.mean(y)) if y is not None else 0.5
        return self

    def transform(self, x):
        x = x.copy()
        maduros = x['historico_instrumentos_maduros'].astype(float)
        eventos = x['historico_eventos_financeiros'].astype(float)
        a = self.suavizacao
        x['taxa_atraso_hist'] = (x['historico_atrasados'].astype(float) + a * self.prevalencia_) / (maduros + a)
        x['sem_historico'] = (maduros == 0).astype(float)
        x['valor_medio_evento'] = np.where(eventos > 0, x['historico_valor_desembolsado'] / eventos.where(eventos > 0, 1), 0.0)
        return x


def carregar_censurados(config):
    """Os 242 instrumentos de 2024 que o pacote deixou fora por falta de 365 dias até o corte de 2024."""
    c = pd.read_parquet(ROOT / config['pacote'] / 'data' / 'censored.parquet')
    c['modalidade'] = c['modalidade'].astype(str)
    c['codigo_ibge'] = c['codigo_ibge'].astype(str)
    return c


def rotular_por_desembolsos(base, config):
    """Y=1 se não há desembolso positivo em até 365 dias (inclusive) após a assinatura, pelos
    desembolsos do Silver (carga de 17/07/2026). Desembolsos anteriores à assinatura não contam."""
    des = pd.read_parquet((ROOT / config['desembolsos']).resolve())
    des = des[des.valor_desembolsado > 0].merge(base[['nr_convenio', 'data_assinatura']], on='nr_convenio')
    des = des[pd.to_datetime(des.data_desembolso) >= des.data_assinatura]
    primeiro = pd.to_datetime(base.nr_convenio.map(des.groupby('nr_convenio').data_desembolso.min()))
    dias = (primeiro - base.data_assinatura).dt.days
    return (~(dias <= 365)).astype(int).to_numpy()


def porte(codigos, config):
    """Faixa de população (IBGE, ano mais recente no Silver). Só para leitura de erros, nunca preditor."""
    caminho = (ROOT / config['ibge']).resolve()
    if not caminho.exists():
        return pd.Series('sem IBGE', index=codigos.index)
    ibge = pd.read_parquet(caminho).dropna(subset=['populacao']).sort_values('ano')
    pop = ibge.groupby(ibge.codigo_ibge.astype(str)).populacao.last()
    return classificar_porte(codigos, pop)


def classificar_porte(codigos, populacao):
    return pd.cut(codigos.map(populacao), FAIXAS_PORTE, labels=ROTULOS_PORTE, right=False).astype(str)


def experiencia(maduros):
    return pd.cut(maduros, [-1, 0, 5, np.inf], labels=['sem histórico', '1 a 5 maduros', 'mais de 5']).astype(str)
