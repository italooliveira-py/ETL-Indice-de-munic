# E05 — Resultado executado em 2026-10-28

Dados exclusivamente públicos. Alvo: `sem_repasse_90d`, por instrumento assinado na PB.

## Comparação no mesmo teste de 2024

| Método | N | Acurácia balanceada | ROC-AUC | Estado do ajuste |
|---|---:|---:|---:|---|
| Baseline trivial (prevalência do treino) | 242 | 0.5000 | 0.5000 | estimado |
| Baseline operacional (Regressão Logística) | 242 | não estimável | não estimável | nao_estimavel_treino_classe_unica |
| Decision Tree Classifier | 242 | 0.5000 | 0.5000 | degenerado_treino_classe_unica |
| Random Forest Classifier | 242 | 0.5000 | 0.5000 | degenerado_treino_classe_unica |

## Interpretação

A disponibilidade de mais preditores municipais não compensa a ausência de uma classe no treino. Uma árvore ajustada em classe única produz uma folha constante; a floresta repete essa regra. A Regressão Logística não foi substituída por um baseline diferente para fabricar números.

O limiar foi fixado em 0,5; não houve seleção pelo teste. Os rótulos do treino final precisaram estar observáveis antes de 01/01/2024. As coortes são definidas pela assinatura, não pelo desembolso.

Não há modelo discriminativo validado neste experimento se o treino contém somente a classe 1. Acurácia global elevada nesse cenário não significa utilidade para identificar quais projetos receberão repasse. Qualquer mudança futura da janela exigirá nova versão do contrato e um experimento separado, acordado com a equipe.

## Limitações

- O evento é ausência de repasse dentro da janela, não estouro de custo ou insucesso definitivo.
- O conjunto é restrito a instrumentos municipais da PB nas Discricionárias; não representa todos os projetos públicos.
- Contexto: IBGE, DCA/RGF e histórico das duas modalidades do Transferegov, com datas anteriores à assinatura.
- Datas de divulgação/envio foram respeitadas, mas versões públicas atuais podem conter revisões e registros tardios.
- Um único ano de teste e suporte minoritário escasso não permitem alegar estabilidade futura ou calibração operacional.

## Uso de IA

Codex auxiliou a implementação, a revisão do contrato temporal, os testes e a documentação. Os dados são públicos. Métricas vêm da execução; ausência de resultado foi explicitada. A equipe deve revisar e ser capaz de defender os blocos do notebook.
