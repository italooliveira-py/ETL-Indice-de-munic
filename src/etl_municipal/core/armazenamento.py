"""Bronze imutável, identificado pelo conteúdo."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from etl_confiabilidade import salvar_json_atomico


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def preservar(raiz: Path, fonte: str, nome: str, conteudo: bytes, origem: str) -> Path:
    if Path(nome).name != nome or not fonte.replace('_', '').isalnum():
        raise ValueError('Fonte ou nome de artefato inválido')
    digest = sha256(conteudo)
    pasta = raiz / 'bronze' / fonte / digest
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome
    if destino.exists():
        if sha256(destino.read_bytes()) != digest:
            raise ValueError(f'Bronze corrompido: {destino}')
    else:
        with destino.open('xb') as arquivo:
            arquivo.write(conteudo)
    manifesto = pasta / f'{nome}.manifesto.json'
    if manifesto.exists():
        anterior = json.loads(manifesto.read_text(encoding='utf-8'))
        if anterior['sha256'] != digest or anterior['tamanho_bytes'] != len(conteudo):
            raise ValueError(f'Manifesto inconsistente: {manifesto}')
    else:
        salvar_json_atomico(manifesto, {
            'fonte': fonte, 'arquivo': nome, 'origem': origem,
            'sha256': digest, 'tamanho_bytes': len(conteudo),
            'preservado_em_utc': datetime.now(timezone.utc).isoformat(),
            'data_disponibilidade_publica': None,
            'nota': 'Data de coleta não equivale à data de publicação da informação.',
        })
    return destino
