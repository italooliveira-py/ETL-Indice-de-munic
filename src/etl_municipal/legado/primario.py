"""ETL exploratório para seleção de variáveis de risco municipal.

Preserva os dados brutos, cria uma base município-ano e gera auditorias de
cobertura, faltantes e redundância. Não calcula um score final.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import shutil
import time
import unicodedata
import zipfile
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
import etl_tse_eleitoral
from etl_confiabilidade import (
    FalhaConsulta, salvar_json_atomico, ler_cache, requisitar_json,
    janelas_ano, validar_pagina, atualizar_manifesto, chave_compra, geracao_cache,
)
from obrasgov_qualidade import (
    ResolvedorMalhaIBGE, campos_temporais as campos_temporais_obras,
    carregar_mapeamento_csv, resolver_atribuicao as resolver_atribuicao_obra,
)


ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data" / "raw"
MANUAL_DIR = ROOT / "data" / "manual"
OUTPUT_DIR = ROOT / "output"
CATALOGO_VARIAVEIS = ROOT / "catalogo_variaveis.csv"

LOGGER = logging.getLogger("etl_risco_municipal")


def sem_acento(valor: Any) -> str:
    texto = "" if valor is None else str(valor)
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def chave_texto(valor: Any) -> str:
    texto = sem_acento(valor).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def texto_busca(valor: Any) -> str:
    return re.sub(r"\s+", " ", sem_acento(valor).lower()).strip()


def numero(valor: Any) -> float | None:
    if valor is None or valor is pd.NA:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto in {"-", "..", "...", "X"}:
        return None
    texto = texto.replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def divisao_segura(numerador: pd.Series, denominador: pd.Series) -> pd.Series:
    den = pd.to_numeric(denominador, errors="coerce").replace(0, pd.NA)
    return pd.to_numeric(numerador, errors="coerce") / den


def criar_sessao(config: dict[str, Any]) -> requests.Session:
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "Pesquisa-UFPB-Risco-Municipal/1.0"})
    # Uma única camada de retry: evita multiplicar tentativas no adaptador HTTP.
    sessao.mount("https://", HTTPAdapter(max_retries=0))
    return sessao


def get_json(
    sessao: requests.Session,
    url: str,
    config: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> Any:
    return requisitar_json(sessao, url, config, params)


def salvar_json(caminho: Path, dados: Any) -> None:
    if caminho.is_relative_to(RAW_DIR) and caminho.exists():
        import hashlib
        anterior = caminho.read_bytes()
        novo = json.dumps(dados, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        if anterior != novo:
            versao = hashlib.sha256(anterior).hexdigest()[:20]
            destino = RAW_DIR / "historico" / caminho.relative_to(RAW_DIR).parent / f"{caminho.stem}_{versao}.json"
            destino.parent.mkdir(parents=True, exist_ok=True)
            if not destino.exists():
                shutil.copy2(caminho, destino)
    salvar_json_atomico(caminho, dados)


def registrar_erro(erros: list[dict[str, Any]], fonte: str, contexto: str, exc: Exception) -> None:
    LOGGER.warning("%s | %s | %s", fonte, contexto, exc)
    erros.append(
        {
            "fonte": fonte,
            "contexto": contexto,
            "tipo_erro": type(exc).__name__,
            "mensagem": str(exc),
        }
    )


def anos_fonte(config, fonte):
    inicio = max(int(config["ano_inicial"]), int(config.get(f"{fonte}_ano_inicial", config["ano_inicial"])))
    fim = min(int(config["ano_final"]), int(config.get(f"{fonte}_ano_final", config["ano_final"])))
    return range(inicio, fim + 1)


def resolver_municipios(sessao, config):
    escopo = config.get("escopo") or {}
    if escopo.get("tipo") == "uf":
        ufs = escopo.get("ufs", [])
        if not isinstance(ufs, list) or not ufs:
            raise ValueError("escopo.tipo=uf exige uma lista não vazia de ufs")
        municipios = []
        for uf in dict.fromkeys(str(u).upper() for u in ufs):
            if uf not in "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split():
                raise ValueError(f"UF inválida: {uf}")
            caminho = RAW_DIR / "ibge" / f"municipios_{uf}.json"

            def validar(dados):
                if not isinstance(dados, list) or not dados:
                    raise ValueError(f"Catálogo IBGE vazio para {uf}")
                if any(not isinstance(m, dict) or not re.fullmatch(r"\d{7}", str(m.get("id", ""))) or not m.get("nome") for m in dados):
                    raise ValueError("Catálogo IBGE inválido")
                if len({str(m["id"]) for m in dados}) != len(dados):
                    raise ValueError("Catálogo IBGE com códigos duplicados")

            dados = None if "ibge" in config.get("_refresh_fontes", []) else ler_cache(caminho, validar)
            if dados is None:
                if config.get("_only_profile"):
                    raise ValueError("Catálogo territorial ausente; execute primeiro um smoke test IBGE ou coleta IBGE")
                dados = get_json(sessao, f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios", config)
                validar(dados)
                salvar_json(caminho, dados)
            LOGGER.info("IBGE | %s | %d municípios no catálogo", uf, len(dados))
            if uf == "PB" and len(dados) != 223:
                LOGGER.warning("PB: catálogo com %d municípios; referência esperada 223; confira a divisão territorial", len(dados))
            municipios.extend({"codigo_ibge": str(m["id"]), "nome": m["nome"], "uf": uf} for m in dados)
    else:
        municipios = config.get("municipios", [])
    if not municipios or any(not re.fullmatch(r"\d{7}", str(m.get("codigo_ibge", ""))) or not m.get("nome") or not m.get("uf") for m in municipios):
        raise ValueError("Configure escopo.tipo=uf com ufs, ou uma lista válida de municipios")
    if len({str(m["codigo_ibge"]) for m in municipios}) != len(municipios):
        raise ValueError("Municípios duplicados na configuração")
    return [{**m, "codigo_ibge": str(m["codigo_ibge"])} for m in municipios]


def serie_sidra(
    sessao: requests.Session,
    config: dict[str, Any],
    agregado: int,
    variavel: int,
    codigo_ibge: str,
    anos: Iterable[int],
) -> dict[int, float]:
    periodos = "|".join(str(a) for a in anos)
    url = (
        "https://servicodados.ibge.gov.br/api/v3/agregados/"
        f"{agregado}/periodos/{periodos}/variaveis/{variavel}"
    )
    resposta = get_json(
        sessao,
        url,
        config,
        params={"localidades": f"N6[{codigo_ibge}]"},
    )
    saida: dict[int, float] = {}
    for bloco in resposta or []:
        for resultado in bloco.get("resultados", []):
            for serie in resultado.get("series", []):
                if str(serie.get("localidade", {}).get("id")) != str(codigo_ibge):
                    continue
                for ano, valor in serie.get("serie", {}).items():
                    n = numero(valor)
                    if n is not None:
                        saida[int(ano)] = n
    return saida


def serie_sidra_lote(sessao, config, agregado, variavel, codigos, anos):
    import hashlib
    anos = list(anos)
    if not anos:
        return {}
    periodos = "|".join(map(str, anos))
    locais = ",".join(codigos)
    assinatura = hashlib.sha256(f"{agregado}-{variavel}-{periodos}-{locais}".encode()).hexdigest()[:20]
    caminho = RAW_DIR / "ibge" / "lotes" / f"sidra_{agregado}_{assinatura}.json"
    def validar(dados):
        if not isinstance(dados, list) or any(not isinstance(b, dict) or not isinstance(b.get("resultados"), list) for b in dados):
            raise ValueError("Resposta SIDRA invalida")
    resposta = None if "ibge" in config.get("_refresh_fontes", []) else ler_cache(caminho, validar)
    reutilizado = resposta is not None
    registro = dict(fonte="IBGE", escopo=",".join(codigos), periodo=periodos, modalidade=str(agregado),
                    paginas_esperadas=1, paginas_concluidas=0, quantidade_registros=0,
                    situacao="falhou", erro_final=None)
    try:
        if resposta is None:
            resposta = get_json(sessao, f"https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}/periodos/{periodos}/variaveis/{variavel}",
                                config, params={"localidades": f"N6[{locais}]"})
            validar(resposta)
            salvar_json(caminho, resposta)
        saida = {}
        for bloco in resposta:
            for resultado in bloco["resultados"]:
                for serie in resultado.get("series", []):
                    codigo = str(serie.get("localidade", {}).get("id"))
                    if codigo in codigos:
                        for ano, valor in serie.get("serie", {}).items():
                            n = numero(valor)
                            if n is not None and int(ano) in anos:
                                saida[(codigo, int(ano))] = n
        registro.update(situacao="sem_registros_confirmado" if not saida else "cache_reutilizado" if reutilizado else "completa", paginas_concluidas=1,
                        quantidade_registros=len(saida))
        return saida
    except Exception as exc:
        registro["erro_final"] = str(exc)
        raise
    finally:
        atualizar_manifesto(OUTPUT_DIR, registro)


def coletar_ibge(sessao, config, erros):
    anos = list(anos_fonte(config, "ibge"))
    linhas = []
    municipios = config["municipios"][:2] if config.get("_smoke_test") else config["municipios"]
    tamanho = max(1, min(int(config.get("ibge_tamanho_lote", 50)), 500, 100000 // max(1, len(anos))))
    for inicio in range(0, len(municipios), tamanho):
        lote = municipios[inicio:inicio + tamanho]
        codigos = [str(m["codigo_ibge"]) for m in lote]
        series = {}
        for nome, agregado, variavel, periodo in (("populacao", 6579, 9324, anos),
                ("censo", 4709, 93, [2022] if 2022 in anos else []), ("pib", 5938, 37, anos)):
            try:
                series[nome] = serie_sidra_lote(sessao, config, agregado, variavel, codigos, periodo)
            except Exception as exc:
                registrar_erro(erros, "IBGE", f"{nome} lote {inicio // tamanho + 1}", exc)
                series[nome] = {}
        for m in lote:
            codigo = str(m["codigo_ibge"])
            pop = {ano: series["populacao"][(codigo, ano)] for ano in anos if (codigo, ano) in series["populacao"]}
            pop.update({ano: series["censo"][(codigo, ano)] for ano in anos if (codigo, ano) in series["censo"]})
            pib = {ano: series["pib"][(codigo, ano)] for ano in anos if (codigo, ano) in series["pib"]}
            salvar_json(RAW_DIR / "ibge" / f"sidra_{codigo}.json", {"populacao": pop, "pib_mil_reais": pib})
            for ano in anos:
                linhas.append(dict(codigo_ibge=codigo, municipio=m["nome"], uf=m["uf"], ano=ano,
                                   populacao=pop.get(ano), pib=pib[ano] * 1000 if ano in pib else None,
                                   fonte_populacao="IBGE-Censo" if (codigo, ano) in series["censo"] else "IBGE-EstimaPop" if ano in pop else None))
    return pd.DataFrame(linhas)


def valor_dca(
    itens: list[dict[str, Any]],
    anexo: str,
    cod_conta: str,
    coluna: str,
    subtrair_deducoes: bool = False,
) -> float | None:
    candidatos = [
        i
        for i in itens
        if i.get("anexo") == anexo and i.get("cod_conta") == cod_conta
    ]
    valores = [numero(i.get("valor")) for i in candidatos if i.get("coluna") == coluna]
    if not valores or any(v is None for v in valores):
        return None
    principal = sum(valores)
    if subtrair_deducoes:
        valores_deducoes = [
            numero(i.get("valor"))
            for i in candidatos
            if "dedu" in texto_busca(i.get("coluna"))
        ]
        if any(v is None for v in valores_deducoes):
            return None
        principal -= sum(valores_deducoes)
    return principal


def carregar_dca(sessao, config, codigo, ano, estado_http):
    caminho = RAW_DIR / "siconfi" / f"dca_{codigo}_{ano}.json"
    refresh = "siconfi" in config.get("_refresh_fontes", [])
    pasta_paginas = geracao_cache(RAW_DIR / "siconfi", f"{codigo}-{ano}", refresh)
    caminho_cache = caminho if pasta_paginas == RAW_DIR / "siconfi" / "pages" else pasta_paginas / "completo.json"

    def validar(dados, completa=False):
        if not isinstance(dados, dict) or not isinstance(dados.get("items"), list) or not isinstance(dados.get("hasMore"), bool):
            raise ValueError("DCA sem items/hasMore válidos")
        if completa and dados["hasMore"]:
            raise ValueError("DCA incompleta")
        for item in dados["items"]:
            if not isinstance(item, dict) or str(item.get("cod_ibge")) != codigo or int(item.get("exercicio", 0)) != ano:
                raise ValueError("DCA com município/ano inesperado")

    registro = dict(fonte="SICONFI", escopo=codigo, periodo=str(ano), modalidade=None,
                    paginas_esperadas=None, paginas_concluidas=0, quantidade_registros=0,
                    situacao="parcial", erro_final=None)
    dados = None if refresh else ler_cache(caminho_cache, lambda d: validar(d, completa=True))
    if dados is not None:
        registro.update(situacao="cache_reutilizado", quantidade_registros=len(dados["items"]),
                        paginas_concluidas=dados.get("_paginas", 1), paginas_esperadas=dados.get("_paginas", 1))
        atualizar_manifesto(OUTPUT_DIR, registro)
        return dados
    itens, offset, vistos = [], 0, set()
    try:
        while True:
            if offset in vistos:
                raise FalhaConsulta("SICONFI repetiu o offset")
            vistos.add(offset)
            pagina = pasta_paginas / f"dca_{codigo}_{ano}_offset_{offset}.json"
            dados = None if refresh else ler_cache(pagina, validar)
            if dados is None:
                dados = requisitar_json(sessao, "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca",
                    config, params={"an_exercicio": ano, "id_ente": codigo, "offset": offset},
                    fonte="SICONFI", contexto=f"{codigo}-{ano} offset={offset}", estado=estado_http)
                validar(dados)
                salvar_json(pagina, dados)
            itens.extend(dados["items"])
            registro.update(paginas_concluidas=len(vistos), quantidade_registros=len(itens))
            atualizar_manifesto(OUTPUT_DIR, registro)
            if not dados["hasMore"]:
                break
            # Links ORDS podem apontar para hosts internos: usar apenas offset,
            # mantendo endpoint público e filtros originais de município/ano.
            link = next((l.get("href", "") for l in dados.get("links", []) if l.get("rel") == "next"), "")
            proximo = parse_qs(urlparse(link).query).get("offset")
            limite = dados.get("limit")
            if proximo:
                novo_offset = int(proximo[0])
            elif isinstance(limite, int) and limite > 0:
                novo_offset = offset + limite
            else:
                raise FalhaConsulta("DCA hasMore sem próximo offset verificável")
            if novo_offset <= offset or not dados["items"]:
                raise FalhaConsulta("DCA com paginação inconsistente")
            offset = novo_offset
        completo = {**dados, "items": itens, "hasMore": False, "_paginas": len(vistos)}
        if caminho_cache != caminho:
            salvar_json(caminho_cache, completo)
        salvar_json(caminho, completo)
        registro.update(situacao="completa" if itens else "sem_registros_confirmado", paginas_esperadas=len(vistos))
        return completo
    except (Exception, KeyboardInterrupt) as exc:
        registro.update(situacao="parcial" if registro["paginas_concluidas"] else "falhou", erro_final=str(exc) or "Ctrl+C")
        raise
    finally:
        atualizar_manifesto(OUTPUT_DIR, registro)


def coletar_siconfi(
    sessao: requests.Session,
    config: dict[str, Any],
    erros: list[dict[str, Any]],
) -> pd.DataFrame:
    linhas: list[dict[str, Any]] = []
    estado_http = {}
    municipios = config["municipios"][:2] if config.get("_smoke_test") else config["municipios"]
    for indice, municipio in enumerate(municipios, 1):
        codigo = str(municipio["codigo_ibge"])
        for ano in anos_fonte(config, "siconfi"):
            LOGGER.info("SICONFI | %s | município %d/%d | ano %d", municipio["uf"], indice, len(municipios), ano)
            try:
                resposta = carregar_dca(sessao, config, codigo, ano, estado_http)
                itens = resposta.get("items", [])
                if not itens:
                    linhas.append(dict(codigo_ibge=codigo, ano=ano, cobertura_siconfi="sem_registros_confirmado"))
                    continue
                receita = valor_dca(
                    itens,
                    "DCA-Anexo I-C",
                    "ReceitasExcetoIntraOrcamentarias",
                    "Receitas Brutas Realizadas",
                    subtrair_deducoes=True,
                )
                transferencias = valor_dca(
                    itens,
                    "DCA-Anexo I-C",
                    "RO1.7.0.0.00.0.0",
                    "Receitas Brutas Realizadas",
                    subtrair_deducoes=True,
                )
                despesa = valor_dca(
                    itens, "DCA-Anexo I-D", "TotalDespesas", "Despesas Liquidadas"
                )
                pessoal = valor_dca(
                    itens, "DCA-Anexo I-D", "DO3.1.00.00.00.00", "Despesas Liquidadas"
                )
                investimento = valor_dca(
                    itens, "DCA-Anexo I-D", "DO4.4.00.00.00.00", "Despesas Liquidadas"
                )
                rpp = valor_dca(
                    itens,
                    "DCA-Anexo I-D",
                    "TotalDespesas",
                    "Inscrição de Restos a Pagar Processados",
                )
                rpnp = valor_dca(
                    itens,
                    "DCA-Anexo I-D",
                    "TotalDespesas",
                    "Inscrição de Restos a Pagar Não Processados",
                )
                caixa = valor_dca(
                    itens,
                    "DCA-Anexo I-AB",
                    "P1.1.1.0.0.00.00",
                    f"31/12/{ano}",
                )
                linhas.append(
                    {
                        "codigo_ibge": codigo,
                        "municipio": municipio["nome"],
                        "uf": municipio["uf"],
                        "ano": ano,
                        "cobertura_siconfi": "completa",
                        "populacao_siconfi": numero(itens[0].get("populacao")),
                        "receita_total_realizada": receita,
                        "transferencias_correntes_realizadas": transferencias,
                        "despesa_total_liquidada": despesa,
                        "despesa_pessoal_liquidada": pessoal,
                        "investimentos_liquidados": investimento,
                        "restos_pagar_processados": rpp,
                        "restos_pagar_nao_processados": rpnp,
                        "caixa_equivalentes": caixa,
                    }
                )
            except Exception as exc:
                registrar_erro(erros, "SICONFI", f"{codigo}-{ano}", exc)
                linhas.append(dict(codigo_ibge=codigo, ano=ano, cobertura_siconfi="falhou"))
    return pd.DataFrame(linhas)


PNCP_METRICAS = [
    "total_contratacoes", "valor_estimado_contratacoes", "valor_homologado_contratacoes",
    "contratacoes_similares", "valor_contratacoes_similares",
]


def coletar_janela_pncp(
    sessao, config, escopo, filtro, inicio, fim, modalidade, estado_http,
    _pasta_arvore=None,
):
    """Coleta uma janela; subdivide somente HTTP 400 de intervalos com mais de um dia."""
    if not isinstance(inicio, date) or not isinstance(fim, date) or inicio > fim:
        raise ValueError("Período PNCP inválido")
    if not isinstance(modalidade, int) or modalidade <= 0:
        raise ValueError("Modalidade PNCP inválida")
    filtros_validos = [chave for chave in ("uf", "codigoMunicipioIbge") if filtro.get(chave)]
    if len(filtros_validos) != 1:
        raise ValueError("Consulta PNCP exige exatamente um filtro territorial válido")

    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    periodo = f"{inicio}/{fim}"
    registro = dict(
        fonte="PNCP", escopo=escopo, periodo=periodo, modalidade=modalidade,
        paginas_esperadas=None, paginas_concluidas=0, situacao="parcial",
        quantidade_registros=0, erro_final=None,
        registros_antes_deduplicacao=0, registros_apos_deduplicacao=0,
        janelas_filhas=[],
    )
    atualizar_manifesto(OUTPUT_DIR, registro)
    pagina, total, caches = 1, None, 0
    total_registros = None
    dados = []
    tamanho = int(config.get("pncp_tamanho_pagina", 50))
    refresh = "pncp" in config.get("_refresh_fontes", [])
    if _pasta_arvore is None:
        _pasta_arvore = geracao_cache(
            RAW_DIR / "pncp", f"{escopo}-{inicio}-{fim}-{modalidade}-{tamanho}", refresh
        )
    pasta_paginas = _pasta_arvore
    try:
        while total is None or pagina <= max(1, total):
            caminho = pasta_paginas / (
                f"{escopo}_{inicio:%Y%m%d}_{fim:%Y%m%d}_modalidade_{modalidade:02d}"
                f"_tamanho_{tamanho}_pagina_{pagina:04d}.json"
            )
            validar = lambda resposta: validar_pagina(resposta, pagina=pagina)
            resposta = None if refresh else ler_cache(caminho, validar)
            if resposta is None:
                resposta = requisitar_json(
                    sessao, url, config, fonte="PNCP", estado=estado_http,
                    contexto=f"{escopo} {inicio}/{fim} modalidade {modalidade} página {pagina}",
                    params={
                        "dataInicial": inicio.strftime("%Y%m%d"),
                        "dataFinal": fim.strftime("%Y%m%d"),
                        "codigoModalidadeContratacao": modalidade,
                        **filtro,
                        "pagina": pagina,
                        "tamanhoPagina": tamanho,
                    },
                )
                validar(resposta)
                salvar_json(caminho, resposta)
            else:
                caches += 1
            esperado = resposta["totalPaginas"]
            if total is not None and esperado != total:
                raise FalhaConsulta("Paginação mudou durante a coleta; use --refresh para esta fonte")
            total = esperado
            informado = resposta.get("totalRegistros")
            if total_registros is not None and informado != total_registros:
                raise FalhaConsulta("PNCP mudou total de registros durante a coleta")
            total_registros = informado
            dados.extend(resposta["data"])
            registro.update(
                paginas_esperadas=max(1, total), paginas_concluidas=pagina,
                quantidade_registros=len(dados),
            )
            atualizar_manifesto(OUTPUT_DIR, registro)
            if config.get("_smoke_test") and pagina >= 2 and pagina < total:
                raise FalhaConsulta("Limite de duas páginas do smoke test; cobertura parcial")
            pagina += 1
        if total_registros is not None and len(dados) != total_registros:
            raise FalhaConsulta("PNCP: soma das páginas não corresponde ao total de registros")
        quantidade_bruta = len(dados)
        unicos = {chave_compra(item): item for item in dados}
        dados = list(unicos.values())
        registro.update(
            situacao=("sem_registros_confirmado" if not dados else
                      "cache_reutilizado" if caches == registro["paginas_concluidas"] else "completa"),
            quantidade_registros=len(dados),
            registros_antes_deduplicacao=quantidade_bruta,
            registros_apos_deduplicacao=len(dados),
        )
    except KeyboardInterrupt:
        registro.update(situacao="parcial", erro_final="Interrompido por Ctrl+C")
        atualizar_manifesto(OUTPUT_DIR, registro)
        raise
    except FalhaConsulta as exc:
        if exc.status_code == 400 and inicio < fim:
            meio = inicio + timedelta(days=(fim - inicio).days // 2)
            intervalos = [(inicio, meio), (meio + timedelta(days=1), fim)]
            registro["janelas_filhas"] = [f"{a}/{b}" for a, b in intervalos]
            atualizar_manifesto(OUTPUT_DIR, registro)
            filhos = []
            try:
                for inicio_filho, fim_filho in intervalos:
                    filhos.append(coletar_janela_pncp(
                        sessao, config, escopo, filtro, inicio_filho, fim_filho,
                        modalidade, estado_http, _pasta_arvore,
                    ))
                    registro.update(
                        paginas_concluidas=sum(filho["paginas_concluidas"] for filho in filhos),
                        registros_antes_deduplicacao=sum(
                            filho["registros_antes_deduplicacao"] for filho in filhos
                        ),
                        registros_apos_deduplicacao=sum(
                            filho["registros_apos_deduplicacao"] for filho in filhos
                        ),
                    )
                    atualizar_manifesto(OUTPUT_DIR, registro)
            except KeyboardInterrupt:
                registro.update(
                    situacao="parcial",
                    erro_final="Interrompido por Ctrl+C durante subdivisão",
                    paginas_concluidas=sum(filho["paginas_concluidas"] for filho in filhos),
                    registros_antes_deduplicacao=sum(
                        filho["registros_antes_deduplicacao"] for filho in filhos
                    ),
                    registros_apos_deduplicacao=sum(
                        filho["registros_apos_deduplicacao"] for filho in filhos
                    ),
                )
                atualizar_manifesto(OUTPUT_DIR, registro)
                raise
            combinados = [item for filho in filhos for item in filho["dados"]]
            unicos = {chave_compra(item): item for item in combinados}
            dados = list(unicos.values())
            estados_validos = {"completa", "sem_registros_confirmado", "cache_reutilizado"}
            completa = all(filho["situacao"] in estados_validos for filho in filhos)
            erros_filhos = [filho["erro_final"] for filho in filhos if filho.get("erro_final")]
            registro.update(
                paginas_esperadas=(sum(filho["paginas_esperadas"] for filho in filhos)
                                   if all(filho["paginas_esperadas"] is not None for filho in filhos) else None),
                paginas_concluidas=sum(filho["paginas_concluidas"] for filho in filhos),
                situacao=("sem_registros_confirmado" if completa and not dados else
                          "completa" if completa else "parcial"),
                quantidade_registros=len(dados),
                erro_final=" | ".join(erros_filhos) or None,
                registros_antes_deduplicacao=sum(
                    filho["registros_antes_deduplicacao"] for filho in filhos
                ),
                registros_apos_deduplicacao=len(dados),
            )
        else:
            quantidade_bruta = len(dados)
            dados = list({chave_compra(item): item for item in dados}.values())
            registro.update(
                situacao="parcial" if registro["paginas_concluidas"] else "falhou",
                erro_final=str(exc)[:800],
                registros_antes_deduplicacao=quantidade_bruta,
                registros_apos_deduplicacao=len(dados),
            )
    except Exception as exc:
        quantidade_bruta = len(dados)
        dados = list({chave_compra(item): item for item in dados}.values())
        registro.update(
            situacao="parcial" if registro["paginas_concluidas"] else "falhou",
            erro_final=str(exc)[:800],
            registros_antes_deduplicacao=quantidade_bruta,
            registros_apos_deduplicacao=len(dados),
        )
    atualizar_manifesto(OUTPUT_DIR, registro)
    return {**registro, "dados": dados}


def coletar_pncp(sessao, config, erros):
    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    eventos, agregados, rejeitados = [], [], []
    termos = [texto_busca(t) for t in config.get("palavras_objeto", [])]
    estado_http = {}
    catalogo = {str(m["codigo_ibge"]): m for m in config["municipios"]}
    estadual = (config.get("escopo") or {}).get("tipo") == "uf"
    escopos = list(dict.fromkeys(m["uf"] for m in config["municipios"])) if estadual else list(catalogo)
    for codigo in escopos:
        municipios = [m for m in catalogo.values() if m["uf"] == codigo] if estadual else [catalogo[codigo]]
        filtro = {"uf": codigo} if estadual else {"codigoMunicipioIbge": codigo}
        for ano in range(max(int(config["ano_inicial"]), int(config.get("pncp_ano_inicial", 2022))),
                         min(int(config["ano_final"]), int(config.get("pncp_ano_final", config["ano_final"]))) + 1):
            bruto_ano, estados = [], []
            janelas = list(janelas_ano(ano, int(config.get("pncp_janela_meses", 3))))
            if config.get("_smoke_test"):
                janelas = [(date(ano, 1, 2), date(ano, 1, 2))]
            for inicio, fim in janelas:
                for modalidade in config.get("pncp_modalidades", list(range(1, 14))):
                    resultado = coletar_janela_pncp(
                        sessao, config, codigo, filtro, inicio, fim, modalidade, estado_http
                    )
                    bruto_ano.extend(resultado["dados"])
                    estados.append(resultado["situacao"])
                    if resultado["situacao"] not in {"completa", "sem_registros_confirmado", "cache_reutilizado"}:
                        registrar_erro(
                            erros, "PNCP", f"{codigo}-{inicio}-{modalidade}",
                            FalhaConsulta(resultado["erro_final"] or "Cobertura PNCP incompleta"),
                        )
            # Páginas são a fonte da retomada; o arquivo anual mantém o nome legado.
            salvar_json(RAW_DIR / "pncp" / f"contratacoes_{codigo}_{ano}.json", bruto_ano)
            unicos = {chave_compra(item): item for item in bruto_ano}
            eventos_ano = []
            nao_identificados = 0
            for chave, item in unicos.items():
                unidade, orgao = item.get("unidadeOrgao") or {}, item.get("orgaoEntidade") or {}
                codigo_item = str(unidade.get("codigoIbge") or "").strip()
                municipio = next((m for m in municipios if str(m["codigo_ibge"]) == codigo_item), None)
                if municipio is None:
                    motivo = "sem_codigo_ibge" if not re.fullmatch(r"\d{7}", codigo_item) else "fora_catalogo"
                    nao_identificados += int(motivo == "sem_codigo_ibge")
                    rejeitados.append(dict(escopo=codigo, ano=ano, motivo=motivo, registro=item))
                    continue
                objeto = item.get("objetoCompra") or ""
                eventos_ano.append({
                    "codigo_ibge": codigo_item, "municipio": municipio["nome"], "uf": municipio["uf"], "ano": ano,
                    "numero_controle_pncp": item.get("numeroControlePNCP"), "chave_deduplicacao": chave,
                    "data_publicacao": item.get("dataPublicacaoPncp"), "cnpj_orgao": orgao.get("cnpj"),
                    "orgao": orgao.get("razaoSocial"), "modalidade": item.get("modalidadeNome"),
                    "situacao": item.get("situacaoCompraNome"), "objeto": objeto,
                    "valor_estimado": numero(item.get("valorTotalEstimado")),
                    "valor_homologado": numero(item.get("valorTotalHomologado")),
                    "contratacao_similar": int(any(t in texto_busca(objeto) for t in termos if t)),
                })
            eventos.extend(eventos_ano)
            completa = bool(estados) and all(e in {"completa", "sem_registros_confirmado", "cache_reutilizado"} for e in estados)
            completa = completa and not config.get("_smoke_test") and not nao_identificados
            for municipio in municipios:
                codigo_m = str(municipio["codigo_ibge"])
                registros_m = [e for e in eventos_ano if e["codigo_ibge"] == codigo_m]
                linha = {"codigo_ibge": codigo_m, "municipio": municipio["nome"], "uf": municipio["uf"], "ano": ano}
                linha.update({c: None for c in PNCP_METRICAS})
                linha["cobertura_pncp"] = ("sem_registros_confirmado" if completa and not registros_m else "completa" if completa
                                            else "falhou" if estados and all(e == "falhou" for e in estados) else "parcial")
                if completa:
                    if not registros_m:
                        linha.update({c: 0 for c in PNCP_METRICAS})
                    else:
                        quadro = pd.DataFrame(registros_m)
                        estimado = pd.to_numeric(quadro["valor_estimado"], errors="coerce")
                        homologado = pd.to_numeric(quadro["valor_homologado"], errors="coerce")
                        similar = quadro["contratacao_similar"].eq(1)
                        linha.update(total_contratacoes=len(quadro), contratacoes_similares=int(similar.sum()),
                                     valor_estimado_contratacoes=estimado.sum(min_count=len(quadro)),
                                     valor_homologado_contratacoes=homologado.sum(min_count=len(quadro)),
                                     valor_contratacoes_similares=homologado.fillna(estimado)[similar].sum(min_count=int(similar.sum())))
                agregados.append(linha)
    salvar_json(OUTPUT_DIR / "rejeitados_pncp.json", rejeitados)
    df = pd.DataFrame(eventos)
    if not df.empty:
        df["valor_similar"] = pd.to_numeric(df["valor_homologado"], errors="coerce").fillna(
            pd.to_numeric(df["valor_estimado"], errors="coerce")) * df["contratacao_similar"]
    return df, pd.DataFrame(agregados)


def identificar_municipio_obra(item, municipios):
    catalogo = {str(m["codigo_ibge"]): m for m in municipios}
    decisao = resolver_atribuicao_obra(item, municipios)
    codigo = decisao["codigo_ibge_modelagem"]
    return (catalogo.get(codigo), decisao["metodo_atribuicao"] or decisao["status_atribuicao_territorial"])


def carregar_paginas_obras(sessao, config, endpoint, params, chave, escopo, periodo, erros):
    itens, pagina, total = [], 1, None
    total_registros = None
    registro = dict(fonte="ObrasGov", escopo=escopo, periodo=str(periodo), modalidade=endpoint,
                    paginas_esperadas=None, paginas_concluidas=0, quantidade_registros=0,
                    situacao="parcial", erro_final=None)
    caches = 0
    tamanho = int(config.get("obrasgov_tamanho_pagina", 200))
    pasta_paginas = geracao_cache(RAW_DIR / "obrasgov", f"{chave}-{tamanho}", "obrasgov" in config.get("_refresh_fontes", []))
    try:
        while total is None or pagina <= max(1, total):
            tamanho = int(config.get("obrasgov_tamanho_pagina", 200))
            caminho = pasta_paginas / f"{chave}_tamanho_{tamanho}_pagina_{pagina:04d}.json"
            validar = lambda r: validar_pagina(r, "total_pages", pagina=pagina)
            resposta = None if "obrasgov" in config.get("_refresh_fontes", []) else ler_cache(caminho, validar)
            if resposta is None:
                resposta = get_json(sessao, f"https://api-publica.obrasgov.gestao.gov.br/obras/{endpoint}", config,
                                    params={**params, "pagina": pagina, "tamanho_da_pagina": tamanho})
                validar(resposta)
                salvar_json(caminho, resposta)
            else:
                caches += 1
            esperado = resposta["total_pages"]
            if total is not None and total != esperado:
                raise FalhaConsulta("ObrasGov mudou total de paginas; atualize a fonte")
            total = esperado
            informado = resposta.get("total_items")
            if total_registros is not None and informado != total_registros:
                raise FalhaConsulta("ObrasGov mudou total de registros durante a coleta")
            total_registros = informado
            itens.extend(resposta["data"])
            registro.update(paginas_esperadas=max(1, total), paginas_concluidas=pagina, quantidade_registros=len(itens))
            atualizar_manifesto(OUTPUT_DIR, registro)
            limite = 2 if config.get("_smoke_test") else int(config.get("obrasgov_max_paginas_por_uf_ano", 100))
            if pagina >= limite and pagina < total:
                raise FalhaConsulta(f"Limite de {limite} paginas; coleta parcial")
            pagina += 1
        if total_registros is not None and len(itens) != total_registros:
            raise FalhaConsulta("ObrasGov: soma das páginas diverge do total de registros")
        registro["situacao"] = "sem_registros_confirmado" if not itens else "cache_reutilizado" if caches == registro["paginas_concluidas"] else "completa"
    except KeyboardInterrupt:
        registro.update(erro_final="Ctrl+C", situacao="parcial")
        raise
    except Exception as exc:
        registro.update(erro_final=str(exc), situacao="parcial" if registro["paginas_concluidas"] else "falhou")
        registrar_erro(erros, "ObrasGov", chave, exc)
    finally:
        atualizar_manifesto(OUTPUT_DIR, registro)
    return itens, registro["situacao"]


def coletar_obrasgov(sessao, config, erros):
    eventos, agregados, rejeitados, multiterritoriais, relatorio = [], [], [], [], []
    referencia = ROOT / "data" / "reference"
    mapa_cnpj = carregar_mapeamento_csv(Path(config.get("obrasgov_mapeamento_cnpj", referencia / "obrasgov_cnpj_municipal.csv")), "cnpj")
    mapa_cep = carregar_mapeamento_csv(Path(config.get("obrasgov_mapeamento_cep", referencia / "cep_municipio.csv")), "cep")
    resolvedor_espacial = config.get("_obrasgov_resolvedor_espacial")
    if resolvedor_espacial is None:
        geojson = Path(config.get("obrasgov_malha_geojson", RAW_DIR / "ibge" / "malha_municipal.geojson"))
        metadados = Path(config.get("obrasgov_malha_metadados", RAW_DIR / "ibge" / "malha_municipal.metadados.json"))
        if geojson.exists() and metadados.exists():
            try:
                resolvedor_espacial = ResolvedorMalhaIBGE(geojson, metadados, config.get("obrasgov_tolerancia_limite_graus", 1e-8))
            except Exception as exc:
                LOGGER.warning("ObrasGov | malha municipal indisponivel: %s", exc)
    municipios_por_uf = {}
    for m in config["municipios"]:
        municipios_por_uf.setdefault(m["uf"], []).append(m)
    for uf, municipios in municipios_por_uf.items():
        catalogo_uf = municipios
        catalogo_carregado = (config.get("escopo") or {}).get("tipo") == "uf"
        catalogo_tentado = catalogo_carregado
        codigos_selecionados = {str(m["codigo_ibge"]) for m in municipios}
        for ano in anos_fonte(config, "obrasgov"):
            bruto_ano, status = carregar_paginas_obras(sessao, config, "projeto-investimento",
                {"uf_principal": uf, "ano_cadastro": ano}, f"projetos_{uf}_{ano}", uf, ano, erros)
            salvar_json(RAW_DIR / "obrasgov" / f"projetos_{uf}_{ano}.json", bruto_ano)
            unicos = {}
            for item in bruto_ano:
                unicos[str(item.get("id_projeto_investimento")) if item.get("id_projeto_investimento") else json.dumps(item, sort_keys=True)] = item
            eventos_ano, pendentes_municipais, fora_escopo = [], 0, 0
            multiterritoriais_ano = 0
            for item in unicos.values():
                decisao = resolver_atribuicao_obra(item, catalogo_uf, mapa_cnpj, mapa_cep, resolvedor_espacial)
                codigo_decidido = decisao["codigo_ibge_modelagem"]
                municipio = next((m for m in catalogo_uf if str(m["codigo_ibge"]) == codigo_decidido), None)
                usa_nome = bool(item.get("executores") or item.get("tomadores") or item.get("contratantes"))
                if usa_nome and not catalogo_tentado:
                    # Catálogo territorial não amplia a seleção final; serve apenas
                    # para distinguir nomes estruturados de cidades fora do recorte.
                    catalogo_tentado = True
                    try:
                        catalogo_uf = resolver_municipios(sessao, {**config, "escopo": {"tipo": "uf", "ufs": [uf]}})
                        catalogo_carregado = True
                        decisao = resolver_atribuicao_obra(item, catalogo_uf, mapa_cnpj, mapa_cep, resolvedor_espacial)
                        codigo_decidido = decisao["codigo_ibge_modelagem"]
                        municipio = next((m for m in catalogo_uf if str(m["codigo_ibge"]) == codigo_decidido), None)
                    except Exception as exc:
                        registrar_erro(erros, "ObrasGov-catalogo", uf, exc)
                if usa_nome and not catalogo_carregado:
                    municipio = None
                    decisao.update(status_atribuicao_territorial="nao_identificada", motivo_nao_atribuicao="catalogo_territorial_indisponivel", indicio_municipal_pendente=True)
                if decisao["status_atribuicao_territorial"] == "multiterritorial":
                    multiterritoriais_ano += 1
                    multiterritoriais.append({"id_projeto_investimento": item.get("id_projeto_investimento"),
                        "codigos_ibge_envolvidos": sorted({e["codigo_ibge"] for e in decisao["evidencias_atribuicao"] if e.get("codigo_ibge")}),
                        "quantidade_municipios": decisao["quantidade_municipios_atribuidos"],
                        "metodo_identificacao": "multiplas_evidencias_territoriais", "evidencias": decisao["evidencias_atribuicao"]})
                    continue
                if decisao["status_atribuicao_territorial"] == "fora_escopo_municipal" or municipio is not None and str(municipio["codigo_ibge"]) not in codigos_selecionados:
                    fora_escopo += 1
                    rejeitados.append(dict(uf=uf, ano=ano, motivo="fora_escopo_municipal", atribuicao=decisao, registro=item))
                    continue
                if municipio is None:
                    rejeitados.append(dict(uf=uf, ano=ano, motivo=decisao["motivo_nao_atribuicao"], atribuicao=decisao, registro=item))
                    pendentes_municipais += int(decisao["indicio_municipal_pendente"] or decisao["status_atribuicao_territorial"] == "conflitante")
                    continue
                temporal = campos_temporais_obras(item, ano)
                if temporal["ano_cadastro"] != int(ano):
                    rejeitados.append(dict(uf=uf, ano=ano, motivo="ano_cadastro_divergente", atribuicao=decisao,
                                           ano_cadastro_retornado=temporal["ano_cadastro"], registro=item))
                    pendentes_municipais += 1
                    continue
                projeto_id = item.get("id_projeto_investimento")
                execucoes, historico = [], []
                hist_status = "nao_consultado"
                if not config.get("_smoke_test") and projeto_id:
                    execucoes, exec_status = carregar_paginas_obras(sessao, config, "execucao-fisica",
                        {"id_projeto_investimento": projeto_id}, f"execucao_{projeto_id}", str(projeto_id), ano, erros)
                    historico, hist_status = carregar_paginas_obras(sessao, config, "historico-situacao-cancelada-paralisada",
                        {"id_projeto_investimento": projeto_id}, f"historico_{projeto_id}", str(projeto_id), ano, erros)
                    if exec_status not in {"completa", "cache_reutilizado", "sem_registros_confirmado"}:
                        execucoes = []
                percentuais = [numero(x.get("percentual_execucao_fisica")) for x in execucoes if numero(x.get("percentual_execucao_fisica")) is not None]
                investimentos = [numero(x.get("vl_investimento_previsto")) for x in item.get("investimentos_previstos", []) or []]
                valor = sum(investimentos) if investimentos and all(v is not None for v in investimentos) else None
                eventos_ano.append({
                    "codigo_ibge": str(municipio["codigo_ibge"]), "municipio": municipio["nome"], "uf": municipio["uf"], **temporal,
                    "id_projeto_investimento": projeto_id, "nome_projeto": item.get("desc_nome"), "situacao_atual": item.get("situacao"),
                    "data_inicial_prevista": item.get("dt_inicial_prevista"), "data_final_prevista": item.get("dt_final_prevista"),
                    "data_inicial_efetiva": item.get("dt_inicial_efetiva"), "data_final_efetiva": item.get("dt_final_efetiva"),
                    "valor_investimento_previsto": valor, "percentual_execucao": max(percentuais) if percentuais else None,
                    "possui_estudo_viabilidade": item.get("possui_estudo_viabilidade"), "identificacao_municipio": decisao["metodo_atribuicao"],
                    **{k: (json.dumps(v, ensure_ascii=False, sort_keys=True) if k == "evidencias_atribuicao" else v) for k, v in decisao.items() if k != "codigo_ibge_modelagem"},
                    "areas_restricao": "; ".join(str(x["area_restricao"]) for x in item.get("areas_restricao", []) or [] if x.get("area_restricao")),
                    "quantidade_eventos_paralisacao_cancelamento": len(historico) if hist_status in {"completa", "cache_reutilizado", "sem_registros_confirmado"} else None,
                    "sem_estudo_viabilidade": 1 if texto_busca(item.get("possui_estudo_viabilidade")) == "nao" else 0 if texto_busca(item.get("possui_estudo_viabilidade")) == "sim" else None,
                })
            eventos.extend(eventos_ano)
            status_api = "completa" if status in {"completa", "cache_reutilizado", "sem_registros_confirmado"} else "falhou" if status == "falhou" else "parcial"
            incertos = pendentes_municipais + multiterritoriais_ano
            status_atribuicao = "parcial" if pendentes_municipais else "multiterritorial" if multiterritoriais_ano else "exata"
            status_agregado = "indisponivel" if status_api != "completa" else "observado_parcial" if incertos else "completo_no_escopo"
            completa = status_agregado == "completo_no_escopo"
            for m in municipios:
                registros = [e for e in eventos_ano if e["codigo_ibge"] == str(m["codigo_ibge"])]
                linha = dict(codigo_ibge=str(m["codigo_ibge"]), municipio=m["nome"], uf=uf, ano=ano,
                             cobertura_obrasgov="completa" if completa else "falhou" if status_api == "falhou" else "parcial",
                             status_coleta_api=status_api, status_atribuicao_territorial=status_atribuicao,
                             status_agregado=status_agregado, cobertura_atribuicao=(len(eventos_ano) / (len(eventos_ano) + incertos)) if len(eventos_ano) + incertos else 1.0,
                             valor_observado_total_obras=(len(registros) if status_api == "completa" and (registros or completa) else None))
                metricas = ("total_obras", "obras_paradas", "valor_obras_paradas", "percentual_execucao_medio", "obras_sem_estudo_viabilidade", "taxa_obras_paradas")
                linha.update({c: None for c in metricas})
                if completa:
                    linha["total_obras"] = len(registros)
                    if not registros:
                        linha.update(obras_paradas=0, valor_obras_paradas=0, obras_sem_estudo_viabilidade=0)
                    else:
                        quadro = pd.DataFrame(registros)
                        linha["obras_paradas"] = pd.to_numeric(quadro["obra_parada"], errors="coerce").sum(min_count=len(quadro))
                        linha["obras_sem_estudo_viabilidade"] = pd.to_numeric(quadro["sem_estudo_viabilidade"], errors="coerce").sum(min_count=len(quadro))
                        valores = pd.to_numeric(quadro["valor_investimento_previsto"], errors="coerce")
                        paradas = quadro["obra_parada"].eq(1)
                        linha["valor_obras_paradas"] = valores[paradas].sum(min_count=int(paradas.sum())) if quadro["obra_parada"].notna().all() else None
                        linha["percentual_execucao_medio"] = pd.to_numeric(quadro["percentual_execucao"], errors="coerce").mean() if quadro["percentual_execucao"].notna().all() else None
                        linha["taxa_obras_paradas"] = linha["obras_paradas"] / len(registros)
                agregados.append(linha)
            relatorio.append({"ano": ano, "projetos_brutos": len(unicos), "projetos_atribuidos": len(eventos_ano),
                "projetos_nao_identificados": pendentes_municipais, "projetos_multiterritoriais": multiterritoriais_ano,
                "projetos_fora_escopo_municipal": fora_escopo,
                "taxa_atribuicao": len(eventos_ano) / len(unicos) if unicos else 1.0,
                "municipios_representados": len({e["codigo_ibge"] for e in eventos_ano}),
                "status_coleta_api": status_api, "status_atribuicao_territorial": status_atribuicao,
                "status_agregado": status_agregado})
    salvar_json(OUTPUT_DIR / "rejeitados_obrasgov.json", rejeitados)
    salvar_json(OUTPUT_DIR / "projetos_multiterritoriais_obrasgov.json", multiterritoriais)
    salvar_csv(pd.DataFrame(relatorio), "cobertura_territorial_obrasgov.csv")
    df = pd.DataFrame(eventos)
    if not df.empty:
        df["valor_obra_parada"] = pd.to_numeric(df["valor_investimento_previsto"], errors="coerce") * pd.to_numeric(df["obra_parada"], errors="coerce")
    return df, pd.DataFrame(agregados)


@dataclass
class TabelaManual:
    fonte: str
    arquivo: str
    tabela: str
    quadro: pd.DataFrame


def inferir_fonte(caminho: Path) -> str:
    texto = chave_texto(str(caminho))
    for fonte in ("transferegov", "mapbiomas", "sinisa", "snis", "fnde", "ana"):
        if fonte in texto:
            return fonte.upper()
    return "MANUAL-NAO-CLASSIFICADA"


def ler_csv_flexivel(objeto: Any) -> pd.DataFrame:
    ultimo: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin1"):
        try:
            if hasattr(objeto, "seek"):
                objeto.seek(0)
            return pd.read_csv(
                objeto,
                sep=None,
                engine="python",
                encoding=encoding,
                decimal=",",
            )
        except Exception as exc:
            ultimo = exc
    raise ultimo or ValueError("Não foi possível ler o CSV")


def ler_arquivo_manual(caminho: Path) -> list[TabelaManual]:
    fonte = inferir_fonte(caminho)
    sufixo = caminho.suffix.lower()
    saida: list[TabelaManual] = []
    if sufixo in {".csv", ".txt"}:
        saida.append(TabelaManual(fonte, str(caminho), caminho.name, ler_csv_flexivel(caminho)))
    elif sufixo in {".xlsx", ".xls"}:
        abas = pd.read_excel(caminho, sheet_name=None)
        saida.extend(TabelaManual(fonte, str(caminho), nome, df) for nome, df in abas.items())
    elif sufixo == ".parquet":
        saida.append(TabelaManual(fonte, str(caminho), caminho.name, pd.read_parquet(caminho)))
    elif sufixo == ".json":
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            dados = dados.get("data") or dados.get("items") or [dados]
        saida.append(TabelaManual(fonte, str(caminho), caminho.name, pd.json_normalize(dados)))
    elif sufixo == ".zip":
        with zipfile.ZipFile(caminho) as zf:
            for nome in zf.namelist():
                if nome.endswith("/"):
                    continue
                ext = Path(nome).suffix.lower()
                conteudo = zf.read(nome)
                if ext in {".csv", ".txt"}:
                    df = ler_csv_flexivel(io.BytesIO(conteudo))
                    saida.append(TabelaManual(fonte, f"{caminho}!{nome}", nome, df))
                elif ext in {".xlsx", ".xls"}:
                    abas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None)
                    saida.extend(
                        TabelaManual(fonte, f"{caminho}!{nome}", f"{nome}:{aba}", df)
                        for aba, df in abas.items()
                    )
    return saida


def perfilar_manuais(erros: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    inventario_arquivos: list[dict[str, Any]] = []
    inventario_colunas: list[dict[str, Any]] = []
    if not MANUAL_DIR.exists():
        return pd.DataFrame(), pd.DataFrame()
    extensoes = {".csv", ".txt", ".xlsx", ".xls", ".json", ".parquet", ".zip"}
    for caminho in sorted(p for p in MANUAL_DIR.rglob("*") if p.suffix.lower() in extensoes):
        try:
            tabelas = ler_arquivo_manual(caminho)
            for tabela in tabelas:
                df = tabela.quadro
                inventario_arquivos.append(
                    {
                        "fonte": tabela.fonte,
                        "arquivo": tabela.arquivo,
                        "tabela_ou_aba": tabela.tabela,
                        "linhas": len(df),
                        "colunas": len(df.columns),
                    }
                )
                for coluna in df.columns:
                    serie = df[coluna]
                    numerica = pd.to_numeric(serie, errors="coerce")
                    inventario_colunas.append(
                        {
                            "fonte": tabela.fonte,
                            "arquivo": tabela.arquivo,
                            "tabela_ou_aba": tabela.tabela,
                            "coluna_original": str(coluna),
                            "coluna_normalizada": chave_texto(coluna),
                            "tipo_pandas": str(serie.dtype),
                            "linhas": len(serie),
                            "faltantes": int(serie.isna().sum()),
                            "percentual_faltantes": float(serie.isna().mean()) if len(serie) else None,
                            "valores_unicos": int(serie.nunique(dropna=True)),
                            "percentual_numerico": float(numerica.notna().mean()) if len(serie) else None,
                            "min_numerico": numerica.min() if numerica.notna().any() else None,
                            "max_numerico": numerica.max() if numerica.notna().any() else None,
                            "exemplo": next((str(v) for v in serie.dropna().head(1)), None),
                        }
                    )
        except Exception as exc:
            registrar_erro(erros, "ARQUIVO-MANUAL", str(caminho), exc)
    return pd.DataFrame(inventario_arquivos), pd.DataFrame(inventario_colunas)


def combinar_bases(bases: list[pd.DataFrame], config: dict[str, Any]) -> pd.DataFrame:
    chaves = ["codigo_ibge", "ano"]
    esqueleto = pd.DataFrame(
        [
            {
                "codigo_ibge": str(m["codigo_ibge"]),
                "municipio": m["nome"],
                "uf": m["uf"],
                "ano": ano,
            }
            for m in config["municipios"]
            for ano in range(int(config["ano_inicial"]), int(config["ano_final"]) + 1)
        ]
    )
    resultado = esqueleto
    for base in bases:
        if base is None or base.empty:
            continue
        base = base.copy()
        base["codigo_ibge"] = base["codigo_ibge"].astype(str)
        sobrepostas = [c for c in base.columns if c in resultado.columns and c not in chaves]
        base = base.drop(columns=sobrepostas, errors="ignore")
        resultado = resultado.merge(base, on=chaves, how="left", validate="one_to_one")
    # A população informada na DCA pode usar uma referência diferente ou defasada.
    # Ela é preservada para auditoria, mas não preenche automaticamente a série IBGE.
    formulas = {
        "pib_per_capita": ("pib", "populacao"),
        "dependencia_transferencias": (
            "transferencias_correntes_realizadas",
            "receita_total_realizada",
        ),
        "investimento_per_capita": ("investimentos_liquidados", "populacao"),
        "restos_pagar_sobre_receita": ("restos_pagar_total", "receita_total_realizada"),
        "caixa_sobre_receita": ("caixa_equivalentes", "receita_total_realizada"),
        "pressao_pessoal_proxy": ("despesa_pessoal_liquidada", "receita_total_realizada"),
    }
    if {"restos_pagar_processados", "restos_pagar_nao_processados"}.issubset(resultado.columns):
        resultado["restos_pagar_total"] = resultado[
            ["restos_pagar_processados", "restos_pagar_nao_processados"]
        ].sum(axis=1, min_count=2)
    for destino, (num, den) in formulas.items():
        if num in resultado and den in resultado:
            resultado[destino] = divisao_segura(resultado[num], resultado[den])
    if {"receita_total_realizada", "despesa_total_liquidada"}.issubset(resultado.columns):
        resultado["resultado_orcamentario_proxy"] = (
            resultado["receita_total_realizada"] - resultado["despesa_total_liquidada"]
        )
    return resultado.sort_values(["codigo_ibge", "ano"]).reset_index(drop=True)


SINONIMOS: dict[str, tuple[str, ...]] = {
    "codigo_ibge": ("codigo_ibge", "cod_ibge", "codigo_municipio", "cd_ibge"),
    "municipio": ("municipio", "nome_municipio", "nm_municipio"),
    "ano": ("ano", "ano_referencia", "exercicio", "ano_base"),
    "valor_pactuado": ("valor_pactuado", "vl_global", "valor_global", "valor_convenio"),
    "valor_liberado": ("valor_liberado", "vl_liberado", "valor_repasse", "vl_repasse"),
    "cobertura_agua": ("indice_atendimento_agua", "populacao_atendida_agua", "in055"),
    "cobertura_esgoto": ("indice_atendimento_esgoto", "populacao_atendida_esgoto", "in056"),
    "tratamento_esgoto": ("indice_tratamento_esgoto", "in016", "in046"),
    "cobertura_coleta_residuos": ("taxa_cobertura_coleta", "in015_rs", "in014_rs"),
    "cobertura_drenagem": ("cobertura_drenagem", "in021_ap", "in020_ap"),
    "area_urbanizada_ha": ("urbanizada", "infraestrutura_urbana", "classe_24"),
    "vegetacao_nativa_ha": ("vegetacao_nativa", "natural", "formacao_florestal"),
    "superficie_agua_ha": ("rio_lago_oceano", "corpo_dagua", "agua"),
    "precipitacao_anual_mm": ("precipitacao", "chuva_anual", "precipitacao_total"),
}


def gerar_status_variaveis(
    base: pd.DataFrame, inventario_colunas: pd.DataFrame
) -> pd.DataFrame:
    catalogo = pd.read_csv(CATALOGO_VARIAVEIS)
    colunas_base = {chave_texto(c): c for c in base.columns}
    colunas_manuais: dict[str, list[str]] = {}
    if not inventario_colunas.empty:
        for _, linha in inventario_colunas.iterrows():
            colunas_manuais.setdefault(str(linha["coluna_normalizada"]), []).append(
                f'{linha["fonte"]}:{linha["coluna_original"]}'
            )
    resultados: list[dict[str, Any]] = []
    for _, linha in catalogo.iterrows():
        variavel = str(linha["variavel"])
        chave = chave_texto(variavel)
        candidatos = (chave,) + SINONIMOS.get(variavel, ())
        api = next((colunas_base[c] for c in candidatos if c in colunas_base), None)
        manuais = [
            valor
            for candidato in candidatos
            for valor in colunas_manuais.get(chave_texto(candidato), [])
        ]
        if api and base[api].notna().any():
            status = "disponivel_na_base_municipio_ano"
            encontrado = api
        elif api:
            status = "campo_presente_sem_observacoes_validas"
            encontrado = api
        elif manuais:
            status = "encontrado_em_arquivo_manual_requer_mapeamento"
            encontrado = " | ".join(sorted(set(manuais)))
        elif linha["tipo"] == "derivada":
            status = "formula_definida_mas_insumos_ausentes"
            encontrado = ""
        elif linha["nivel"] == "area-do-projeto":
            status = "requer_etl_geoespacial_localizado"
            encontrado = ""
        else:
            status = "nao_encontrada_nesta_execucao"
            encontrado = ""
        item = linha.to_dict()
        item.update({"status_etl": status, "campo_encontrado": encontrado})
        resultados.append(item)
    return pd.DataFrame(resultados)


def auditar_qualidade(
    base: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    chaves = {"codigo_ibge", "municipio", "uf", "ano", "fonte_populacao"}
    qualidade: list[dict[str, Any]] = []
    numericas: list[str] = []
    catalogo = pd.read_csv(CATALOGO_VARIAVEIS).fillna("").set_index("variavel").to_dict("index")
    campos_resultado_obras = {
        "evento_adverso_execucao", "obra_parada", "obras_paradas", "taxa_obras_paradas",
        "valor_obras_paradas", "percentual_execucao", "percentual_execucao_medio",
        "resultado_observavel", "projeto_censurado", "ano_fim_efetivo", "data_observacao_status",
    }
    for coluna in dict.fromkeys([*base.columns, *catalogo]):
        if coluna in chaves or coluna.startswith("cobertura_") and coluna not in catalogo:
            continue
        serie = base[coluna] if coluna in base else pd.Series(float("nan"), index=base.index)
        serie_num = pd.to_numeric(serie, errors="coerce")
        valida = serie.notna()
        cobertura = float(valida.mean()) if len(base) else 0.0
        unicos = int(serie.nunique(dropna=True))
        frequencias = serie.value_counts(normalize=True)
        quase_constante = bool(len(frequencias) and frequencias.iloc[0] >= float(config.get("limiar_quase_constante", 0.95)))
        if cobertura >= float(config.get("limiar_cobertura_manter", 0.70)) and unicos > 1:
            recomendacao = "manter_para_analise"
        elif cobertura >= float(config.get("limiar_cobertura_revisar", 0.50)) and unicos > 1:
            recomendacao = "revisar_cobertura"
        elif unicos <= 1 and cobertura > 0:
            recomendacao = "remover_constante_ou_quase_constante"
        else:
            recomendacao = "nao_usar_ate_melhorar_cobertura"
        if quase_constante:
            recomendacao = "remover_constante_ou_quase_constante"
        if coluna in campos_resultado_obras:
            recomendacao = "nao_usar_como_preditor_resultado"
        metadados = catalogo.get(coluna, {})
        fonte = metadados.get("fonte_principal", "SICONFI" if coluna == "populacao_siconfi" else "nao_catalogada")
        anos_validos = base.loc[valida, "ano"]
        qualidade.append(
            {
                "variavel": coluna,
                "fonte": fonte,
                "dimensao": metadados.get("dimensao", "nao_catalogada"),
                "tipo": metadados.get("tipo", "bruta"),
                "quantidade_municipios": int(base.loc[valida, "codigo_ibge"].nunique()),
                "quantidade_anos": int(anos_validos.nunique()),
                "primeiro_ano": anos_validos.min() if len(anos_validos) else None,
                "ultimo_ano": anos_validos.max() if len(anos_validos) else None,
                "percentual_cobertura": cobertura * 100,
                "percentual_faltantes": (1 - cobertura) * 100,
                "possivel_vazamento_temporal": "sim: informacao de resultado posterior ao inicio" if coluna in campos_resultado_obras else "sim: estado atual consultado depois do ano de cadastro" if "Obras" in fonte else "verificar data de publicacao e revisoes antes de modelar",
                "mudanca_metodologica": "Censo 2022 versus estimativas intercensitarias" if coluna in {"populacao", "pib_per_capita", "investimento_per_capita"} else "Transicao SNIS/SINISA: conferir conceitos e referencia" if "SINISA" in fonte or "SNIS" in fonte else metadados.get("observacao", ""),
                "observacoes": len(base),
                "validas": int(valida.sum()),
                "cobertura": cobertura,
                "faltantes": int((~valida).sum()),
                "valores_unicos": unicos,
                "media": serie_num.mean(),
                "desvio_padrao": serie_num.std(),
                "minimo": serie_num.min(),
                "maximo": serie_num.max(),
                "recomendacao_inicial": recomendacao,
            }
        )
        if serie_num.notna().any() and serie_num.nunique() > 1:
            numericas.append(coluna)
    pares: list[dict[str, Any]] = []
    if len(numericas) >= 2:
        quadro_num = base[numericas].apply(pd.to_numeric, errors="coerce")
        minimo_n = max(20, int(config.get("min_observacoes_correlacao", 20)))
        corr = quadro_num.corr(method="spearman", min_periods=minimo_n)
        limiar = float(config.get("limiar_correlacao", 0.85))
        for i, a in enumerate(numericas):
            for b in numericas[i + 1 :]:
                valor = corr.loc[a, b]
                n_pares = int(quadro_num[[a, b]].dropna().shape[0])
                if n_pares >= minimo_n and pd.notna(valor) and abs(valor) >= limiar:
                    pares.append(
                        {
                            "variavel_a": a,
                            "variavel_b": b,
                            "correlacao_spearman": valor,
                            "observacoes_pareadas": n_pares,
                            "alerta": "avaliar_redundancia_nao_remover_automaticamente",
                        }
                    )
    return pd.DataFrame(qualidade), pd.DataFrame(pares, columns=["variavel_a", "variavel_b", "correlacao_spearman", "observacoes_pareadas", "alerta"])


def cobertura_fontes(base, qualidade, config, fontes):
    linhas = []
    for fonte in ("ibge", "siconfi", "pncp", "obrasgov", "tse_eleitoral"):
        colunas = [r["variavel"] for r in qualidade.to_dict("records")
                   if fonte in str(r["fonte"]).lower() and r["variavel"] in base]
        for ano, quadro in base.groupby("ano"):
            preenchidas = quadro[colunas].notna() if colunas else pd.DataFrame(index=quadro.index)
            status = quadro.get(f"cobertura_{fonte}", pd.Series(dtype=str)).value_counts().to_dict()
            linhas.append(dict(fonte=fonte.upper(), ano=int(ano), municipios=len(quadro),
                               municipios_com_dados=int(preenchidas.any(axis=1).sum()),
                               cobertura=float(preenchidas.to_numpy().mean()) if len(colunas) else 0,
                               variaveis=len(colunas), solicitada=fonte in fontes,
                               periodo_configurado=f"{config.get(fonte + '_ano_inicial', config['ano_inicial'])}/{config.get(fonte + '_ano_final', config['ano_final'])}",
                               situacoes=json.dumps(status, ensure_ascii=False)))
    return pd.DataFrame(linhas)


def salvar_csv(df: pd.DataFrame, nome: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_DIR / nome, index=False, encoding="utf-8-sig")


def main() -> int:
    global RAW_DIR, OUTPUT_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--resume", action="store_true", help="Reutiliza checkpoints válidos (padrão)")
    modo.add_argument("--refresh", action="store_true", help="Atualiza apenas as fontes selecionadas")
    parser.add_argument("--smoke-test", action="store_true", help="Teste limitado em diretórios isolados")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=("ibge", "siconfi", "pncp", "obrasgov", "tse_eleitoral"),
        help="Sobrescreve a lista de fontes automáticas do config.json",
    )
    parser.add_argument(
        "--only-profile",
        action="store_true",
        help="Não consulta APIs; apenas perfila dados brutos existentes e arquivos manuais",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    fontes = args.sources or config.get("fontes", [])
    config["_refresh_fontes"] = fontes if args.refresh else []
    config["_only_profile"] = args.only_profile
    if int(config["ano_inicial"]) > int(config["ano_final"]):
        parser.error("ano_inicial não pode ser maior que ano_final")
    if args.smoke_test:
        config["_smoke_test"] = True
        if fontes == ["tse_eleitoral"]:
            config["ano_inicial"] = int(config.get("tse_eleitoral_ano_inicial", 2020))
            config["ano_final"] = int(config.get("tse_eleitoral_ano_final", 2024))
            config["tse_eleitoral_edicoes"] = [2016, 2020]
        else:
            config["ano_inicial"] = config["ano_final"]
        config["pncp_modalidades"] = [8]
        config["pncp_max_tentativas"] = 2
        config["max_tentativas"] = 2
        config["pncp_timeout_segundos"] = 30
        escopo_smoke = "uf" if (config.get("escopo") or {}).get("tipo") == "uf" else "municipal"
        RAW_DIR = RAW_DIR / "smoke" / escopo_smoke
        OUTPUT_DIR = OUTPUT_DIR / "smoke" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        LOGGER.info("Smoke isolado | saída: %s", OUTPUT_DIR)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sessao = criar_sessao(config)
    try:
        config["municipios"] = resolver_municipios(sessao, config)
    except (ValueError, FalhaConsulta) as exc:
        parser.error(str(exc))
    if args.smoke_test and escopo_smoke == "municipal":
        config["municipios"] = config["municipios"][:1]
    # Preserva uma cópia das saídas anteriores antes de gerar a nova execução.
    existentes = [p for p in OUTPUT_DIR.iterdir() if p.is_file()]
    if existentes:
        backup = OUTPUT_DIR / "historico" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup.mkdir(parents=True)
        for caminho in existentes:
            shutil.copy2(caminho, backup / caminho.name)
    if not (OUTPUT_DIR / "manifesto_coleta.json").exists():
        salvar_json(OUTPUT_DIR / "manifesto_coleta.json", [])
    erros: list[dict[str, Any]] = []
    bases: list[pd.DataFrame] = []
    eventos_pncp = pd.DataFrame()
    eventos_obras = pd.DataFrame()
    resultado_tse = None

    if not args.only_profile:
        if "ibge" in fontes:
            LOGGER.info("Coletando IBGE")
            bases.append(coletar_ibge(sessao, config, erros))
        if "siconfi" in fontes:
            LOGGER.info("Coletando SICONFI")
            bases.append(coletar_siconfi(sessao, config, erros))
        if "pncp" in fontes:
            LOGGER.info("Coletando PNCP")
            eventos_pncp, pncp_ano = coletar_pncp(sessao, config, erros)
            bases.append(pncp_ano)
        if "obrasgov" in fontes:
            LOGGER.info("Coletando ObrasGov")
            eventos_obras, obras_ano = coletar_obrasgov(sessao, config, erros)
            bases.append(obras_ano)
        if "tse_eleitoral" in fontes:
            LOGGER.info("Coletando TSE eleitoral")
            try:
                resultado_tse = etl_tse_eleitoral.executar_tse_eleitoral(
                    sessao, config, RAW_DIR / "tse_eleitoral", OUTPUT_DIR
                )
                if args.smoke_test and fontes == ["tse_eleitoral"]:
                    codigos_smoke = set(resultado_tse.municipio_ano["codigo_ibge"].astype(str))
                    config["municipios"] = [
                        municipio for municipio in config["municipios"]
                        if str(municipio["codigo_ibge"]) in codigos_smoke
                    ]
                    if len(config["municipios"]) != 2:
                        raise etl_tse_eleitoral.FalhaTSE("Smoke TSE exige exatamente dois municípios")
                bases.append(etl_tse_eleitoral.adaptar_municipio_ano_para_base(resultado_tse.municipio_ano))
                etl_tse_eleitoral.gravar_resultado_tse(resultado_tse, OUTPUT_DIR)
            except etl_tse_eleitoral.FalhaTSE as exc:
                registrar_erro(erros, "TSE-ELEITORAL", "PB", exc)

    LOGGER.info("Perfilando arquivos manuais")
    inventario_arquivos, inventario_colunas = perfilar_manuais(erros)
    base = combinar_bases(bases, config)
    status = gerar_status_variaveis(base, inventario_colunas)
    qualidade, correlacoes = auditar_qualidade(base, config)

    salvar_csv(base, "base_municipio_ano.csv")
    salvar_csv(eventos_pncp, "eventos_pncp.csv")
    salvar_csv(eventos_obras, "eventos_obrasgov.csv")
    salvar_csv(inventario_arquivos, "inventario_arquivos.csv")
    salvar_csv(inventario_colunas, "inventario_colunas.csv")
    salvar_csv(status, "status_variaveis.csv")
    salvar_csv(qualidade, "qualidade_variaveis.csv")
    salvar_csv(cobertura_fontes(base, qualidade, config, [] if args.only_profile else fontes), "cobertura_fontes.csv")
    salvar_csv(correlacoes, "pares_correlacionados.csv")
    salvar_csv(pd.DataFrame(erros), "erros_coleta.csv")

    resumo = {
        "executado_em": datetime.now(timezone.utc).isoformat(),
        "fontes_automaticas": [] if args.only_profile else fontes,
        "municipios": len(config["municipios"]),
        "periodo": [config["ano_inicial"], config["ano_final"]],
        "periodos_por_fonte": {
            f: ([int(ano) for ano in config.get("tse_eleitoral_edicoes", [])]
                if f == "tse_eleitoral" else
                list(anos_fonte({**config, "pncp_ano_inicial": config.get("pncp_ano_inicial", 2022)}, f)))
            for f in fontes
        },
        "smoke_test": bool(args.smoke_test),
        "linhas_base_municipio_ano": len(base),
        "colunas_base_municipio_ano": len(base.columns),
        "eventos_pncp": len(eventos_pncp),
        "eventos_obrasgov": len(eventos_obras),
        "eventos_tse_eleitoral": len(resultado_tse.eventos) if resultado_tse is not None else 0,
        "mandatos_municipais": len(resultado_tse.mandatos) if resultado_tse is not None else 0,
        "arquivos_manuais_lidos": len(inventario_arquivos),
        "erros": len(erros),
        "aviso": "Saídas são exploratórias; não interpretar como score final ou causalidade.",
    }
    salvar_json(OUTPUT_DIR / "resumo_execucao.json", resumo)
    print(json.dumps({**resumo, "municipios": len(config["municipios"]), "diretorio_saida": str(OUTPUT_DIR)}, ensure_ascii=False, indent=2))
    sessao.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
