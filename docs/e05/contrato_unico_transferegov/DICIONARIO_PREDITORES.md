# Dicionário de preditores — contrato Transferegov 365d

Todos os oito modelos recebem a mesma matriz e as mesmas 11 variáveis.

| Variável | Tipo | Disponibilidade | Tratamento |
|---|---|---|---|
| `valor_global_original` | numérica | assinatura | mediana; escala quando aplicável |
| `valor_global_assinatura` | numérica | assinatura | mediana; escala quando aplicável |
| `valor_contrapartida` | numérica | assinatura | mediana; escala quando aplicável |
| `duracao_original_dias` | numérica derivada | assinatura | mediana; escala quando aplicável |
| `dias_proposta_ate_assinatura` | numérica derivada | assinatura | mediana; escala quando aplicável |
| `modalidade` | categórica | assinatura | ausência + one-hot |
| `orgao_superior` | categórica | assinatura | ausência + one-hot |
| `orgao` | categórica | assinatura | ausência + one-hot |
| `origem_emenda` | categórica | assinatura | ausência + one-hot |
| `emenda_individual` | categórica | assinatura | ausência + one-hot |
| `emenda_impositiva` | categórica | assinatura | ausência + one-hot |

Excluídos: identificadores, `codigo_ibge`, ano, partição, alvo, desembolsos, datas e componentes do desfecho, status operacionais, resultados administrativos, CNPJ e metadados de auditoria. A lista é aplicada antes do ajuste e registrada no manifesto do snapshot.
