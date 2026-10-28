"""Gera um notebook executável que reproduz a comparação a partir da base congelada."""
from pathlib import Path
import nbformat as nbf


def criar(raiz: Path):
    md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
    nb = nbf.v4.new_notebook()
    nb.metadata['kernelspec'] = {'display_name': 'Python 3 (E05)', 'language': 'python', 'name': 'python3'}
    nb.metadata['language_info'] = {'name': 'python', 'version': '3.12'}
    nb.cells = [
        md('''# E05 — Risco inicial do projeto em contexto municipal

**Versão 1.0 — 28/10/2026 — contribuição de Samuel Colaço.**

Dados exclusivamente públicos. Comparação de **Decision Tree Classifier**, **Random Forest Classifier**, baseline trivial e baseline operacional de referência (**Regressão Logística**).

O alvo atualizado é **`sem_repasse_90d`**: 1 se não houver desembolso positivo entre a assinatura e o dia 90, inclusive; 0 se houver. Não se prevê diretamente estouro de custo, margem ou fracasso definitivo. Uma linha representa um instrumento municipal da PB; características do município são contexto, não um alvo municipal agregado.

**Achado de viabilidade:** o treino desta versão possui uma única classe. O notebook não oculta essa restrição: árvores podem ser ajustadas, mas aprendem uma regra constante; a Logística não é estimável. O teste não autoriza fabricar exemplos ou trocar o horizonte.'''),
        md('''## 1. Reprodução e proveniência

Execute os comandos de coleta e preparação descritos no README antes deste notebook. A execução abaixo é **offline**: confere o hash da base congelada e utiliza o mesmo código compartilhado da CLI. Instale `requirements-e05.txt` no ambiente Python x64 e execute da raiz do repositório.

As fontes são Transferegov Discricionárias, Transferências Especiais como histórico, IBGE e SICONFI DCA/RGF. As datas públicas de divulgação/envio são respeitadas; registros tardios e revisões atuais impedem afirmar que a reconstrução é uma fotografia histórica integral.'''),
        code('''from pathlib import Path
import sys, json, os
import numpy as np
import pandas as pd
from IPython.display import display, Markdown, Image

ROOT = Path.cwd()
if not (ROOT / 'config.e05.json').exists():
    ROOT = ROOT.parent
assert (ROOT / 'config.e05.json').exists(), 'Execute o notebook a partir do projeto'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.e05.__main__ import ler_base
from src.e05.dados import PREDITORES, NUMERICAS, CATEGORICAS
from src.e05.experimento import executar, criar_pipeline
from src.e05.relatorio import figuras
from unittest.mock import patch
# Nenhum download faz parte da execução do notebook.
_bloqueio_rede = patch('requests.Session.request', side_effect=RuntimeError('Notebook E05 executado offline'))
_bloqueio_rede.start()

PASTA = Path(os.environ.get('E05_OUTPUT_DIR', str(ROOT / 'output/e05')))
CONFIG = json.loads((ROOT / 'config.e05.json').read_text(encoding='utf-8'))
SEED = CONFIG['random_state']
base, manifesto = ler_base(PASTA)
assert manifesto['configuracao'] == CONFIG
print('SHA-256:', manifesto['sha256_dataset'])
print('Carga Transferegov:', manifesto['data_carga_transferegov'])
print('Ambiente:', manifesto['ambiente'])
print('Instrumentos:', len(base))'''),
        md('''## 2. Contrato, seguimento e partições

Pré-convênios não entram. Desembolso zero não caracteriza repasse; desembolso anterior à assinatura é inconsistência. Seguimento incompleto não recebe classe 1. A janela de 90 dias é técnica e não representa um prazo legal.

Desenvolvimento em 2022 → validação em 2023 → reajuste em 2022–2023 → teste em 2024. Para validar 2023, o rótulo precisa estar conhecido antes de 01/01/2023. Para o ajuste final, antes de 01/01/2024. Por isso assinaturas recentes podem ser excluídas do ajuste mesmo pertencendo ao ano de treino. Os mesmos IDs são usados por todos os métodos.'''),
        code('''coortes = base.groupby('ano_coorte').agg(
    instrumentos=('nr_convenio', 'size'),
    classe_0=('sem_repasse_90d', lambda s: int((s == 0).sum())),
    classe_1=('sem_repasse_90d', lambda s: int((s == 1).sum())),
    excluidos_corte=('exclusao_temporal', 'sum'))
display(coortes)
suporte = []
for nome in ['treino_validacao', 'validacao', 'treino_final', 'teste']:
    q = base[base[nome]]
    suporte.append({'particao': nome, 'n': len(q), 'classe_0': int((q.sem_repasse_90d == 0).sum()),
                    'classe_1': int((q.sem_repasse_90d == 1).sum())})
display(pd.DataFrame(suporte))
assert not set(base.loc[base.treino_final, 'nr_convenio']) & set(base.loc[base.teste, 'nr_convenio'])
assert (base.loc[base.treino_final, 'fim_horizonte'] < pd.Timestamp('2024-01-01')).all()
display(base.motivo_exclusao.fillna('sem_problema_qualidade').value_counts().to_frame('n'))'''),
        md('''## 3. Contexto municipal e prevenção de vazamento

Usamos 12 preditores pré-declarados: valor na assinatura; população e PIB per capita do IBGE já divulgados; histórico de instrumentos e repasses nos 365 dias anteriores; receita por habitante, dependência de convênios e pessoal/RCL com envio anterior; modalidade, órgão superior e mês.

Não entram situação atual, vigência atual, prorrogações, primeiro repasse, acumulados posteriores, identificadores ou o próprio alvo. A DCA de um ano não é considerada conhecida só porque seu ano é anterior: a data da versão enviada também precisa preceder a assinatura. O mesmo vale para o RGF. Censo 2022 e PIB defasados respeitam o calendário de divulgação.

Imputação, escala da Logística e codificação de categorias são ajustadas dentro de `Pipeline`/`ColumnTransformer`, somente no treino de cada avaliação. Árvores dispensam escala. Categorias pouco frequentes são agrupadas; não há SMOTE nem seleção de variáveis pelo teste.'''),
        code('''display(pd.DataFrame({'preditor': PREDITORES,
                      'cobertura_treino_final': [base.loc[base.treino_final, c].notna().mean() for c in PREDITORES]}))
for c in base.filter(like='disponibilidade_'):
    assert not (base[c] >= base.data_assinatura).any(), c
display(base.loc[base.treino_final, NUMERICAS].describe().T)
print('Preditores categóricos:', CATEGORICAS)
display(criar_pipeline('arvore', SEED))'''),
        md('''## 4. Modelos, baselines e regularização

- **Trivial:** probabilidade constante igual à prevalência do treino.
- **Logística:** referência regularizada, `C=1`, com preparo no pipeline. Requer exemplos das duas classes. Não substituir por Dummy caso não possa ser ajustada.
- **Árvore:** profundidade inicial 3 e no mínimo 10 instrumentos por folha.
- **Floresta:** 300 árvores, profundidade inicial 5, no mínimo 10 instrumentos por folha e fração de atributos 0,7.

O ajuste de complexidade só é habilitado com pelo menos dois folds temporais válidos e suporte mínimo de cada classe. Classe única bloqueia a busca: uma árvore tem impureza zero na raiz, não há separação a aprender. Mais árvores ou mais preditores não resolvem isso.

O limiar é 0,5, fixado antes do teste. Não há custos B/C de uma política externa confirmada; esse é um limiar técnico. Baseline logístico e modelos não foram escolhidos pelos resultados de 2024.'''),
        code('''# Executa os ajustes e a avaliação final com o mesmo protocolo da CLI.
resultados, tabela_metricas, predicoes = executar(base, CONFIG, PASTA / 'notebook')
display(pd.DataFrame(resultados['classes_por_particao']).T)
display(pd.read_csv(PASTA / 'notebook/auditoria_cv.csv'))
print('Ajustes:', json.dumps(resultados['ajustes'], ensure_ascii=False, indent=2))'''),
        md('''## 5. Quadro de comparação — exatamente o teste de 2024

**Acurácia balanceada** é a média da sensibilidade de cada classe. **ROC-AUC** mede ordenação, atribuindo meio crédito a empates. **Average Precision** deve ser lida contra a prevalência da classe positiva. Acurácia global, isoladamente, é enganosa com desbalanceamento extremo.

Métrica não estimável fica ausente. Uma Regressão Logística que não pôde ser ajustada não possui um ROC-AUC medido. Árvores constantes podem ter métricas matematicamente calculáveis no teste, sem constituir modelos discriminativos validados.'''),
        code('''teste_metricas = tabela_metricas[tabela_metricas.particao == 'teste_2024']
display(teste_metricas[['nome', 'n', 'classe_0', 'classe_1', 'acuracia', 'acuracia_balanceada',
                       'roc_auc', 'average_precision', 'brier', 'status_ajuste']])
ids_por_modelo = predicoes.groupby('modelo').nr_convenio.apply(set)
assert all(ids == ids_por_modelo.iloc[0] for ids in ids_por_modelo)
# Comparação de reprodução com a execução de referência, se já existir.
referencia = PASTA / 'experimento/metricas.csv'
if referencia.exists():
    pd.testing.assert_frame_equal(tabela_metricas.reset_index(drop=True), pd.read_csv(referencia),
                                  check_dtype=False, check_exact=False, rtol=1e-12)
figuras(predicoes, PASTA / 'figuras_notebook')
display(Image(filename=str(PASTA / 'figuras_notebook/suporte_teste.png')))
display(Image(filename=str(PASTA / 'figuras_notebook/matrizes_confusao.png')))
display(Image(filename=str(PASTA / 'figuras_notebook/roc_teste.png')))'''),
        md('''## 6. Diagnóstico de erros e confiabilidade

Inspecionar falsos positivos e negativos, não apenas a média. Um falso positivo aqui sinaliza ausência de repasse quando houve; não é um estouro de custo. Verificar também resultados por modalidade e município, reconhecendo o suporte reduzido.

O Brier pode parecer baixo quando a classe dominante quase sempre ocorre, mesmo sem discriminação. Probabilidade constante extrema não demonstra calibração operacional. Intervalos por bootstrap não são publicados com menos de dez casos da classe minoritária: um intervalo estreito para uma regra constante não resolveria a falta de informação.'''),
        code('''erros = predicoes[(predicoes.modelo == 'arvore') & (predicoes.y_real != predicoes.y_previsto)]
detalhes = erros.merge(base[['nr_convenio', 'modalidade', 'orgao_superior', 'primeiro_repasse']],
                       on='nr_convenio', validate='one_to_one')
display(detalhes)
display(predicoes.groupby('modelo').agg(instrumentos=('nr_convenio', 'size'),
                                        probabilidades_distintas=('probabilidade', 'nunique')))
print('Incerteza:', resultados['intervalos'])
print('Conclusão:', resultados['status_conclusao'])'''),
        md('''## 7. Conclusão, limites e defesa individual

Este estudo preserva o alvo solicitado e mostra sua limitação nesta população e nestes anos. No treino há somente instrumentos sem repasse em 90 dias; as árvores ajustadas viram respostas constantes e não superam a regra trivial em discriminação. A Logística não pode ser estimada. Isso é um diagnóstico estatístico do desenho do problema, não evidência de que Random Forest é sempre inadequado.

O uso de IBGE, receitas, pessoal e histórico de transferências foi implementado com datas anteriores, mas não cria exemplos de projetos pagos dentro da janela. Não há classificador operacional validado, não há previsão direta de estouro financeiro e não há estimativa definitiva de risco municipal.

O teste cobre um ano e poucos exemplos da classe minoritária. Revisões de dados e defasagem do registro no portal permanecem limitações. Qualquer revisão de horizonte, população ou momento da previsão deve ser versionada, acordada com a equipe e avaliada como outro experimento; não ajustar o alvo para melhorar o placar de 2024.

**Para explicar na avaliação:** por que purgar rótulos ainda desconhecidos; por que usar a mesma partição dos baselines; por que árvore de classe única não aprende separação; por que ROC-AUC constante vale 0,5; por que a Logística fica sem métrica; por que acurácia alta não implica utilidade.

**Uso de IA:** Codex auxiliou a implementação, a auditoria, os testes e a redação. Os resultados são calculados neste notebook, com dados públicos e código inspecionável. A equipe deve revisar e ser capaz de explicar cada bloco.'''),
    ]
    for i, celula in enumerate(nb.cells):
        celula.id = f'e05-{i:02d}'
    destino = raiz / 'notebooks/02_E05_classificacao_risco_municipal.ipynb'
    nbf.write(nb, destino)
    return destino
