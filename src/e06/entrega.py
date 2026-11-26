"""Executa a entrega coletiva E06 com validação cruzada temporal e operação mensal."""
from __future__ import annotations

import argparse
import json
import platform
import tempfile
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from . import base_bronze, dados, experimento as exp, operacao, registro

CANDIDATOS = ("logistica", "arvore", "floresta", "gb")
MODELOS = ("modalidade", *CANDIDATOS)
CONJUNTO = "M1_plus"
ANOS_CV = (2016, 2017, 2018, 2019)
FAIXAS = np.linspace(0, 1, 11)
FONTE_POPULACAO = dados.ROOT / "dados/bruto/base_municipio_ano_snapshot.csv"


def _preparar_base(config, args, destino):
    pacote = dados.verificar_pacote(config)
    congelado = dados.carregar(config)
    if args.origem == "bronze":
        base = base_bronze.construir(args.raiz_dados)
        auditoria = {**base.auditoria, "comparacao_congelado": base_bronze.comparar_pacote(base.partes, congelado)}
        partes = base.partes
        prospectivo = base.prospectivo.dropna(subset=[dados.ALVO])
    else:
        partes, prospectivo, auditoria = congelado, None, {}
    for nome, parte in partes.items():
        parte[dados.ALVO] = parte[dados.ALVO].astype(int)
        parte.to_parquet(destino / f"{nome}.parquet", index=False)
    if prospectivo is not None:
        prospectivo.to_parquet(destino / "prospectivo_2024.parquet", index=False)
    registro.gravar_json(destino / "auditoria_base.json", {"origem": args.origem, "pacote_verificado": pacote,
                                                            **auditoria})
    return partes, prospectivo


def _escolher(config, treino, destino):
    janelas = exp.janelas_tempo(treino, ANOS_CV)
    colunas = config["conjuntos"][CONJUNTO]
    melhores, notas, tamanhos = {}, [], []
    for ano, ajuste, avaliacao in janelas:
        tamanhos.append({"ano": ano, "treino": len(ajuste), "validacao": len(avaliacao)})
    for modelo in MODELOS:
        inicio = perf_counter()
        grade = exp.avaliar_grade(modelo, colunas, config, treino, janelas=janelas)
        melhor = min(grade, key=lambda linha: linha["brier_escolha"])
        melhores[modelo] = {**melhor, "segundos_busca": perf_counter() - inicio}
        notas.extend(grade)
        print(f"CV {modelo}: {melhor['hiperparametros']} | Brier {melhor['brier_escolha']:.5f}", flush=True)
    registro.escrever_csv(pd.DataFrame(notas), destino / "grades_cv.csv")
    registro.escrever_csv(pd.DataFrame(tamanhos), destino / "janelas_cv.csv")
    registro.gravar_json(destino / "escolhas.json", melhores)


def _prever(ajuste, base, colunas, populacao):
    inicio = perf_counter()
    p = exp.prever(ajuste, base[colunas])
    tempo = perf_counter() - inicio
    colunas_auditoria = ["nr_convenio", "data_assinatura", "ano_origem", "codigo_ibge", "modalidade"]
    quadro = base[colunas_auditoria].assign(y=base[dados.ALVO].astype(int), p=p)
    quadro["experiencia"] = dados.experiencia(base["historico_instrumentos_maduros"])
    quadro["porte"] = dados.classificar_porte(base["codigo_ibge"].astype(str), populacao)
    return quadro.reset_index(drop=True), tempo


def _avaliar(config, partes, prospectivo, destino):
    escolhas = json.loads((destino / "escolhas.json").read_text(encoding="utf-8"))
    colunas = exp.entrada(config["conjuntos"][CONJUNTO])
    treino = partes["train"]
    prevalencia = treino[dados.ALVO].mean()
    painel = pd.read_csv(FONTE_POPULACAO, dtype={"codigo_ibge": str},
                         usecols=["codigo_ibge", "ano", "fonte_populacao", "populacao"])
    censo = painel.loc[painel["ano"].eq(2022) & painel["fonte_populacao"].eq("IBGE-Censo")]
    populacao = censo.set_index("codigo_ibge", verify_integrity=True)["populacao"]
    if populacao.empty or populacao.isna().any():
        raise ValueError("A auditoria de porte exige população municipal do Censo 2022.")
    amostras = {nome: partes[nome] for nome in ("validation", "test")}
    if prospectivo is not None and not prospectivo.empty:
        amostras["prospectivo_2024"] = prospectivo
    sorteios = {nome: exp.sorteios_municipios(base["codigo_ibge"].astype(str).to_numpy(),
                                            config["bootstrap"], config["semente"])
                for nome, base in amostras.items()}
    (destino / "modelos").mkdir()
    metricas, previsoes, calibracao, erros = [], [], [], []
    for modelo, escolha in escolhas.items():
        parametros = escolha["hiperparametros"]
        inicio = perf_counter()
        ajuste = exp.criar_pipeline(modelo, parametros, colunas, config).fit(treino[colunas], treino[dados.ALVO])
        segundos_ajuste = perf_counter() - inicio
        joblib.dump(ajuste, destino / "modelos" / f"{modelo}.joblib", compress=3)
        for nome, base in amostras.items():
            quadro, tempo = _prever(ajuste, base, colunas, populacao)
            y, p = quadro["y"], quadro["p"]
            tags = {"modelo": modelo, "particao": nome}
            metricas.append({
                **tags, "hiperparametros": json.dumps(parametros, sort_keys=True),
                "brier_cv": escolha["brier_escolha"], "segundos_busca": escolha["segundos_busca"],
                "segundos_ajuste": segundos_ajuste, "segundos_predicao": tempo,
                **exp.metricas(y, p, prevalencia),
                **exp.intervalos_cluster(y, p, quadro["codigo_ibge"].astype(str), prevalencia, sorteios[nome]),
            })
            previsoes.append(quadro.assign(**tags))
            faixas = pd.cut(p, FAIXAS, include_lowest=True).astype(str)
            for tipo, grupos in (("faixa", faixas), ("ano", quadro["ano_origem"])):
                diag = exp.calibracao(y, p, grupos).assign(**tags, tipo=tipo)
                calibracao.append(diag)
            if nome == "test":
                dimensoes = ["modalidade", "ano_origem", "experiencia", "porte"]
                grupos = {coluna: quadro[coluna].to_numpy() for coluna in dimensoes}
                grupos["faixa_escore"] = faixas.to_numpy()
                erros.append(exp.erros_por_grupo(y, p, grupos, prevalencia).assign(**tags))
    previsoes = pd.concat(previsoes, ignore_index=True)
    previsoes.to_parquet(destino / "previsoes.parquet", index=False)
    registro.escrever_csv(pd.DataFrame(metricas), destino / "comparacao.csv")
    registro.escrever_csv(pd.concat(calibracao), destino / "calibracao.csv")
    registro.escrever_csv(pd.concat(erros), destino / "erros.csv")
    return previsoes.loc[previsoes["particao"].eq("test")].reset_index(drop=True)


def _operar(previsoes, validacao, args, destino):
    meses_validacao = pd.period_range(base_bronze.INICIO_VALIDACAO,
                                     base_bronze.INICIO_TESTE - pd.Timedelta(days=1), freq="M")
    referencia = max(1, int(np.floor(0.20 * len(validacao) / len(meses_validacao) + 0.5)))
    principal = operacao.Cenario("referencia", args.beneficio or 1.0, args.custo or 1.0,
                                 args.capacidade or referencia)
    cenarios = [
        principal,
        operacao.Cenario("beneficio_maior", 4.0, 1.0, principal.capacidade),
        operacao.Cenario("custo_maior", 1.0, 4.0, principal.capacidade),
        operacao.Cenario("capacidade_menor", principal.beneficio, principal.custo,
                        max(1, principal.capacidade // 2)),
        operacao.Cenario("capacidade_maior", principal.beneficio, principal.custo, 2 * principal.capacidade),
    ]
    resumo, meses, grupos, casos = [], [], [], []
    for modelo, quadro in previsoes.groupby("modelo", sort=False):
        for cenario in cenarios:
            medidas, detalhe, selecionados = operacao.avaliar_cenario(quadro, cenario)
            tags = {"modelo": modelo, "cenario": cenario.nome}
            meses.extend({**tags, **linha} for linha in detalhe)
            resumo.append({
                **tags, "beneficio": cenario.beneficio, "custo": cenario.custo,
                "capacidade_mensal": cenario.capacidade, "limiar_economico": cenario.limiar,
                **medidas,
            })
            if cenario == principal:
                dimensoes = ["modalidade", "ano_origem", "experiencia", "porte"]
                grupos.extend({"modelo": modelo, **linha}
                              for linha in operacao.equidade(selecionados, dimensoes))
                falsos_positivos = selecionados.loc[selecionados["y"].eq(0) & selecionados["peso"].gt(0)]
                falsos_negativos = selecionados.loc[selecionados["y"].eq(1) & selecionados["peso"].lt(1)]
                casos.extend([falsos_positivos.nlargest(3, "p").assign(erro="FP"),
                              falsos_negativos.nlargest(3, "p").assign(erro="FN")])
    for nome, linhas in (("operacao", resumo), ("operacao_mensal", meses), ("equidade", grupos)):
        registro.escrever_csv(pd.DataFrame(linhas), destino / f"{nome}.csv")
    registro.escrever_csv(pd.concat(casos), destino / "casos.csv")
    registro.gravar_json(destino / "premissas.json", {
        "cadencia": "mensal", "momento_escore": "assinatura", "priorizacao": "fechamento do mês",
        "origem_parametros": "informados pelo usuário" if args.beneficio is not None else "sensibilidade ilustrativa",
        "unidade": "utilidade líquida normalizada por revisão",
        "meses_validacao": len(meses_validacao), "instrumentos_validacao": len(validacao),
        "capacidade_referencia_validacao": referencia,
    })


def executar(args):
    config = dados.ler_config()
    destino = args.saida.resolve()
    if destino.exists():
        raise FileExistsError(f"Use um diretório de saída novo: {destino}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".e06-", dir=destino.parent) as temporario:
        trabalho = Path(temporario) / "resultado"
        trabalho.mkdir()
        partes, prospectivo = _preparar_base(config, args, trabalho)
        with threadpool_limits(limits=1):
            _escolher(config, partes["train"], trabalho)
            previsoes = _avaliar(config, partes, prospectivo, trabalho)
        _operar(previsoes, partes["validation"], args, trabalho)
        hashes = {p.relative_to(trabalho).as_posix(): registro.sha256(p.read_bytes())
                  for p in sorted(trabalho.rglob("*")) if p.is_file()}
        registro.gravar_json(trabalho / "manifesto.json", {
            "origem": args.origem, "semente": config["semente"], "anos_cv": ANOS_CV,
            "pacote": config["versao_pacote"], "hash_pacote": registro.hash_pacote(config),
            "codigo": registro.commit_codigo(), "python": platform.python_version(),
            "pacotes": registro.versoes(), "hashes": hashes,
            "sha256_fonte_porte": registro.sha256(FONTE_POPULACAO.read_bytes()),
        })
        trabalho.rename(destino)
    print(f"Entrega E06 gerada em {destino}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origem", choices=("bronze", "pacote"), default="bronze")
    parser.add_argument("--raiz-dados", type=Path, default=dados.ROOT / "data")
    parser.add_argument("--saida", type=Path, default=dados.ROOT / "output/e06_entrega")
    parser.add_argument("--beneficio", type=float)
    parser.add_argument("--custo", type=float)
    parser.add_argument("--capacidade", type=int, help="Revisões por mês.")
    args = parser.parse_args()
    parametros = (args.beneficio, args.custo, args.capacidade)
    if any(v is not None for v in parametros):
        if any(v is None for v in parametros):
            parser.error("Informe benefício, custo e capacidade juntos.")
        try:
            operacao.Cenario("informado", *parametros)
        except ValueError as erro:
            parser.error(str(erro))
    executar(args)


if __name__ == "__main__":
    main()

