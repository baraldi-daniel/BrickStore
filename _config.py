# Databricks notebook source
# MAGIC %md
# MAGIC # ⚙️ _config · Configuração central do BrickStore (varejo)
# MAGIC
# MAGIC Todos os notebooks fazem `%run ./_config` e reaproveitam as variáveis abaixo. Os valores vêm do arquivo
# MAGIC **`config.yaml`** na raiz do repositório: **edite lá** se precisar (catálogo, schema, nomes dos Apps, modelos,
# MAGIC roteador, warehouse). Eles também aparecem como **widgets** no topo do `INSTALAR`, para trocar só numa execução.
# MAGIC
# MAGIC | Variável | Padrão | Para quê |
# MAGIC |----------|--------|----------|
# MAGIC | `CATALOG` | `brickstore` | Catálogo do Unity Catalog (é criado se não existir; se a criação falhar, usa `workspace`) |
# MAGIC | `SCHEMA` | `varejo` | Schema com todas as tabelas, volumes e índices do lab |
# MAGIC | `APP_NAME` | `brickstore` | Nome do Databricks App (vitrine de varejo + MCP Detetive de Produtos) |
# MAGIC | `MARCA` | `BrickStore` | Nome da loja fictícia (aparece no App, no Genie e nos dados) |
# MAGIC | `DOMINIO` | `brickstore.com.br` | Domínio fictício dos e-mails dos clientes (derivado da marca) |
# MAGIC | `LLM` | `databricks-llama-4-maverick` | Modelo **multimodal** com *tool calling* (visão do Detetive + agente) |
# MAGIC | `EMBEDDING` | `databricks-qwen3-embedding-0-6b` | Embeddings **multilíngues** do Vector Search (bom em português) |
# MAGIC | `VS_ENDPOINT` | `brickstore_vs` | Endpoint de Vector Search. Se o workspace permitir **só 1** e já existir outro, ele é reaproveitado |

# COMMAND ----------

import os as _os

# Caminho deste repositório dentro do workspace (Git folder / pasta importada).
_nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
REPO_ROOT = _os.path.dirname(_nb_path)
if _os.path.basename(REPO_ROOT) == "setup":        # quando um notebook de setup/ é aberto sozinho
    REPO_ROOT = _os.path.dirname(REPO_ROOT)
REPO_FS = "/Workspace" + REPO_ROOT if not REPO_ROOT.startswith("/Workspace") else REPO_ROOT


def _ler_config(caminho: str) -> dict:
    """Lê o config.yaml (formato simples `chave: valor  # comentário`, sem dependências)."""
    cfg = {}
    try:
        for linha in open(caminho, encoding="utf-8"):
            linha = linha.split("#", 1)[0].strip()
            if ":" in linha:
                k, v = linha.split(":", 1)
                cfg[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        print(f"⚠️ {caminho} não encontrado: usando os padrões internos")
    return cfg


CFG = {"catalog": "brickstore", "schema": "varejo", "app_name": "brickstore", "marca": "BrickStore",
       "mcp_app_name": "", "llm": "databricks-llama-4-maverick", "embedding": "databricks-qwen3-embedding-0-6b",
       "llm_juiz": "databricks-meta-llama-3-3-70b-instruct", "vs_endpoint": "brickstore_vs", "warehouse_id": "",
       "roteador_destino_a": "system.ai.llama-4-maverick", "roteador_destino_a_pct": "50",
       "roteador_destino_b": "system.ai.qwen3-next-80b-a3b-instruct", "roteador_destino_b_pct": "50",
       "roteador_fallback": "system.ai.gpt-oss-120b", "enterprise": "false",
       "whisper_modelo": "openai/whisper-large-v3-turbo", "whisper_compute": "CPU", "whisper_sempre_ligado": "true"}
CFG.update({k: v for k, v in _ler_config(f"{REPO_FS}/config.yaml").items() if v != "" or k == "warehouse_id"})

# Widgets: mostram o config.yaml e permitem trocar um valor só nesta execução
dbutils.widgets.text("catalog", CFG["catalog"], "1. Catálogo")
dbutils.widgets.text("schema", CFG["schema"], "2. Schema")
dbutils.widgets.text("app_name", CFG["app_name"], "3. Nome do App")
dbutils.widgets.text("llm", CFG["llm"], "4. LLM (visão + tools)")
dbutils.widgets.text("embedding", CFG["embedding"], "5. Modelo de embedding")
dbutils.widgets.text("vs_endpoint", CFG["vs_endpoint"], "6. Endpoint Vector Search")
dbutils.widgets.text("marca", CFG["marca"], "7. Marca (loja fictícia)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
APP_NAME = dbutils.widgets.get("app_name").strip()
LLM = dbutils.widgets.get("llm").strip()
EMBEDDING = dbutils.widgets.get("embedding").strip()
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint").strip()
MARCA = dbutils.widgets.get("marca").strip() or "BrickStore"
MCP_APP_NAME = CFG["mcp_app_name"] or ("mcp-detetive-produtos" if APP_NAME == "brickstore" else f"mcp-{APP_NAME}-detetive")
LLM_JUIZ = CFG["llm_juiz"]
ENTERPRISE = str(CFG["enterprise"]).strip().lower() in ("true", "sim", "yes", "1")   # extras do workspace corporativo
WHISPER_MODELO = CFG["whisper_modelo"]
WHISPER_COMPUTE = (CFG["whisper_compute"] or "CPU").strip().upper()
WHISPER_SEMPRE_LIGADO = str(CFG["whisper_sempre_ligado"]).strip().lower() in ("true", "sim", "yes", "1")   # False = scale to zero
WHISPER_ENDPOINT_NOME = f"{APP_NAME}-whisper"
WAREHOUSE_ID_CFG = CFG["warehouse_id"]
ROTEADOR = {"a": CFG["roteador_destino_a"], "a_pct": int(CFG["roteador_destino_a_pct"]),
            "b": CFG["roteador_destino_b"], "b_pct": int(CFG["roteador_destino_b_pct"]), "fallback": CFG["roteador_fallback"]}

# Catálogo: usa o informado (config.yaml / widget). Se não existir, tenta criar; se a conta não permitir,
# usa `workspace` quando ele existe (workspaces novos). Num workspace corporativo, informe um catálogo seu.
if spark.sql(f"SHOW CATALOGS LIKE '{CATALOG}'").count() == 0:
    try:
        spark.sql(f"CREATE CATALOG IF NOT EXISTS `{CATALOG}`")
    except Exception as _e:
        if spark.sql("SHOW CATALOGS LIKE 'workspace'").count() == 0:
            raise RuntimeError(f"O catálogo {CATALOG} não existe e não pude criá-lo ({str(_e)[:120]}). Informe em config.yaml "
                               "(chave catalog) ou no widget um catálogo em que você tenha USE CATALOG + CREATE SCHEMA.")
        print(f"⚠️ não foi possível criar o catálogo {CATALOG} ({str(_e)[:120]}) → usando 'workspace'")
        CATALOG = "workspace"

# COMMAND ----------

import os
import re
import unicodedata

# Domínio fictício derivado da marca: "BrickStore" -> "brickstore.com.br"
_slug = unicodedata.normalize("NFKD", MARCA).encode("ascii", "ignore").decode("ascii").lower()
_slug = re.sub(r"[^a-z0-9]", "", _slug) or "loja"
DOMINIO = f"{_slug}.com.br"


GENIE_TITLE = f"{MARCA} · Genie de Dados"
USUARIO = spark.sql("SELECT current_user()").first()[0]

def fq(nome):
    """Nome totalmente qualificado catalog.schema.nome."""
    return f"{CATALOG}.{SCHEMA}.{nome}"


# ── Estado do lab: ids dos recursos criados (Genie...), numa tabela do próprio schema. Assim cada etapa acha o
#    recurso QUE ESTA INSTALAÇÃO criou, e não um de outra pessoa com o mesmo título num workspace compartilhado.
def estado_gravar(chave: str, valor: str) -> None:
    spark.sql(f"CREATE TABLE IF NOT EXISTS {fq('_lab_estado')} (chave STRING, valor STRING, atualizado_em TIMESTAMP) "
              "COMMENT 'Ids dos recursos criados pelo INSTALAR (uso interno do lab)'")
    spark.sql(f"MERGE INTO {fq('_lab_estado')} t USING (SELECT :c AS chave, :v AS valor) s ON t.chave = s.chave "
              "WHEN MATCHED THEN UPDATE SET valor = s.valor, atualizado_em = current_timestamp() "
              "WHEN NOT MATCHED THEN INSERT (chave, valor, atualizado_em) VALUES (s.chave, s.valor, current_timestamp())",
              args={"c": chave, "v": valor})


def estado_ler(chave: str) -> str | None:
    try:
        r = spark.sql(f"SELECT valor FROM {fq('_lab_estado')} WHERE chave = :c", args={"c": chave}).collect()
        return r[0][0] if r else None
    except Exception:
        return None


def app_publicar(w, corpo: dict, alternativa: dict | None = None) -> str:
    """Cria ou atualiza um Databricks App (REST). Não mexe em App de OUTRA pessoa com o mesmo nome (workspace
    compartilhado): pede outro app_name. Se a criação falhar por limite de Apps (ex.: 3 no workspace gratuito),
    espera uma vaga por até 3 min. `alternativa`: corpo reserva (ex.: sem user_api_scopes) se o principal for recusado."""
    import time as _t
    nome = corpo["name"]
    try:
        atual = w.api_client.do("GET", f"/api/2.0/apps/{nome}")
    except Exception:
        atual = None
    dono = (atual or {}).get("creator")
    if dono and dono != USUARIO:
        raise RuntimeError(f"Já existe um App '{nome}' criado por {dono}. Use outro nome em config.yaml "
                           f"(app_name / mcp_app_name), por exemplo '{nome}-{re.sub(r'[^a-z0-9]', '', USUARIO.split('@')[0].lower())[:12]}'.")
    limite = lambda e: any(k in str(e).lower() for k in ("limit", "quota", "maximum", "exceed"))

    def chamar(b):
        if atual:
            return w.api_client.do("PATCH", f"/api/2.0/apps/{nome}", body=b)
        return w.api_client.do("POST", "/api/2.0/apps", body=b)

    for tentativa in range(12):
        try:
            try:
                chamar(corpo)
            except Exception as e:
                if not alternativa or limite(e):
                    raise
                print("⚠️ configuração recusada, usando a reserva:", str(e)[:160])
                chamar(alternativa)
            return "atualizado" if atual else "criado"
        except Exception as e:
            if atual or not limite(e):
                raise
            if tentativa == 11:
                raise RuntimeError(f"Limite de Apps do workspace atingido ({str(e)[:120]}). Apague um App que não use "
                                   "(Compute → Apps) ou troque app_name por um App seu e rode de novo.")
            print("⏳ limite de Apps atingido; aguardando uma vaga (15 s)…")
            _t.sleep(15)


def escolher_warehouse(w) -> str:
    """SQL warehouse usado pelas etapas: o do config.yaml (warehouse_id) ou o primeiro serverless (senão o primeiro)."""
    if WAREHOUSE_ID_CFG:
        return WAREHOUSE_ID_CFG
    whs = sorted(w.warehouses.list(), key=lambda x: (not bool(getattr(x, "enable_serverless_compute", False)), x.name or ""))
    if not whs:
        raise RuntimeError("Nenhum SQL warehouse no workspace: crie um em SQL Warehouses (serverless) ou informe warehouse_id no config.yaml")
    return whs[0].id


# ── Lakebase (etapa 05c): cada instalação cria um projeto NOVO, com o primeiro nome livre ──
#    <app_name>, <app_name>-2, <app_name>-3...  (nunca restaura nem reaproveita projeto antigo; as etapas
#    seguintes usam o projeto mais novo). O catálogo UC registrado é <catalog>_loja (ou _loja_2... se o nome estiver preso).
LAKEBASE_BASE = re.sub(r"[^a-z0-9-]", "-", APP_NAME.lower()).strip("-")[:56] or "loja"
_RX_LAKEBASE = re.compile(rf"^{re.escape(LAKEBASE_BASE)}(-\d+)?$")


def lakebase_projetos(w, incluir_lixeira: bool = False) -> list[dict]:
    """Projetos Lakebase deste lab QUE SÃO DO USUÁRIO ATUAL, do mais novo para o mais antigo
    (num workspace compartilhado, projetos de outras pessoas com o mesmo nome-base são ignorados)."""
    itens, token = [], None
    while True:
        r = w.api_client.do("GET", "/api/2.0/postgres/projects", query={"page_token": token} if token else None)
        itens += r.get("projects") or []
        token = r.get("next_page_token")
        if not token:
            break
    return sorted([p for p in itens if _RX_LAKEBASE.match(p.get("project_id", ""))
                   and (p.get("status") or {}).get("owner", USUARIO) == USUARIO
                   and (incluir_lixeira or not p.get("delete_time"))],
                  key=lambda p: p.get("create_time", ""), reverse=True)


def lakebase_atual(w) -> str | None:
    """project_id do projeto criado pela última execução da etapa 05c (o mais novo), ou None."""
    try:
        ps = lakebase_projetos(w)
    except Exception:
        return None
    return ps[0]["project_id"] if ps else None


def lakebase_catalogo(w, branch: str) -> str | None:
    """Catálogo UC registrado para este branch: <catalog>_loja, <catalog>_loja_2..."""
    for i in range(1, 6):
        nome = f"{CATALOG}_loja" + ("" if i == 1 else f"_{i}")
        try:
            c = w.api_client.do("GET", f"/api/2.0/postgres/catalogs/{nome}")
        except Exception:
            continue
        if branch in ((c.get("spec") or {}).get("branch"), (c.get("status") or {}).get("branch")):
            return nome
    return None

print(f"✅ config → {MARCA} | {CATALOG}.{SCHEMA} | app={APP_NAME} | domínio={DOMINIO} | llm={LLM} | emb={EMBEDDING}")
print(f"   repositório no workspace: {REPO_FS}")
