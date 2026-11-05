# Contrato de dados MUNIC

## Regra temporal e auditoria

O Gold analítico não publica `MREG0151`, `MREG0152`, `MREG0153` ou `MCUL42` como variáveis, colunas, componentes de indicadores ou campos aptos para visualização/modelagem. A tabela `gold/munic_auditoria_disponibilidade_variavel` preserva a rastreabilidade dos metadados da errata e tem uso analítico falso.

As datas distinguem `data_publicacao_edicao_original`, `data_publicacao_arquivo_fisico` e `data_disponibilidade_variavel`. Para RH da MUNIC 2021 não listado na errata, os bytes são da revisão `revisao_2024_04_25`, mas a disponibilidade de 08/12/2022 é adotada sob evidência condicional; isso não equivale à preservação dos bytes originais.

O Bronze preserva a revisão oficial atualmente disponível. Quando o original não está no FTP consultado, o manifesto usa `status_versao=revisao_unica_disponivel`, `original_disponivel=false` e não inventa metadados do original.

A nota oficial do IBGE registra correções em `MREG0151`, `MREG0152`, `MREG0153` na MUNIC 2019 e `MCUL42` na MUNIC 2021. Essas variáveis permanecem na auditoria, mas ficam fora do Gold largo do MVP. Recursos humanos e demais variáveis não listadas na nota podem ser usadas com `evidencia_temporal=condicional_por_nota_de_correcao`.

O Silver versionado usa município × edição × versão × variável; o Silver adotado usa município × edição. Estados de resposta não são convertidos em zero. O painel temporal usa corte de 31 de dezembro e mantém 223 municípios × 5 anos = 1.115 chaves.

Condição temporal: `apta_com_ressalva_documentada`. Não há preservação histórica integral nem comparação byte a byte com os originais indisponíveis.
