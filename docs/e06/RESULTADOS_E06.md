# E06 — Resultados

Execução do `PLANO_E06.md` sobre o pacote `4h1a7c9e3b5d0f2e6a8c`.

- Alvo: `y_1_sem_desembolso_365`.
- Teste 2022–2023: 625 instrumentos, 83,2% com Y=1. Os números vêm da primeira abertura do teste de cada experimento.
- Intervalos de 95% por bootstrap de municípios (1.000 reamostragens).
- Brier skill: 0 equivale a prever a prevalência do treino (76,5%).

## Resumo

1. Nenhum modelo supera a taxa de Y=1 da modalidade no treino. Contrato de repasse tem 89% de Y=1 no teste e convênio, 67%.
2. Dentro de cada modalidade, os modelos ordenam como um sorteio.
3. A validação 2020–2021 escolheu a logística pelo nível da previsão, e esse ganho não se repetiu no teste.
4. Histórico do município, valor na assinatura e ano não acrescentam informação que se mantenha em anos novos.
5. Em 2024 surge a modalidade "TERMO DE COMPROMISSO", ausente do pacote, com 47% dos instrumentos do ano.

## 1. Teste (A0)

A precisão no top k% usa o valor esperado nos empates (seção 6).

| Conjunto | Modelo | Brier skill [IC 95%] | ROC-AUC [IC 95%] | Previsto médio | Precisão top 10 / 20 / 30% |
|---|---|---|---|---|---|
| — | Trivial | 0,000 | 0,500 | 0,765 | 83,2 / 83,2 / 83,2 |
| — | Taxa por modalidade | +0,071 [+0,034; +0,114] | 0,645 [0,591; 0,707] | 0,780 | 88,6 / 88,6 / 88,6 |
| M1 | Logística | +0,030 [−0,059; +0,125] | 0,606 [0,508; 0,705] | 0,904 | 74,4 / 82,4 / 84,5 |
| M1 | Árvore | −0,011 [−0,021; −0,003] | 0,500 | 0,754 | 83,2 / 83,2 / 83,2 |
| M1 | Random Forest | +0,071 [+0,032; +0,113] | 0,652 [0,581; 0,733] | 0,808 | 93,6 / 89,6 / 90,4 |
| M1 | Gradient Boosting | +0,050 [+0,026; +0,079] | 0,637 [0,572; 0,707] | 0,787 | 91,9 / 89,9 / 90,8 |
| M1 | SVC | +0,023 [−0,001; +0,050] | 0,516 [0,439; 0,597] | 0,798 | 80,8 / 87,2 / 86,5 |
| M1 | MLP | +0,054 [+0,023; +0,084] | 0,662 [0,571; 0,751] | 0,787 | 95,2 / 86,4 / 89,9 |
| M1+ | Logística | +0,014 [−0,076; +0,110] | 0,586 [0,512; 0,670] | 0,902 | 74,4 / 83,2 / 86,7 |
| M1+ | Árvore | +0,049 [−0,022; +0,127] | 0,643 [0,591; 0,706] | 0,865 | 88,6 / 88,6 / 88,6 |
| M1+ | Random Forest | +0,063 [+0,012; +0,118] | 0,645 [0,565; 0,730] | 0,829 | 94,9 / 91,2 / 88,8 |
| M1+ | Gradient Boosting | +0,030 [−0,006; +0,071] | 0,597 [0,533; 0,671] | 0,783 | 91,5 / 89,6 / 89,8 |
| M1+ | SVC | +0,016 [−0,008; +0,044] | 0,415 [0,346; 0,482] | 0,798 | 60,8 / 68,0 / 76,0 |
| M1+ | MLP | +0,015 [−0,022; +0,052] | 0,614 [0,529; 0,704] | 0,760 | 82,4 / 85,6 / 88,5 |

- A taxa por modalidade e o Random Forest M1 empatam (+0,071), com intervalos quase iguais.
- Dentro de cada modalidade, o Random Forest M1+ tem ROC-AUC de 0,504 nos contratos de repasse (472) e 0,485 nos convênios (153).
- No top 10% (63 instrumentos), o Random Forest acerta cerca de 4 instrumentos a mais que a taxa por modalidade. Essa métrica não tem intervalo, e a diferença não é conclusiva.
- O SVC M1+ ordena ao contrário: o intervalo do ROC-AUC fica todo abaixo de 0,5.
- O M1+ não melhora o M1 em nenhum modelo.
- Contra uma constante igual à taxa real do teste (83,2%), que nenhum modelo poderia conhecer, só a taxa por modalidade (+4,2%), o Random Forest M1 (+4,1%) e o M1+ (+3,4%) ganham com folga. O ganho deles vem da ordenação, não só do nível.
- Reajustar em treino + validação piora quase todos os modelos. A previsão média sobe para 0,90–0,94, e o ROC-AUC de vários cai para 0,39–0,47 (`registro.csv`, partição `teste_refit_treino_validacao`).

## 2. Validação (A0)

1.023 instrumentos, 93,4% com Y=1.

| Conjunto | Modelo | Brier skill [IC 95%] | ROC-AUC [IC 95%] | Previsto médio |
|---|---|---|---|---|
| — | Taxa por modalidade | −0,078 [−0,112; −0,043] | 0,431 [0,386; 0,481] | 0,772 |
| M1 | Logística | +0,244 [+0,176; +0,331] | 0,456 [0,389; 0,533] | 0,881 |
| M1 | Árvore | −0,044 [−0,054; −0,036] | 0,500 | 0,754 |
| M1 | Random Forest | +0,088 [+0,057; +0,126] | 0,484 [0,410; 0,557] | 0,803 |
| M1 | Gradient Boosting | +0,032 [+0,002; +0,062] | 0,538 [0,466; 0,610] | 0,780 |
| M1 | SVC | +0,121 [+0,098; +0,149] | 0,502 [0,408; 0,593] | 0,802 |
| M1 | MLP | +0,104 [+0,072; +0,143] | 0,506 [0,443; 0,571] | 0,805 |
| M1+ | Logística | +0,233 [+0,173; +0,311] | 0,482 [0,414; 0,552] | 0,870 |
| M1+ | Árvore | +0,141 [+0,082; +0,213] | 0,436 [0,389; 0,488] | 0,848 |
| M1+ | Random Forest | +0,118 [+0,078; +0,168] | 0,474 [0,403; 0,550] | 0,819 |
| M1+ | Gradient Boosting | −0,037 [−0,085; +0,011] | 0,530 [0,464; 0,597] | 0,782 |
| M1+ | SVC | +0,123 [+0,099; +0,152] | 0,514 [0,440; 0,581] | 0,803 |
| M1+ | MLP | +0,013 [−0,022; +0,051] | 0,509 [0,445; 0,574] | 0,785 |

- Nenhum modelo ordena na validação: todos os intervalos de ROC-AUC incluem 0,5 ou ficam abaixo dele. O Brier skill premia apenas a previsão média mais próxima de 93%.
- A logística chega perto desse nível porque usa o ano como número e prolonga a tendência. No teste, a mesma tendência leva a previsão a 0,90 para uma taxa de 0,83.
- A escolha repetida em janelas dentro do treino (2016–2019) coincidiu com a oficial em 4 dos 6 modelos do M1+ e em nenhum do M1. Nas divergências, a diferença de Brier na validação ficou abaixo de 0,002, exceto na MLP M1 (0,139 contra 0,081). A grade importa pouco; o problema está no período usado para escolher.

## 3. Experimentos

Modelos: logística e árvore (as duas melhores da validação em M1+) e a taxa por modalidade. Em A1 e A2, a escolha é feita em janelas no tempo, e os baselines são reajustados na janela de treino do experimento.

| Experimento | Logística [IC 95%] | Árvore [IC 95%] | Taxa por modalidade |
|---|---|---|---|
| A0 oficial (M1+) | +0,014 [−0,076; +0,110] | +0,049 [−0,022; +0,127] | +0,071 |
| A1 escolha sem 2020–2021 | +0,022 [−0,060; +0,110] | +0,046 [−0,025; +0,125] | +0,071 |
| A2 treino 2015–2019 | −0,022 [−0,084; +0,032] | −0,022 [−0,068; +0,016] | +0,038 |
| B1 histórico derivado no lugar das contagens | +0,014 [−0,078; +0,106] | +0,048 [−0,022; +0,124] | +0,071 |
| B2 contagens + histórico derivado | +0,012 [−0,081; +0,105] | +0,048 [−0,022; +0,124] | +0,071 |
| C1 M1+ sem o ano | +0,044 [−0,016; +0,109] | +0,024 [−0,051; +0,101] | +0,071 |

- A1: escolher sem o período atípico não muda o resultado.
- A2: treinar só com anos recentes piora.
- B1 e B2: a taxa de atraso do município não acrescenta nada às contagens, e as contagens não acrescentam nada à modalidade.
- C1: sem o ano, a previsão média da logística cai de 0,902 para 0,845 e o Brier skill sobe para +0,044, ainda abaixo da taxa por modalidade. A árvore piora sem o ano.

## 4. Erros por grupo (A0, M1+, teste)

Cada célula traz previsto / Brier skill / ROC-AUC.

| Grupo | n | Taxa real | Random Forest | Logística | Taxa por modalidade |
|---|---|---|---|---|---|
| 2022 | 239 | 88,3% | 0,83 / +0,18 / 0,84 | 0,90 / +0,18 / 0,83 | 0,79 / +0,21 / — |
| 2023 | 386 | 80,1% | 0,83 / +0,01 / 0,56 | 0,91 / −0,06 / 0,52 | 0,78 / +0,01 / — |
| Contrato de repasse | 472 | 88,6% | 0,85 / +0,12 / 0,50 | 0,92 / +0,10 / 0,39 | 0,82 / +0,09 / — |
| Convênio | 153 | 66,7% | 0,77 / −0,02 / 0,49 | 0,85 / −0,12 / 0,50 | 0,65 / +0,04 / — |
| Até 10 mil hab. | 335 | 83,6% | 0,83 / +0,07 / 0,65 | 0,90 / +0,03 / 0,57 | 0,78 / +0,07 / — |
| 10–20 mil | 173 | 77,5% | 0,83 / +0,03 / 0,64 | 0,91 / −0,07 / 0,63 | 0,78 / +0,08 / — |
| 20–50 mil | 66 | 92,4% | 0,84 / +0,21 / 0,84 | 0,91 / +0,28 / 0,55 | 0,80 / +0,12 / — |
| 1 a 5 maduros | 30 | 90,0% | 0,85 / +0,19 / 0,75 | 0,89 / +0,23 / 0,72 | 0,78 / +0,10 / — |
| Mais de 5 maduros | 595 | 82,9% | 0,83 / +0,06 / 0,64 | 0,90 / +0,01 / 0,58 | 0,78 / +0,07 / — |

- A ordenação vem de 2022 (ROC-AUC de 0,84). Em 2023, nenhum modelo supera a média.
- Nos convênios, a logística prevê 85% para uma taxa de 67%.
- Faixas de 50–100 mil (17) e acima de 100 mil (34) não aparecem na tabela por terem n pequeno.
- O teste não tem município sem histórico, então esse grupo não pode ser avaliado.

**Calibração por ano** (previsão média, M1+; o M1 está em `dados/modelagem/e06/calibracao_por_ano_A0.csv`):

| | Real | Trivial | Modalidade | Logística | Árvore | Random Forest | Gradient Boosting | SVC | MLP |
|---|---|---|---|---|---|---|---|---|---|
| 2022 | 0,883 | 0,765 | 0,787 | 0,896 | 0,864 | 0,830 | 0,787 | 0,797 | 0,774 |
| 2023 | 0,801 | 0,765 | 0,776 | 0,906 | 0,866 | 0,829 | 0,781 | 0,797 | 0,751 |

A taxa real cai 8 pontos de um ano para o outro, e nenhum modelo acompanha a mudança. Por decil, o Random Forest prevê entre 0,75 e 0,87 para taxas reais entre 0,67 e 0,95.

## 5. Matrizes de confusão (A0, M1+, teste)

520 com Y=1 e 105 com Y=0. Na capacidade, os 20% marcados são 125 instrumentos, e as contagens são esperadas. Figuras em `docs/e06/figuras/`.

| Modelo | Limiar | VP | FP | FN | VN | Precisão | Recall |
|---|---|---|---|---|---|---|---|
| Todos | F1 máximo na validação | 518–520 | 104–105 | 0–2 | 0–1 | 0,83 | ≈1,00 |
| Taxa por modalidade | prevalência (0,765) | 418 | 54 | 102 | 51 | 0,886 | 0,804 |
| Logística | prevalência | 515 | 105 | 5 | 0 | 0,831 | 0,990 |
| Árvore | prevalência | 513 | 104 | 7 | 1 | 0,831 | 0,987 |
| Random Forest | prevalência | 485 | 90 | 35 | 15 | 0,843 | 0,933 |
| Gradient Boosting | prevalência | 342 | 53 | 178 | 52 | 0,866 | 0,658 |
| SVC | prevalência | 507 | 103 | 13 | 2 | 0,831 | 0,975 |
| MLP | prevalência | 278 | 39 | 242 | 66 | 0,877 | 0,535 |
| Trivial | capacidade 20% | 104,0 | 21,0 | 416,0 | 84,0 | 0,832 | 0,200 |
| Taxa por modalidade | capacidade 20% | 110,7 | 14,3 | 409,3 | 90,7 | 0,886 | 0,213 |
| Logística | capacidade 20% | 104 | 21 | 416 | 84 | 0,832 | 0,200 |
| Random Forest | capacidade 20% | 114 | 11 | 406 | 94 | 0,912 | 0,219 |
| Gradient Boosting | capacidade 20% | 112 | 13 | 408 | 92 | 0,896 | 0,215 |
| SVC | capacidade 20% | 85 | 40 | 435 | 65 | 0,680 | 0,163 |
| MLP | capacidade 20% | 107 | 18 | 413 | 87 | 0,856 | 0,206 |

- Com 93% de Y=1 na validação, o limiar de F1 máximo marca todos os instrumentos (decisão 0002).
- No limiar da prevalência, a taxa por modalidade marca exatamente os contratos de repasse.
- Na capacidade de 20%, a árvore repete a taxa por modalidade.

## 6. Integridade e desvios

**Integridade**
- **Replicação:** o A0 rodado de novo deu previsões iguais, com diferença máxima de 3·10⁻¹⁶ (Random Forest).
- **Refatoração:** depois dela, as previsões da validação e todos os quadros foram conferidos e não mudaram.
- **Ambiente:** lock da equipe (Python 3.12.4, pandas 2.3.3, numpy 2.5.4, scikit-learn 1.9.1). Um ensaio fora do lock chegou às mesmas escolhas.
- **Aberturas do teste:** uma por experimento, mais a replicação do A0 e a aplicação aos instrumentos de 2024.
- **Testes:** 14 testes `unittest` passando.
- **Ordem:** as escolhas de cada experimento foram commitadas antes do teste, e a fase prospectiva antes de ser aplicada. Isso ocorreu no repositório local de trabalho; os horários estão em `escolhas/*.json` (`run_id`) e `aberturas_teste.csv`.

**Desvios do plano**
1. **Capacidade com empates.** A primeira versão escolhia os k% pela ordem do arquivo, que segue a data, e inflava a precisão dos baselines: o trivial aparecia com 90,5% no top 10%. Os quadros usam o valor esperado nos empates, e o código passou a calculá-lo assim. As linhas antigas do `registro.csv` mantêm o cálculo anterior.
2. **B1/B2.** A primeira escolha falhou por um erro de código, corrigido antes de abrir o teste.
3. **E05.** A comparação com o modelo de tempo da E05 foi retirada do escopo pelo Jorge.
4. **Seção 7 do plano.** O desfecho de 2024 já estava disponível e foi apurado agora (seção 7 deste documento).

## 7. Instrumentos de 2024

O pacote apurou o desfecho até 31/12/2024 e deixou de fora os 242 instrumentos de 2024. Todos completam 365 dias até 31/12/2025, antes da carga do Silver (17/07/2026).

- O rótulo foi apurado pelos desembolsos do Silver (`dados.rotular_por_desembolsos`). A mesma regra reproduz os 5.359 rótulos do pacote, e isso é verificado por um teste automático.
- Foram usados os modelos do A0, com treino 2008–2019 e sem reajuste.
- Em 2024, 87,6% dos instrumentos ficaram com Y=1.

114 dos 242 instrumentos (47%) são "TERMO DE COMPROMISSO". A modalidade não aparece no pacote; no Silver, surge em 2024 e continua em 2025 (94) e 2026 (28). Desses termos, 95,6% ficaram sem desembolso em 365 dias. A taxa por modalidade usa para eles a taxa geral do treino.

| Modelo (M1+) | Brier skill [IC 95%] | ROC-AUC [IC 95%] | Previsto médio | Precisão top 20% |
|---|---|---|---|---|
| Trivial | 0,000 | 0,500 | 0,765 | 87,6 |
| Taxa por modalidade | +0,042 [−0,007; +0,090] | 0,552 [0,409; 0,680] | 0,774 | 85,7 |
| Logística | +0,118 [+0,012; +0,268] | 0,701 [0,597; 0,792] | 0,932 | 93,8 |
| Árvore | +0,078 [−0,000; +0,174] | 0,474 [0,357; 0,586] | 0,840 | 85,7 |
| Random Forest | +0,093 [+0,036; +0,165] | 0,565 [0,430; 0,695] | 0,823 | 87,6 |
| Gradient Boosting | −0,043 [−0,127; +0,030] | 0,479 [0,388; 0,577] | 0,775 | 85,5 |
| SVC | +0,034 [+0,004; +0,074] | 0,472 [0,371; 0,602] | 0,792 | 83,5 |
| MLP | +0,047 [−0,009; +0,093] | 0,672 [0,560; 0,769] | 0,762 | 91,7 |

- A logística vence em 2024 porque sua previsão média (0,93) fica próxima da taxa do ano. Contra uma constante igual à taxa real de 2024 (87,6%), só a logística fica acima, por +1,8% (M1+) e +0,2% (M1); todos os outros ficam abaixo.
- Dentro de cada modalidade, o ROC-AUC da logística é 0,46 nos contratos de repasse, 0,45 nos termos e 0,62 nos 30 convênios. O 0,70 no total vem de prever 0,95 para os termos e 0,87 para os convênios.
- A taxa por modalidade perde força porque não conhece os termos de compromisso.

## 8. Encaminhamentos

- **Relatório:** pelo protocolo, o modelo escolhido é a logística, que venceu a validação. No teste, ela não supera a taxa por modalidade. O empate do Random Forest com a taxa por modalidade foi visto no teste, entre 16 modelos, e não serve para escolher modelo: entra como comparação, não como vencedor. A taxa por modalidade fica como baseline a ser batido. Registrar que a validação 2020–2021 não permite escolher modelos por ordenação.
- **Professor:** a partição oficial escolhe pelo período mais atípico da série; o A1 mostra que mudar o critério não altera o resultado.
- **Ítalo:** registrar no pacote a modalidade "TERMO DE COMPROMISSO", que aparece a partir de 2024.
- **Modelagem:** a ordem entre os modelos muda de ano para ano conforme o nível de cada um se aproxima da taxa do ano. Com estas variáveis, só a modalidade separa instrumentos de forma consistente.
