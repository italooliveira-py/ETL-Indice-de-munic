"""Primitivas de HTTP e checkpoints; sem dependência dos coletores."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import tempfile
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import RemoteDisconnected
from pathlib import Path

import requests

LOGGER = logging.getLogger("etl_risco_municipal")
TRANSITORIOS = {429, 500, 502, 503, 504}


class FalhaConsulta(RuntimeError):
    """Consulta não concluída: nunca equivale a uma resposta vazia."""

    def __init__(self, mensagem, status_code=None, resposta_corpo=None):
        super().__init__(mensagem)
        self.status_code = status_code
        self.resposta_corpo = resposta_corpo


def salvar_json_atomico(caminho: Path, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=caminho.parent,
                                         prefix=caminho.name + ".", suffix=".tmp", delete=False) as f:
            temporario = Path(f.name)
            json.dump(dados, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, caminho)
    finally:
        if temporario is not None and temporario.exists():
            temporario.unlink()


def ler_cache(caminho, validar):
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        validar(dados)
        return dados
    except (OSError, ValueError, TypeError, KeyError):
        return None


def geracao_cache(pasta, chave, refresh=False):
    """Uma atualização interrompida nunca reutiliza páginas da versão anterior."""
    identificador = hashlib.sha256(chave.encode()).hexdigest()[:24]
    marcador = pasta / "geracoes" / f"{identificador}.json"
    if refresh:
        salvar_json_atomico(marcador, {"geracao": uuid.uuid4().hex})
    try:
        geracao = json.loads(marcador.read_text(encoding="utf-8"))["geracao"]
        if not isinstance(geracao, str) or len(geracao) != 32 or any(c not in "0123456789abcdef" for c in geracao):
            raise ValueError("Marcador de geração inválido")
        return pasta / "pages" / "versoes" / identificador / geracao
    except FileNotFoundError:
        return pasta / "pages"


def retry_after(valor):
    try:
        return max(0.0, float(valor))
    except (ValueError, TypeError):
        try:
            data = parsedate_to_datetime(valor)
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            return max(0.0, (data - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0.0


def requisitar_json(sessao, url, config, params=None, fonte="", contexto="", estado=None):
    prefixo = fonte.lower() + "_" if fonte else ""
    tentativas = max(1, int(config.get(prefixo + "max_tentativas", config.get("max_tentativas", 4))))
    timeout = config.get(prefixo + "timeout_segundos", config.get("timeout_segundos", 60))
    base = max(0.0, float(config.get(prefixo + "backoff_base_segundos", 3)))
    intervalo = max(0.0, float(config.get(prefixo + "intervalo_requisicoes_segundos", 0)))
    estado = estado if estado is not None else {}
    for tentativa in range(tentativas):
        espera = max(0.0, estado.get("proxima", 0) - time.monotonic())
        if espera:
            time.sleep(espera)
        resposta = None
        try:
            LOGGER.info("%s | %s | tentativa %d/%d", fonte, contexto or params, tentativa + 1, tentativas)
            resposta = sessao.get(url, params=params, timeout=timeout)
            resposta.raise_for_status()
            if resposta.status_code == 204:
                if fonte.upper() == "PNCP":
                    return {"data": [], "totalPaginas": 0, "totalRegistros": 0}
                return {}
            if not resposta.content:
                raise FalhaConsulta("Resposta vazia sem HTTP 204")
            try:
                return resposta.json()
            except ValueError as exc:
                raise FalhaConsulta("JSON inválido") from exc
        except (requests.Timeout, requests.ConnectionError, RemoteDisconnected, requests.HTTPError) as exc:
            status = resposta.status_code if resposta is not None else None
            if status is not None and status not in TRANSITORIOS:
                corpo = resposta.text[:500].replace("\x00", "") if resposta is not None else ""
                detalhe = f" | resposta: {corpo}" if corpo else ""
                raise FalhaConsulta(
                    f"HTTP permanente {status}: {exc}{detalhe}",
                    status_code=status,
                    resposta_corpo=corpo,
                ) from exc
            atraso = max(base * 2 ** tentativa + random.uniform(0, base),
                         retry_after(resposta.headers.get("Retry-After")) if resposta is not None else 0)
            if status in {429, 503}:
                atraso = max(atraso, intervalo * 2)
            estado["proxima"] = time.monotonic() + atraso
            LOGGER.warning("%s | %s | %s | tentativa %d/%d | espera %.2fs",
                           fonte, contexto or params, status or type(exc).__name__, tentativa + 1, tentativas, atraso)
            if tentativa + 1 == tentativas:
                raise FalhaConsulta(f"Esgotadas {tentativas} tentativas: {type(exc).__name__}: {exc}") from exc
        finally:
            estado["proxima"] = max(estado.get("proxima", 0), time.monotonic() + intervalo)


def janelas_ano(ano, meses=3):
    if not 1 <= int(meses) <= 12:
        raise ValueError("janela_meses deve estar entre 1 e 12")
    inicio = date(int(ano), 1, 1)
    while inicio.year == int(ano):
        mes = inicio.month + int(meses)
        proxima = date(ano + 1, 1, 1) if mes > 12 else date(ano, mes, 1)
        yield inicio, proxima - timedelta(days=1)
        inicio = proxima


def validar_pagina(dados, campo_total="totalPaginas", pagina=None):
    if not isinstance(dados, dict) or not isinstance(dados.get("data"), list):
        raise ValueError("Resposta sem lista data")
    total = dados.get(campo_total)
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError("Total de páginas ausente ou inválido")
    if any(not isinstance(item, dict) for item in dados["data"]):
        raise ValueError("Registro inválido")
    if total == 0 and dados["data"]:
        raise ValueError("Registros com total de páginas zero")
    campo_registros = "totalRegistros" if campo_total == "totalPaginas" else "total_items"
    registros = dados.get(campo_registros)
    if registros is not None:
        if isinstance(registros, bool) or not isinstance(registros, int) or registros < len(dados["data"]):
            raise ValueError("Total de registros inválido")
        if total <= 1 and registros != len(dados["data"]):
            raise ValueError("Página única contradiz total de registros")
    if pagina is not None:
        if "numeroPagina" in dados and dados["numeroPagina"] != pagina:
            raise ValueError("API retornou outra página")
        if "page_number" in dados and dados["page_number"] != pagina:
            raise ValueError("ObrasGov retornou outra página")
        if pagina > max(1, total) or (total > 1 and not dados["data"]):
            raise ValueError("Página vazia/inconsistente com paginação")


def atualizar_manifesto(pasta, registro):
    caminho = pasta / "manifesto_coleta.json"
    try:
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(manifesto, list):
            raise ValueError("Manifesto inválido")
    except FileNotFoundError:
        manifesto = []
    # Um manifesto corrompido não é descartado silenciosamente.
    chaves = ("fonte", "escopo", "periodo", "modalidade")
    manifesto = [r for r in manifesto if any(r.get(k) != registro.get(k) for k in chaves)]
    manifesto.append({**registro, "executado_em": datetime.now(timezone.utc).isoformat()})
    salvar_json_atomico(caminho, manifesto)


def chave_compra(item):
    if item.get("numeroControlePNCP"):
        return "pncp:" + str(item["numeroControlePNCP"])
    orgao = item.get("orgaoEntidade") or {}
    campos = [orgao.get("cnpj"), item.get("anoCompra"), item.get("sequencialCompra")]
    if all(v is not None and str(v).strip() for v in campos):
        return "orgao:" + ":".join(map(str, campos))
    # Último recurso conservador: só elimina cópias exatas do JSON completo.
    return "sha256:" + hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
