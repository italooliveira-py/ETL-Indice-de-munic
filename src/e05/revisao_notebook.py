"""Notebook didático da revisão: alvo, desenho, benchmarking e limites separados."""
import nbformat as nbf
from .dados import ROOT


def criar():
    md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
    n = nbf.v4.new_notebook()
    n.metadata['kernelspec'] = {'display_name': 'Python 3 (E05)', 'language': 'python', 'name': 'python3'}
    n.metadata['language_info'] = {'name': 'python', 'version': '3.12'}
    n.cells = [
        md('''# E05 v2 — Benchmarking de risco observado em obras públicas

**28/10/2026 · Seed 42 · Samuel Colaço · dados exclusivamente públicos**

**Pergunta deste notebook:** entre Árvore de Decisão e Random Forest, como se comportam os classificadores de evento adverso observado em obras, frente a baselines nas mesmas partições? Contexto municipal ajuda a ordenar os casos?

O objetivo imediato é o benchmarking estatístico. Este notebook não calcula os pesos de um índice, não valida automaticamente um índice municipal e não demonstra que um modelo possa apoiar decisões reais. Essa avaliação de utilidade exige outra etapa.

Análise principal: o alvo da E04. Análise secundária: ausência de repasse em **180 dias**, sem substituir o conceito de risco de execução. A versão anterior de 90 dias permanece preservada.'''),
        md('''## 1. O que estamos tentando prever

| Elemento | Principal — ObrasGov | Secundário — Transferegov |
|---|---|---|
| Unidade | Projeto de obra pública | Instrumento assinado |
| Classe 1 | Cancelada, inacabada ou paralisada no snapshot | Sem desembolso positivo em até 180 dias |
| Classe 0 | Concluída no snapshot | Com desembolso positivo em até 180 dias |
| Não rotular | Obra sem resultado observável | Instrumento sem seguimento completo |
| O que não significa | Custo/margem ou todo o risco municipal | Fracasso definitivo da execução |

A E04 fornecida tem 1.638 obras, 1.077 censuradas e 358 elegíveis. Preservamos os mesmos 358 IDs e os rótulos para dar continuidade ao trabalho. Não convertemos censura em sucesso.

O artigo **Desafios e Oportunidades para o Desenvolvimento Regional** usa âncoras, Elastic Net e PCA para compor um índice de competitividade. Isso não fornece um rótulo observado de falha. O PDF **Predição de Fatores de Risco na Execução de Obras Públicas** é a apresentação da própria E04, e não um artigo externo independente. Usamos essas referências para distinguir objetivos, sem copiar pesos de outra amostra.'''),
        code('''from pathlib import Path
import os, sys, json
import numpy as np
import pandas as pd
from IPython.display import display, Image, Markdown
from unittest.mock import patch

ROOT = Path.cwd()
if not (ROOT / 'config.e05.revisao.json').exists():
    ROOT = ROOT.parent
assert (ROOT / 'config.e05.revisao.json').exists()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.e05.revisao import carregar, configuracoes, rodar
from src.e05.experimento import criar_pipeline

SEED = 42
_rede = patch('requests.Session.request', side_effect=RuntimeError('Notebook offline'))
_rede.start()
bases, manifesto = carregar()
configs = configuracoes()
assert all(c['random_state'] == SEED for c in configs.values())
print('Hashes das bases:', manifesto['hashes'])
print('Ambiente da preparação:', manifesto['ambiente'])
print('Diagnóstico:', manifesto['diagnostico'])'''),
        md('''## 2. A correção temporal e os limites que continuam existindo

Na montagem original, `ano_ref` podia vir do início previsto e avançar além do ano de cadastro usado na partição. Encontramos **21 casos** em que o ano de contexto era igual ou posterior ao ano da coorte. Além disso, referência de um ano não é o mesmo que divulgação naquele ano.

Nesta revisão, a coorte principal continua sendo o **ano de cadastro**, mas X é congelado antes de **1º de janeiro desse ano**. Recalculamos o contexto com datas de divulgação do IBGE, datas da versão enviada de DCA/RGF e histórico financeiro anterior. Não reutilizamos os 24 valores antigos automaticamente.

**Limite essencial:** o rótulo ObrasGov é um estado observado no snapshot; não temos datas completas do primeiro evento adverso e de sua publicação para reconstruir quando todos os rótulos teriam sido conhecidos. Portanto, esta é uma comparação **retrospectiva entre coortes de resultados observados**, condicionada à seleção da E04; não é um backtest prospectivo completo de todas as obras. O teste de 2024 já foi utilizado na E04 e não constitui validação externa inédita.'''),
        code('''principal = bases['principal']
display(principal.groupby('ano').agg(
    projetos=('id_projeto_investimento', 'size'), positivos=('evento_adverso_obrasgov', 'sum')))
assert principal.id_projeto_investimento.is_unique
assert not set(principal.loc[principal.treino_final, 'id_projeto_investimento']) & set(principal.loc[principal.teste, 'id_projeto_investimento'])
for c in principal.filter(like='disponibilidade_'):
    assert not (principal[c] >= principal.data_corte).any(), c
print('Contextos antigos potencialmente posteriores não reutilizados:', int(principal.contexto_e04_posterior_coorte.sum()))
display(principal.groupby('ano')[configs['principal']['numericas']].count())'''),
        md('''## 3. Preditores, transformações e por que não aplicar log por hábito

O conjunto principal tem **oito variáveis numéricas pré-declaradas**: população, PIB por habitante, instrumentos assinados no histórico, desembolsos e ordens de pagamento por habitante, receita por habitante, dependência de convênios e pessoal/RCL. Não entram IDs, ano, situação, execução física, datas finais, controles de qualidade ou qualquer derivação do próprio alvo.

As árvores trabalham com cortes do tipo `x ≤ limite`. Uma transformação estritamente crescente, como log, preserva a ordenação; elas não exigem normalidade nem log para corrigir assimetria. Por isso usamos **valores na escala original** nesta análise. Também não normalizamos o teste junto com o treino. A Logística recebe padronização dentro do pipeline porque a penalização depende da escala.

A ausência é imputada somente no treino de cada avaliação, com indicadores de faltantes. As versões fiscais disponíveis hoje podem ter sido retificadas; datas posteriores são excluídas, mas a reconstrução de todas as versões históricas permanece limitada. Não interpretar faltantes como incapacidade do município.'''),
        code('''preditores = configs['principal']['numericas']
display(pd.DataFrame({'preditor': preditores,
                      'cobertura_treino': [principal.loc[principal.treino_validacao, c].notna().mean() for c in preditores]}))
display(criar_pipeline('arvore', SEED, preditores, [], configs['principal']['parametros_modelos']))'''),
        md('''## 4. Protocolo estatístico e controle de complexidade

1. Desenvolvimento em **2022**; validação temporal em **2023**. O ajuste final usa 2022–2023 e todos os métodos são avaliados nos mesmos IDs de 2024.
2. CV de três folds **somente dentro de 2022**, agrupada por município e estratificada, com seed 42. Obras de um município não ficam dos dois lados de um fold. Essa CV mede sensibilidade interna; não substitui a validação temporal de 2023.
3. Configurações fixadas antes da avaliação: árvore com profundidade 3 e folha mínima 10; floresta com 300 árvores, profundidade 3 e folha mínima 10. Pesos balanceados nas árvores compensam a prevalência, mas podem prejudicar a calibração e não representam custos de negócio.
4. Sem busca extensa de hiperparâmetros ou seleção de variáveis pelo teste. Com apenas 12 positivos no desenvolvimento e cinco na validação, uma busca grande seria instável.
5. Baseline trivial = prevalência do treino; baseline logístico = regressão L2, C=1. Mesmos dados, cortes e preditores disponíveis. Os números antigos da E04 não são reaproveitados: o contexto e o ajuste final mudaram.
6. Critério de referência pré-definido: **AP na validação 2023**. Limiar técnico 0,5, sem otimização em 2024. Comparar com os baselines antes de recomendar substituição.'''),
        code('''PASTA = Path(os.environ.get('E05_OUTPUT_DIR', str(ROOT / 'output/e05_revisao')))
# Reproduz treinamento, CV, reajuste, teste e intervalos sem consultar a rede.
resultados, metricas = rodar(PASTA / 'notebook')
display(pd.read_csv(PASTA / 'notebook/principal/auditoria_cv.csv'))
cv = pd.read_csv(PASTA / 'notebook/principal/metricas_cv.csv')
display(cv.groupby('modelo')[['roc_auc', 'average_precision', 'acuracia_balanceada']].agg(['mean', 'std']))
display(metricas[(metricas.analise == 'principal') & (metricas.particao == 'validacao_2023')][
    ['nome', 'average_precision', 'roc_auc', 'acuracia_balanceada']])
print('Candidato entre as árvores:', resultados['principal']['candidato_validado'])
print('Referência por AP de validação, incluindo baselines:', resultados['principal'].get('referencia_por_ap_validacao'))'''),
        md('''## 5. Benchmark principal no teste de 2024

ROC-AUC mede a ordenação; Acurácia Balanceada é a média do acerto por classe; AP resume precisão–recall e deve ser comparada à prevalência. Acurácia global alta pode esconder a perda de todos os eventos adversos.

Incluímos **MAE das probabilidades** e **RMSE das probabilidades** como diagnósticos auxiliares: `MAE = média(|y−p|)` e `RMSE = √média((y−p)²) = √Brier`. São erros na escala 0–1, **não dias, reais ou erro de um índice contínuo**. MAE de probabilidade não é uma regra própria para avaliar calibração; não é critério principal de seleção. Não chamar esses classificadores de regressão contínua apenas porque essas contas existem.

As métricas de probabilidade também mostram o preço de pesos balanceados: um modelo pode ordenar melhor e ainda produzir probabilidades piores. Sem custos e validação de calibração, não tratamos seu score como probabilidade operacional confiável.'''),
        code('''campos = ['nome', 'n', 'classe_1', 'acuracia_balanceada', 'roc_auc', 'average_precision',
          'mae_probabilidade', 'rmse_probabilidade', 'brier']
display(metricas[(metricas.analise == 'principal') & (metricas.particao == 'teste_2024')][campos])
referencia = ROOT / 'docs/e05/revisao_v2/metricas.csv'
if referencia.exists():
    pd.testing.assert_frame_equal(metricas.reset_index(drop=True), pd.read_csv(referencia), check_dtype=False, rtol=1e-12)
display(Image(filename=str(PASTA / 'notebook/principal/figuras/matrizes_confusao.png')))
display(Image(filename=str(PASTA / 'notebook/principal/figuras/roc_teste.png')))
display(pd.read_csv(PASTA / 'notebook/principal/intervalos_cluster.csv'))'''),
        md('''## 6. Inspeção dos erros e do sobreajuste

Resíduos de classificação podem ser examinados como `y−p`, mas a análise deve destacar falsos negativos e falsos positivos. Não se exige normalidade desses resíduos para validar árvores. Comparar desempenho interno, validação e teste; um resultado pontual de 2024 não corrige uma validação fraca.

Os intervalos são condicionais ao teste e aos modelos ajustados, por reamostragem dos municípios; não simulam outros anos nem incluem toda a incerteza de seleção do modelo. A amostra tem poucos eventos e a exclusão de obras censuradas pode gerar viés de seleção.'''),
        code('''p = pd.read_csv(PASTA / 'notebook/principal/predicoes_teste_2024.csv')
ids = p.groupby('modelo').id_projeto_investimento.apply(set)
assert all(i == ids.iloc[0] for i in ids)
p['residuo_probabilidade'] = p.y_real - p.probabilidade
p['erro'] = np.select([(p.y_real == 1) & (p.y_previsto == 0), (p.y_real == 0) & (p.y_previsto == 1)],
                     ['falso_negativo', 'falso_positivo'], default='acerto')
display(p.groupby(['modelo', 'erro']).size().unstack(fill_value=0))
display(p[p.modelo == 'arvore'].assign(erro_absoluto=lambda q: q.residuo_probabilidade.abs())
        .sort_values('erro_absoluto', ascending=False).head(10))'''),
        md('''## 7. Sensibilidade separada — repasse em 180 dias

Alterar 90 para 180 dias não é a mesma tarefa que prever evento adverso em obra. Não escolhemos o horizonte que dá o melhor teste. A janela de 180 foi solicitada e fica explícita como outra análise.

No recorte estrito, desenvolvimento e validação continuam com classe única. O ajuste final possui apenas dois instrumentos com repasse em 180 dias e o teste tem três. Logo, uma ROC-AUC alta pode ser extremamente instável; não implica utilidade, e **não se compara sua AUC diretamente com a do alvo ObrasGov**. Sem validação discriminativa, não há candidato validado nessa análise.'''),
        code('''display(pd.DataFrame(resultados['secundario']['classes_por_particao']).T)
display(metricas[(metricas.analise == 'secundario') & (metricas.particao == 'teste_2024')][campos])
print('Estado:', resultados['secundario']['status_conclusao'])
assert resultados['secundario']['candidato_validado'] is None
assert resultados['secundario']['intervalos']['status'].startswith('nao_estimado')'''),
        md('''## 8. Conclusão e o que estes modelos não fazem

Concluímos um benchmarking reproduzível com um alvo observado mais próximo de risco de execução. Comparar os resultados não significa demonstrar causalidade, validar um índice multidimensional ou comprovar utilidade operacional. Os oito preditores são contexto municipal, sem atributos intrínsecos suficientes para explicar todos os problemas de uma obra.

Se um baseline superar as árvores na validação, isso deve orientar a conclusão, mesmo que uma árvore mostre uma métrica maior no teste já conhecido. A incerteza precisa acompanhar os números; não declarar um vencedor definitivo com cinco eventos na validação e 11 no teste.

O índice do artigo tem outro procedimento: selecionar âncoras e variáveis e compor dimensões com pesos. Importância de variável de uma árvore não substitui automaticamente esse procedimento nem vira peso causal de risco. Aprender a reproduzir uma pontuação calculada a partir das mesmas entradas seria circular como validação de risco.

**Para a defesa:** saber explicar y, a unidade, a censura, as datas de divulgação, o corte da coorte, CV por município, pesos balanceados, diferenças entre discriminação/calibração e a razão de preservar os baselines.

**IA e transparência:** Codex apoiou código, auditoria, testes e esta revisão técnica. Os dados são públicos e os resultados vêm das células executadas. Não foram refeitas Prospecção, Escuta ou Canvas já existentes. A equipe deve revisar e defender cada bloco.

**Referências:** artigo fornecido *Desafios e Oportunidades para o Desenvolvimento Regional*, pp. 5–6 e 12–15; apresentação própria *Predição de Fatores de Risco na Execução de Obras Públicas*, pp. 2–10; relatório E04 atualizado. Documentação técnica: [métricas](https://scikit-learn.org/stable/modules/model_evaluation.html), [árvores](https://scikit-learn.org/stable/modules/tree.html) e [CV por grupos](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html).'''),
    ]
    for i, c in enumerate(n.cells):
        c.id = f'e05-v2-{i:02d}'
    destino = ROOT / 'notebooks/03_E05_benchmark_risco_obras_180dias.ipynb'
    nbf.write(n, destino)
    return destino
