"""Coleta e transformação auditável de dados eleitorais municipais do TSE."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests


class FalhaTSE(RuntimeError):
    """Falha controlada que impede confirmar a cobertura eleitoral."""


CHAVE_CANDIDATURA_TURNO = (
    "ano_eleicao_origem_ciclo", "CD_ELEICAO", "CD_TIPO_ELEICAO", "DT_ELEICAO",
    "NR_TURNO", "codigo_municipio_tse", "CD_CARGO", "SQ_CANDIDATO",
)
CHAVE_EVENTO = (
    "ano_eleicao_origem_ciclo", "CD_ELEICAO", "CD_TIPO_ELEICAO", "DT_ELEICAO",
    "codigo_municipio_tse", "CD_CARGO",
)
CARGO_PREFEITO = 11
COLUNAS_EVIDENCIA_POSSE = [
    "id_evidencia", "codigo_ibge", "cd_eleicao", "ano_eleicao_origem_ciclo", "data_posse",
    "precisao_data_posse", "tipo_fonte_oficial", "nivel_hierarquia_fonte", "orgao_publicador",
    "url_fonte_oficial", "data_publicacao_fonte", "titulo_documento", "identificador_documento",
    "data_verificacao_utc", "status_validacao", "observacao",
]


@dataclass(frozen=True)
class EspecificacaoArtefato:
    nome: str
    edicao: int
    url: str
    membro_zip: str
    sha256_oficial: str | None = None
    algoritmo_hash_oficial: str | None = None


@dataclass(frozen=True)
class ResultadoArtefato:
    caminho: Path
    metodo: str
    estado: str
    tamanho_comprimido: int
    tamanho_descomprimido: int
    crc32_zip: str
    sha256_local: str
    cache_reutilizado: bool


@dataclass
class ResultadoTSE:
    eventos: pd.DataFrame
    mandatos: pd.DataFrame
    municipio_ano: pd.DataFrame
    qualidade: pd.DataFrame
    manifesto: list[dict[str, Any]]


def _ler_json(caminho: Path) -> dict[str, Any]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FalhaTSE(f"Referência inválida: {caminho}: {exc}") from exc
    if not isinstance(dados, dict):
        raise FalhaTSE(f"Referência deve ser objeto JSON: {caminho}")
    return dados


def carregar_mapa_situacao(caminho: Path) -> dict[int, dict[str, str]]:
    return {int(ano): {str(k): str(v) for k, v in mapa.items()} for ano, mapa in _ler_json(caminho).items()}


def carregar_mapa_esquemas(caminho: Path) -> dict[str, Any]:
    return _ler_json(caminho)


def obter_esquema(mapa: dict[str, Any], conjunto: str, edicao: int) -> dict[str, Any]:
    try:
        esquema = mapa[conjunto][str(edicao)]
    except KeyError as exc:
        raise FalhaTSE(f"Sem esquema para {conjunto}/{edicao}") from exc
    obrigatorios = {"encoding", "separador", "aliases", "campos_obrigatorios", "sentinelas"}
    if not obrigatorios.issubset(esquema):
        raise FalhaTSE(f"Esquema incompleto para {conjunto}/{edicao}")
    return esquema


def normalizar_codigo_municipio_tse(df: pd.DataFrame, campo: str) -> pd.DataFrame:
    if campo not in df:
        raise FalhaTSE(f"Campo territorial ausente: {campo}")
    saida = df.copy()
    saida["codigo_municipio_tse"] = saida[campo].astype("string").str.strip()
    return saida


def validar_catalogo_tse_ibge(catalogo: pd.DataFrame, uf: str = "PB", quantidade_esperada: int = 223) -> pd.DataFrame:
    aliases = {
        "codigo_municipio_tse": ("codigo_municipio_tse", "CD_MUNICIPIO_TSE"),
        "codigo_ibge": ("codigo_ibge", "CD_MUNICIPIO_IBGE"),
        "municipio": ("municipio", "NM_MUNICIPIO_IBGE"),
        "uf": ("uf", "SG_UF"),
    }
    renomear = {}
    for destino, candidatos in aliases.items():
        origem = next((c for c in candidatos if c in catalogo), None)
        if origem is None:
            raise FalhaTSE(f"Correspondência sem campo {destino}")
        renomear[origem] = destino
    saida = catalogo.rename(columns=renomear)[list(aliases)].copy()
    for coluna in ("codigo_municipio_tse", "codigo_ibge", "municipio", "uf"):
        saida[coluna] = saida[coluna].astype("string").str.strip()
    if len(saida) != quantidade_esperada or not saida.uf.eq(uf).all():
        raise FalhaTSE(f"Correspondência {uf} exige exatamente {quantidade_esperada} municípios")
    if saida.codigo_municipio_tse.duplicated().any() or saida.codigo_ibge.duplicated().any():
        raise FalhaTSE("Correspondência TSE-IBGE contém códigos duplicados")
    if not saida.codigo_ibge.str.fullmatch(r"\d{7}").all():
        raise FalhaTSE("Código IBGE deve ter sete dígitos")
    return saida.reset_index(drop=True)


def _salvar_bytes_atomico(caminho: Path, conteudo: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix=caminho.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def validar_checkpoint_artefato(caminho: Path, metadados: dict[str, Any]) -> bool:
    if not caminho.is_file() or metadados.get("estado") != "completa":
        return False
    digest = hashlib.sha256(caminho.read_bytes()).hexdigest()
    return digest == metadados.get("sha256_local") and caminho.stat().st_size == metadados.get("tamanho_descomprimido")


class _ArquivoHTTPRange(io.RawIOBase):
    def __init__(self, sessao, url: str, timeout: float):
        self.sessao, self.url, self.timeout, self.posicao = sessao, url, timeout, 0
        resposta = sessao.get(url, headers={"Range": "bytes=0-0"}, timeout=timeout)
        if resposta.status_code != 206:
            raise FalhaTSE("Servidor não confirmou HTTP Range")
        correspondencia = re.fullmatch(r"bytes 0-0/(\d+)", resposta.headers.get("Content-Range", ""))
        if not correspondencia or len(resposta.content) != 1:
            raise FalhaTSE("Content-Range inicial inconsistente")
        self.tamanho = int(correspondencia.group(1))
        self.etag = resposta.headers.get("ETag")

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.posicao
    def seek(self, offset, whence=io.SEEK_SET):
        destino = offset if whence == io.SEEK_SET else self.posicao + offset if whence == io.SEEK_CUR else self.tamanho + offset
        if destino < 0:
            raise ValueError("seek negativo")
        self.posicao = destino
        return destino

    def read(self, size=-1):
        if self.posicao >= self.tamanho or size == 0:
            return b""
        fim = self.tamanho - 1 if size is None or size < 0 else min(self.tamanho - 1, self.posicao + size - 1)
        inicio = self.posicao
        resposta = self.sessao.get(self.url, headers={"Range": f"bytes={inicio}-{fim}"}, timeout=self.timeout)
        esperado = f"bytes {inicio}-{fim}/{self.tamanho}"
        if resposta.status_code != 206 or resposta.headers.get("Content-Range") != esperado:
            raise FalhaTSE("Resposta HTTP Range inconsistente")
        if self.etag and resposta.headers.get("ETag") not in (None, self.etag):
            raise FalhaTSE("Artefato remoto mudou durante a leitura")
        if len(resposta.content) != fim - inicio + 1:
            raise FalhaTSE("Tamanho HTTP Range divergente")
        self.posicao = fim + 1
        return resposta.content


def _extrair_membro(arquivo_zip, membro: str) -> tuple[bytes, zipfile.ZipInfo]:
    with zipfile.ZipFile(arquivo_zip) as pacote:
        try:
            info = pacote.getinfo(membro)
        except KeyError as exc:
            raise FalhaTSE(f"Membro ausente no ZIP: {membro}") from exc
        conteudo = pacote.read(info)  # zipfile valida CRC durante a leitura
    if len(conteudo) != info.file_size:
        raise FalhaTSE("Tamanho descomprimido divergente")
    return conteudo, info


def coletar_membro_zip_tse(sessao, especificacao: EspecificacaoArtefato, destino: Path,
                           config: dict[str, Any]) -> ResultadoArtefato:
    meta_path = destino.with_suffix(destino.suffix + ".meta.json")
    metadados = {}
    if meta_path.exists():
        try:
            metadados = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadados = {}
    if validar_checkpoint_artefato(destino, metadados):
        return ResultadoArtefato(destino, metadados["metodo"], "completa",
                                 metadados["tamanho_comprimido"], metadados["tamanho_descomprimido"],
                                 metadados["crc32_zip"], metadados["sha256_local"], True)
    timeout = float(config.get("tse_eleitoral_timeout_segundos", 60))
    metodo = "http_range"
    try:
        remoto = _ArquivoHTTPRange(sessao, especificacao.url, timeout)
        conteudo, info = _extrair_membro(remoto, especificacao.membro_zip)
    except (Exception,):
        metodo = "zip_integral"
        try:
            resposta = sessao.get(especificacao.url, timeout=timeout)
            resposta.raise_for_status()
            conteudo, info = _extrair_membro(io.BytesIO(resposta.content), especificacao.membro_zip)
        except Exception as exc:
            raise FalhaTSE(f"Falha no Range e no ZIP integral: {exc}") from exc
    sha_local = hashlib.sha256(conteudo).hexdigest()
    if especificacao.sha256_oficial:
        algoritmo = (especificacao.algoritmo_hash_oficial or "sha256").lower()
        if algoritmo != "sha256" or sha_local.lower() != especificacao.sha256_oficial.lower():
            raise FalhaTSE("Hash oficial divergente")
    _salvar_bytes_atomico(destino, conteudo)
    metadados = {
        **asdict(especificacao), "caminho": str(destino), "metodo": metodo, "estado": "completa",
        "tamanho_comprimido": info.compress_size, "tamanho_descomprimido": info.file_size,
        "crc32_zip": f"{info.CRC:08x}", "sha256_local": sha_local,
        "executado_em": datetime.now(timezone.utc).isoformat(),
    }
    _salvar_bytes_atomico(meta_path, json.dumps(metadados, ensure_ascii=False, indent=2).encode("utf-8"))
    return ResultadoArtefato(destino, metodo, "completa", info.compress_size, info.file_size,
                             f"{info.CRC:08x}", sha_local, False)


def ler_csv_tse(caminho: Path, conjunto: str, edicao: int,
                mapa_esquemas: dict[str, Any]) -> pd.DataFrame:
    esquema = obter_esquema(mapa_esquemas, conjunto, edicao)
    try:
        df = pd.read_csv(caminho, sep=esquema["separador"], encoding=esquema["encoding"], dtype=str)
    except Exception as exc:
        raise FalhaTSE(f"CSV TSE inválido {conjunto}/{edicao}: {exc}") from exc
    ausentes = [c for c in esquema["campos_obrigatorios"] if c not in df]
    if ausentes:
        raise FalhaTSE(f"Campos obrigatórios ausentes em {conjunto}/{edicao}: {ausentes}")
    opcionais = set(esquema.get("campos_opcionais", []))
    preservar = set(esquema.get("preservar_metadados", []))
    renomear = {}
    for canonico, aliases in esquema["aliases"].items():
        origem = next((a for a in aliases if a in df), None)
        if origem is None:
            if canonico not in opcionais:
                raise FalhaTSE(f"Alias ausente para {canonico} em {conjunto}/{edicao}")
            df[canonico] = pd.NA
            if canonico in preservar:
                df[f"{canonico}_ORIGINAL"] = pd.NA
                df[f"{canonico}_METODO"] = "indisponivel"
                df[f"{canonico}_ESQUEMA_EDICAO"] = str(edicao)
                df[f"{canonico}_REGRA"] = "denominador_nao_publicado"
                df[f"{canonico}_STATUS"] = "indisponivel_denominador"
            continue
        if canonico in preservar:
            df[f"{canonico}_ORIGINAL"] = df[origem]
            df[f"{canonico}_METODO"] = "campo_oficial_direto" if origem == canonico else "alias_versionado"
            df[f"{canonico}_ESQUEMA_EDICAO"] = str(edicao)
            df[f"{canonico}_REGRA"] = "campo_oficial_direto" if origem == canonico else "alias_versionado_sem_derivacao"
            df[f"{canonico}_STATUS"] = "disponivel"
        renomear[origem] = canonico
    df = df.rename(columns=renomear)
    for campo, valores in esquema["sentinelas"].items():
        campo_final = renomear.get(campo, campo)
        if campo_final in df:
            df[campo_final] = df[campo_final].replace(valores, pd.NA)
    return df


def _normalizar_eleitoral(df: pd.DataFrame) -> pd.DataFrame:
    saida = df.copy()
    campo = "codigo_municipio_tse" if "codigo_municipio_tse" in saida else (
        "SG_UE" if "SG_UE" in saida else "CD_MUNICIPIO"
    )
    saida = normalizar_codigo_municipio_tse(saida, campo)
    for coluna in CHAVE_CANDIDATURA_TURNO:
        if coluna in saida:
            saida[coluna] = saida[coluna].astype("string").str.strip()
    return saida


def normalizar_candidaturas(df: pd.DataFrame, edicao: int) -> pd.DataFrame:
    saida = _normalizar_eleitoral(df)
    saida["ano_eleicao_origem_ciclo"] = str(edicao)
    return saida


def normalizar_votos(df: pd.DataFrame, edicao: int) -> pd.DataFrame:
    saida = _normalizar_eleitoral(df)
    saida["ano_eleicao_origem_ciclo"] = str(edicao)
    return saida


def normalizar_detalhes(df: pd.DataFrame, edicao: int) -> pd.DataFrame:
    saida = _normalizar_eleitoral(df)
    saida["ano_eleicao_origem_ciclo"] = str(edicao)
    return saida


def selecionar_municipios_smoke(catalogo: pd.DataFrame, candidaturas: pd.DataFrame) -> list[str]:
    """Seleciona João Pessoa e um município sem segundo turno para o smoke TSE."""
    territorial = validar_catalogo_tse_ibge(catalogo, quantidade_esperada=223)
    normalizados = territorial["municipio"].map(
        lambda valor: "".join(
            caractere for caractere in unicodedata.normalize("NFKD", str(valor).upper())
            if not unicodedata.combining(caractere)
        )
    )
    joao_pessoa = territorial.loc[normalizados.eq("JOAO PESSOA")]
    if len(joao_pessoa) != 1:
        raise FalhaTSE("Smoke TSE exige João Pessoa no catálogo oficial")
    prefeito = candidaturas[
        candidaturas["CD_CARGO"].astype(str).eq(str(CARGO_PREFEITO))
        & candidaturas["ano_eleicao_origem_ciclo"].astype(str).eq("2020")
    ]
    sem_segundo_turno = []
    for codigo, grupo in prefeito.groupby("codigo_municipio_tse", sort=False):
        if not grupo["NR_TURNO"].astype(str).eq("2").any():
            sem_segundo_turno.append(str(codigo))
    codigo_joao_pessoa = str(joao_pessoa.iloc[0].codigo_municipio_tse)
    candidatos = territorial[
        territorial.codigo_municipio_tse.astype(str).isin(sem_segundo_turno)
        & territorial.codigo_municipio_tse.astype(str).ne(codigo_joao_pessoa)
    ]
    if candidatos.empty:
        raise FalhaTSE("Smoke TSE não encontrou município PB sem segundo turno")
    return [str(joao_pessoa.iloc[0].codigo_ibge), str(candidatos.iloc[0].codigo_ibge)]


def resolver_vencedor(grupo: pd.DataFrame, mapa_edicao: dict[str, str]):
    codigos_vencedores = {str(c) for c, estado in mapa_edicao.items() if estado == "eleito"}
    candidatos = grupo[grupo["CD_SIT_TOT_TURNO"].astype(str).isin(codigos_vencedores)]
    if len(candidatos) != 1:
        return None, "pendente_codigo_totalizacao"
    vencedor = candidatos.iloc[0]
    descricao = str(vencedor.get("DS_SIT_TOT_TURNO", "")).upper()
    if "NÃO ELEITO" in descricao or "NAO ELEITO" in descricao:
        return None, "pendente_contradicao_totalizacao"
    return vencedor, "validado"


def definir_disponibilidade(data_pleito: date, data_oficial: date | None):
    if data_oficial is not None:
        return data_oficial, "dia_oficial", "data_oficial_totalizacao"
    return date(data_pleito.year + 1, 1, 1), "ano_regra_conservadora", "primeiro_dia_ano_seguinte"


def _data_tse(valor: Any) -> date:
    data_pd = pd.to_datetime(valor, dayfirst=True, errors="coerce")
    if pd.isna(data_pd):
        raise FalhaTSE(f"Data eleitoral inválida: {valor}")
    return data_pd.date()


def construir_eventos_eleitorais(candidaturas: pd.DataFrame, votos: pd.DataFrame,
                                  detalhes: pd.DataFrame, correspondencia: pd.DataFrame,
                                  suplementares: pd.DataFrame,
                                  mapa_situacao: dict[int, dict[str, str]]) -> pd.DataFrame:
    catalogo = validar_catalogo_tse_ibge(correspondencia)
    mapa_territorial = catalogo.set_index("codigo_municipio_tse").to_dict("index")
    candidatos = candidaturas.copy()
    candidatos = candidatos[candidatos["CD_CARGO"].astype(str).eq(str(CARGO_PREFEITO))].copy()
    votos_n = votos.copy()
    for quadro in (candidatos, votos_n, detalhes):
        for coluna in ("codigo_municipio_tse", "CD_ELEICAO", "NR_TURNO", "SQ_CANDIDATO"):
            if coluna in quadro:
                quadro[coluna] = quadro[coluna].astype("string").str.strip()
    chaves_voto = [c for c in CHAVE_CANDIDATURA_TURNO if c in votos_n]
    votos_n["votos"] = pd.to_numeric(votos_n["QT_VOTOS_NOMINAIS"], errors="coerce")
    votos_agregados = votos_n.groupby(chaves_voto, dropna=False, as_index=False).votos.sum(min_count=1)
    chaves_merge = [c for c in CHAVE_CANDIDATURA_TURNO if c in candidatos and c in votos_agregados]
    candidatos = candidatos.merge(votos_agregados, on=chaves_merge, how="left", validate="one_to_one")

    detalhe = detalhes.copy()
    numericas = ["QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_VALIDOS"]
    for coluna in numericas:
        if coluna not in detalhe:
            detalhe[coluna] = pd.NA
        detalhe[coluna] = pd.to_numeric(detalhe[coluna], errors="coerce")
    metadados_denominador = [
        "QT_VOTOS_VALIDOS_ORIGINAL", "QT_VOTOS_VALIDOS_METODO", "QT_VOTOS_VALIDOS_ESQUEMA_EDICAO",
        "QT_VOTOS_VALIDOS_REGRA", "QT_VOTOS_VALIDOS_STATUS",
    ]
    for coluna in metadados_denominador:
        if coluna not in detalhe:
            detalhe[coluna] = pd.NA
    detalhe["QT_VOTOS_VALIDOS_ORIGINAL"] = pd.to_numeric(detalhe["QT_VOTOS_VALIDOS_ORIGINAL"], errors="coerce")
    chaves_detalhe = [c for c in (*CHAVE_EVENTO, "NR_TURNO", "NR_ZONA") if c in detalhe]
    detalhe_zona = detalhe.groupby(chaves_detalhe, dropna=False, as_index=False)[numericas + metadados_denominador].agg(
        {**{coluna: "first" for coluna in numericas + metadados_denominador}}
    )
    chaves_turno = [c for c in (*CHAVE_EVENTO, "NR_TURNO") if c in detalhe_zona]
    agrupado_turno = detalhe_zona.groupby(chaves_turno, dropna=False, as_index=False)
    detalhe_turno = agrupado_turno[numericas + ["QT_VOTOS_VALIDOS_ORIGINAL"]].sum(min_count=1)
    metadados_turno = agrupado_turno[[coluna for coluna in metadados_denominador if coluna != "QT_VOTOS_VALIDOS_ORIGINAL"]].first()
    detalhe_turno = detalhe_turno.merge(metadados_turno, on=chaves_turno, how="left", validate="one_to_one")

    linhas = []
    for chave, grupo in candidatos.groupby(list(CHAVE_EVENTO), dropna=False):
        dados_chave = dict(zip(CHAVE_EVENTO, chave if isinstance(chave, tuple) else (chave,)))
        ano_ciclo = int(dados_chave["ano_eleicao_origem_ciclo"])
        vencedor, status = resolver_vencedor(grupo, mapa_situacao.get(ano_ciclo, {}))
        codigo_tse = str(dados_chave["codigo_municipio_tse"])
        territorio = mapa_territorial.get(codigo_tse)
        if territorio is None:
            continue
        turno = str(vencedor["NR_TURNO"]) if vencedor is not None else None
        turnos_apuracao = sorted({str(valor) for valor in grupo["NR_TURNO"].dropna()})
        turno_apuracao = turno or (turnos_apuracao[-1] if len(turnos_apuracao) == 1 else None)
        detalhe_evento = detalhe_turno
        for coluna in ("CD_ELEICAO", "codigo_municipio_tse", "CD_CARGO", "NR_TURNO"):
            if coluna in detalhe_evento and coluna in dados_chave | {"NR_TURNO": turno}:
                valor = turno_apuracao if coluna == "NR_TURNO" else str(dados_chave[coluna])
                detalhe_evento = detalhe_evento[detalhe_evento[coluna].astype(str) == valor]
        totais = detalhe_evento.iloc[0] if len(detalhe_evento) == 1 else pd.Series(dtype=object)
        aptos, comp, abst, validos = (totais.get(c) for c in numericas)
        status_denominador_origem = totais.get("QT_VOTOS_VALIDOS_STATUS")
        if pd.isna(status_denominador_origem):
            status_denominador_origem = "disponivel" if pd.notna(validos) else "indisponivel_denominador"
        status_denominador = "validado" if pd.notna(validos) else "ausente"
        cobertura_comparecimento = "validada" if pd.notna(aptos) and aptos == comp + abst else "pendente_divergencia_totais"
        if cobertura_comparecimento != "validada":
            aptos = comp = abst = None
        votos_ordenados = grupo.loc[grupo.NR_TURNO.astype(str) == turno, "votos"].dropna().sort_values(ascending=False)
        votos_vencedor = float(vencedor.get("votos")) if vencedor is not None and pd.notna(vencedor.get("votos")) else None
        percentual = votos_vencedor / validos * 100 if votos_vencedor is not None and pd.notna(validos) and validos else None
        margem = ((votos_ordenados.iloc[0] - votos_ordenados.iloc[1]) / validos * 100
                  if len(votos_ordenados) > 1 and pd.notna(validos) and validos else None)
        data_pleito = _data_tse(dados_chave["DT_ELEICAO"])
        data_disp, precisao, regra = definir_disponibilidade(data_pleito, None)
        linhas.append({
            **dados_chave, **territorio, "numero_turno_decisivo": turno, "numero_turno_apuracao": turno_apuracao,
            "origem_evento": "suplementar" if str(dados_chave["CD_TIPO_ELEICAO"]) == "1" else "regular",
            "partido_vencedor": vencedor.get("SG_PARTIDO") if vencedor is not None else None,
            "CD_SIT_TOT_TURNO": vencedor.get("CD_SIT_TOT_TURNO") if vencedor is not None else None,
            "DS_SIT_TOT_TURNO": vencedor.get("DS_SIT_TOT_TURNO") if vencedor is not None else None,
            "status_resultado": status, "votos_vencedor": votos_vencedor,
            "percentual_vencedor": percentual, "margem_pontos_percentuais": margem,
            "valor_votos_validos_original": totais.get("QT_VOTOS_VALIDOS_ORIGINAL"),
            "valor_votos_validos_normalizado": validos,
            "metodo_denominador_votos_validos": totais.get("QT_VOTOS_VALIDOS_METODO"),
            "edicao_esquema_denominador_votos_validos": totais.get("QT_VOTOS_VALIDOS_ESQUEMA_EDICAO"),
            "regra_denominador_votos_validos": totais.get("QT_VOTOS_VALIDOS_REGRA"),
            "status_qualidade": "validada" if status_denominador == "validado" else "pendente_denominador_votos_validos",
            "status_detalhe_apuracao": "validado" if cobertura_comparecimento == "validada" else "pendente_divergencia_totais",
            "status_denominador": status_denominador,
            "status_vencedor": "validado" if vencedor is not None else "sem_eleito_no_turno",
            "status_evento": "turno_decisivo" if vencedor is not None else "turno_nao_decisivo",
            "qt_aptos": aptos, "qt_comparecimento": comp, "qt_abstencoes": abst,
            "taxa_comparecimento": comp / aptos * 100 if comp is not None and aptos else None,
            "taxa_abstencao": abst / aptos * 100 if abst is not None and aptos else None,
            "status_comparecimento": cobertura_comparecimento,
            "data_disponibilidade_adotada": data_disp.isoformat(),
            "precisao_data_disponibilidade": precisao, "regra_data_disponibilidade": regra,
        })
    return pd.DataFrame(linhas)


def _url_oficial(valor: Any) -> bool:
    try:
        parsed = urlparse(str(valor))
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(host.endswith(s) for s in (".gov.br", ".jus.br", ".leg.br"))
    except ValueError:
        return False


def classificar_fonte_posse(linha) -> int | None:
    try:
        nivel = int(linha.get("nivel_hierarquia_fonte"))
    except (TypeError, ValueError):
        return None
    return nivel if nivel in {1, 2, 3, 4} else None


def validar_evidencia_posse(linha) -> dict[str, Any]:
    registro = dict(linha)
    data_posse = pd.to_datetime(registro.get("data_posse"), errors="coerce")
    valida = (
        registro.get("status_validacao") == "validada"
        and registro.get("precisao_data_posse") == "dia_oficial"
        and pd.notna(data_posse)
        and classificar_fonte_posse(registro) is not None
        and bool(str(registro.get("orgao_publicador", "")).strip())
        and _url_oficial(registro.get("url_fonte_oficial"))
    )
    registro["status_validacao"] = "validada" if valida else "pendente"
    return registro


def ler_evidencias_posse(caminho: Path) -> pd.DataFrame:
    if not caminho.exists():
        return pd.DataFrame(columns=COLUNAS_EVIDENCIA_POSSE)
    df = pd.read_csv(caminho, dtype=str, keep_default_na=False)
    ausentes = [c for c in COLUNAS_EVIDENCIA_POSSE if c not in df]
    if ausentes:
        raise FalhaTSE(f"Evidências de posse sem campos: {ausentes}")
    if df.id_evidencia.duplicated().any() or df.duplicated(["codigo_ibge", "cd_eleicao", "ano_eleicao_origem_ciclo"]).any():
        raise FalhaTSE("Evidências de posse duplicadas")
    return pd.DataFrame([validar_evidencia_posse(r) for r in df.to_dict("records")], columns=COLUNAS_EVIDENCIA_POSSE)


def construir_mandatos_municipais(eventos: pd.DataFrame, evidencias_posse: pd.DataFrame) -> pd.DataFrame:
    colunas = ["codigo_ibge", "ano_eleicao_origem_ciclo", "cd_eleicao_origem",
               "partido_prefeito_no_pleito_origem", "origem_gestao", "data_inicio_vigencia",
               "data_fim_vigencia", "precisao_inicio_vigencia", "fonte_oficial_transicao",
               "status_transicao", "motivo_pendencia", "cd_cargo_origem", "numero_turno_origem"]
    linhas = []
    status_vencedor = eventos.get("status_vencedor", pd.Series(index=eventos.index, dtype=str))
    status_evento = eventos.get("status_evento", pd.Series(index=eventos.index, dtype=str))
    eventos_validos = eventos[status_vencedor.eq("validado") & status_evento.eq("turno_decisivo")]
    if "CD_CARGO" in eventos_validos:
        eventos_validos = eventos_validos[eventos_validos.CD_CARGO.astype(str).eq(str(CARGO_PREFEITO))]
    if "partido_vencedor" in eventos_validos:
        eventos_validos = eventos_validos[eventos_validos.partido_vencedor.notna()]
    regulares = eventos_validos[eventos_validos.origem_evento.eq("regular")].copy()
    grupo_mandato = ["codigo_ibge", "ano_eleicao_origem_ciclo"]
    if "CD_TIPO_ELEICAO" in regulares:
        grupo_mandato.append("CD_TIPO_ELEICAO")
    for _, grupo in regulares.groupby(grupo_mandato, dropna=False, sort=False):
        turnos = pd.to_numeric(grupo.get("numero_turno_decisivo", pd.Series(0, index=grupo.index)), errors="coerce").fillna(0)
        turno_maximo = turnos.max()
        candidatos_turno = grupo.loc[turnos.eq(turno_maximo)]
        if len(candidatos_turno) != 1:
            raise FalhaTSE("Conflito: mais de um prefeito eleito no turno decisivo")
        evento = candidatos_turno.iloc[0].to_dict()
        ciclo = int(evento["ano_eleicao_origem_ciclo"])
        linhas.append({
            "codigo_ibge": str(evento["codigo_ibge"]), "ano_eleicao_origem_ciclo": ciclo,
            "cd_eleicao_origem": str(evento["CD_ELEICAO"]),
            "partido_prefeito_no_pleito_origem": evento.get("partido_vencedor"), "origem_gestao": "regular",
            "data_inicio_vigencia": date(ciclo + 1, 1, 1).isoformat(),
            "data_fim_vigencia": date(ciclo + 4, 12, 31).isoformat(), "precisao_inicio_vigencia": "dia_oficial",
            "fonte_oficial_transicao": None, "status_transicao": "validada", "motivo_pendencia": None,
            "cd_cargo_origem": CARGO_PREFEITO, "numero_turno_origem": evento.get("numero_turno_decisivo"),
        })
    evidencias = pd.DataFrame([validar_evidencia_posse(r) for r in evidencias_posse.to_dict("records")]) if len(evidencias_posse) else pd.DataFrame()
    suplementos = eventos_validos[eventos_validos.origem_evento.eq("suplementar")]
    for evento in suplementos.to_dict("records"):
        if evidencias.empty:
            continue
        filtro = (
            evidencias.codigo_ibge.astype(str).eq(str(evento["codigo_ibge"]))
            & evidencias.cd_eleicao.astype(str).eq(str(evento["CD_ELEICAO"]))
            & evidencias.ano_eleicao_origem_ciclo.astype(str).eq(str(evento["ano_eleicao_origem_ciclo"]))
            & evidencias.status_validacao.eq("validada")
        )
        candidatas = evidencias[filtro].sort_values("nivel_hierarquia_fonte")
        if candidatas.empty:
            continue
        evidencia = candidatas.iloc[0]
        inicio = pd.to_datetime(evidencia.data_posse).date()
        codigo, ciclo = str(evento["codigo_ibge"]), int(evento["ano_eleicao_origem_ciclo"])
        for mandato in reversed(linhas):
            if mandato["codigo_ibge"] == codigo and mandato["ano_eleicao_origem_ciclo"] == ciclo:
                mandato["data_fim_vigencia"] = (inicio - timedelta(days=1)).isoformat()
                break
        linhas.append({
            "codigo_ibge": codigo, "ano_eleicao_origem_ciclo": ciclo,
            "cd_eleicao_origem": str(evento["CD_ELEICAO"]),
            "partido_prefeito_no_pleito_origem": evento.get("partido_vencedor"), "origem_gestao": "suplementar",
            "data_inicio_vigencia": inicio.isoformat(), "data_fim_vigencia": date(ciclo + 4, 12, 31).isoformat(),
            "precisao_inicio_vigencia": "dia_oficial", "fonte_oficial_transicao": evidencia.url_fonte_oficial,
            "status_transicao": "validada", "motivo_pendencia": None,
            "cd_cargo_origem": CARGO_PREFEITO, "numero_turno_origem": evento.get("numero_turno_decisivo"),
        })
    resultado = pd.DataFrame(linhas, columns=colunas).sort_values(["codigo_ibge", "data_inicio_vigencia"]).reset_index(drop=True)
    if resultado.empty:
        return resultado
    chave = ["codigo_ibge", "ano_eleicao_origem_ciclo", "cd_eleicao_origem", "origem_gestao"]
    if resultado.duplicated(chave).any():
        raise FalhaTSE("Chave de mandato duplicada")
    inicio = pd.to_datetime(resultado["data_inicio_vigencia"], errors="coerce")
    fim = pd.to_datetime(resultado["data_fim_vigencia"], errors="coerce")
    if (inicio > fim).any():
        raise FalhaTSE("Mandato com data inicial posterior à final")
    ordenado = resultado.assign(_inicio=inicio, _fim=fim).sort_values(["codigo_ibge", "_inicio"])
    for _, grupo in ordenado.groupby("codigo_ibge"):
        if (grupo["_inicio"].iloc[1:].to_numpy() <= grupo["_fim"].iloc[:-1].to_numpy()).any():
            raise FalhaTSE("Sobreposição de mandatos para o município")
    return resultado


def construir_municipio_ano_politico(catalogo: pd.DataFrame, eventos: pd.DataFrame,
                                     mandatos: pd.DataFrame, ano_inicial: int = 2020,
                                     ano_final: int = 2024) -> pd.DataFrame:
    territorial = validar_catalogo_tse_ibge(catalogo)
    linhas = []
    eventos_n = eventos.copy()
    if len(eventos_n):
        eventos_n["_disponibilidade"] = pd.to_datetime(eventos_n["data_disponibilidade_adotada"], errors="coerce")
        eventos_n["_data_pleito"] = pd.to_datetime(eventos_n["DT_ELEICAO"], dayfirst=True, errors="coerce")
    mandatos_n = mandatos.copy()
    if len(mandatos_n):
        mandatos_n["_inicio"] = pd.to_datetime(mandatos_n["data_inicio_vigencia"], errors="coerce")
        mandatos_n["_fim"] = pd.to_datetime(mandatos_n["data_fim_vigencia"], errors="coerce")
    mandatos_por_codigo = {
        str(codigo): grupo.to_dict("records")
        for codigo, grupo in mandatos_n.groupby(mandatos_n["codigo_ibge"].astype(str), sort=False)
    } if len(mandatos_n) else {}
    eventos_por_codigo = {
        str(codigo): grupo.to_dict("records")
        for codigo, grupo in eventos_n.groupby(eventos_n["codigo_ibge"].astype(str), sort=False)
    } if len(eventos_n) else {}
    for municipio in territorial.to_dict("records"):
        codigo = municipio["codigo_ibge"]
        mandatos_m = mandatos_por_codigo.get(codigo, [])
        eventos_m = eventos_por_codigo.get(codigo, [])
        for ano in range(ano_inicial, ano_final + 1):
            corte = pd.Timestamp(ano, 1, 1)
            vigente = [linha for linha in mandatos_m if linha["_inicio"] <= corte and linha["_fim"] >= corte]
            mandato = max(vigente, key=lambda linha: linha["_inicio"]) if vigente else None
            continuidade = pd.NA
            if mandato is not None and ano > ano_inicial and mandato.get("status_transicao") == "validada":
                disponiveis = [linha for linha in eventos_m
                               if linha["_disponibilidade"] <= corte
                               and str(linha.get("CD_ELEICAO")) == str(mandato.get("cd_eleicao_origem"))
                               and str(linha.get("ano_eleicao_origem_ciclo")) == str(mandato.get("ano_eleicao_origem_ciclo"))
                               and linha.get("origem_evento") == mandato.get("origem_gestao")
                               and linha.get("status_vencedor") == "validado"
                               and linha.get("status_evento") == "turno_decisivo"
                               and pd.notna(linha.get("partido_vencedor"))]
                if disponiveis:
                    pleito = max(disponiveis, key=lambda linha: (linha["_disponibilidade"], linha["_data_pleito"]))
                    anteriores = [linha for linha in mandatos_m
                                  if linha["_fim"] < mandato["_inicio"]]
                    if anteriores:
                        anterior = max(anteriores, key=lambda linha: linha["_inicio"])
                        partido_anterior = anterior.get("partido_prefeito_no_pleito_origem")
                        if pd.notna(partido_anterior):
                            continuidade = str(partido_anterior) == str(pleito["partido_vencedor"])
            linha = {"codigo_ibge": codigo, "municipio": municipio["municipio"], "uf": municipio["uf"],
                     "ano_fotografia": ano, "continuidade_partidaria_pleito": continuidade}
            if mandato is not None:
                inicio = mandato["_inicio"].date()
                linha.update({
                    "ano_eleicao_origem_ciclo": int(mandato["ano_eleicao_origem_ciclo"]),
                    "numero_ano_ciclo_eleitoral": ano - int(mandato["ano_eleicao_origem_ciclo"]),
                    "numero_ano_gestao_atual": ano - inicio.year + 1 if mandato.get("precisao_inicio_vigencia") == "dia_oficial" else pd.NA,
                    "partido_prefeito_no_pleito_origem": mandato.get("partido_prefeito_no_pleito_origem"),
                    "origem_gestao": mandato.get("origem_gestao"),
                    "status_transicao": mandato.get("status_transicao"),
                })
            linhas.append(linha)
    resultado = pd.DataFrame(linhas)
    if resultado.duplicated(["codigo_ibge", "ano_fotografia"]).any():
        raise FalhaTSE("Fotografia contém chaves duplicadas")
    esperado = len(territorial) * (ano_final - ano_inicial + 1)
    if len(resultado) != esperado:
        raise FalhaTSE("Cardinalidade da fotografia divergente")
    return resultado


def adaptar_municipio_ano_para_base(municipio_ano: pd.DataFrame) -> pd.DataFrame:
    saida = municipio_ano.copy()
    if saida.duplicated(["codigo_ibge", "ano_fotografia"]).any():
        raise FalhaTSE("Fotografia duplicada antes da integração")
    saida["ano"] = pd.to_numeric(saida["ano_fotografia"], errors="raise").astype(int)
    return saida


REFERENCE_DIR = Path(__file__).resolve().parents[3] / "data" / "reference" / "tse_eleitoral"


def _especificacoes_tse(edicoes=(2016, 2020, 2024)):
    base = "https://cdn.tse.jus.br/estatistica/sead/odsele"
    specs = [EspecificacaoArtefato("municipio_tse_ibge", 2024,
             f"{base}/municipio_tse_ibge/municipio_tse_ibge.zip", "municipio_tse_ibge.csv")]
    for ano in edicoes:
        specs.extend([
            EspecificacaoArtefato("consulta_cand", ano, f"{base}/consulta_cand/consulta_cand_{ano}.zip", f"consulta_cand_{ano}_PB.csv"),
            EspecificacaoArtefato("votacao_candidato_munzona", ano, f"{base}/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip", f"votacao_candidato_munzona_{ano}_PB.csv"),
            EspecificacaoArtefato("detalhe_votacao_munzona", ano, f"{base}/detalhe_votacao_munzona/detalhe_votacao_munzona_{ano}.zip", f"detalhe_votacao_munzona_{ano}_PB.csv"),
        ])
    return specs


def carregar_quadros_tse(sessao, config: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
    edicoes = tuple(int(a) for a in config.get("tse_eleitoral_edicoes", [2016, 2020, 2024]))
    mapa_esquemas = carregar_mapa_esquemas(REFERENCE_DIR / "esquemas_tse.json")
    mapa_situacao = carregar_mapa_situacao(REFERENCE_DIR / "situacao_totalizacao.json")
    coletados, manifesto = {}, []
    for spec in _especificacoes_tse(edicoes):
        destino = raw_dir / spec.nome / str(spec.edicao) / spec.membro_zip
        resultado = coletar_membro_zip_tse(sessao, spec, destino, config)
        coletados[(spec.nome, spec.edicao)] = resultado.caminho
        manifesto.append({"fonte": "TSE", "conjunto": spec.nome, "edicao": spec.edicao,
                           "url": spec.url, "membro": spec.membro_zip, "metodo": resultado.metodo,
                           "estado": "cache_reutilizado" if resultado.cache_reutilizado else resultado.estado,
                           "sha256_local": resultado.sha256_local, "crc32_zip": resultado.crc32_zip})
    catalogo_bruto = ler_csv_tse(coletados[("municipio_tse_ibge", 2024)], "municipio_tse_ibge", 2024, mapa_esquemas)
    catalogo_bruto = catalogo_bruto[catalogo_bruto.SG_UF.eq(config.get("tse_eleitoral_uf", "PB"))]
    candidaturas, votos, detalhes = [], [], []
    for ano in edicoes:
        candidaturas.append(normalizar_candidaturas(ler_csv_tse(coletados[("consulta_cand", ano)], "consulta_cand", ano, mapa_esquemas), ano))
        votos.append(normalizar_votos(ler_csv_tse(coletados[("votacao_candidato_munzona", ano)], "votacao_candidato_munzona", ano, mapa_esquemas), ano))
        detalhes.append(normalizar_detalhes(ler_csv_tse(coletados[("detalhe_votacao_munzona", ano)], "detalhe_votacao_munzona", ano, mapa_esquemas), ano))
    candidaturas_n = pd.concat(candidaturas, ignore_index=True)
    smoke_municipios = selecionar_municipios_smoke(validar_catalogo_tse_ibge(catalogo_bruto), candidaturas_n) if config.get("_smoke_test") else None
    eventos = construir_eventos_eleitorais(pd.concat(candidaturas, ignore_index=True), pd.concat(votos, ignore_index=True),
                                            pd.concat(detalhes, ignore_index=True), catalogo_bruto, pd.DataFrame(), mapa_situacao)
    evidencias = ler_evidencias_posse(REFERENCE_DIR / "evidencias_posse.csv")
    mandatos = construir_mandatos_municipais(eventos, evidencias)
    por_cargo = candidaturas_n.groupby(candidaturas_n["CD_CARGO"].astype(str), dropna=False).size()
    qualidade_cargos = [{
        "cargo": str(cargo), "total_bruto": int(total),
        "total_excluido": int(total) if str(cargo) != str(CARGO_PREFEITO) else 0,
        "total_eventos_analiticos_prefeito": int(len(eventos)) if str(cargo) == str(CARGO_PREFEITO) else 0,
        "regra_aplicada": f"CD_CARGO = {CARGO_PREFEITO}",
        "edicoes_esquema": ",".join(str(ano) for ano in edicoes),
    } for cargo, total in por_cargo.items()]
    return {"catalogo": catalogo_bruto, "eventos": eventos, "mandatos": mandatos, "manifesto": manifesto,
            "smoke_municipios": smoke_municipios, "qualidade_cargos": qualidade_cargos}


def _qualidade_tse(eventos: pd.DataFrame, mandatos: pd.DataFrame, municipio_ano: pd.DataFrame,
                   qualidade_cargos: list[dict[str, Any]] | None = None) -> pd.DataFrame:
    def status_series(quadro: pd.DataFrame, coluna: str) -> pd.Series:
        valor = quadro.get(coluna)
        if isinstance(valor, pd.Series):
            return valor
        return pd.Series(index=quadro.index, dtype=str)

    status_evento = status_series(eventos, "status_evento")
    origem_gestao = municipio_ano.get("origem_gestao")
    if not isinstance(origem_gestao, pd.Series):
        origem_gestao = pd.Series(index=municipio_ano.index, dtype=str)
    linhas = [
        {"tabela": "eventos_eleitorais_tse", "linhas": len(eventos), "pendencias": int((status_evento != "turno_decisivo").sum()) if len(eventos) else 0},
        {"tabela": "mandatos_municipais", "linhas": len(mandatos), "pendencias": int((status_series(mandatos, "status_transicao") != "validada").sum()) if len(mandatos) else 0},
        {"tabela": "municipio_ano_politico", "linhas": len(municipio_ano), "pendencias": int(origem_gestao.isna().sum())},
    ]
    for coluna, valido in (("status_detalhe_apuracao", "validado"), ("status_denominador", "validado"),
                           ("status_vencedor", "validado"), ("status_evento", "turno_decisivo")):
        status = status_series(eventos, coluna)
        linhas.append({"tabela": f"eventos_{coluna}", "linhas": len(eventos),
                       "pendencias": int((status != valido).sum()) if len(eventos) else 0})
    transicao = status_series(mandatos, "status_transicao")
    linhas.append({"tabela": "mandatos_status_transicao", "linhas": len(mandatos),
                   "pendencias": int((transicao != "validada").sum()) if len(mandatos) else 0})
    for linha in qualidade_cargos or []:
        linhas.append({"tabela": "filtro_cargo_analitico", **linha})
    return pd.DataFrame(linhas)


def executar_tse_eleitoral(sessao, config: dict[str, Any], raw_dir: Path, output_dir: Path) -> ResultadoTSE:
    config_execucao = dict(config)
    if config_execucao.get("_smoke_test"):
        config_execucao["tse_eleitoral_edicoes"] = [
            ano for ano in config_execucao.get("tse_eleitoral_edicoes", [2016, 2020])
            if int(ano) in (2016, 2020)
        ]
    quadros = carregar_quadros_tse(sessao, config_execucao, raw_dir)
    catalogo = validar_catalogo_tse_ibge(quadros["catalogo"], config.get("tse_eleitoral_uf", "PB"), 223)
    ano_inicial = int(config.get("tse_eleitoral_ano_inicial", config.get("ano_inicial", 2020)))
    ano_final = int(config.get("tse_eleitoral_ano_final", config.get("ano_final", 2024)))
    municipio_ano = construir_municipio_ano_politico(catalogo, quadros["eventos"], quadros["mandatos"], ano_inicial, ano_final)
    if config.get("_smoke_test"):
        codigos = quadros.get("smoke_municipios") or catalogo.codigo_ibge.head(2).tolist()
        municipio_ano = municipio_ano[municipio_ano.codigo_ibge.isin(codigos)].reset_index(drop=True)
        eventos = quadros["eventos"]
        if "codigo_ibge" in eventos:
            eventos = eventos[eventos.codigo_ibge.astype(str).isin(codigos)].reset_index(drop=True)
        mandatos = quadros["mandatos"]
        if "codigo_ibge" in mandatos:
            mandatos = mandatos[mandatos.codigo_ibge.astype(str).isin(codigos)].reset_index(drop=True)
    else:
        eventos = quadros["eventos"]
        mandatos = quadros["mandatos"]
    qualidade = _qualidade_tse(eventos, mandatos, municipio_ano, quadros.get("qualidade_cargos"))
    return ResultadoTSE(eventos, mandatos, municipio_ano, qualidade, quadros["manifesto"])


def _salvar_csv_atomico(df: pd.DataFrame, caminho: Path):
    conteudo = df.to_csv(index=False).encode("utf-8-sig")
    _salvar_bytes_atomico(caminho, conteudo)


def gravar_resultado_tse(resultado: ResultadoTSE, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _salvar_csv_atomico(resultado.eventos, output_dir / "eventos_eleitorais_tse.csv")
    _salvar_csv_atomico(resultado.mandatos, output_dir / "mandatos_municipais.csv")
    _salvar_csv_atomico(resultado.municipio_ano, output_dir / "municipio_ano_politico.csv")
    _salvar_csv_atomico(resultado.qualidade, output_dir / "qualidade_tse_eleitoral.csv")
    _salvar_bytes_atomico(output_dir / "manifesto_tse_eleitoral.json",
                          json.dumps(resultado.manifesto, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
