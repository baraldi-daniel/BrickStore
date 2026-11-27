"""
Camada de acesso aos serviços Databricks usados pelo App.

Tudo roda com a **service principal do App** (credenciais injetadas automaticamente pelo
Databricks Apps). As permissões dela são concedidas pelo notebook `setup/06_app`.

  • SQL Warehouse  → leitura/escrita das tabelas Delta (Statement Execution API)
  • Vector Search  → busca semântica nos produtos e na central de ajuda
  • Model Serving  → LLM multimodal (Llama 4 Maverick) via API compatível com OpenAI
  • Volumes UC     → fotos de produtos, imagens do Detetive e PDFs
  • Genie          → perguntas em linguagem natural sobre os dados
"""
import base64
import io
import json
import logging
import os
import re
import time
from functools import lru_cache

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (Disposition, Format, StatementParameterListItem,
                                        StatementState)

log = logging.getLogger("varejo")

MARCA = os.environ.get("NB_MARCA", "BrickStore")
CATALOG = os.environ.get("NB_CATALOG", "brickstore")
SCHEMA = os.environ.get("NB_SCHEMA", "varejo")
LLM = os.environ.get("NB_LLM", "databricks-llama-4-maverick")
# Roteador do Unity Gateway (model service com routing + fallback + inference table) usado pelo Assistente
LLM_CHAT = os.environ.get("NB_LLM_CHAT", "")
# destinos do roteador (06_app): permitem ao admin chamar UM modelo direto, sem o roteador (e sem as service policies dele)
DESTINOS_ROTEADOR = [m for m in os.environ.get("NB_ROTEADOR_DESTINOS", "").split(",") if m.strip()]
MODELO_ASSISTENTE = {"atual": LLM_CHAT or LLM}   # 🛠️ o admin troca no Estúdio (vale até o App reiniciar)


def _nome_curto(m: str) -> str:
    """system.ai.llama-4-maverick → Llama 4 Maverick"""
    n = m.split(".")[-1].replace("databricks-", "")
    return " ".join(p.upper() if p in ("gpt", "oss") else p.capitalize() for p in n.replace("_", "-").split("-"))


def opcoes_modelo() -> list[dict]:
    ops = []
    if LLM_CHAT:
        ops.append({"id": LLM_CHAT, "nome": f"Roteador {LLM_CHAT.split('.')[-1]} (50/50 + fallback + policies)"})
    for m in DESTINOS_ROTEADOR:
        ops.append({"id": m, "nome": f"{_nome_curto(m)} direto (sem roteador)"})
    ops.append({"id": LLM, "nome": f"{_nome_curto(LLM)} pelo endpoint (sem Unity Gateway)"})
    vistos = set()
    return [o for o in ops if not (o["id"] in vistos or vistos.add(o["id"]))]
EMBEDDING = os.environ.get("NB_EMBEDDING", "databricks-qwen3-embedding-0-6b")
VS_ENDPOINT = os.environ.get("NB_VS_ENDPOINT", "brickstore_vs")
GENIE_SPACE_ID = os.environ.get("NB_GENIE_SPACE_ID", "")
# Endpoint de Model Serving com o recomendador (pyfunc da etapa 03c); vazio = lê a tabela recomendacoes_personalizadas
RECOMENDADOR = os.environ.get("NB_RECOMENDADOR", "")
WAREHOUSE_ID = os.environ.get("NB_WAREHOUSE_ID", "")
IDX_PRODUTOS = f"{CATALOG}.{SCHEMA}.produtos_index"
IDX_AJUDA = f"{CATALOG}.{SCHEMA}.ajuda_index"
VOL_MIDIA = f"/Volumes/{CATALOG}/{SCHEMA}/midia"
VOL_DOCS = f"/Volumes/{CATALOG}/{SCHEMA}/documentos"


def dominio() -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", MARCA).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", base) + ".com.br"


def fq(nome: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{nome}"


@lru_cache(maxsize=1)
def ws() -> WorkspaceClient:
    return WorkspaceClient()


def recomendar_endpoint(cliente_id: str, n: int, timeout_s: float = 6) -> list[dict]:
    """Consulta o endpoint de Model Serving do recomendador. Timeout curto: com scale-to-zero, o 1º acesso pode demorar."""
    import requests
    cab = {**ws().config.authenticate(), "Content-Type": "application/json"}
    r = requests.post(f"{ws().config.host.rstrip('/')}/serving-endpoints/{RECOMENDADOR}/invocations", headers=cab,
                      json={"dataframe_records": [{"cliente_id": cliente_id, "quantidade": int(n)}]}, timeout=timeout_s)
    r.raise_for_status()
    return r.json().get("predictions") or []


def estado_endpoint(nome: str) -> dict:
    try:
        e = ws().api_client.do("GET", f"/api/2.0/serving-endpoints/{nome}")
        st = e.get("state") or {}
        ent = ((e.get("config") or {}).get("served_entities") or [{}])[0]
        return {"nome": nome, "pronto": st.get("ready") == "READY", "estado": st.get("ready"), "atualizacao": st.get("config_update"),
                "modelo": f"{ent.get('entity_name', '')} v{ent.get('entity_version', '')}".strip(),
                "url": f"{ws().config.host.rstrip('/')}/ml/endpoints/{nome}"}
    except Exception as ex:
        return {"nome": nome, "pronto": False, "estado": "indisponível", "erro": str(ex)[:160]}


def warehouse_id() -> str:
    global WAREHOUSE_ID
    if not WAREHOUSE_ID:
        WAREHOUSE_ID = next(iter(ws().warehouses.list())).id
    return WAREHOUSE_ID


# ───────────────────────────── SQL ─────────────────────────────
_CONV = {"INT": int, "LONG": int, "SHORT": int, "BYTE": int, "BIGINT": int,
         "DOUBLE": float, "FLOAT": float, "DECIMAL": float,
         "BOOLEAN": lambda v: str(v).lower() == "true"}


def _param(nome, valor):
    if valor is None:
        return StatementParameterListItem(name=nome, value=None, type="STRING")
    if isinstance(valor, bool):
        return StatementParameterListItem(name=nome, value=str(valor).lower(), type="BOOLEAN")
    if isinstance(valor, int):
        return StatementParameterListItem(name=nome, value=str(valor), type="INT")
    if isinstance(valor, float):
        return StatementParameterListItem(name=nome, value=str(valor), type="DOUBLE")
    return StatementParameterListItem(name=nome, value=str(valor), type="STRING")


def sql(query: str, params: dict | None = None, timeout_s: int = 180) -> list[dict]:
    """Executa SQL no warehouse e devolve lista de dicts (com tipos convertidos)."""
    w = ws()
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id(), statement=query, wait_timeout="50s",
        parameters=[_param(k, v) for k, v in (params or {}).items()] or None,
        format=Format.JSON_ARRAY, disposition=Disposition.INLINE)
    inicio = time.time()
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() - inicio > timeout_s:
            w.statement_execution.cancel_execution(resp.statement_id)
            raise TimeoutError("consulta SQL demorou demais")
        time.sleep(1)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL falhou: {resp.status.error.message if resp.status.error else resp.status.state}")
    if not resp.manifest or not resp.manifest.schema or not resp.manifest.schema.columns:
        return []
    cols = [(c.name, (c.type_name.value if c.type_name else "STRING")) for c in resp.manifest.schema.columns]
    linhas = list((resp.result.data_array if resp.result else None) or [])
    chunk = resp.result.next_chunk_index if resp.result else None
    while chunk is not None:
        r = w.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk)
        linhas.extend(r.data_array or [])
        chunk = r.next_chunk_index
    out = []
    for l in linhas:
        d = {}
        for (nome, tipo), v in zip(cols, l):
            conv = _CONV.get(tipo)
            d[nome] = conv(v) if (v is not None and conv) else v
        out.append(d)
    return out


# ─────────────────────────── Vector Search ───────────────────────────
def vs_query(index_name: str, columns: list[str], texto: str, n: int = 8, filtros: dict | None = None) -> list[dict]:
    kw = dict(index_name=index_name, columns=columns, query_text=texto, num_results=n)
    if filtros:
        kw["filters_json"] = json.dumps(filtros)
    resp = ws().vector_search_indexes.query_index(**kw)
    nomes = [c.name for c in (resp.manifest.columns or [])] if resp.manifest else columns + ["score"]
    return [dict(zip(nomes, r)) for r in ((resp.result.data_array if resp.result else None) or [])]


def vs_sync(index_name: str) -> str:
    try:
        ws().vector_search_indexes.sync_index(index_name)
        return "sincronização iniciada"
    except Exception as e:  # sync já em andamento, por exemplo
        return f"não foi possível sincronizar agora: {str(e)[:160]}"


def vs_status(index_name: str) -> dict:
    try:
        idx = ws().vector_search_indexes.get_index(index_name)
        st = idx.status
        return {"nome": index_name, "pronto": bool(st and st.ready), "linhas": (st.indexed_row_count if st else None),
                "mensagem": (st.message if st else "").split(". Check latest status")[0][:120]}
    except Exception as e:
        return {"nome": index_name, "pronto": False, "linhas": None, "mensagem": str(e)[:200]}


# ─────────────────────────────── LLM ───────────────────────────────
@lru_cache(maxsize=1)
def llm_client():
    return ws().serving_endpoints.get_open_ai_client()


def chat(messages, tools=None, max_tokens=1200, temperature=0.2, tentativas=4, tool_choice=None):
    """Chamada ao LLM com nova tentativa em caso de limite de taxa (HTTP 429 — comum com cota baixa)."""
    kw = dict(model=LLM, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if tools:
        kw["tools"] = tools
        if tool_choice:
            kw["tool_choice"] = tool_choice
    for i in range(tentativas):
        try:
            return llm_client().chat.completions.create(**kw)
        except Exception as e:
            limite = "429" in str(e) or "RateLimit" in type(e).__name__ or "REQUEST_LIMIT" in str(e)
            if not limite or i == tentativas - 1:
                raise
            time.sleep(2 * (i + 1))


def chat_assistente(messages, tools=None, max_tokens=1400, temperature=0.2, tool_choice=None):
    """Chat do Assistente via **roteador do Unity Gateway** (API unificada /ai-gateway/mlflow/v1, nome UC de 3 partes).

    O gateway escolhe o destino (50% Llama 4 Maverick / 50% Qwen3-Next) e cai no fallback (GPT OSS 120B) se
    algo falhar. Se o roteador não estiver configurado ou falhar, usa o LLM direto. Devolve (resposta, modelo)."""
    modelo = MODELO_ASSISTENTE["atual"]
    if "." in modelo:   # nome do Unity Catalog (roteador <catalog>.<schema>.assistente_llm ou system.ai.*): API unificada
        try:
            from openai import OpenAI
            w = ws()
            token = w.config.authenticate()["Authorization"].split(" ", 1)[1]
            cli = OpenAI(api_key=token, base_url=f"{w.config.host.rstrip('/')}/ai-gateway/mlflow/v1")
            kw = dict(model=modelo, messages=messages, max_tokens=max_tokens, temperature=temperature)
            if tools:
                kw["tools"] = tools
                if tool_choice:
                    kw["tool_choice"] = tool_choice
            r = cli.chat.completions.create(**kw)
            if modelo == LLM_CHAT:
                return r, f"{getattr(r, 'model', '') or 'roteador'} (via {LLM_CHAT.split('.')[-1]})"
            return r, f"{modelo.split('.')[-1]} (direto, sem roteador)"
        except Exception as e:
            log.warning("modelo %s falhou (%s); usando %s direto", modelo, str(e)[:120], LLM)
    return chat(messages, tools, max_tokens, temperature, tool_choice=tool_choice), LLM


def extrair_json(texto: str) -> dict:
    """Extrai o primeiro objeto JSON de uma resposta do LLM (tolerante a ```json ... ```)."""
    if not texto:
        return {}
    texto = re.sub(r"```(?:json)?", "", texto)
    ini, fim = texto.find("{"), texto.rfind("}")
    if ini < 0 or fim <= ini:
        return {}
    try:
        return json.loads(texto[ini:fim + 1])
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", texto[ini:fim + 1]))
        except Exception:
            return {}


# ─────────────────────────── Volumes (arquivos) ───────────────────────────
def upload(caminho: str, dados: bytes):
    ws().files.upload(caminho, io.BytesIO(dados), overwrite=True)


def download(caminho: str) -> bytes:
    return ws().files.download(caminho).contents.read()


def normalizar_imagem(dados: bytes, lado_max: int = 1024) -> bytes:
    """Reduz e converte para JPEG (menos tokens para o modelo de visão, upload mais leve)."""
    from PIL import Image
    img = Image.open(io.BytesIO(dados))
    img = img.convert("RGB")
    img.thumbnail((lado_max, lado_max))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


# ─────────────────────────────── Genie ───────────────────────────────
async def perguntar_genie_mcp(pergunta: str, timeout_s: int = 120) -> dict:
    """Pergunta ao Genie pelo **servidor MCP gerenciado** do Genie Agent (/api/2.0/mcp/genie/<space_id>).

    Ferramentas expostas pela Databricks: query_space_<id> (pergunta) e poll_response_<id> (acompanha até concluir)."""
    import asyncio
    import httpx2
    from mcp.client.client import Client
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    w = ws()
    url = f"{w.config.host.rstrip('/')}/api/2.0/mcp/genie/{GENIE_SPACE_ID}"
    inicio = time.time()

    def ler(r):
        return r.structured_content or json.loads(r.content[0].text)
    async with create_mcp_http_client(headers=w.config.authenticate(), timeout=httpx2.Timeout(timeout_s)) as http:
        async with Client(streamable_http_client(url, http_client=http)) as c:
            d = ler(await c.call_tool(f"query_space_{GENIE_SPACE_ID}", {"query": pergunta}))
            while d.get("status") not in ("COMPLETED", "FAILED", "CANCELLED") and time.time() - inicio < timeout_s:
                await asyncio.sleep(2)
                d = ler(await c.call_tool(f"poll_response_{GENIE_SPACE_ID}",
                                          {"conversation_id": d["conversationId"], "message_id": d["messageId"]}))
    conteudo = d.get("content") or {}
    if isinstance(conteudo, str):
        try:
            conteudo = json.loads(conteudo)
        except Exception:
            conteudo = {"textAttachments": [conteudo]}
    out = {"via": "MCP do Genie", "status": d.get("status"), "texto": [], "sql": None, "colunas": [], "linhas": []}
    for t in conteudo.get("textAttachments") or []:
        out["texto"].append(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False))
    for q in conteudo.get("queryAttachments") or []:
        out["sql"] = q.get("query")
        if q.get("description"):
            out["texto"].append(q["description"])
        sr = q.get("statement_response") or {}
        out["colunas"] = [col["name"] for col in ((sr.get("manifest") or {}).get("schema") or {}).get("columns", [])]
        out["linhas"] = ((sr.get("result") or {}).get("data_array") or [])[:30]
    out["texto"] = "\n".join(out["texto"])
    return out


def perguntar_genie(pergunta: str) -> dict:
    if not GENIE_SPACE_ID:
        return {"erro": "Genie não configurado (NB_GENIE_SPACE_ID vazio)."}
    w = ws()
    msg = w.genie.start_conversation_and_wait(GENIE_SPACE_ID, pergunta)
    out = {"texto": [], "sql": None, "colunas": [], "linhas": []}
    for att in msg.attachments or []:
        if att.text and att.text.content:
            out["texto"].append(att.text.content)
        if att.query:
            out["sql"] = att.query.query
            if att.query.description:
                out["texto"].append(att.query.description)
            try:
                res = w.genie.get_message_attachment_query_result(GENIE_SPACE_ID, msg.conversation_id, msg.id, att.attachment_id)
                sr = res.statement_response
                if sr and sr.manifest and sr.manifest.schema:
                    out["colunas"] = [c.name for c in sr.manifest.schema.columns]
                if sr and sr.result and sr.result.data_array:
                    out["linhas"] = sr.result.data_array[:30]
            except Exception as e:
                out["erro_resultado"] = str(e)[:200]
    out["texto"] = "\n".join(out["texto"])
    return out
