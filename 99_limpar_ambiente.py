# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 99 · Limpar ambiente — BrickStore
# MAGIC
# MAGIC Remove o que o `INSTALAR` criou, na ordem de dependência:
# MAGIC
# MAGIC | Ordem | Objeto |
# MAGIC |------:|--------|
# MAGIC | 1 | App do lab (widget `app_name`, padrão `brickstore`), o App do MCP (`mcp-detetive-produtos`) e as pastas de implantação |
# MAGIC | 2 | Índices de Vector Search `produtos_index` e `ajuda_index` |
# MAGIC | 3 | Endpoint de Vector Search — **só se** o widget `apagar_vs_endpoint = sim` (ele pode ser compartilhado com outros labs) |
# MAGIC | 4 | Genie "<Marca> · Genie de Dados" (padrão "BrickStore · Genie de Dados") |
# MAGIC | 5 | Dashboard "AI Gateway Usage Analytics" |
# MAGIC | 6 | Lakebase: synced tables `lb_produtos` / `lb_recomendacoes`, catálogo registrado `<catalog>_loja` e **todos** os projetos Lakebase do lab (`<app_name>`, `<app_name>-2`…), apagados de vez (sem lixeira) |
# MAGIC | 7 | Policy ABAC `mascara_dados_sensiveis` do schema (a governed tag `dados_sensiveis` fica: ela é da conta e pode servir a outros labs) |
# MAGIC | 8 | Schema `catalog.schema` inteiro (tabelas, views, volumes) com `CASCADE` |
# MAGIC
# MAGIC > ⚠️ **Ação destrutiva e irreversível.** Nada é apagado enquanto o widget **`confirmar`** não estiver em
# MAGIC > **`sim`**. O **catálogo não é apagado** (só o schema do lab).

# COMMAND ----------

# MAGIC %pip install --quiet -U databricks-sdk databricks-vectorsearch
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

dbutils.widgets.dropdown("confirmar", "nao", ["nao", "sim"], "Confirmar exclusão")
dbutils.widgets.dropdown("apagar_vs_endpoint", "nao", ["nao", "sim"], "Apagar também o endpoint de Vector Search")
CONFIRMAR = dbutils.widgets.get("confirmar") == "sim"
APAGAR_VS = dbutils.widgets.get("apagar_vs_endpoint") == "sim"
if not CONFIRMAR:
    dbutils.notebook.exit("Nada foi apagado: mude o widget 'confirmar' para 'sim' e rode de novo.")

# COMMAND ----------

import shutil
from databricks.sdk import WorkspaceClient
from databricks.vector_search.client import VectorSearchClient

w = WorkspaceClient()
vsc = VectorSearchClient(disable_notice=True)


def tentar(nome, fn):
    try:
        fn()
        print("🗑️", nome)
    except Exception as e:
        print("•", nome, "→", str(e)[:120])


def meu(caminho):
    """True se o recurso existe e foi criado por você (workspace compartilhado: não apaga o de outra pessoa)."""
    try:
        r = w.api_client.do("GET", caminho)
    except Exception:
        return False
    dono = r.get("creator") or r.get("owner")
    if dono and dono != USUARIO:
        print(f"• {caminho} é de {dono}: mantido")
        return False
    return True


MCP_APP = MCP_APP_NAME   # config.yaml → mcp_app_name
for _app in (APP_NAME, MCP_APP):
    if meu(f"/api/2.0/apps/{_app}"):
        tentar(f"App {_app}", lambda _app=_app: w.api_client.do("DELETE", f"/api/2.0/apps/{_app}"))
tentar("pasta de implantação do MCP", lambda: shutil.rmtree(f"/Workspace/Users/{USUARIO}/.mcp_detetive_app"))
if meu(f"/api/2.0/serving-endpoints/{WHISPER_ENDPOINT_NOME}"):   # SAC por voz (só workspace corporativo)
    tentar(f"endpoint de Model Serving {WHISPER_ENDPOINT_NOME}",
           lambda: w.api_client.do("DELETE", f"/api/2.0/serving-endpoints/{WHISPER_ENDPOINT_NOME}"))
if meu(f"/api/2.0/serving-endpoints/{APP_NAME}-recomendador"):
    tentar(f"endpoint de Model Serving {APP_NAME}-recomendador",
           lambda: w.api_client.do("DELETE", f"/api/2.0/serving-endpoints/{APP_NAME}-recomendador"))
tentar(f"model service {fq('assistente_llm')}",
       lambda: w.api_client.do("DELETE", f"/api/2.1/unity-catalog/model-services/{fq('assistente_llm')}"))
tentar("pasta de implantação", lambda: shutil.rmtree(f"/Workspace/Users/{USUARIO}/.{APP_NAME}_app"))

endpoints = [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]
for ep in endpoints:
    for idx in (fq("produtos_index"), fq("ajuda_index")):
        if idx in [i["name"] for i in vsc.list_indexes(ep).get("vector_indexes", [])]:
            tentar(f"índice {idx}", lambda idx=idx, ep=ep: vsc.delete_index(ep, idx))
if APAGAR_VS:   # só o endpoint do lab (config.yaml → vs_endpoint) e só se ficou vazio
    if VS_ENDPOINT in endpoints and not vsc.list_indexes(VS_ENDPOINT).get("vector_indexes"):
        tentar(f"endpoint {VS_ENDPOINT}", lambda: vsc.delete_endpoint(VS_ENDPOINT))

_genie = estado_ler("genie_space_id")   # só o Genie criado por esta instalação (não outro com o mesmo título)
if _genie:
    tentar(f"Genie {_genie}", lambda: w.api_client.do("DELETE", f"/api/2.0/genie/spaces/{_genie}"))

# ABAC (etapa 05d): a policy do schema (a governed tag é da conta; fica para não afetar outros labs)
tentar("policy ABAC mascara_dados_sensiveis",
       lambda: spark.sql(f"DROP POLICY IF EXISTS mascara_dados_sensiveis ON SCHEMA {CATALOG}.{SCHEMA}"))

for d in w.lakeview.list():
    if d.display_name == "AI Gateway Usage Analytics" and (d.parent_path or "").rstrip("/") == f"/Users/{USUARIO}":
        tentar(f"dashboard {d.dashboard_id}", lambda d=d: w.lakeview.trash(d.dashboard_id))

# Lakebase (etapa 05c): synced tables → catálogo registrado no UC → projeto (apaga o Postgres inteiro)
for _st in ("lb_produtos", "lb_recomendacoes"):
    tentar(f"synced table {fq(_st)}", lambda _st=_st: w.api_client.do("DELETE", f"/api/2.0/postgres/synced_tables/{fq(_st)}"))
# todos os projetos do lab QUE SÃO SEUS (<app_name>, <app_name>-2...), apagados DE VEZ (purge): o nome fica livre na hora
try:
    _projetos = lakebase_projetos(w, incluir_lixeira=True)
except Exception:
    _projetos = []
_meus_branches = {f"projects/{_p['project_id']}/branches/production" for _p in _projetos}
for _i in range(1, 6):
    _cat = f"{CATALOG}_loja" + ("" if _i == 1 else f"_{_i}")
    try:
        _c = w.api_client.do("GET", f"/api/2.0/postgres/catalogs/{_cat}")
    except Exception:
        continue
    if ({(_c.get("spec") or {}).get("branch"), (_c.get("status") or {}).get("branch")} & _meus_branches):
        tentar(f"catálogo Lakebase {_cat}", lambda _cat=_cat: w.api_client.do("DELETE", f"/api/2.0/postgres/catalogs/{_cat}"))
for _p in _projetos:
    tentar(f"projeto Lakebase {_p['project_id']} (purge)",
           lambda _p=_p: w.api_client.do("DELETE", f"/api/2.0/postgres/projects/{_p['project_id']}", query={"purge": "true"}))

tentar(f"schema {CATALOG}.{SCHEMA}", lambda: spark.sql(f"DROP SCHEMA IF EXISTS {CATALOG}.{SCHEMA} CASCADE"))
print("✅ limpeza concluída")
