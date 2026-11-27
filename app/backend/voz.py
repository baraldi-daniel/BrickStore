"""
📞 SAC por voz (só workspace corporativo): Whisper servido no Model Serving + ai_classify / ai_analyze_sentiment / ai_extract.

  transcrever_bytes(dados)            -> {"texto", "duracao_seg", "erro"}   (endpoint NB_WHISPER: <app_name>-whisper)
  transcrever_volume("/Volumes/...")  -> idem, lendo o áudio do Volume
  analisar_atendimento("texto")       -> {"categoria", "sentimento", "pedido_id", "produto", "motivo"}
  atendimentos(cliente_id=None)       -> linhas da tabela atendimentos_voz

Sem NB_WHISPER (workspace sem GPU, enterprise: false no config.yaml) a parte de voz fica desligada e o App segue igual.
"""
import json
import os
import re

from . import lakebase
from . import servicos as S

CATEGORIAS = json.dumps({
    "troca": "troca de tamanho, cor ou modelo de um produto",
    "atraso": "entrega atrasada, rastreio parado, pedido que não chegou",
    "defeito": "produto com defeito, quebrado ou que parou de funcionar",
    "elogio": "elogio, agradecimento ou satisfação com a compra",
    "garantia": "dúvida ou acionamento de garantia",
    "cancelamento": "cancelar compra, desistência ou pedido de estorno"}, ensure_ascii=False)
CAMPOS = json.dumps({
    "pedido_id": {"type": "string", "description": "código do pedido: letra P seguida de 7 dígitos (junte os dígitos falados)"},
    "produto": {"type": "string", "description": "produto citado pelo cliente"},
    "motivo": {"type": "string", "description": "motivo do contato em poucas palavras"}}, ensure_ascii=False)
RX_CAMINHO = re.compile(r"^/Volumes/[\w\-]+/[\w\-]+/[\w\-]+/[\w\-./ ]+\.(mp3|wav|m4a|flac|opus|ogg)$", re.I)


WHISPER = os.environ.get("NB_WHISPER", "").strip()


def disponivel() -> bool:
    return bool(WHISPER)


def transcrever_bytes(dados: bytes) -> dict:
    """Manda o áudio (MP3/WAV/FLAC/OGG) para o endpoint do Whisper. Com scale to zero, a 1ª chamada pode esperar o
    endpoint acordar: devolve um erro amigável para tentar de novo."""
    import base64
    import requests
    w = S.ws()
    try:
        r = requests.post(f"{w.config.host.rstrip('/')}/serving-endpoints/{WHISPER}/invocations", timeout=240,
                          headers={**w.config.authenticate(), "Content-Type": "application/json"},
                          json={"dataframe_split": {"columns": ["audio"], "data": [[base64.b64encode(dados).decode()]]}})
    except requests.Timeout:
        return {"texto": "", "erro": "o Whisper está acordando (scale to zero); tente de novo em 1 ou 2 minutos"}
    if r.status_code >= 400:
        return {"texto": "", "erro": f"Whisper HTTP {r.status_code}: {r.text[:160]}"}
    pred = (r.json().get("predictions") or [{}])[0]
    if not isinstance(pred, dict):
        pred = {"texto": str(pred or "")}
    return {"texto": (pred.get("texto") or "").strip(), "duracao_seg": pred.get("duracao_seg"), "erro": None}


def transcrever_volume(path: str) -> dict:
    """Transcreve um áudio do Volume de mídia da loja."""
    import posixpath
    caminho = posixpath.normpath(path or "")
    if not RX_CAMINHO.match(caminho) or not caminho.startswith(S.VOL_MIDIA.rstrip("/") + "/"):
        raise ValueError("Caminho de áudio inválido (use o Volume de mídia da loja).")
    return transcrever_bytes(S.download(caminho))


def analisar_atendimento(texto: str) -> dict:
    """Classifica, mede o sentimento e extrai pedido/produto/motivo de um texto de atendimento."""
    linhas = S.sql(f"""
        WITH a AS (SELECT ai_classify(:t, :cats, map('version', '2.0')) AS c, ai_analyze_sentiment(:t) AS sentimento,
                          ai_extract(:t, :campos, map('version', '2.1')) AS e)
        SELECT c:response[0]::string AS categoria, sentimento,
               upper(regexp_replace(coalesce(e:response.pedido_id.value::string, e:response.pedido_id::string, ''), '[^A-Za-z0-9]', '')) AS pedido_id,
               coalesce(e:response.produto.value::string, e:response.produto::string) AS produto,
               coalesce(e:response.motivo.value::string, e:response.motivo::string) AS motivo
        FROM a""", {"t": texto, "cats": CATEGORIAS, "campos": CAMPOS}, timeout_s=180)
    r = linhas[0] if linhas else {}
    r["pedido_id"] = r.get("pedido_id") or None
    return r


_PROTOCOLO_OK = {"ok": False}


def _garantir_protocolo() -> None:
    """A coluna protocolo liga a ligação à solicitação aberta no SAC (tabelas de instalações antigas não têm)."""
    if _PROTOCOLO_OK["ok"]:
        return
    cols = {c["col_name"] for c in S.sql(f"DESCRIBE TABLE {S.fq('atendimentos_voz')}")}
    if "protocolo" not in cols:
        S.sql(f"ALTER TABLE {S.fq('atendimentos_voz')} ADD COLUMNS (protocolo STRING)")
    _PROTOCOLO_OK["ok"] = True


def atendimentos(cliente_id: str | None = None, limite: int = 50) -> list[dict]:
    """Ligações (todas, no modo admin; ou de um cliente), com o nome do cliente e o protocolo do SAC, se houver."""
    _garantir_protocolo()
    filtro = "WHERE a.cliente_id = :c" if cliente_id else ""
    return S.sql(f"""SELECT a.arquivo, a.duracao_seg, a.transcricao, a.fonte_transcricao, a.categoria, a.sentimento, a.pedido_id,
                            a.status_pedido, a.produto, a.motivo, a.cliente_id, c.nome AS cliente_nome, a.protocolo, a.processado_em
                     FROM {S.fq('atendimentos_voz')} a LEFT JOIN {S.fq('clientes')} c USING (cliente_id)
                     {filtro} ORDER BY a.processado_em DESC, a.arquivo LIMIT {int(limite)}""",
                 {"c": cliente_id} if cliente_id else None)


def vincular(arquivo: str, protocolo: str, pedido_id: str, cliente_id: str) -> None:
    """Grava na ligação o protocolo aberto no SAC e o pedido/cliente corrigidos (se o Whisper errou o número)."""
    _garantir_protocolo()
    S.sql(f"""UPDATE {S.fq('atendimentos_voz')} SET protocolo = :pr, pedido_id = :p, cliente_id = :c,
                     status_pedido = (SELECT status FROM {lakebase.tabela('pedidos')} WHERE pedido_id = :p)
              WHERE arquivo = :a OR arquivo = regexp_extract(:a, '[^/]+$', 0)""",   # ligações prontas: só o nome do arquivo
          {"pr": protocolo, "p": pedido_id, "c": cliente_id, "a": arquivo})


def registrar(arquivo: str, transcricao: str, duracao_seg, analise: dict, cliente_id: str | None, fonte: str) -> None:
    """Grava o atendimento processado no App em atendimentos_voz (aparece na aba e no Genie)."""
    _garantir_protocolo()
    S.sql(f"""INSERT INTO {S.fq('atendimentos_voz')} (arquivo, duracao_seg, transcricao, fonte_transcricao, categoria, sentimento,
                                                     pedido_id, produto, motivo, cliente_id, status_pedido, processado_em)
              SELECT :arq, CAST(:dur AS DOUBLE), :txt, :fonte, :cat, :sent, :ped, :prod, :mot,
                     coalesce((SELECT cliente_id FROM {lakebase.tabela('pedidos')} WHERE pedido_id = :ped), :cli),
                     (SELECT status FROM {lakebase.tabela('pedidos')} WHERE pedido_id = :ped), current_timestamp()""",
          {"arq": arquivo, "dur": None if duracao_seg is None else str(duracao_seg), "txt": transcricao[:8000], "fonte": fonte,
           "cat": analise.get("categoria"), "sent": analise.get("sentimento"), "ped": analise.get("pedido_id"),
           "prod": analise.get("produto"), "mot": analise.get("motivo"), "cli": cliente_id})
