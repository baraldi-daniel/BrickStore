# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 06b · App próprio do MCP "Detetive de Produtos" (`mcp-detetive-produtos`)
# MAGIC
# MAGIC O App da loja já expõe o MCP em `/mcp`. Aqui publicamos o **mesmo servidor MCP** num **Databricks App só
# MAGIC dele**, com nome começando por `mcp-`. É esse prefixo que faz o servidor aparecer no **AI Playground**:
# MAGIC
# MAGIC > **Playground** → escolha um modelo com *tools* (ex.: GPT OSS 120B ou Llama 4 Maverick) → **Tools** →
# MAGIC > **+ Add tool** → **MCP servers** → **Databricks Apps** → `mcp-detetive-produtos`
# MAGIC
# MAGIC | Rota | O que é |
# MAGIC |------|---------|
# MAGIC | `/` | Página com a descrição do servidor e a lista das 9 ferramentas |
# MAGIC | `/mcp` | Servidor MCP (Streamable HTTP) |
# MAGIC | `/api/saude` | Catálogo carregado? |
# MAGIC
# MAGIC O código é a mesma pasta `app/` do App da loja; muda só o comando de entrada (`python mcp_main.py`).
# MAGIC
# MAGIC > Alguns workspaces limitam a **3 Apps** (aqui usamos 2: a loja e o MCP) e param o App após 24h:
# MAGIC > é só dar *Start* de novo na página do App, ou rodar este notebook.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import os, shutil, time
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
MCP_APP = MCP_APP_NAME   # config.yaml → mcp_app_name
WAREHOUSE_ID = escolher_warehouse(w)
def _endpoint_do_indice(nome_indice, padrao):
    """Endpoint de Vector Search onde o índice desta instalação foi criado (etapa 04)."""
    try:
        return w.api_client.do("GET", f"/api/2.0/vector-search/indexes/{nome_indice}").get("endpoint_name") or padrao
    except Exception:
        return padrao
VS_ENDPOINT = _endpoint_do_indice(fq("produtos_index"), VS_ENDPOINT)
RECOMENDADOR = f"{APP_NAME}-recomendador"
try:
    w.api_client.do("GET", f"/api/2.0/serving-endpoints/{RECOMENDADOR}")
except Exception:
    RECOMENDADOR = ""   # sem endpoint: a ferramenta recomendar_para_cliente lê a tabela
print("App MCP:", MCP_APP, "| warehouse:", WAREHOUSE_ID, "| vs:", VS_ENDPOINT, "| recomendador:", RECOMENDADOR or "—")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1) Pasta de implantação com o `app.yaml` do MCP

# COMMAND ----------

MCP_DEPLOY_DIR = f"/Workspace/Users/{USUARIO}/.mcp_detetive_app"
if os.path.exists(MCP_DEPLOY_DIR):
    shutil.rmtree(MCP_DEPLOY_DIR)
shutil.copytree(f"{REPO_FS}/app", MCP_DEPLOY_DIR, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "app.yaml"))

MCP_APP_YAML = f"""command: ["python", "mcp_main.py"]
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
  - name: NB_RECOMENDADOR
    value: "{RECOMENDADOR}"
  - name: NB_WAREHOUSE_ID
    valueFrom: sql-warehouse
"""
with open(f"{MCP_DEPLOY_DIR}/app.yaml", "w") as f:
    f.write(MCP_APP_YAML)
print("✅ código em", MCP_DEPLOY_DIR)
print(MCP_APP_YAML)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2) Criar/atualizar o App com os recursos

# COMMAND ----------

def rest(metodo, caminho, corpo=None):
    return w.api_client.do(metodo, caminho, body=corpo) if corpo is not None else w.api_client.do(metodo, caminho)

recursos_mcp = [
    {"name": "sql-warehouse", "sql_warehouse": {"id": WAREHOUSE_ID, "permission": "CAN_USE"}},
    {"name": "llm", "serving_endpoint": {"name": LLM, "permission": "CAN_QUERY"}},
    {"name": "embedding", "serving_endpoint": {"name": EMBEDDING, "permission": "CAN_QUERY"}},
    {"name": "volume-midia", "uc_securable": {"securable_full_name": f"{CATALOG}.{SCHEMA}.midia",
                                              "securable_type": "VOLUME", "permission": "WRITE_VOLUME"}},
    {"name": "volume-documentos", "uc_securable": {"securable_full_name": f"{CATALOG}.{SCHEMA}.documentos",
                                                   "securable_type": "VOLUME", "permission": "WRITE_VOLUME"}},
]
if RECOMENDADOR:
    recursos_mcp.append({"name": "recomendador", "serving_endpoint": {"name": RECOMENDADOR, "permission": "CAN_QUERY"}})

corpo_mcp = {"name": MCP_APP, "resources": recursos_mcp,
             "description": f"{MARCA} · Servidor MCP Detetive de Produtos: busca visual (foto → produtos parecidos), busca semântica, "
                            "quem comprou também comprou, recomendação ML e pós-venda."}
print(f"App {MCP_APP}:", app_publicar(w, corpo_mcp), "(o compute leva ~2-4 min para subir)")


def estado_mcp():
    return (rest("GET", f"/api/2.0/apps/{MCP_APP}").get("compute_status") or {}).get("state")


inicio = time.time()
while estado_mcp() in ("STARTING", "UPDATING", None) and time.time() - inicio < 900:
    time.sleep(15)
if estado_mcp() in ("STOPPED", "ERROR"):
    print("▶ iniciando o compute do App...")
    rest("POST", f"/api/2.0/apps/{MCP_APP}/start", {})
    while estado_mcp() != "ACTIVE" and time.time() - inicio < 1200:
        time.sleep(15)
app_mcp = rest("GET", f"/api/2.0/apps/{MCP_APP}")
SP_MCP = app_mcp["service_principal_client_id"]
print("compute:", estado_mcp(), "| service principal:", app_mcp.get("service_principal_name"), SP_MCP)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3) Permissões da service principal do App MCP
# MAGIC Leitura do catálogo e escrita só onde as ferramentas gravam (`solicitacoes_atendimento`, imagens no Volume).

# COMMAND ----------

for g in [f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{SP_MCP}`",
          f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOG}.{SCHEMA} TO `{SP_MCP}`",
          f"GRANT MODIFY ON TABLE {CATALOG}.{SCHEMA}.solicitacoes_atendimento TO `{SP_MCP}`",
          f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {CATALOG}.{SCHEMA}.midia TO `{SP_MCP}`",
          f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME {CATALOG}.{SCHEMA}.documentos TO `{SP_MCP}`"]:
    try:
        spark.sql(g)
        print("✓", g)
    except Exception as e:
        print("⚠️", g, "→", str(e)[:150])

from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
try:
    ep_id = w.vector_search_endpoints.get_endpoint(VS_ENDPOINT).id
    w.permissions.update("vector-search-endpoints", ep_id, access_control_list=[
        AccessControlRequest(service_principal_name=SP_MCP, permission_level=PermissionLevel.CAN_MANAGE)])
    print(f"✓ CAN_MANAGE no endpoint de Vector Search {VS_ENDPOINT}")
except Exception as e:
    print("⚠️ permissão no endpoint de Vector Search:", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 4) Deploy + teste `tools/list`

# COMMAND ----------

print("🚀 deploy em andamento...")
dep = rest("POST", f"/api/2.0/apps/{MCP_APP}/deployments", {"source_code_path": MCP_DEPLOY_DIR, "mode": "SNAPSHOT"})
inicio = time.time()
while True:
    st = rest("GET", f"/api/2.0/apps/{MCP_APP}/deployments/{dep['deployment_id']}").get("status", {})
    if st.get("state") not in ("IN_PROGRESS", "PENDING", None) or time.time() - inicio > 1200:
        break
    time.sleep(15)
print("deploy:", st.get("state"), "-", st.get("message"))
if st.get("state") != "SUCCEEDED":
    raise RuntimeError(f"Deploy do App MCP falhou: {st}. Veja os logs em Compute → Apps → {MCP_APP} → Logs.")
MCP_APP_URL = rest("GET", f"/api/2.0/apps/{MCP_APP}")["url"]
MCP_URL = MCP_APP_URL + "/mcp"

import requests
cab = {**w.config.authenticate(), "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
try:
    for _ in range(20):   # o App leva alguns segundos para aceitar requisições após o deploy
        r = requests.post(MCP_URL, headers=cab, timeout=60, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        if r.status_code == 200:
            break
        time.sleep(10)
    nomes = [t["name"] for t in r.json()["result"]["tools"]]
    print(f"✅ tools/list: {len(nomes)} ferramentas → {nomes}")
except Exception as e:
    print("⚠️ teste tools/list não concluído (o App pode estar terminando de subir):", str(e)[:200])

print("✅ App MCP no ar:", MCP_APP_URL)
print("   MCP:", MCP_URL)
displayHTML(f'<a href="{MCP_APP_URL}" target="_blank" style="font-size:16px;font-weight:700">🔎 Abrir o MCP Detetive de Produtos →</a>'
            f'<div style="margin-top:6px">Endpoint MCP: <code>{MCP_URL}</code></div>')
