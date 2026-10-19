import json
import hashlib
import io
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import etl_tse_eleitoral as tse


def catalogo_sintetico_pb(n=223):
    return pd.DataFrame([
        {"CD_MUNICIPIO_TSE": f"{10000+i}", "CD_MUNICIPIO_IBGE": f"25{i:05d}",
         "NM_MUNICIPIO_IBGE": f"Municipio {i}", "SG_UF": "PB"}
        for i in range(n)
    ])


class RespostaBytes:
    def __init__(self, conteudo, status=200, headers=None):
        self.content = conteudo
        self.status_code = status
        self.headers = headers or {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class SessaoRange:
    def __init__(self, conteudo, ignorar=False):
        self.conteudo = conteudo
        self.ignorar = ignorar
        self.chamadas = []
    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(headers or {})
        faixa = (headers or {}).get("Range")
        if not faixa or self.ignorar:
            return RespostaBytes(self.conteudo, 200, {"ETag": "v1"})
        inicio, fim = map(int, faixa.removeprefix("bytes=").split("-"))
        fim = min(fim, len(self.conteudo)-1)
        return RespostaBytes(self.conteudo[inicio:fim+1], 206,
                             {"Content-Range": f"bytes {inicio}-{fim}/{len(self.conteudo)}", "ETag": "v1"})


def zip_minimo():
    destino = io.BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("arquivo_PB.csv", "A;B\n1;2\n".encode("latin-1"))
    return destino.getvalue()


class TestContratosTerritoriais(unittest.TestCase):
    def test_chaves_candidatura_e_evento_sao_distintas(self):
        self.assertIn("SQ_CANDIDATO", tse.CHAVE_CANDIDATURA_TURNO)
        self.assertIn("NR_TURNO", tse.CHAVE_CANDIDATURA_TURNO)
        self.assertNotIn("SQ_CANDIDATO", tse.CHAVE_EVENTO)
        self.assertNotIn("NR_TURNO", tse.CHAVE_EVENTO)

    def test_catalogo_pb_exige_223_codigos_unicos(self):
        catalogo = catalogo_sintetico_pb()
        validado = tse.validar_catalogo_tse_ibge(catalogo)
        self.assertEqual(len(validado), 223)
        self.assertEqual(validado.codigo_ibge.str.len().unique().tolist(), [7])
        with self.assertRaises(tse.FalhaTSE):
            tse.validar_catalogo_tse_ibge(catalogo.iloc[:-1])

    def test_catalogo_rejeita_duplicidade_e_uf_divergente(self):
        catalogo = catalogo_sintetico_pb()
        catalogo.loc[1, "CD_MUNICIPIO_IBGE"] = catalogo.loc[0, "CD_MUNICIPIO_IBGE"]
        with self.assertRaises(tse.FalhaTSE):
            tse.validar_catalogo_tse_ibge(catalogo)
        catalogo = catalogo_sintetico_pb()
        catalogo.loc[0, "SG_UF"] = "PE"
        with self.assertRaises(tse.FalhaTSE):
            tse.validar_catalogo_tse_ibge(catalogo)

    def test_normaliza_codigo_sem_converter_em_numero(self):
        df = pd.DataFrame({"SG_UE": ["00123"]})
        out = tse.normalizar_codigo_municipio_tse(df, "SG_UE")
        self.assertEqual(out.loc[0, "codigo_municipio_tse"], "00123")

    def test_mapa_de_esquema_exige_conjunto_e_edicao(self):
        with self.assertRaises(tse.FalhaTSE):
            tse.obter_esquema({"consulta_cand": {}}, "consulta_cand", 2020)


class TestArtefatosTSE(unittest.TestCase):
    def test_range_valido_confere_crc_tamanho_e_sha_local(self):
        with tempfile.TemporaryDirectory() as temp:
            sessao = SessaoRange(zip_minimo())
            spec = tse.EspecificacaoArtefato("teste", 2020, "https://tse/arquivo.zip", "arquivo_PB.csv")
            resultado = tse.coletar_membro_zip_tse(sessao, spec, Path(temp) / "pb.csv", {"tse_eleitoral_timeout_segundos": 2})
            self.assertEqual(resultado.metodo, "http_range")
            self.assertEqual(resultado.estado, "completa")
            self.assertEqual(resultado.sha256_local, hashlib.sha256((Path(temp) / "pb.csv").read_bytes()).hexdigest())
            self.assertGreater(resultado.tamanho_descomprimido, 0)

    def test_range_ignorado_faz_fallback_integral(self):
        with tempfile.TemporaryDirectory() as temp:
            sessao = SessaoRange(zip_minimo(), ignorar=True)
            spec = tse.EspecificacaoArtefato("teste", 2020, "https://tse/arquivo.zip", "arquivo_PB.csv")
            resultado = tse.coletar_membro_zip_tse(sessao, spec, Path(temp) / "pb.csv", {})
            self.assertEqual(resultado.metodo, "zip_integral")
            self.assertEqual(resultado.estado, "completa")

    def test_checkpoint_valido_e_reutilizado_sem_http(self):
        with tempfile.TemporaryDirectory() as temp:
            destino = Path(temp) / "pb.csv"
            spec = tse.EspecificacaoArtefato("teste", 2020, "https://tse/arquivo.zip", "arquivo_PB.csv")
            tse.coletar_membro_zip_tse(SessaoRange(zip_minimo()), spec, destino, {})
            sessao = SessaoRange(b"corrompido")
            resultado = tse.coletar_membro_zip_tse(sessao, spec, destino, {})
            self.assertTrue(resultado.cache_reutilizado)
            self.assertEqual(sessao.chamadas, [])

    def test_checkpoint_sha_divergente_e_fallback_invalido_falha(self):
        with tempfile.TemporaryDirectory() as temp:
            destino = Path(temp) / "pb.csv"
            spec = tse.EspecificacaoArtefato("teste", 2020, "https://tse/arquivo.zip", "arquivo_PB.csv")
            tse.coletar_membro_zip_tse(SessaoRange(zip_minimo()), spec, destino, {})
            destino.write_bytes(b"alterado")
            with self.assertRaises(tse.FalhaTSE):
                tse.coletar_membro_zip_tse(SessaoRange(b"nao zip", ignorar=True), spec, destino, {})


class TestNormalizacaoEleitoral(unittest.TestCase):
    def test_detalhe_2016_normaliza_qt_total_votos_validos_com_metadados(self):
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / "detalhe.csv"
            caminho.write_bytes(
                "CD_MUNICIPIO;CD_ELEICAO;NR_TURNO;QT_APTOS;QT_COMPARECIMENTO;QT_ABSTENCOES;QT_TOTAL_VOTOS_VALIDOS\n"
                "1;10;1;100;80;20;70\n".encode("latin-1")
            )
            mapa = tse.carregar_mapa_esquemas(tse.REFERENCE_DIR / "esquemas_tse.json")
            df = tse.ler_csv_tse(caminho, "detalhe_votacao_munzona", 2016, mapa)
            self.assertEqual(df.loc[0, "QT_VOTOS_VALIDOS"], "70")
            self.assertEqual(df.loc[0, "QT_VOTOS_VALIDOS_ORIGINAL"], "70")
            self.assertEqual(df.loc[0, "QT_VOTOS_VALIDOS_METODO"], "alias_versionado")
            self.assertEqual(df.loc[0, "QT_VOTOS_VALIDOS_ESQUEMA_EDICAO"], "2016")
            self.assertEqual(df.loc[0, "QT_VOTOS_VALIDOS_STATUS"], "disponivel")

    def test_detalhe_sem_denominador_preserva_evento_e_deixa_metricas_ausentes(self):
        catalogo = catalogo_sintetico_pb()
        cod_tse = catalogo.iloc[0].CD_MUNICIPIO_TSE
        base = {"ano_eleicao_origem_ciclo": "2016", "CD_ELEICAO": "10", "CD_TIPO_ELEICAO": "2",
                "DT_ELEICAO": "02/10/2016", "NR_TURNO": "1", "codigo_municipio_tse": cod_tse, "CD_CARGO": "11"}
        candidatos = pd.DataFrame([{**base, "SQ_CANDIDATO": "1", "CD_SIT_TOT_TURNO": "1",
                                    "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "AAA"}])
        votos = pd.DataFrame([{**base, "SQ_CANDIDATO": "1", "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "70"}])
        detalhes = pd.DataFrame([{**base, "NR_ZONA": "1", "QT_APTOS": "100",
                                  "QT_COMPARECIMENTO": "80", "QT_ABSTENCOES": "20"}])
        eventos = tse.construir_eventos_eleitorais(candidatos, votos, detalhes, catalogo,
                                                    pd.DataFrame(), {2016: {"1": "eleito"}})
        self.assertEqual(len(eventos), 1)
        self.assertTrue(pd.isna(eventos.iloc[0].percentual_vencedor))
        self.assertTrue(pd.isna(eventos.iloc[0].margem_pontos_percentuais))
        self.assertEqual(eventos.iloc[0].status_qualidade, "pendente_denominador_votos_validos")

    def test_ler_csv_aplica_aliases_sentinelas_e_obrigatorios(self):
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / "x.csv"
            caminho.write_bytes("ORIG;REQ\n00123;#NULO#\n".encode("latin-1"))
            mapa = {"x": {"2020": {"encoding": "latin-1", "separador": ";",
                    "aliases": {"codigo": ["ORIG"]}, "campos_obrigatorios": ["ORIG", "REQ"],
                    "sentinelas": {"REQ": ["#NULO#"]}}}}
            df = tse.ler_csv_tse(caminho, "x", 2020, mapa)
            self.assertEqual(df.loc[0, "codigo"], "00123")
            self.assertTrue(pd.isna(df.loc[0, "REQ"]))
            with self.assertRaises(tse.FalhaTSE):
                tse.ler_csv_tse(caminho, "x", 2024, mapa)

    def test_vencedor_usa_codigo_e_nao_maior_votacao(self):
        grupo = pd.DataFrame([
            {"CD_SIT_TOT_TURNO": "4", "DS_SIT_TOT_TURNO": "NÃO ELEITO", "votos": 100},
            {"CD_SIT_TOT_TURNO": "1", "DS_SIT_TOT_TURNO": "ELEITO", "votos": 50},
        ])
        vencedor, status = tse.resolver_vencedor(grupo, {"1": "eleito"})
        self.assertEqual(vencedor.votos, 50)
        self.assertEqual(status, "validado")

    def test_codigo_desconhecido_nao_infere_vencedor(self):
        grupo = pd.DataFrame([{"CD_SIT_TOT_TURNO": "9", "DS_SIT_TOT_TURNO": "OUTRO", "votos": 100}])
        vencedor, status = tse.resolver_vencedor(grupo, {"1": "eleito"})
        self.assertIsNone(vencedor)
        self.assertEqual(status, "pendente_codigo_totalizacao")

    def test_disponibilidade_oficial_e_conservadora(self):
        self.assertEqual(tse.definir_disponibilidade(date(2020, 11, 15), date(2020, 11, 20)),
                         (date(2020, 11, 20), "dia_oficial", "data_oficial_totalizacao"))
        self.assertEqual(tse.definir_disponibilidade(date(2020, 11, 15), None),
                         (date(2021, 1, 1), "ano_regra_conservadora", "primeiro_dia_ano_seguinte"))


class TestEventosEleitorais(unittest.TestCase):
    def test_evento_sem_vencedor_preserva_detalhe_e_separa_statuses(self):
        catalogo = catalogo_sintetico_pb()
        cod_tse = catalogo.iloc[0].CD_MUNICIPIO_TSE
        base = {"ano_eleicao_origem_ciclo": "2020", "CD_ELEICAO": "426", "CD_TIPO_ELEICAO": "2",
                "DT_ELEICAO": "15/11/2020", "NR_TURNO": "1", "codigo_municipio_tse": cod_tse,
                "CD_CARGO": "11"}
        candidatos = pd.DataFrame([{**base, "SQ_CANDIDATO": "1", "CD_SIT_TOT_TURNO": "4",
                                    "DS_SIT_TOT_TURNO": "NAO ELEITO", "SG_PARTIDO": "AAA"}])
        votos = pd.DataFrame([{**base, "SQ_CANDIDATO": "1", "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "100"}])
        detalhes = pd.DataFrame([{**base, "NR_ZONA": "1", "QT_APTOS": "200",
                                  "QT_COMPARECIMENTO": "150", "QT_ABSTENCOES": "50",
                                  "QT_VOTOS_VALIDOS": "120"}])
        evento = tse.construir_eventos_eleitorais(candidatos, votos, detalhes, catalogo,
                                                   pd.DataFrame(), {2020: {"1": "eleito"}}).iloc[0]
        self.assertEqual(evento.valor_votos_validos_normalizado, 120)
        self.assertEqual(evento.qt_aptos, 200)
        self.assertEqual(evento.qt_comparecimento, 150)
        self.assertEqual(evento.qt_abstencoes, 50)
        self.assertNotIn("SQ_CANDIDATO_VENCEDOR", evento.index)
        self.assertTrue(pd.isna(evento.partido_vencedor))
        self.assertEqual(evento.status_denominador, "validado")
        self.assertEqual(evento.status_vencedor, "sem_eleito_no_turno")
        self.assertEqual(evento.status_evento, "turno_nao_decisivo")
        self.assertTrue(pd.isna(evento.percentual_vencedor))
        self.assertTrue(pd.isna(evento.margem_pontos_percentuais))

    def test_eventos_analiticos_publicam_somente_cargo_prefeito(self):
        catalogo = catalogo_sintetico_pb()
        cod_tse = catalogo.iloc[0].CD_MUNICIPIO_TSE
        base = {"ano_eleicao_origem_ciclo": "2020", "CD_ELEICAO": "426", "CD_TIPO_ELEICAO": "2",
                "DT_ELEICAO": "15/11/2020", "NR_TURNO": "1", "codigo_municipio_tse": cod_tse}
        candidatos = pd.DataFrame([
            {**base, "CD_CARGO": "11", "SQ_CANDIDATO": "1", "CD_SIT_TOT_TURNO": "1", "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "AAA"},
            {**base, "CD_CARGO": "12", "SQ_CANDIDATO": "2", "CD_SIT_TOT_TURNO": "1", "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "BBB"},
            {**base, "CD_CARGO": "13", "SQ_CANDIDATO": "3", "CD_SIT_TOT_TURNO": "1", "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "CCC"},
        ])
        votos = pd.DataFrame([{**r, "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "50"}
                              for r in candidatos.to_dict("records")])
        detalhes = pd.DataFrame([{**base, "CD_CARGO": "11", "NR_ZONA": "1", "QT_APTOS": "60",
                                  "QT_COMPARECIMENTO": "50", "QT_ABSTENCOES": "10", "QT_VOTOS_VALIDOS": "50"}])
        eventos = tse.construir_eventos_eleitorais(candidatos, votos, detalhes, catalogo,
                                                    pd.DataFrame(), {2020: {"1": "eleito"}})
        self.assertEqual(eventos.CD_CARGO.tolist(), ["11"])

    def test_denominador_separa_cargo_ao_juntar_detalhes(self):
        catalogo = catalogo_sintetico_pb()
        cod_tse = catalogo.iloc[0].CD_MUNICIPIO_TSE
        base = {"ano_eleicao_origem_ciclo": "2020", "CD_ELEICAO": "426", "CD_TIPO_ELEICAO": "2",
                "DT_ELEICAO": "15/11/2020", "NR_TURNO": "1", "codigo_municipio_tse": cod_tse}
        candidatos = pd.DataFrame([{**base, "CD_CARGO": "11", "SQ_CANDIDATO": "1", "CD_SIT_TOT_TURNO": "1",
                                    "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "AAA"}])
        votos = pd.DataFrame([{**base, "CD_CARGO": "11", "SQ_CANDIDATO": "1", "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "40"}])
        detalhes = pd.DataFrame([
            {**base, "CD_CARGO": "11", "NR_ZONA": "1", "QT_APTOS": "100", "QT_COMPARECIMENTO": "80", "QT_ABSTENCOES": "20", "QT_VOTOS_VALIDOS": "70"},
            {**base, "CD_CARGO": "13", "NR_ZONA": "1", "QT_APTOS": "100", "QT_COMPARECIMENTO": "80", "QT_ABSTENCOES": "20", "QT_VOTOS_VALIDOS": "75"},
        ])
        eventos = tse.construir_eventos_eleitorais(candidatos, votos, detalhes, catalogo,
                                                    pd.DataFrame(), {2020: {"1": "eleito"}})
        evento = eventos.iloc[0]
        self.assertEqual(evento.CD_CARGO, "11")
        self.assertEqual(evento.qt_aptos, 100)
        self.assertEqual(evento.valor_votos_validos_normalizado, 70)
        self.assertAlmostEqual(evento.percentual_vencedor, 40 / 70 * 100)

    def test_totais_zona_nao_multiplicam_e_votos_nao_misturam_turno(self):
        catalogo = catalogo_sintetico_pb()
        cod_tse = catalogo.iloc[0].CD_MUNICIPIO_TSE
        base = {"ano_eleicao_origem_ciclo": "2020", "CD_ELEICAO": "426", "CD_TIPO_ELEICAO": "2",
                "DT_ELEICAO": "15/11/2020", "NR_TURNO": "1", "codigo_municipio_tse": cod_tse, "CD_CARGO": "11"}
        candidatos = pd.DataFrame([{**base, "SQ_CANDIDATO": "1", "CD_SIT_TOT_TURNO": "1", "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "AAA"},
                                   {**base, "SQ_CANDIDATO": "2", "CD_SIT_TOT_TURNO": "4", "DS_SIT_TOT_TURNO": "NÃO ELEITO", "SG_PARTIDO": "BBB"}])
        votos = pd.DataFrame([{**base, "SQ_CANDIDATO": "1", "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "60"},
                              {**base, "SQ_CANDIDATO": "2", "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "40"},
                              {**base, "SQ_CANDIDATO": "1", "NR_ZONA": "2", "QT_VOTOS_NOMINAIS": "30"},
                              {**base, "SQ_CANDIDATO": "2", "NR_ZONA": "2", "QT_VOTOS_NOMINAIS": "20"},
                              {**base, "NR_TURNO": "2", "SQ_CANDIDATO": "1", "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "999"}])
        detalhes = pd.DataFrame([{**base, "NR_ZONA": "1", "QT_APTOS": "120", "QT_COMPARECIMENTO": "100", "QT_ABSTENCOES": "20", "QT_VOTOS_VALIDOS": "100"},
                                  {**base, "NR_ZONA": "2", "QT_APTOS": "60", "QT_COMPARECIMENTO": "50", "QT_ABSTENCOES": "10", "QT_VOTOS_VALIDOS": "50"}])
        eventos = tse.construir_eventos_eleitorais(candidatos, votos, detalhes, catalogo,
                                                    pd.DataFrame(), {2020: {"1": "eleito"}})
        self.assertEqual(len(eventos), 1)
        evento = eventos.iloc[0]
        self.assertEqual(evento.votos_vencedor, 90)
        self.assertEqual(evento.qt_aptos, 180)
        self.assertEqual(evento.qt_comparecimento, 150)
        self.assertEqual(evento.qt_abstencoes, 30)
        self.assertAlmostEqual(evento.percentual_vencedor, 60)

    def test_candidatura_unica_tem_margem_ausente(self):
        catalogo = catalogo_sintetico_pb()
        cod_tse = catalogo.iloc[0].CD_MUNICIPIO_TSE
        base = {"ano_eleicao_origem_ciclo": "2020", "CD_ELEICAO": "1", "CD_TIPO_ELEICAO": "2",
                "DT_ELEICAO": "15/11/2020", "NR_TURNO": "1", "codigo_municipio_tse": cod_tse, "CD_CARGO": "11", "SQ_CANDIDATO": "1"}
        cand = pd.DataFrame([{**base, "CD_SIT_TOT_TURNO": "1", "DS_SIT_TOT_TURNO": "ELEITO", "SG_PARTIDO": "AAA"}])
        votos = pd.DataFrame([{**base, "NR_ZONA": "1", "QT_VOTOS_NOMINAIS": "50"}])
        det = pd.DataFrame([{**base, "NR_ZONA": "1", "QT_APTOS": "60", "QT_COMPARECIMENTO": "50", "QT_ABSTENCOES": "10", "QT_VOTOS_VALIDOS": "50"}])
        evento = tse.construir_eventos_eleitorais(cand, votos, det, catalogo, pd.DataFrame(), {2020: {"1": "eleito"}}).iloc[0]
        self.assertTrue(pd.isna(evento.margem_pontos_percentuais))


class TestMandatosMunicipais(unittest.TestCase):
    def test_mandato_decide_por_status_autoritativo_e_ignora_legado(self):
        eventos = pd.DataFrame([{
            "codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
            "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
            "status_resultado": "pendente_codigo_totalizacao", "status_vencedor": "validado",
            "status_evento": "turno_decisivo", "partido_vencedor": "AAA",
        }])
        mandatos = tse.construir_mandatos_municipais(eventos, pd.DataFrame())
        self.assertEqual(len(mandatos), 1)

    def test_mandato_rejeita_status_autoritativo_invalido_mesmo_com_legado_validado(self):
        eventos = pd.DataFrame([{
            "codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
            "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
            "status_resultado": "validado", "status_vencedor": "sem_eleito_no_turno",
            "status_evento": "turno_nao_decisivo", "partido_vencedor": None,
        }])
        self.assertEqual(len(tse.construir_mandatos_municipais(eventos, pd.DataFrame())), 0)

    def test_mandato_usa_somente_prefeito_e_maior_turno_validado(self):
        eventos = pd.DataFrame([
            {"codigo_ibge": "2500001", "CD_ELEICAO": "10", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2016, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "AAA"},
            {"codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "BBB"},
            {"codigo_ibge": "2500001", "CD_ELEICAO": "21", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
             "numero_turno_decisivo": "2", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "CCC"},
            {"codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "12",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "DDD"},
            {"codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "13",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "EEE"},
        ])
        eventos["status_vencedor"] = "validado"
        eventos["status_evento"] = "turno_decisivo"
        mandatos = tse.construir_mandatos_municipais(eventos, pd.DataFrame())
        self.assertEqual(len(mandatos), 2)
        self.assertEqual(mandatos.partido_prefeito_no_pleito_origem.tolist(), ["AAA", "CCC"])
        self.assertFalse(mandatos.duplicated(["codigo_ibge", "ano_eleicao_origem_ciclo", "cd_eleicao_origem"]).any())

    def test_primeiro_turno_sem_eleito_nao_cria_mandato(self):
        eventos = pd.DataFrame([
            {"codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "pendente_codigo_totalizacao", "partido_vencedor": None},
        ])
        self.assertEqual(len(tse.construir_mandatos_municipais(eventos, pd.DataFrame())), 0)

    def test_dois_prefeitos_no_turno_decisivo_bloqueiam_escolha_silenciosa(self):
        eventos = pd.DataFrame([
            {"codigo_ibge": "2500001", "CD_ELEICAO": "20", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "AAA"},
            {"codigo_ibge": "2500001", "CD_ELEICAO": "21", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
             "numero_turno_decisivo": "1", "ano_eleicao_origem_ciclo": 2020, "origem_evento": "regular",
             "status_resultado": "validado", "partido_vencedor": "BBB"},
        ])
        eventos["status_vencedor"] = "validado"
        eventos["status_evento"] = "turno_decisivo"
        with self.assertRaises(tse.FalhaTSE):
            tse.construir_mandatos_municipais(eventos, pd.DataFrame())

    def test_csv_evidencias_exige_origem_auditavel(self):
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / "evidencias.csv"
            colunas = tse.COLUNAS_EVIDENCIA_POSSE
            pd.DataFrame([{c: "" for c in colunas} | {
                "id_evidencia": "e1", "codigo_ibge": "2500001", "cd_eleicao": "99",
                "ano_eleicao_origem_ciclo": "2016", "data_posse": "2019-01-02",
                "precisao_data_posse": "dia_oficial", "tipo_fonte_oficial": "ata_posse",
                "nivel_hierarquia_fonte": "1", "orgao_publicador": "Camara Municipal",
                "url_fonte_oficial": "https://camara.pb.gov.br/ata", "status_validacao": "validada"
            }]).to_csv(caminho, index=False)
            evidencias = tse.ler_evidencias_posse(caminho)
            self.assertEqual(evidencias.iloc[0].status_validacao, "validada")
            evidencias.loc[0, "url_fonte_oficial"] = "https://exemplo.com/ata"
            evidencias.to_csv(caminho, index=False)
            self.assertEqual(tse.ler_evidencias_posse(caminho).iloc[0].status_validacao, "pendente")

    def test_posse_validada_substitui_mandato_e_pendente_nao(self):
        eventos = pd.DataFrame([
            {"codigo_ibge": "2500001", "CD_ELEICAO": "10", "ano_eleicao_origem_ciclo": 2016,
             "DT_ELEICAO": "02/10/2016", "origem_evento": "regular", "status_resultado": "validado",
             "status_vencedor": "validado", "status_evento": "turno_decisivo", "partido_vencedor": "AAA"},
            {"codigo_ibge": "2500001", "CD_ELEICAO": "11", "ano_eleicao_origem_ciclo": 2016,
             "DT_ELEICAO": "17/03/2019", "origem_evento": "suplementar", "status_resultado": "validado",
             "status_vencedor": "validado", "status_evento": "turno_decisivo", "partido_vencedor": "BBB"},
        ])
        evidencias = pd.DataFrame([{
            "id_evidencia": "e1", "codigo_ibge": "2500001", "cd_eleicao": "11",
            "ano_eleicao_origem_ciclo": "2016", "data_posse": "2019-04-01",
            "precisao_data_posse": "dia_oficial", "tipo_fonte_oficial": "ata_posse",
            "nivel_hierarquia_fonte": "1", "orgao_publicador": "Camara",
            "url_fonte_oficial": "https://camara.pb.gov.br/ata", "data_publicacao_fonte": "2019-04-01",
            "titulo_documento": "Ata", "identificador_documento": "1", "data_verificacao_utc": "2026-10-15T00:00:00Z",
            "status_validacao": "validada", "observacao": ""
        }])
        mandatos = tse.construir_mandatos_municipais(eventos, evidencias)
        self.assertEqual(mandatos.origem_gestao.tolist(), ["regular", "suplementar"])
        self.assertEqual(mandatos.iloc[0].data_fim_vigencia, "2019-03-31")
        self.assertEqual(mandatos.iloc[1].partido_prefeito_no_pleito_origem, "BBB")
        pendente = evidencias.assign(status_validacao="pendente", data_posse="")
        self.assertEqual(len(tse.construir_mandatos_municipais(eventos, pendente)), 1)


class TestFotografiaPolitica(unittest.TestCase):
    def test_suplementar_sem_posse_nao_altera_continuidade_anual(self):
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
        codigo = catalogo.iloc[0].codigo_ibge
        eventos = pd.DataFrame([
            {"codigo_ibge": codigo, "CD_ELEICAO": "10", "ano_eleicao_origem_ciclo": 2016,
             "DT_ELEICAO": "02/10/2016", "data_disponibilidade_adotada": "2017-01-01",
             "status_resultado": "validado", "status_vencedor": "validado", "status_evento": "turno_decisivo",
             "origem_evento": "regular", "partido_vencedor": "AAA"},
            {"codigo_ibge": codigo, "CD_ELEICAO": "11", "ano_eleicao_origem_ciclo": 2016,
             "DT_ELEICAO": "17/03/2019", "data_disponibilidade_adotada": "2019-04-01",
             "status_resultado": "validado", "status_vencedor": "validado", "status_evento": "turno_decisivo",
             "origem_evento": "suplementar", "partido_vencedor": "BBB"},
        ])
        mandatos = pd.DataFrame([{
            "codigo_ibge": codigo, "ano_eleicao_origem_ciclo": 2016, "cd_eleicao_origem": "10",
            "partido_prefeito_no_pleito_origem": "AAA", "origem_gestao": "regular",
            "data_inicio_vigencia": "2017-01-01", "data_fim_vigencia": "2020-12-31",
            "precisao_inicio_vigencia": "dia_oficial", "status_transicao": "validada",
        }])
        foto = tse.construir_municipio_ano_politico(catalogo, eventos, mandatos, 2020, 2020)
        linha = foto.iloc[0]
        self.assertTrue(pd.isna(linha.continuidade_partidaria_pleito))
        self.assertEqual(linha.partido_prefeito_no_pleito_origem, "AAA")

    def test_continuidade_usa_status_autoritativo_e_nao_status_legado(self):
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
        codigo = catalogo.iloc[0].codigo_ibge
        eventos = pd.DataFrame([{
            "codigo_ibge": codigo, "CD_ELEICAO": "20", "ano_eleicao_origem_ciclo": 2020,
            "DT_ELEICAO": "15/11/2020", "data_disponibilidade_adotada": "2021-01-01",
            "status_resultado": "pendente_codigo_totalizacao", "status_vencedor": "validado",
            "status_evento": "turno_decisivo", "origem_evento": "regular", "partido_vencedor": "BBB",
        }])
        mandatos = pd.DataFrame([{
            "codigo_ibge": codigo, "ano_eleicao_origem_ciclo": 2016, "cd_eleicao_origem": "10",
            "partido_prefeito_no_pleito_origem": "BBB", "origem_gestao": "regular",
            "data_inicio_vigencia": "2017-01-01", "data_fim_vigencia": "2020-12-31",
            "precisao_inicio_vigencia": "dia_oficial", "status_transicao": "validada",
        }, {
            "codigo_ibge": codigo, "ano_eleicao_origem_ciclo": 2020, "cd_eleicao_origem": "20",
            "partido_prefeito_no_pleito_origem": "BBB", "origem_gestao": "regular",
            "data_inicio_vigencia": "2021-01-01", "data_fim_vigencia": "2024-12-31",
            "precisao_inicio_vigencia": "dia_oficial", "status_transicao": "validada",
        }])
        foto = tse.construir_municipio_ano_politico(catalogo, eventos, mandatos, 2020, 2021)
        linha = foto.query("codigo_ibge == @codigo and ano_fotografia == 2021").iloc[0]
        self.assertTrue(bool(linha.continuidade_partidaria_pleito))
    def test_1115_chaves_e_resultado_2020_so_em_2021(self):
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
        codigo = catalogo.iloc[0].codigo_ibge
        eventos = pd.DataFrame([
            {"codigo_ibge": codigo, "CD_ELEICAO": "10", "ano_eleicao_origem_ciclo": 2016,
             "DT_ELEICAO": "02/10/2016", "data_disponibilidade_adotada": "2017-01-01",
             "status_resultado": "validado", "status_vencedor": "validado", "status_evento": "turno_decisivo",
             "origem_evento": "regular", "partido_vencedor": "AAA"},
            {"codigo_ibge": codigo, "CD_ELEICAO": "20", "ano_eleicao_origem_ciclo": 2020,
             "DT_ELEICAO": "15/11/2020", "data_disponibilidade_adotada": "2021-01-01",
             "status_resultado": "validado", "status_vencedor": "validado", "status_evento": "turno_decisivo",
             "origem_evento": "regular", "partido_vencedor": "BBB"},
        ])
        mandatos = pd.DataFrame([
            {"codigo_ibge": codigo, "ano_eleicao_origem_ciclo": 2016, "partido_prefeito_no_pleito_origem": "AAA",
             "cd_eleicao_origem": "10",
             "origem_gestao": "regular", "data_inicio_vigencia": "2017-01-01", "data_fim_vigencia": "2020-12-31", "precisao_inicio_vigencia": "dia_oficial"},
            {"codigo_ibge": codigo, "ano_eleicao_origem_ciclo": 2020, "partido_prefeito_no_pleito_origem": "BBB",
             "cd_eleicao_origem": "20", "origem_gestao": "regular",
             "data_inicio_vigencia": "2021-01-01", "data_fim_vigencia": "2024-12-31", "precisao_inicio_vigencia": "dia_oficial",
             "status_transicao": "validada"},
        ])
        foto = tse.construir_municipio_ano_politico(catalogo, eventos, mandatos)
        self.assertEqual(len(foto), 1115)
        self.assertFalse(foto.duplicated(["codigo_ibge", "ano_fotografia"]).any())
        f2020 = foto.query("codigo_ibge == @codigo and ano_fotografia == 2020").iloc[0]
        f2021 = foto.query("codigo_ibge == @codigo and ano_fotografia == 2021").iloc[0]
        self.assertEqual(f2020.ano_eleicao_origem_ciclo, 2016)
        self.assertTrue(pd.isna(f2020.continuidade_partidaria_pleito))
        self.assertEqual(f2021.ano_eleicao_origem_ciclo, 2020)
        self.assertFalse(bool(f2021.continuidade_partidaria_pleito))
        adaptada = tse.adaptar_municipio_ano_para_base(foto)
        self.assertTrue((adaptada.ano == adaptada.ano_fotografia).all())


class TestOrquestracaoTSE(unittest.TestCase):
    def test_qualidade_separa_status_autoritativos(self):
        eventos = pd.DataFrame([{
            "status_resultado": "validado", "status_detalhe_apuracao": "validado",
            "status_denominador": "ausente", "status_vencedor": "validado",
            "status_evento": "turno_decisivo",
        }])
        qualidade = tse._qualidade_tse(eventos, pd.DataFrame(), pd.DataFrame())
        pendencias = qualidade.set_index("tabela")["pendencias"]
        self.assertEqual(pendencias["eventos_status_detalhe_apuracao"], 0)
        self.assertEqual(pendencias["eventos_status_denominador"], 1)
        self.assertEqual(pendencias["eventos_status_vencedor"], 0)
        self.assertEqual(pendencias["eventos_status_evento"], 0)

    def test_selecao_smoke_eh_joao_pessoa_e_municipio_sem_segundo_turno(self):
        catalogo = catalogo_sintetico_pb()
        catalogo.loc[0, "NM_MUNICIPIO_IBGE"] = "João Pessoa"
        catalogo.loc[1, "NM_MUNICIPIO_IBGE"] = "Município sem segundo turno"
        catalogo = tse.validar_catalogo_tse_ibge(catalogo)
        candidaturas = pd.DataFrame([
            {"codigo_municipio_tse": catalogo.iloc[0].codigo_municipio_tse, "ano_eleicao_origem_ciclo": "2020", "CD_CARGO": "11", "NR_TURNO": "1"},
            {"codigo_municipio_tse": catalogo.iloc[0].codigo_municipio_tse, "ano_eleicao_origem_ciclo": "2020", "CD_CARGO": "11", "NR_TURNO": "2"},
            {"codigo_municipio_tse": catalogo.iloc[1].codigo_municipio_tse, "ano_eleicao_origem_ciclo": "2020", "CD_CARGO": "11", "NR_TURNO": "1"},
        ])
        selecionados = tse.selecionar_municipios_smoke(catalogo, candidaturas)
        self.assertEqual(selecionados, [catalogo.iloc[0].codigo_ibge, catalogo.iloc[1].codigo_ibge])

    def test_smoke_tem_dez_fotografias_e_nao_consulta_2024(self):
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
        codigo_a, codigo_b = catalogo.iloc[0].codigo_ibge, catalogo.iloc[1].codigo_ibge
        foto = tse.construir_municipio_ano_politico(catalogo, pd.DataFrame(), pd.DataFrame())
        quadros = {"catalogo": catalogo, "eventos": pd.DataFrame(), "mandatos": pd.DataFrame(),
                   "manifesto": [], "smoke_municipios": [codigo_a, codigo_b]}
        with tempfile.TemporaryDirectory() as temp, patch.object(tse, "carregar_quadros_tse", return_value=quadros) as carregar:
            resultado = tse.executar_tse_eleitoral(
                object(), {"_smoke_test": True, "tse_eleitoral_edicoes": [2016, 2020, 2024]},
                Path(temp) / "raw", Path(temp) / "out")
        carregar.assert_called_once()
        self.assertEqual(tuple(carregar.call_args.args[1]["tse_eleitoral_edicoes"]), (2016, 2020))
        self.assertEqual(len(resultado.municipio_ano), 10)
        self.assertEqual(resultado.municipio_ano[["codigo_ibge", "ano_fotografia"]].drop_duplicates().shape[0], 10)

    def test_smoke_restringe_edicoes_a_2016_e_2020_antes_da_coleta(self):
        capturado = {}

        def carregar(_sessao, config, _raw_dir):
            capturado["edicoes"] = tuple(config["tse_eleitoral_edicoes"])
            catalogo = tse.validar_catalogo_tse_ibge(catalogo_sintetico_pb())
            return {
                "catalogo": catalogo,
                "eventos": pd.DataFrame(),
                "mandatos": pd.DataFrame(),
                "manifesto": [],
            }

        with tempfile.TemporaryDirectory() as temp, patch.object(tse, "carregar_quadros_tse", side_effect=carregar):
            tse.executar_tse_eleitoral(
                object(),
                {"tse_eleitoral_edicoes": [2016, 2020, 2024], "_smoke_test": True},
                Path(temp) / "raw",
                Path(temp) / "out",
            )
        self.assertEqual(capturado["edicoes"], (2016, 2020))

    def test_execucao_e_gravacao_cinco_saidas_atomicas(self):
        catalogo_bruto = catalogo_sintetico_pb()
        catalogo = tse.validar_catalogo_tse_ibge(catalogo_bruto)
        codigo, cod_tse = catalogo.iloc[0].codigo_ibge, catalogo.iloc[0].codigo_municipio_tse
        evento = pd.DataFrame([{"codigo_ibge": codigo, "municipio": "Municipio 0", "uf": "PB",
            "codigo_municipio_tse": cod_tse, "CD_ELEICAO": "10", "CD_TIPO_ELEICAO": "2", "CD_CARGO": "11",
            "ano_eleicao_origem_ciclo": 2016, "DT_ELEICAO": "02/10/2016", "origem_evento": "regular",
            "status_resultado": "validado", "partido_vencedor": "AAA", "data_disponibilidade_adotada": "2017-01-01"}])
        mandato = pd.DataFrame([{"codigo_ibge": codigo, "ano_eleicao_origem_ciclo": 2016,
            "partido_prefeito_no_pleito_origem": "AAA", "origem_gestao": "regular",
            "data_inicio_vigencia": "2017-01-01", "data_fim_vigencia": "2020-12-31",
            "precisao_inicio_vigencia": "dia_oficial", "status_transicao": "validada"}])
        with tempfile.TemporaryDirectory() as temp, patch.object(tse, "carregar_quadros_tse", return_value={
            "catalogo": catalogo_bruto, "eventos": evento, "mandatos": mandato,
            "manifesto": [{"fonte": "TSE", "estado": "cache_reutilizado"}] }):
            raiz = Path(temp)
            resultado = tse.executar_tse_eleitoral(object(), {"ano_inicial": 2020, "ano_final": 2024}, raiz / "raw", raiz / "out")
            self.assertEqual(len(resultado.municipio_ano), 1115)
            tse.gravar_resultado_tse(resultado, raiz / "out")
            for nome in ("eventos_eleitorais_tse.csv", "mandatos_municipais.csv", "municipio_ano_politico.csv", "qualidade_tse_eleitoral.csv", "manifesto_tse_eleitoral.json"):
                self.assertTrue((raiz / "out" / nome).exists())


if __name__ == "__main__":
    unittest.main()
