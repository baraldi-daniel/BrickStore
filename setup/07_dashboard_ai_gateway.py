# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 07 · Dashboard "AI Gateway Usage Analytics"
# MAGIC
# MAGIC Publica um dashboard AI/BI (Lakeview) que mostra **uso, custo, latência e MCPs** de tudo que passa
# MAGIC pelo AI Gateway — incluindo as chamadas que o App acabou de fazer (LLM do Detetive, embeddings do
# MAGIC Vector Search, Genie...). Ele lê as tabelas de sistema `system.ai_gateway.usage`,
# MAGIC `system.billing.usage`, `system.billing.list_prices` e `system.access.audit`.
# MAGIC
# MAGIC O JSON do dashboard (`dashboards/ai_gateway_usage_analytics.lvdash.json`) foi exportado de outro
# MAGIC workspace e tem o **workspace_id fixo** nas consultas (`WHERE workspace_id = '...'`). Este notebook
# MAGIC **detecta esse ID e troca pelo ID do workspace onde você está rodando** antes de publicar.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import json, re
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.dashboards import Dashboard

w = WorkspaceClient()
WORKSPACE_ID = str(w.get_workspace_id())
WAREHOUSE_ID = escolher_warehouse(w)

with open(f"{REPO_FS}/dashboards/ai_gateway_usage_analytics.lvdash.json", encoding="utf-8") as f:
    bruto = f.read()

ids_modelo = sorted(set(re.findall(r"workspace_id\s*=\s*'(\d+)'", bruto)))
print("workspace_id(s) no JSON :", ids_modelo)
print("workspace_id deste lugar:", WORKSPACE_ID)
serializado = re.sub(r"(workspace_id\s*=\s*')\d+(')", rf"\g<1>{WORKSPACE_ID}\g<2>", bruto)
print(f"✓ {len(re.findall(WORKSPACE_ID, serializado))} ocorrências apontando para {WORKSPACE_ID}")
json.loads(serializado)  # garante que continua um JSON válido

# COMMAND ----------

NOME = "AI Gateway Usage Analytics"
PASTA = f"/Users/{USUARIO}"
norm = lambda p: (p or "").replace("/Workspace", "", 1).rstrip("/")
existente = next((d for d in w.lakeview.list() if d.display_name == NOME and norm(d.parent_path) == PASTA), None)
if not existente:
    try:
        dash = w.lakeview.create(Dashboard(display_name=NOME, parent_path=PASTA, serialized_dashboard=serializado,
                                           warehouse_id=WAREHOUSE_ID))
        print("＋ dashboard criado")
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise
        st = w.workspace.get_status(f"{PASTA}/{NOME}.lvdash.json")
        existente = w.lakeview.get(st.resource_id)
if existente:
    dash = w.lakeview.update(existente.dashboard_id, Dashboard(display_name=NOME, serialized_dashboard=serializado,
                                                                warehouse_id=WAREHOUSE_ID))
    print("↻ dashboard atualizado")
try:
    w.lakeview.publish(dash.dashboard_id, warehouse_id=WAREHOUSE_ID, embed_credentials=True)
    DASHBOARD_URL = f"{w.config.host.rstrip('/')}/dashboardsv3/{dash.dashboard_id}/published"
    print("✅ publicado:", DASHBOARD_URL)
except Exception as e:   # sem publicar, o rascunho continua utilizável
    DASHBOARD_URL = f"{w.config.host.rstrip('/')}/dashboardsv3/{dash.dashboard_id}"
    print("⚠️ não publiquei o dashboard (abra o rascunho e clique em Publish):", str(e)[:160])
displayHTML(f'<a href="{DASHBOARD_URL}" target="_blank" style="font-size:16px;font-weight:700">📊 Abrir o AI Gateway Usage Analytics →</a>')
