# Revisão técnica da E05

**Versão 2.0.0 — 28/10/2026.** Esta revisão preserva os experimentos anteriores e não reescreve Prospecção, Escuta, Canvas ou os documentos fornecidos pela equipe.

## Avaliação do trabalho anterior

A base de engenharia era aproveitável: snapshots públicos, hashes, seed, pipeline, cuidado com censura e comparação de baselines. O problema foi tomar a falta de repasse em 90 dias como se representasse o objetivo amplo de risco de execução municipal. Esse alvo não media paralisação, conclusão, margem ou custo; na amostra, tampouco oferecia duas classes no treino.

Trocar 90 por 180 dias não resolve sozinho a formulação. Nesta revisão, a decisão confirmada pelo usuário é retomar o desfecho observado da E04 como principal e apresentar 180 dias apenas como sensibilidade de outro fenômeno. Não foi criado um índice artificial para ser previsto a partir dos próprios componentes, o que seria uma validação circular de risco.

## Duas análises e seus contratos

| Elemento | Principal | Secundária |
|---|---|---|
| Unidade | Projeto ObrasGov | Instrumento Transferegov |
| Alvo | 1 = cancelada, inacabada ou paralisada; 0 = concluída | 1 = sem desembolso positivo até 180 dias; 0 = com desembolso |
| Ausência de resultado | Censura, excluída sem rotular como sucesso | Seguimento incompleto, excluído sem rotular como ausência |
| População | Mesmos 358 IDs elegíveis da E04 | Assinaturas municipais da PB em 2022–2024 |
| Desenvolvimento / validação / teste | 127 / 121 / 110, respectivamente | 46 / 10 / 242 após os cortes de maturidade |
| Ajuste final | 248 projetos de 2022–2023 | 249 instrumentos de 2022–2023 com 180 dias conhecidos antes de 2024 |

O risco da análise principal é **evento adverso observado em obras**, não custo, margem, falha definitiva de qualquer projeto ou o próprio índice municipal. As duas tarefas não possuem uma classificação conjunta de “melhor AUC”: os rótulos, as populações e o suporte são diferentes.

## Correção de comparabilidade temporal

Nos dados da E04, `ano_ref` podia ser definido pelo início previsto, enquanto a coorte vinha do cadastro. Em 21 projetos, isso fornecia contexto de ano igual ou posterior ao ano da partição. O código novo usa esses valores apenas no diagnóstico, nunca como entrada do modelo.

O contexto principal é reconstruído antes de 1º de janeiro do ano da coorte de cadastro, com calendário de divulgação do IBGE, data da versão enviada de DCA/RGF e eventos financeiros anteriores. O conjunto foi reduzido a oito preditores teóricos disponíveis; os 24 valores antigos não são carregados automaticamente em X. Por isso os baselines são recalculados: não se espera reproduzir a antiga ROC-AUC 0,4155, que pertencia a outra preparação e a um ajuste apenas em 2022.

Permanece uma limitação que não pode ser corrigida com uma divisão de anos: não há data confiável do primeiro evento adverso e de publicação de todos os rótulos ObrasGov. O benchmark é retrospectivo, condicionado a obras com resultado observável na seleção da E04. Ele não demonstra quais rótulos já eram conhecidos em janeiro de 2024, não resolve o viés da censura e não equivale a uma simulação prospectiva completa. O teste 2024 já foi consultado na E04, portanto não é uma avaliação externa inédita.

## Modelo e princípios estatísticos

- Seed 42 em todas as etapas aleatórias; snapshots e configurações versionados, sem rede durante o notebook.
- Árvore de profundidade 3 e folha mínima 10; floresta com 300 árvores, profundidade 3 e folha mínima 10. Pesos balanceados fixados como hipótese técnica para o desbalanceamento, sem ajuste pelo teste.
- CV estratificada por grupos municipais somente em 2022. Nenhum município aparece nos dois lados de um fold. Essa CV é um diagnóstico interno; a validação temporal separada continua sendo 2023.
- Não há busca extensa de hiperparâmetros, seleção de variáveis pelo teste, oversampling ou calibração ajustada em 2024.
- O candidato é indicado pela AP da validação de 2023, incluindo a verificação de superioridade frente aos baselines. Os números de 2024 não redefinem o critério.
- Imputação e escala são aprendidas dentro do pipeline. Os modelos de árvore usam valores na escala original: log não é um requisito para árvores, que operam por ordenação e limiares. A escala da Logística é necessária para que sua penalização não seja dominada por unidades monetárias.
- Intervalos por bootstrap dos municípios são condicionais ao teste e ao ajuste fixo. Não representam toda a incerteza entre anos ou de escolha do modelo.

## Como interpretar MAE e RMSE aqui

Como o alvo principal é binário, os critérios principais continuam sendo Acurácia Balanceada, ROC-AUC e Average Precision. Para dialogar com o pedido de benchmarking estatístico da equipe, também calculamos `MAE = média(|y−p|)` e `RMSE = √média((y−p)²)`, sobre as probabilidades.

Esses erros estão na escala 0–1; não são erros em dias, reais, margem ou pontuação de um índice. O RMSE é a raiz do Brier. MAE de probabilidade não é uma regra própria de calibração e não será usado isoladamente para escolher o modelo. Discriminação e qualidade das probabilidades podem apontar em direções diferentes, principalmente com pesos balanceados. A apresentação dessas medidas auxiliares não transforma o problema em regressão contínua.

## Literatura e limites da transferência de métodos

O artigo fornecido **Desafios e Oportunidades para o Desenvolvimento Regional Um Índice Multidimensional de Competitividade Municipal para o Nordeste**, especialmente pp. 5–6 e 12–15, usa âncoras por dimensão, seleção por Elastic Net e ponderação por PCA. Isso ajuda a pensar o índice, mas não fornece rótulos observados de falha. Seus pesos, escalas e resultados não devem ser transplantados para este conjunto incompleto de fontes e outra população. Importância de variável em uma árvore também não é automaticamente um peso de índice ou um efeito causal.

**Predição de Fatores de Risco na Execução de Obras Públicas**, apresentado como Entrega 4 da própria equipe, é uma apresentação de 12 páginas. Junto ao DOCX atualizado da E04, ele fundamenta a continuidade da unidade, dos rótulos e dos limites. Não foi tratado como artigo externo independente nem como demonstração de utilidade operacional.

Como referência externa adicional, o resumo público da editora de [Machine Learning Algorithms for Construction Projects Delay Risk Prediction, Journal of Construction Engineering and Management, 146(1), 2020](https://ascelibrary.com/doi/10.1061/%28ASCE%29CO.1943-7862.0001736) descreve comparação de classificadores, incluindo árvore, sobre desempenho de prazo observado e validação cruzada. O resumo apoia a escolha de um desfecho explícito e benchmarking; não permite importar seu desempenho ou supor que os fatores municipais disponíveis aqui bastem. O texto integral dessa referência não foi usado.

Referências técnicas primárias: [métricas](https://scikit-learn.org/stable/modules/model_evaluation.html), [árvores](https://scikit-learn.org/stable/modules/tree.html), [CV por grupos](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html).

## Reprodução

```powershell
python -m pip install -r requirements-e05-lock.txt
python -m src.e05.revisao executar
python -m src.e05.revisao executar-notebook
python -m unittest discover -s tests -v
```

Os dois primeiros comandos de análise utilizam os snapshots em `dados/modelagem/e05_revisao/`; não exigem coleta de APIs ou caminhos da máquina de um integrante. Se o ambiente foi criado com uv sem pip, use `uv pip install --python .venv/Scripts/python.exe -r requirements-e05-lock.txt`. O runtime validado é Python 3.12 x64; novas plataformas devem usar dependências compatíveis e conferir as métricas.

`python -m src.e05.revisao preparar` é uma operação explícita de reconstrução com o Bronze já disponível. Não faz downloads e não integra o fluxo de treinamento comum. Alterações de fonte ou configuração exigem nova versão e conferência de hashes. Os exemplos de 90 dias e seus resultados ficam preservados como histórico v1.

Resultados: [quadro 2024](quadro_comparacao_2024.csv), [todas as métricas](metricas.csv), [configuração e limites executados](resultados.json) e o notebook `03_E05_benchmark_risco_obras_180dias.ipynb`.
