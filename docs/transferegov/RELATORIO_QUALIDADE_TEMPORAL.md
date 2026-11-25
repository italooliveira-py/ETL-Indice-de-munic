# Relatório de qualidade temporal

Versão corrente do pacote analítico: `95534890b62018db9922`.

Auditoria somente leitura da versão Gold `65260a170ee18cd79501` confirmou manifesto SHA-256 `28E24585431DC29B0DA53B10FD0811B91A02BA79BD00484EA6297D9ABB84F5B5`, 6.182 instrumentos, 9.411 desembolsos e 223 municípios.

Conciliação: 0 instrumentos sem município; 0 fora da PB; 0 desembolsos órfãos; 0 anteriores à assinatura; 0 valores negativos, zero ou nulos. Foram observadas 21 datas de publicação inválidas, excluídas como evento de execução.

O produto é apto para descrição retrospectiva de eventos datados e não apto para afirmar disponibilidade point-in-time de situação atual ou para predição sem novos snapshots de disponibilidade.

A versão analítica corrigida gerada no namespace isolado é `95534890b62018db9922` sob o contrato `transferegov-historico-temporal-v0.1.2`. Ela contém 24.662 snapshots de instrumentos, 9.411 eventos financeiros, 5.596 eventos de Especiais e 1.115 chaves município-ano. Os 24.662 snapshots correspondem aos instrumentos elegíveis repetidos em cada fotografia anual posterior à assinatura, não a novos instrumentos. Eventos posteriores ao corte não aparecem nas colunas observadas; instrumentos sem assinatura permanecem em auditoria e fora dos denominadores.

A cobertura contratada foi confirmada para universo municipal, artefato, modalidade e consulta nos cinco anos. Censurados: 284 (2020), 739 (2021), 239 (2022), 386 (2023) e 242 (2024). Não foram encontradas duplicidades nas entradas auditadas.
