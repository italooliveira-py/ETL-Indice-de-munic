# Plano TDD - Indices de Contexto Municipal

## Gate de ambiente antes do RED

Implementacao autorizada apos autocheck, sem nova aprovacao documental se nenhuma decisao adicional surgir. Permanecem proibidos coleta externa, refresh, alteracao de Bronze/Silver/Gold operacional ou CURRENT.json, correcao historica fora do escopo, commit, push e PR.

Registrar antes do primeiro RED: hash de `origin/main`; hash do pacote de entrada; 1.115 chaves unicas, 223 municipios e 2020-2024; ausencia de alteracao em Bronze/Silver/Gold/CURRENT; executavel Python AMD64/x64; `pip check`; suite-base com aprovados, falhas e skips preexistentes. Usar caminho exato do Python x64 validado, nunca `py -3` generico.

## Arquivos

`config/indice_contexto_municipal.v0.json`; modulo analitico isolado em `src/`; `tests/test_indices_contexto.py`; `notebooks/05_MVP_indices_contexto_municipal.ipynb`; docs em `docs/indices/`; `dados/visualizacao/indices_contexto_municipal.csv`; `dados/visualizacao/indices_contexto_municipal.parquet`; `dados/visualizacao/manifesto_indices_contexto.json`; tabelas auxiliares de limites, cobertura e sensibilidade em diretorio proprio.

## Fases RED/GREEN

1. Fiscal: testar margem relativa, receita positiva, margem negativa valida, infinito/denominador invalido, resultado absoluto nao utilizado, 4/5 componentes e metadados.
2. Institucional: testar tres proporcoes, `pessoal_ativo > 0`, nulos, [0,1], dois componentes minimos e configuracao versionada. Medir correlacao anual; diagnosticos sem estatutarios e sem sem vinculo; classificacao, mudanca de faixa e Spearman.
3. Normalizacao: testar P1/P99 anual com interpolacao linear, limites/contagens, nulos, rank medio, formula 0-100, unico valor = 50, inversao pos-percentil, todos iguais, quartis repetidos, empate no limite e minimo de quatro distintos para faixa.
4. Indices: testar fiscal, institucional, estrutural, pesos 0,5/0,5, bloqueio estrutural e faixas/metadados separados.
5. PNCP: testar as tres formulas por porte, `log1p` somente em intensidades, proporcao sem log, dominios, zero confirmado, ausencia, cobertura incompleta, nao aplicabilidade, `nao_aplicavel_sem_contratacoes`, subindices separados e indice completo nulo com subindice geral preservado.
6. Temporalidade: testar corte 31/12, point-in-time versus `descritivo_retrospectivo`, campos por linha e manifesto de aptidao; MUNIC sem mudanca; Transferegov nulo/status fixo e ampliado nao calculado.
7. Saida: testar nomes, versao, hash da entrada, limites/cobertura/sensibilidade, ordenacao deterministica, hashes iguais em duas execucoes, ausencia de caminhos absolutos e pacote de entrada inalterado. Criar artefatos proprios sem sobrescrever MUNIC.

## Criterios de interrupcao

Interromper por cobertura insuficiente; menos de 4 fiscais; menos de 2 institucionais; PNCP invalido; proporcao fora de [0,1]; sensibilidade irreprodutivel; vazamento temporal; interpretacao como risco; regressao nova; dados contradizendo formula aprovada; ou necessidade de nova decisao metodologica.

## Verificacao

Substituir `<PYTHON_X64>` pelo executavel validado:

```powershell
<PYTHON_X64> -m unittest tests.test_indices_contexto -v
<PYTHON_X64> -m unittest discover -s tests -v
<PYTHON_X64> -m compileall -q src tests
<PYTHON_X64> -m pip check
git diff --check
```

Nenhuma coleta, refresh, commit ou push faz parte do plano.
