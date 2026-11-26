# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch", "psycopg[binary]>=3.2"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 06 · Databricks App + MCP "Detetive de Produtos"
# MAGIC
# MAGIC Implanta a pasta `app/` deste repositório como um **Databricks App** (FastAPI + HTML/JS):
# MAGIC
# MAGIC | Rota | O que é |
# MAGIC |------|---------|
# MAGIC | `/` | Vitrine da loja: perfis, departamentos, Detetive de Produtos, busca, **Estúdio** e assistente |
# MAGIC | `/mcp` | **Servidor MCP** "brickstore-detetive-de-produtos" (Streamable HTTP) para clientes externos |
# MAGIC | `/api/...` | API usada pelo frontend |
# MAGIC
# MAGIC O notebook:
# MAGIC 1. copia `app/` para uma pasta de implantação e grava o `app.yaml` com os valores reais;
# MAGIC 2. cria o App (se não existir) declarando os **recursos** (warehouse, modelos, Genie, volumes);
# MAGIC 3. concede à **service principal do App** as permissões no Unity Catalog e no Vector Search;
# MAGIC 4. faz o deploy e devolve a URL.
# MAGIC
# MAGIC > Alguns workspaces limitam a **3 Apps** e param o App após 24h (é só dar *Start*
# MAGIC > de novo na página do App, ou rodar este notebook).

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import os, shutil, time
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
# config.yaml → warehouse_id (vazio = primeiro SQL warehouse do workspace)
WAREHOUSE_ID = escolher_warehouse(w)

# GENIE_SPACE_ID e VS_ENDPOINT vêm das etapas anteriores quando rodado pelo INSTALAR.
try:
    GENIE_SPACE_ID
except NameError:
    GENIE_SPACE_ID = estado_ler("genie_space_id") or ""   # gravado pelo 05_genie
def _endpoint_do_indice(nome_indice, padrao):
    """Endpoint de Vector Search onde o índice desta instalação foi criado (etapa 04)."""
    try:
        return w.api_client.do("GET", f"/api/2.0/vector-search/indexes/{nome_indice}").get("endpoint_name") or padrao
    except Exception:
        return padrao
VS_ENDPOINT = _endpoint_do_indice(fq("produtos_index"), VS_ENDPOINT)
# Roteador de LLM (etapa 05b): model service no Unity Gateway usado pelo Assistente
try:
    ROTEADOR_LLM
except NameError:
    ROTEADOR_LLM = fq("assistente_llm")
if ROTEADOR_LLM:
    try:
        w.api_client.do("GET", f"/api/2.1/unity-catalog/model-services/{ROTEADOR_LLM}")
    except Exception:
        ROTEADOR_LLM = ""   # sem roteador: o App chama o LLM direto
# Recomendador servido (etapa 03c): endpoint de Model Serving com o pyfunc do modelo híbrido
RECOMENDADOR = f"{APP_NAME}-recomendador"
try:   # só se for seu e não tiver falhado (senão o App lê a tabela recomendacoes_personalizadas)
    _rec = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{RECOMENDADOR}")
    if _rec.get("creator") not in (None, USUARIO) or (_rec.get("state") or {}).get("config_update") == "UPDATE_FAILED":
        RECOMENDADOR = ""
except Exception:
    RECOMENDADOR = ""
# Lakebase (etapa 05c): pedidos novos no Postgres OLTP, lidos ao vivo pelo Lakehouse via catálogo <catalog>_loja
# (o projeto mais novo, criado pela última execução do 05c, e o catálogo UC registrado para ele)
LAKEBASE_PROJETO = lakebase_atual(w) or ""
LAKEBASE_BRANCH = f"projects/{LAKEBASE_PROJETO}/branches/production"
LAKEBASE_CATALOGO = lakebase_catalogo(w, LAKEBASE_BRANCH) if LAKEBASE_PROJETO else None
if not LAKEBASE_CATALOGO or not spark.catalog.tableExists(fq("vw_pedidos_todos")):
    LAKEBASE_PROJETO = ""   # sem Lakebase (ou sem as views): o App grava e lê os pedidos só no Delta
# Whisper (etapa 02b, só com enterprise: true): o App usa no SAC por voz
WHISPER_EP = (estado_ler("whisper_endpoint") or "") if ENTERPRISE else ""
if WHISPER_EP:
    try:
        w.api_client.do("GET", f"/api/2.0/serving-endpoints/{WHISPER_EP}")
    except Exception:
        WHISPER_EP = ""
print("warehouse:", WAREHOUSE_ID, "| genie:", GENIE_SPACE_ID, "| vs:", VS_ENDPOINT, "| roteador:", ROTEADOR_LLM or "—",
      "| recomendador:", RECOMENDADOR or "—", "| lakebase:", LAKEBASE_PROJETO or "—")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1) Pasta de implantação com o `app.yaml` preenchido

# COMMAND ----------

DEPLOY_DIR = f"/Workspace/Users/{USUARIO}/.{APP_NAME}_app"
if os.path.exists(DEPLOY_DIR):
    shutil.rmtree(DEPLOY_DIR)
shutil.copytree(f"{REPO_FS}/app", DEPLOY_DIR, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))

APP_YAML = f"""command: ["python", "main.py"]
env:
  - name: NB_MARCA
    value: "{MARCA}"
  - name: NB_CATALOG
    value: "{CATALOG}"
  - name: NB_SCHEMA
    value: "{SCHEMA}"
  - name: NB_LLM
    value: "{LLM}"
  - name: NB_EMBEDDING
    value: "{EMBEDDING}"
  - name: NB_VS_ENDPOINT
    value: "{VS_ENDPOINT}"
  - name: NB_LLM_JUIZ
    value: "{LLM_JUIZ}"
  - name: NB_LLM_CHAT
    value: "{ROTEADOR_LLM}"
  - name: NB_GENIE_SPACE_ID
    value: "{GENIE_SPACE_ID}"
  - name: NB_RECOMENDADOR
    value: "{RECOMENDADOR}"
  - name: NB_WHISPER
    value: "{WHISPER_EP}"
  - name: NB_WAREHOUSE_ID
    valueFrom: sql-warehouse
"""
if LAKEBASE_PROJETO:
    APP_YAML += f"""  - name: NB_LAKEBASE
    value: "loja"
  - name: NB_LAKEBASE_CATALOG
    value: "{LAKEBASE_CATALOGO}"
  - name: NB_LAKEBASE_ENDPOINT
    value: "{LAKEBASE_BRANCH}/endpoints/primary"
"""
with open(f"{DEPLOY_DIR}/app.yaml", "w") as f:
    f.write(APP_YAML)
print("✅ código em", DEPLOY_DIR)
print(APP_YAML)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2) Criar o App com os recursos

# COMMAND ----------

# API REST direta: funciona com qualquer versão do databricks-sdk (o padrão do serverless é antigo).
def rest(metodo, caminho, corpo=None):
    return w.api_client.do(metodo, caminho, body=corpo) if corpo is not None else w.api_client.do(metodo, caminho)

recursos = [
    {"name": "sql-warehouse", "sql_warehouse": {"id": WAREHOUSE_ID, "permission": "CAN_USE"}},
    {"name": "llm", "serving_endpoint": {"name": LLM, "permission": "CAN_QUERY"}},
    {"name": "embedding", "serving_endpoint": {"name": EMBEDDING, "permission": "CAN_QUERY"}},
    {"name": "volume-midia", "uc_securable": {"securable_full_name": f"{CATALOG}.{SCHEMA}.midia",
                                              "securable_type": "VOLUME", "permission": "WRITE_VOLUME"}},
    {"name": "volume-documentos", "uc_securable": {"securable_full_name": f"{CATALOG}.{SCHEMA}.documentos",
                                                   "securable_type": "VOLUME", "permission": "WRITE_VOLUME"}},
]
recursos.append({"name": "juiz-guardrail", "serving_endpoint": {"name": LLM_JUIZ, "permission": "CAN_QUERY"}})   # config.yaml → llm_juiz
if ROTEADOR_LLM:
    recursos.append({"name": "roteador-llm", "uc_securable": {"securable_full_name": ROTEADOR_LLM,
                                                              "securable_type": "MODEL_SERVICE", "permission": "EXECUTE"}})
if RECOMENDADOR:
    recursos.append({"name": "recomendador", "serving_endpoint": {"name": RECOMENDADOR, "permission": "CAN_QUERY"}})
if WHISPER_EP:
    recursos.append({"name": "whisper", "serving_endpoint": {"name": WHISPER_EP, "permission": "CAN_QUERY"}})
if GENIE_SPACE_ID:
    recursos.append({"name": "genie", "genie_space": {"name": GENIE_TITLE, "space_id": GENIE_SPACE_ID, "permission": "CAN_RUN"}})
if LAKEBASE_PROJETO:   # injeta PGHOST / PGDATABASE / PGUSER / LAKEBASE_ENDPOINT no App
    recursos.append({"name": "lakebase", "postgres": {"branch": LAKEBASE_BRANCH,
                                                       "database": f"{LAKEBASE_BRANCH}/databases/databricks-postgres",
                                                       "permission": "CAN_CONNECT_AND_CREATE"}})

DESCRICAO = f"{MARCA} — loja de departamentos fictícia com Detetive de Produtos (MCP), quem comprou também comprou e Estúdio (ai_parse_document)."
# Autorização de usuário: o App age EM NOME de quem está usando só para criar o evento "Chega hoje" no
# Google Calendar dessa pessoa (conector MCP system.ai.google_calendar do Unity Gateway). Se o workspace
# recusar o escopo, a reserva publica sem ele (o botão de agenda usa link/.ics).
ESCOPOS_USUARIO = ["ai-gateway"]
corpo_app = {"name": APP_NAME, "description": DESCRICAO, "resources": recursos, "user_api_scopes": ESCOPOS_USUARIO}
print(f"App {APP_NAME}:", app_publicar(w, corpo_app, {k: v for k, v in corpo_app.items() if k != "user_api_scopes"}),
      "(o compute do App leva ~2-4 min para subir)")


def estado_compute():
    return (rest("GET", f"/api/2.0/apps/{APP_NAME}").get("compute_status") or {}).get("state")


inicio = time.time()
while estado_compute() in ("STARTING", "UPDATING", None) and time.time() - inicio < 900:
    time.sleep(15)
if estado_compute() in ("STOPPED", "ERROR"):
    print("▶ iniciando o compute do App...")
    rest("POST", f"/api/2.0/apps/{APP_NAME}/start", {})
    while estado_compute() != "ACTIVE" and time.time() - inicio < 1200:
        time.sleep(15)
app = rest("GET", f"/api/2.0/apps/{APP_NAME}")
SP = app["service_principal_client_id"]
print("compute:", estado_compute(), "| service principal do App:", app.get("service_principal_name"), SP)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3) Permissões da service principal do App
# MAGIC Os *resources* já cobrem warehouse, modelos, Genie e volumes. Aqui completamos o acesso às tabelas
# MAGIC (leitura + escrita para o Estúdio e as compras) e ao endpoint de Vector Search.

# COMMAND ----------

for g in [f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{SP}`",
          f"GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA {CATALOG}.{SCHEMA} TO `{SP}`",
          f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {CATALOG}.{SCHEMA}.midia TO `{SP}`",
          f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {CATALOG}.{SCHEMA}.documentos TO `{SP}`"]:
    spark.sql(g)
    print("✓", g)

if LAKEBASE_PROJETO:   # Lakebase: SP lê/grava o schema loja no Postgres e lê o catálogo registrado no UC
    import psycopg
    _ep = f"{LAKEBASE_BRANCH}/endpoints/primary"
    _host = w.api_client.do("GET", f"/api/2.0/postgres/{_ep}")["status"]["hosts"]["host"]
    _tok = w.postgres.generate_database_credential(endpoint=_ep).token
    for _ in range(12):   # o role da SP é criado quando o recurso postgres é anexado
        with psycopg.connect(host=_host, dbname="databricks_postgres", user=USUARIO, password=_tok, sslmode="require", autocommit=True) as c:
            if c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (SP,)).fetchone():
                c.execute(f'GRANT USAGE ON SCHEMA loja TO "{SP}"')
                c.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA loja TO "{SP}"')
                c.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA loja GRANT SELECT, INSERT, UPDATE ON TABLES TO "{SP}"')
                if c.execute("SELECT to_regclass('loja.conversas')").fetchone()[0]:   # memória do chat: botão "esquecer"
                    c.execute(f'GRANT DELETE ON loja.conversas TO "{SP}"')
                print("✓ Lakebase: SP com SELECT/INSERT/UPDATE no schema loja")
                break
        time.sleep(10)
    else:
        print("⚠️ role da SP ainda não existe no Lakebase — rode esta célula de novo em 1 minuto")
    for g in [f"GRANT USE CATALOG ON CATALOG {LAKEBASE_CATALOGO} TO `{SP}`",
              f"GRANT USE SCHEMA, SELECT ON SCHEMA {LAKEBASE_CATALOGO}.loja TO `{SP}`"]:
        try:
            spark.sql(g)
        except Exception as e:
            print("⚠️", g, "→", str(e)[:150], "(peça ao dono do catálogo para conceder)")
        print("✓", g)

from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
try:
    ep_id = w.vector_search_endpoints.get_endpoint(VS_ENDPOINT).id
    w.permissions.update("vector-search-endpoints", ep_id, access_control_list=[
        AccessControlRequest(service_principal_name=SP, permission_level=PermissionLevel.CAN_MANAGE)])
    print(f"✓ CAN_MANAGE no endpoint de Vector Search {VS_ENDPOINT} (consulta + sync dos índices pelo Estúdio)")
except Exception as e:
    print("⚠️ permissão no endpoint de Vector Search:", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 4) Deploy

# COMMAND ----------

print("🚀 deploy em andamento (instala as dependências e sobe o FastAPI)...")
dep = rest("POST", f"/api/2.0/apps/{APP_NAME}/deployments", {"source_code_path": DEPLOY_DIR, "mode": "SNAPSHOT"})
inicio = time.time()
while True:
    st = rest("GET", f"/api/2.0/apps/{APP_NAME}/deployments/{dep['deployment_id']}").get("status", {})
    if st.get("state") not in ("IN_PROGRESS", "PENDING", None) or time.time() - inicio > 1200:
        break
    time.sleep(15)
print("deploy:", st.get("state"), "-", st.get("message"))
if st.get("state") != "SUCCEEDED":
    raise RuntimeError(f"Deploy do App falhou: {st}. Veja os logs em Compute → Apps → {APP_NAME} → Logs.")
APP_URL = rest("GET", f"/api/2.0/apps/{APP_NAME}")["url"]
print("✅ App no ar:", APP_URL)
print("   MCP:", APP_URL + "/mcp")
displayHTML(f'<a href="{APP_URL}" target="_blank" style="font-size:16px;font-weight:700">🛍️ Abrir a {MARCA} →</a>')

# COMMAND ----------

# MAGIC %md
# MAGIC ### 📅 Passo manual: Google Calendar
# MAGIC Para o botão *📅 Adicionar a chegada à minha agenda* criar o evento direto na **sua** agenda:
# MAGIC 1. *AI Gateway → MCP → `system.ai.google_calendar` → Connect* (login Google, uma vez por usuário);
# MAGIC 2. *Compute → Apps → App → Edit → User authorization*: confira o escopo **`ai-gateway`** (este notebook já tenta pôr) → Save → Deploy.
# MAGIC
# MAGIC Sem isso, o botão usa o modo reserva: link "Google Agenda" já preenchido + arquivo .ics.

# COMMAND ----------

_escopos = (rest("GET", f"/api/2.0/apps/{APP_NAME}").get("user_api_scopes") or [])
print("📅 Google Calendar:", "✅ escopo ai-gateway configurado no App" if "ai-gateway" in _escopos else
      "⚠️ escopo ai-gateway AUSENTE — faça o passo manual acima (Compute → Apps → Edit → User authorization)")

