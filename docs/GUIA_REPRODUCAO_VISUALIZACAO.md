# Guia de reprodução da visualização

O pacote `dados/visualizacao/` é uma fotografia compacta e determinística da versão Gold informada explicitamente. Ele contém o painel municipal-ano, o dicionário, a cobertura por variável e o manifesto de proveniência.

## Finalidade e escopo

O pacote consolida contexto municipal para análise descritiva e visualização, no grão `codigo_ibge + ano`, para os 223 municípios da Paraíba entre 2020 e 2024. São 1.115 linhas, sem duplicidades, somente UF `PB`, com `codigo_ibge` textual de sete dígitos.

As dimensões disponíveis são fiscal-financeira, contratual/execução de recursos, capacidade institucional e qualidade/auditoria. O pacote não é índice definitivo de risco, não possui pesos, ranking ou probabilidade de falha, não demonstra causalidade e não deve automatizar decisões sobre municípios ou projetos.

## Campos disponíveis

O painel contém exatamente:

- Identificação: `codigo_ibge`, `municipio`, `uf`, `ano`.
- Fiscal-financeira: `populacao_siconfi`, `receita_total_realizada`, `transferencias_correntes_realizadas`, `despesa_total_liquidada`, `despesa_pessoal_liquidada`, `investimentos_liquidados`, `restos_pagar_processados`, `restos_pagar_nao_processados`, `caixa_equivalentes`, `restos_pagar_total`, `dependencia_transferencias`, `investimento_per_capita`, `restos_pagar_sobre_receita`, `caixa_sobre_receita`, `pressao_pessoal_proxy`, `resultado_orcamentario_proxy`.
- Contratual e execução: `total_contratacoes`, `valor_estimado_contratacoes`, `valor_homologado_contratacoes`, `contratacoes_similares`, `valor_contratacoes_similares`, `cobertura_pncp`.
- Capacidade institucional: `pessoal_ativo`, `pessoal_celetista`, `pessoal_comissionado`, `pessoal_estagiario`, `pessoal_estatutario`, `pessoal_sem_vinculo`, `proporcao_pessoal_estatutario`, `pessoal_ativo_por_mil_habitantes`.
- Controle/qualidade: `populacao`, `cobertura_siconfi`, `status_transicao`, `status_ibge`, `status_siconfi`, `status_pncp`, `status_tse_eleitoral`, `status_pib`, `status_munic`.

Área e densidade territorial não estão presentes nesta versão do pacote e não devem ser inferidas. As tabelas Gold operacionais podem conter metadados adicionais, mas não fazem parte do arquivo compacto.

SICONFI foi usado por representar capacidade fiscal e financeira declarada. Transferegov e PNCP cobrem instrumentos, valores e execução de recursos. A MUNIC acrescenta estrutura de recursos humanos. População é controle proporcional; bases ambientais ficaram fora do MVP por ausência de evidência metodológica geral para todos os tipos de projeto.

Zero é valor observado quando permitido pelo contrato. Nulo preserva ausência, não declaração, não aplicabilidade, indisponibilidade temporal ou denominador inválido. Ausência nunca foi convertida automaticamente em zero; pergunta ausente não significa resposta negativa.

## Reprodução offline

No worktree isolado, com o ambiente x64 validado:

```powershell
$env:PYTHONPATH = 'src'
venv\Scripts\python.exe -m etl_municipal.exportacao_visualizacao `
  --data-dir data `
  --gold-version 30466c6928c682d66a66 `
  --output dados/visualizacao
```

O comando não consulta `CURRENT.json`, não acessa rede e falha se a versão informada não existir. O Parquet é a representação analítica canônica; o CSV usa UTF-8 com BOM, `;`, decimal `,` e nulos vazios.

## Importação no Power BI

1. Selecione **Obter dados → Texto/CSV**.
2. Escolha `painel_municipio_ano_2020_2024.csv`.
3. Use codificação UTF-8 e delimitador ponto e vírgula.
4. Configure localidade Português (Brasil), se necessário.
5. Defina `codigo_ibge` como Texto e `ano` como Número inteiro.
6. Preserve nulos; não substitua nulo por zero sem justificativa.
7. Confira moeda, proporções e contagens antes de criar medidas.
8. Relacione tabelas adicionais pela chave `codigo_ibge + ano`.

Visuais adequados incluem mapas municipais, evolução fiscal anual, transferências, execução contratual, capacidade institucional e cobertura de qualidade. O repositório não entrega um dashboard pronto.

## Conteúdo e uso

O painel mantém 223 municípios da Paraíba nos anos 2020–2024, totalizando 1.115 chaves `codigo_ibge + ano`. Requer-se ler `codigo_ibge` como texto de sete dígitos. As dimensões são fiscal-financeira, contratual/execução de recursos, capacidade institucional e controles territoriais, acompanhadas de status de qualidade.

A MUNIC usa a última edição elegível até 31 de dezembro: 2019 para 2020, 2020 para 2021, 2021 para 2022 e 2023 para 2024. A edição MUNIC 2024, publicada em 2025, não entra na fotografia de 2024. Os originais de 2019 e 2021 não estão disponíveis no FTP consultado; suas revisões são preservadas com a condição `apta_com_ressalva_documentada`. As variáveis corrigidas `MREG0151`, `MREG0152`, `MREG0153` e `MCUL42` permanecem fora do painel largo.

O pacote não contém score, pesos, ranking, variáveis ambientais, dados pessoais ou interpretação causal. Zero observado não é nulo; nulo mantém a indisponibilidade ou o estado declarado pela fonte.

## Reprodução online

A coleta online é uma etapa separada e não é necessária para consumir o pacote. Quando autorizada, execute primeiro o Bronze MUNIC com `--resume`, valide os hashes do manifesto e só então publique o Gold. Não use `--refresh` durante a reprodução deste pacote.

## Recuperação de data-dir com manifesto histórico incompleto

Um `data-dir` histórico pode conter manifestos Bronze antigos cujo caminho completo excede o limite de caminho do Windows durante a criação de um sidecar temporário. Isso é resíduo local, não falha da CLI, desde que a reprodução funcione em um diretório novo.

Para recuperar a reprodução sem apagar o diretório histórico, crie um diretório temporário curto, materialize somente o Bronze MUNIC validado e execute:

```powershell
python -m etl_municipal --offline --data-dir $clean --sources snapshot munic
```

Recalcule os cinco SHA-256 do Bronze antes da execução. Não copie Silver, Gold ou `CURRENT.json`; a CLI deve construir uma nova versão e só criar `CURRENT.json` depois da publicação completa.
