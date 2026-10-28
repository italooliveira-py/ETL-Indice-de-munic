"""Figuras e resumo da E05; métricas indisponíveis continuam ausentes."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import ConfusionMatrixDisplay, RocCurveDisplay


def figuras(predicoes, destino: Path, titulo='Teste 2024 — 1 = sem repasse em 90 dias'):
    destino.mkdir(parents=True, exist_ok=True)
    nomes = [n for n in ['trivial', 'logistica', 'arvore', 'floresta'] if n in set(predicoes.modelo)]
    fig, eixos = plt.subplots(1, len(nomes), figsize=(4 * len(nomes), 3.8), squeeze=False)
    for ax, nome in zip(eixos[0], nomes):
        parte = predicoes[predicoes.modelo == nome]
        ConfusionMatrixDisplay.from_predictions(parte.y_real.astype(int), parte.y_previsto,
                                                labels=[0, 1], colorbar=False, ax=ax, cmap='Blues')
        ax.set_title(nome.capitalize())
        ax.set_xlabel('Classe prevista')
        ax.set_ylabel('Classe observada')
    fig.suptitle(titulo, y=1.02)
    fig.tight_layout()
    fig.savefig(destino / 'matrizes_confusao.png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for nome in nomes:
        parte = predicoes[predicoes.modelo == nome]
        if parte.y_real.nunique() == 2:
            RocCurveDisplay.from_predictions(parte.y_real.astype(int), parte.probabilidade, name=nome, ax=ax)
    ax.plot([0, 1], [0, 1], ':', color='gray')
    ax.set_title('ROC — teste 2024; verificar suporte às duas classes')
    fig.tight_layout()
    fig.savefig(destino / 'roc_teste.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.5, 4))
    parte = predicoes[predicoes.modelo == nomes[0]]
    valores = parte.y_real.value_counts().reindex([0, 1], fill_value=0)
    barras = ax.bar(['0: repasse em até 90 dias', '1: sem repasse em 90 dias'], valores, color=['#267d9a', '#be6538'])
    ax.bar_label(barras, padding=3)
    ax.set_ylim(0, max(valores) * 1.15)
    ax.set_ylabel('Instrumentos')
    ax.set_title('Suporte das classes no teste 2024')
    fig.tight_layout()
    fig.savefig(destino / 'suporte_teste.png', dpi=160)
    plt.close(fig)


def consolidar(base, resultados, metricas, destino: Path):
    """Evidências pequenas e versionáveis, separadas da base e dos artefatos gerados."""
    destino.mkdir(parents=True, exist_ok=True)
    coortes = base.groupby('ano_coorte').agg(
        instrumentos=('nr_convenio', 'size'), classe_0=('sem_repasse_90d', lambda s: int((s == 0).sum())),
        classe_1=('sem_repasse_90d', lambda s: int((s == 1).sum())),
        problemas_qualidade=('motivo_exclusao', lambda s: int(s.notna().sum())),
        excluidos_corte_2024=('exclusao_temporal', 'sum')).reset_index()
    coortes.to_csv(destino / 'auditoria_coortes.csv', index=False)
    campos = ['nome', 'n', 'classe_0', 'classe_1', 'acuracia_balanceada', 'roc_auc',
              'average_precision', 'status_ajuste']
    quadro = metricas[metricas.particao == 'teste_2024'][campos]
    quadro.to_csv(destino / 'quadro_comparacao_2024.csv', index=False, encoding='utf-8-sig')
    (destino / 'resultados_execucao.json').write_text(json.dumps(resultados, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    linhas = ['# E05 — Resultado executado em 2026-10-28', '',
              'Dados exclusivamente públicos. Alvo: `sem_repasse_90d`, por instrumento assinado na PB.', '',
              '## Comparação no mesmo teste de 2024', '',
              '| Método | N | Acurácia balanceada | ROC-AUC | Estado do ajuste |',
              '|---|---:|---:|---:|---|']
    for r in quadro.itertuples():
        fmt = lambda valor: 'não estimável' if pd.isna(valor) else f'{valor:.4f}'
        linhas.append(f'| {r.nome} | {r.n} | {fmt(r.acuracia_balanceada)} | {fmt(r.roc_auc)} | {r.status_ajuste} |')
    linhas += ['', '## Interpretação', '',
               'A disponibilidade de mais preditores municipais não compensa a ausência de uma classe no treino. '
               'Uma árvore ajustada em classe única produz uma folha constante; a floresta repete essa regra. '
               'A Regressão Logística não foi substituída por um baseline diferente para fabricar números.', '',
               'O limiar foi fixado em 0,5; não houve seleção pelo teste. Os rótulos do treino final precisaram '
               'estar observáveis antes de 01/01/2024. As coortes são definidas pela assinatura, não pelo desembolso.', '',
               'Não há modelo discriminativo validado neste experimento se o treino contém somente a classe 1. '
               'Acurácia global elevada nesse cenário não significa utilidade para identificar quais projetos receberão repasse. '
               'Qualquer mudança futura da janela exigirá nova versão do contrato e um experimento separado, acordado com a equipe.', '',
               '## Limitações', '',
               '- O evento é ausência de repasse dentro da janela, não estouro de custo ou insucesso definitivo.',
               '- O conjunto é restrito a instrumentos municipais da PB nas Discricionárias; não representa todos os projetos públicos.',
               '- Contexto: IBGE, DCA/RGF e histórico das duas modalidades do Transferegov, com datas anteriores à assinatura.',
               '- Datas de divulgação/envio foram respeitadas, mas versões públicas atuais podem conter revisões e registros tardios.',
               '- Um único ano de teste e suporte minoritário escasso não permitem alegar estabilidade futura ou calibração operacional.', '',
               '## Uso de IA', '',
               'Codex auxiliou a implementação, a revisão do contrato temporal, os testes e a documentação. '
               'Os dados são públicos. Métricas vêm da execução; ausência de resultado foi explicitada. '
               'A equipe deve revisar e ser capaz de defender os blocos do notebook.', '']
    (destino / 'RESULTADOS.md').write_text('\n'.join(linhas), encoding='utf-8')
