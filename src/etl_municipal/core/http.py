"""Respostas HTTP como bytes originais, com as mesmas regras de repetição dos coletores."""
import random
import time
import requests
from etl_confiabilidade import TRANSITORIOS, FalhaConsulta, requisitar_json, retry_after


class _CapturarResposta:
    def __init__(self, sessao):
        self.sessao = sessao
        self.resposta = None

    def get(self, *args, **kwargs):
        self.resposta = self.sessao.get(*args, **kwargs)
        return self.resposta


def obter_json(sessao, url, config, params=None, fonte='', contexto='', estado=None):
    """Valida o JSON como `requisitar_json` e devolve também os bytes recebidos."""
    captura = _CapturarResposta(sessao)
    dados = requisitar_json(captura, url, config, params=params, fonte=fonte, contexto=contexto, estado=estado)
    return dados, captura.resposta.content


def obter_bytes(sessao, url, config):
    """Arquivo binário completo; tamanho divergente do Content-Length é falha, não arquivo."""
    tentativas = max(1, int(config.get('max_tentativas', 4)))
    base = max(0.0, float(config.get('backoff_base_segundos', 3)))
    for tentativa in range(tentativas):
        resposta = None
        try:
            resposta = sessao.get(url, timeout=config.get('timeout_segundos', 300))
            resposta.raise_for_status()
            conteudo = resposta.content
            esperado = resposta.headers.get('Content-Length')
            if esperado is not None and int(esperado) != len(conteudo):
                raise FalhaConsulta(f'Download incompleto: {len(conteudo)} de {esperado} bytes')
            if not conteudo:
                raise FalhaConsulta('Arquivo vazio')
            return conteudo
        # RequestException cobre também conexão cortada no meio do corpo (ChunkedEncodingError).
        except (requests.RequestException, FalhaConsulta) as exc:
            status = resposta.status_code if resposta is not None else None
            if isinstance(exc, requests.HTTPError) and status not in TRANSITORIOS:
                raise FalhaConsulta(f'HTTP permanente {status}: {url}', status_code=status) from exc
            if tentativa == tentativas - 1:
                raise FalhaConsulta(f'Download falhou após {tentativas} tentativas: {url}') from exc
            atraso = max(base * 2 ** tentativa + random.uniform(0, base),
                         retry_after(resposta.headers.get('Retry-After')) if resposta is not None else 0)
            time.sleep(atraso)
