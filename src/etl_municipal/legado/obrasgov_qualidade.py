"""Regras conservadoras de qualidade territorial e temporal do ObrasGov."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def normalizar(valor: Any) -> str:
    texto = "" if valor is None else str(valor)
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", texto.upper())).strip()


def somente_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", "" if valor is None else str(valor))


def _codigo(valor: Any) -> str | None:
    codigo = somente_digitos(valor)
    return codigo if len(codigo) == 7 else None


def _ano_data(valor: Any) -> int | None:
    if valor is None or str(valor).strip() == "":
        return None
    match = re.match(r"^(\d{4})", str(valor).strip())
    return int(match.group(1)) if match else None


def campos_temporais(item: dict[str, Any], ano_consulta: int) -> dict[str, Any]:
    situacao = normalizar(item.get("situacao"))
    adversos = {"CANCELADA", "INACABADA", "PARALISADA"}
    alvo = 1 if situacao in adversos else 0 if situacao == "CONCLUIDA" else None
    cadastro = item.get("ano_cadastro") or _ano_data(item.get("dt_cadastro")) or int(ano_consulta)
    data_observacao = item.get("data_observacao_status") or item.get("dt_atualizacao") or item.get("data_atualizacao")
    return {
        "ano": int(cadastro),
        "ano_cadastro": int(cadastro),
        "ano_inicio_previsto": _ano_data(item.get("dt_inicial_prevista")),
        "ano_fim_previsto": _ano_data(item.get("dt_final_prevista")),
        "ano_inicio_efetivo": _ano_data(item.get("dt_inicial_efetiva")),
        "ano_fim_efetivo": _ano_data(item.get("dt_final_efetiva")),
        "data_observacao_status": data_observacao,
        "origem_ano_cadastro": "ObrasGov.ano_cadastro/dt_cadastro",
        "origem_datas_previstas": "ObrasGov.dt_inicial_prevista/dt_final_prevista",
        "origem_datas_efetivas": "ObrasGov.dt_inicial_efetiva/dt_final_efetiva",
        "evento_adverso_execucao": alvo,
        "resultado_observavel": alvo is not None,
        "projeto_censurado": alvo is None,
        "obra_parada": alvo,
    }


def _nomes_catalogo(municipios: list[dict[str, Any]]) -> dict[str, set[str]]:
    saida: dict[str, set[str]] = {}
    prefixos = ("PREFEITURA MUNICIPAL DE ", "PREFEITURA DE ", "MUNICIPIO DE ", "MUNICIPIO DO ",
                "MUNICIPIO DA ", "FUNDO MUNICIPAL DE SAUDE DE ")
    for municipio in municipios:
        nome = normalizar(municipio["nome"])
        codigo = str(municipio["codigo_ibge"])
        variantes = {nome, *(p + nome for p in prefixos)}
        for variante in variantes:
            saida.setdefault(variante, set()).add(codigo)
    return saida


def resolver_atribuicao(
    item: dict[str, Any],
    municipios: list[dict[str, Any]],
    mapa_cnpj: dict[str, dict[str, Any]] | None = None,
    mapa_cep: dict[str, dict[str, Any]] | None = None,
    resolver_espacial: Any = None,
) -> dict[str, Any]:
    mapa_cnpj, mapa_cep = mapa_cnpj or {}, mapa_cep or {}
    validos = {str(m["codigo_ibge"]) for m in municipios}
    nomes = _nomes_catalogo(municipios)
    evidencias: list[dict[str, Any]] = []
    por_papel: dict[str, set[str]] = {p: set() for p in ("contratante", "executor", "tomador", "localizacao")}
    metodos: dict[str, set[str]] = {}
    fontes_cnpj, versoes_cnpj, fontes_cep = set(), set(), set()
    indicio_municipal = False
    codigos_oficiais_fora: set[str] = set()

    def adicionar(papel: str, codigo: str | None, metodo: str, valor: Any, fonte: str | None = None):
        if codigo:
            por_papel[papel].add(codigo)
            metodos.setdefault(codigo, set()).add(metodo)
            evidencias.append({"papel": papel, "codigo_ibge": codigo, "metodo": metodo, "valor": valor, "fonte": fonte})

    for campo in ("codigo_ibge", "codigo_municipio_ibge", "codigoIbge", "cod_ibge", "cod_municipio_ibge"):
        if item.get(campo) is not None:
            codigo = _codigo(item[campo])
            if codigo and codigo not in validos:
                codigos_oficiais_fora.add(codigo)
            adicionar("localizacao", codigo, "codigo_ibge_oficial", item[campo], "ObrasGov")
    for papel, plural, campo_nome, campo_cnpj in (
        ("executor", "executores", "organizacao_executor", "cnpj_executor"),
        ("tomador", "tomadores", "organizacao_tomador", "cnpj_tomador"),
        ("contratante", "contratantes", "organizacao_contratante", "cnpj_contratante"),
    ):
        for estrutura in item.get(plural, []) or []:
            for campo in ("codigo_ibge", "codigo_municipio_ibge", "codigoIbge", "cod_ibge"):
                codigo = _codigo(estrutura.get(campo))
                if codigo and codigo not in validos:
                    codigos_oficiais_fora.add(codigo)
                adicionar(papel, codigo, "codigo_ibge_oficial", estrutura.get(campo), "ObrasGov")
            cnpj = somente_digitos(estrutura.get(campo_cnpj))
            cadastro = mapa_cnpj.get(cnpj)
            if cadastro and cadastro.get("entidade_municipal") is True and cadastro.get("fonte") and cadastro.get("versao"):
                adicionar(papel, _codigo(cadastro.get("codigo_ibge")), "cnpj_municipal", cnpj, cadastro.get("fonte"))
                fontes_cnpj.add(str(cadastro.get("fonte", "")))
                versoes_cnpj.add(str(cadastro.get("versao", "")))
            nome = normalizar(estrutura.get(campo_nome))
            if "MUNICIPAL" in nome or nome.startswith("MUNICIPIO ") or nome.startswith("PREFEITURA "):
                indicio_municipal = True
            codigos_nome = nomes.get(nome, set())
            if len(codigos_nome) == 1:
                adicionar(papel, next(iter(codigos_nome)), "nome_municipio", nome, "catalogo_IBGE")

    cep = somente_digitos(item.get("nr_cep"))
    cadastro_cep = mapa_cep.get(cep)
    cep_validado = bool(cadastro_cep and cadastro_cep.get("generico") is False and cadastro_cep.get("fonte")
                         and cadastro_cep.get("versao") and _codigo(cadastro_cep.get("codigo_ibge")))
    if cep_validado:
        adicionar("localizacao", _codigo(cadastro_cep["codigo_ibge"]), "cep_municipal", cep, cadastro_cep.get("fonte"))
        fontes_cep.add(str(cadastro_cep.get("fonte", "")))

    codigos_pontos, ponto_ambiguo = set(), False
    if resolver_espacial is not None:
        for pin in item.get("pins", []) or []:
            try:
                latitude, longitude = float(pin.get("latitude")), float(pin.get("longitude"))
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    continue
                localizado = resolver_espacial.localizar(latitude, longitude)
            except (TypeError, ValueError):
                continue
            if not localizado:
                continue
            if localizado.get("limite") or len(localizado.get("codigos", [])) != 1:
                ponto_ambiguo = True
                evidencias.append({"papel": "localizacao", "codigo_ibge": None,
                                   "metodo": "coordenada_ambigua", "valor": {"latitude": latitude, "longitude": longitude},
                                   "fonte": getattr(resolver_espacial, "metadados", {}).get("fonte_malha")})
                continue
            codigo = str(localizado["codigos"][0])
            if _codigo(codigo):
                codigos_pontos.add(codigo)
        for codigo in codigos_pontos:
            adicionar("localizacao", codigo, "coordenada_unica", "pins", getattr(resolver_espacial, "metadados", {}).get("fonte_malha"))

    unicos_papel = {p: next(iter(c)) for p, c in por_papel.items() if len(c) == 1}
    conflito_interno = any(len(c) > 1 for c in por_papel.values())
    todos = set().union(*por_papel.values())
    multi_espacial = len(codigos_pontos) > 1
    conflito = conflito_interno or (len(todos) > 1 and not multi_espacial) or (ponto_ambiguo and bool(codigos_pontos))
    if multi_espacial:
        status, motivo = "multiterritorial", "coordenadas_em_municipios_distintos"
    elif conflito:
        status, motivo = "conflitante", "evidencias_territoriais_conflitantes"
    elif len(todos) == 1:
        unico = next(iter(todos))
        status, motivo = ("exata", None) if unico in validos else ("fora_escopo_municipal", "codigo_oficial_fora_do_recorte")
    else:
        texto = normalizar(" ".join(str(item.get(c, "")) for c in ("organizacao_resp", "desc_nome", "desc_projeto")))
        federal_estadual = any(x in texto for x in ("MINISTERIO ", "DEPARTAMENTO NACIONAL", "GOVERNO DO ESTADO", "SECRETARIA DE ESTADO"))
        fora = bool(codigos_oficiais_fora) or federal_estadual and not indicio_municipal
        status = "fora_escopo_municipal" if fora else "nao_identificada"
        motivo = "codigo_oficial_fora_do_recorte" if codigos_oficiais_fora else "entidade_federal_ou_estadual_sem_territorio_municipal" if status == "fora_escopo_municipal" else "evidencia_municipal_insuficiente"
    codigo_modelagem = next(iter(todos)) if status == "exata" and next(iter(todos)) in validos else None
    metodo = None
    if codigo_modelagem:
        metodos_codigo = metodos.get(codigo_modelagem, set())
        if "codigo_ibge_oficial" in metodos_codigo:
            metodo = "codigo_ibge_oficial"
        elif "cnpj_municipal" in metodos_codigo:
            metodo = "cnpj_municipal"
        elif unicos_papel.get("executor") == unicos_papel.get("tomador") == codigo_modelagem:
            metodo = "exato_executor_tomador"
        else:
            metodo = next((m for m in ("nome_municipio", "cep_municipal", "coordenada_unica") if m in metodos_codigo), None)
    papel = next((p for p in ("contratante", "executor", "tomador", "localizacao") if unicos_papel.get(p) == codigo_modelagem), None)
    espacial_meta = getattr(resolver_espacial, "metadados", {}) if resolver_espacial is not None else {}
    return {
        "status_atribuicao_territorial": status,
        "codigo_ibge_contratante": unicos_papel.get("contratante"),
        "codigo_ibge_executor": unicos_papel.get("executor"),
        "codigo_ibge_tomador": unicos_papel.get("tomador"),
        "codigo_ibge_localizacao": unicos_papel.get("localizacao"),
        "codigo_ibge_modelagem": codigo_modelagem,
        "papel_municipio_modelagem": papel,
        "metodo_atribuicao": metodo,
        "confianca_atribuicao": "alta" if status == "exata" else "nenhuma",
        "evidencias_atribuicao": evidencias,
        "quantidade_municipios_atribuidos": len(todos),
        "motivo_nao_atribuicao": motivo,
        "indicio_municipal_pendente": status == "nao_identificada",
        "fonte_mapeamento_cnpj": ";".join(sorted(fontes_cnpj)) or None,
        "versao_mapeamento_cnpj": ";".join(sorted(versoes_cnpj)) or None,
        "fonte_mapeamento_cep": ";".join(sorted(fontes_cep)) or None,
        "cep_validado": cep_validado,
        **{k: espacial_meta.get(k) for k in ("fonte_malha", "versao_malha", "data_download_malha", "checksum_malha")},
    }


def carregar_mapeamento_csv(caminho: Path, chave: str) -> dict[str, dict[str, Any]]:
    if not caminho.exists():
        return {}
    import csv
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    resultado: dict[str, dict[str, Any]] = {}
    duplicados: set[str] = set()
    for linha in linhas:
        valor = somente_digitos(linha.get(chave))
        if not valor or valor in resultado:
            duplicados.add(valor)
        entidade = normalizar(linha.get("entidade_municipal"))
        generico = normalizar(linha.get("generico"))
        resultado[valor] = {**linha,
                            "entidade_municipal": True if entidade in {"1", "SIM", "TRUE"} else False if entidade in {"0", "NAO", "FALSE"} else None,
                            "generico": True if generico in {"1", "SIM", "TRUE"} else False if generico in {"0", "NAO", "FALSE"} else None}
    return {k: v for k, v in resultado.items() if k not in duplicados}


class ResolvedorMalhaIBGE:
    def __init__(self, geojson: Path, metadados: Path, tolerancia: float = 1e-8):
        meta = json.loads(metadados.read_text(encoding="utf-8"))
        conteudo = geojson.read_bytes()
        checksum = hashlib.sha256(conteudo).hexdigest()
        if checksum != meta.get("checksum_malha"):
            raise ValueError("Checksum da malha IBGE inválido")
        try:
            from shapely.geometry import Point, shape
        except ImportError as exc:
            raise RuntimeError("Motor geoespacial opcional indisponível") from exc
        dados = json.loads(conteudo)
        self._Point, self._tolerancia = Point, float(tolerancia)
        self._geometrias = []
        for feature in dados.get("features", []):
            props = feature.get("properties", {})
            codigo = _codigo(props.get("CD_MUN") or props.get("CD_GEOCMU") or props.get("codigo_ibge"))
            if codigo and feature.get("geometry"):
                self._geometrias.append((codigo, shape(feature["geometry"])))
        if not self._geometrias:
            raise ValueError("Malha IBGE sem geometrias municipais válidas")
        self.metadados = {k: meta.get(k) for k in ("fonte_malha", "versao_malha", "data_download_malha", "checksum_malha")}

    def localizar(self, latitude: float, longitude: float) -> dict[str, Any] | None:
        ponto = self._Point(float(longitude), float(latitude))
        codigos, limite = [], False
        for codigo, geometria in self._geometrias:
            if geometria.boundary.distance(ponto) <= self._tolerancia:
                limite = True
            elif geometria.contains(ponto):
                codigos.append(codigo)
        return {"codigos": codigos, "limite": limite} if codigos or limite else None
