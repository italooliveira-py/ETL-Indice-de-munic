"""Figuras do E06 no formato da E05 (src/e05/relatorio.py): matriz de confusão, ROC e calibração."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import ConfusionMatrixDisplay, RocCurveDisplay

from .experimento import calibracao


def figuras(previsoes, limiares, destino: Path, titulo):
    """previsoes: colunas modelo, y, p (uma partição, um conjunto); limiares: modelo → limiar F1."""
    destino.mkdir(parents=True, exist_ok=True)
    nomes = list(dict.fromkeys(previsoes.modelo))
    colunas = (len(nomes) + 1) // 2
    fig, eixos = plt.subplots(2, colunas, figsize=(3.6 * colunas, 7), squeeze=False)
    for ax, nome in zip(eixos.flat, nomes):
        parte = previsoes[previsoes.modelo == nome]
        ConfusionMatrixDisplay.from_predictions(parte.y, (parte.p >= limiares[nome]).astype(int), labels=[0, 1],
                                                colorbar=False, ax=ax, cmap='Blues')
        ax.set(title=f'{nome} (limiar {limiares[nome]:.2f})', xlabel='Classe prevista', ylabel='Classe observada')
    for ax in list(eixos.flat)[len(nomes):]:
        ax.axis('off')
    fig.suptitle(titulo + ' — matriz de confusão no limiar F1', y=1.0)
    fig.tight_layout()
    fig.savefig(destino / 'matrizes_confusao.png', dpi=120, bbox_inches='tight')
    plt.close(fig)

    fig, (ax_roc, ax_cal) = plt.subplots(1, 2, figsize=(11, 4.5))
    for nome in nomes:
        parte = previsoes[previsoes.modelo == nome]
        RocCurveDisplay.from_predictions(parte.y, parte.p, name=nome, ax=ax_roc)
        cal = calibracao(parte.y, parte.p)
        ax_cal.plot(cal.previsto, cal.real, marker='o', label=nome)
    for ax in (ax_roc, ax_cal):
        ax.plot([0, 1], [0, 1], color='grey', linestyle='--', linewidth=1)
    ax_roc.set_title('Curva ROC')
    ax_cal.set(xlabel='Probabilidade prevista (decil)', ylabel='Proporção real de Y=1', title='Calibração',
               xlim=(0, 1), ylim=(0, 1))
    ax_cal.legend(fontsize=8)
    fig.suptitle(titulo)
    fig.tight_layout()
    fig.savefig(destino / 'roc_calibracao.png', dpi=120, bbox_inches='tight')
    plt.close(fig)


def figura_matrizes(quadro, destino: Path):
    """Uma grade modelo × limiar por conjunto; na capacidade, as contagens são esperadas (fracionárias)."""
    destino.mkdir(parents=True, exist_ok=True)
    for conjunto, q in quadro.groupby('conjunto', sort=False):
        modelos, tipos = list(dict.fromkeys(q.modelo)), list(dict.fromkeys(q.limiar_tipo))
        fig, eixos = plt.subplots(len(modelos), len(tipos), figsize=(3.2 * len(tipos), 2.6 * len(modelos)), squeeze=False)
        for (i, modelo), (j, tipo) in ((a, b) for a in enumerate(modelos) for b in enumerate(tipos)):
            m = q[(q.modelo == modelo) & (q.limiar_tipo == tipo)].iloc[0]
            grade = np.array([[m.vn, m.fp], [m.fn, m.vp]], dtype=float)
            ax = eixos[i, j]
            ax.imshow(grade, cmap='Blues')
            for a, b in np.ndindex(2, 2):
                ax.text(b, a, f'{grade[a, b]:.0f}' if grade[a, b].is_integer() else f'{grade[a, b]:.1f}',
                        ha='center', va='center')
            ax.set_xticks([0, 1], ['prev. 0', 'prev. 1'])
            ax.set_yticks([0, 1], ['real 0', 'real 1'])
            ax.set_title(f'{modelo} — {tipo}\nprecisão {m.precisao:.2f}, recall {m.recall:.2f}', fontsize=8)
        fig.suptitle(f'A0 {conjunto} — teste 2022–2023: matrizes de confusão em três limiares', y=1.0)
        fig.tight_layout()
        fig.savefig(destino / f'matrizes_tres_limiares_{conjunto}.png', dpi=110, bbox_inches='tight')
        plt.close(fig)
