# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 🛍️ INSTALAR · BrickStore (varejo, Databricks)
# MAGIC
# MAGIC **Este é o único notebook que você precisa rodar.** Clique em **Run all** e, em ~20–30 minutos,
# MAGIC tudo estará criado. No final aparece o link do App.
# MAGIC
# MAGIC | # | Etapa | O que cria | Recurso Databricks em destaque |
# MAGIC |--:|-------|------------|--------------------------------|
# MAGIC | 0 | `setup/00_catalogo` | **Catálogo** `brickstore`, schema `varejo` e volumes `documentos` / `midia` (se não puder criar catálogo, usa `workspace`) | Unity Catalog |
# MAGIC | 1 | `setup/01_dados` | Carrega os **dados prontos** de `dados/` (Parquet): ~3 mil produtos em 6 departamentos, 20 mil clientes, ~83 mil **pedidos com cestas**, navegação e estilos | Delta + Unity Catalog (PK/FK) |
# MAGIC | 2 | `setup/02_documentos_ai_parse` | Central de ajuda e **fichas técnicas em PDF** (trocas, frete, pagamento, garantia...) | **`ai_parse_document`** |
# MAGIC | 2b | `setup/02b_whisper` | **Whisper** (Hugging Face) como modelo no UC + endpoint `<app>-whisper` em CPU (scale to zero). Só com `enterprise: true` no `config.yaml`; senão é pulado e o App segue igual | Model Serving + MLflow |
# MAGIC | 3 | `setup/03_quem_comprou_tambem_comprou` | "Quem comprou também comprou" por **cesta de pedido** (suporte, confiança, **lift**) | SQL puro |
# MAGIC | 4 | `setup/03b_modelo_ml` | **Recomendação híbrida**: regras + SVD + ranking com Gradient Boosting, placar vs. baselines | scikit-learn + **MLflow** + modelo no UC |
# MAGIC | 5 | `setup/03c_servir_modelo` | **Modelo servido**: pyfunc `recomendador` no UC + endpoint `<app>-recomendador` (CPU Small, scale to zero) consultado pelo App | **Model Serving** + MLflow |
# MAGIC | 6 | `setup/03d_previsao_vendas` | **Previsão de vendas** por departamento (30 dias, com intervalo de confiança) | **`ai_forecast`** |
# MAGIC | 7 | `setup/04_vector_search` | Índices semânticos do catálogo (`produtos_index`) e da central de ajuda | Vector Search (AI Search) |
# MAGIC | 8 | `setup/05c_lakebase` | **Lakebase** (Postgres OLTP) para os pedidos novos do App e a **memória do chat** (`loja.conversas`) + registro no UC e views `vw_pedidos_todos` (Lakehouse lê **ao vivo**, ~1 s) + *synced tables* Delta → Postgres | **Lakebase** + Unity Catalog |
# MAGIC | 9 | `setup/05a_sac_voz` | **SAC por voz**: 6 ligações → Whisper → `ai_classify`, `ai_analyze_sentiment`, `ai_extract` → `atendimentos_voz` (só com `enterprise: true`) | Model Serving + AI Functions |
# MAGIC | 9b | `setup/05_genie` | Genie Agent para perguntas em linguagem natural sobre vendas, estoque e fidelidade | Genie |
# MAGIC | 10 | `setup/05b_roteador_llm` | **Roteador de LLM** (50/50 + fallback + inference table) e tabelas de guardrail e atendimento | **Unity Gateway** |
# MAGIC | 11 | `setup/06_app` | Vitrine da loja + **MCP "Detetive de Produtos"** + aba **Estúdio** + **Assistente multiagente com guardrails** | Databricks Apps + MCP |
# MAGIC | 12 | `setup/06b_app_mcp` | **App próprio do MCP** `mcp-detetive-produtos`: aparece no **Playground** (Tools → MCP servers → Databricks Apps) | Databricks Apps + MCP |
# MAGIC | 13 | `setup/07_dashboard_ai_gateway` | Dashboard de uso/custo do AI Gateway (workspace_id ajustado automaticamente) | AI/BI Dashboards + system tables |
# MAGIC
# MAGIC > ⚙️ Os parâmetros (catálogo, schema, **marca**, modelos...) estão nos **widgets** lá em cima. Os padrões
# MAGIC > já funcionam num workspace Databricks novo. O notebook é **idempotente**: pode rodar de novo à vontade.
# MAGIC
# MAGIC > 🧹 Para apagar tudo depois: `99_limpar_ambiente`.

# COMMAND ----------

# MAGIC %pip install --quiet -U databricks-sdk databricks-vectorsearch scikit-learn scipy "mlflow-skinny[databricks]" "psycopg[binary]" huggingface_hub
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import time
_t0 = time.time()
def etapa(n, nome):
    print(f"\n{'═'*70}\n▶ ETAPA {n}/13 · {nome}   (+{int(time.time()-_t0)}s)\n{'═'*70}")

etapa(0, "Catálogo, schema e volumes no Unity Catalog")

# COMMAND ----------

# MAGIC %run ./setup/00_catalogo

# COMMAND ----------

etapa(1, f"Dados da {MARCA}: carrega dados/*.parquet (produtos, clientes, pedidos, cestas e navegação)")

# COMMAND ----------

# MAGIC %run ./setup/01_dados

# COMMAND ----------

etapa(2, "Central de ajuda e fichas técnicas via ai_parse_document (PDF → chunks)")

# COMMAND ----------

# MAGIC %run ./setup/02_documentos_ai_parse

# COMMAND ----------

etapa("2b", "Whisper no Model Serving para o SAC por voz (só com enterprise: true no config.yaml)")

# COMMAND ----------

# MAGIC %run ./setup/02b_whisper

# COMMAND ----------

etapa(3, "Quem comprou também comprou (cestas por pedido + lift)")

# COMMAND ----------

# MAGIC %run ./setup/03_quem_comprou_tambem_comprou

# COMMAND ----------

etapa(4, "Recomendação híbrida com ML (regras + SVD + ranking Gradient Boosting + MLflow)")

# COMMAND ----------

# MAGIC %run ./setup/03b_modelo_ml

# COMMAND ----------

etapa(5, "Modelo de recomendação servido (pyfunc no UC + endpoint de Model Serving)")

# COMMAND ----------

# MAGIC %run ./setup/03c_servir_modelo

# COMMAND ----------

etapa(6, "Previsão de vendas por departamento com ai_forecast (próximos 30 dias)")

# COMMAND ----------

# MAGIC %run ./setup/03d_previsao_vendas

# COMMAND ----------

etapa(7, "Vector Search (produtos + central de ajuda)")

# COMMAND ----------

# MAGIC %run ./setup/04_vector_search

# COMMAND ----------

etapa(8, "Lakebase: pedidos no Postgres OLTP + leitura ao vivo no Lakehouse (UC) + synced tables")

# COMMAND ----------

# MAGIC %run ./setup/05c_lakebase

# COMMAND ----------

etapa(9, "SAC por voz: Whisper + ai_classify / ai_analyze_sentiment / ai_extract (só com enterprise: true)")

# COMMAND ----------

# MAGIC %run ./setup/05a_sac_voz

# COMMAND ----------

etapa("9b", "Genie Agent")

# COMMAND ----------

# MAGIC %run ./setup/05_genie

# COMMAND ----------

etapa(10, "Roteador de LLM no Unity Gateway (routing + fallback + inference table)")

# COMMAND ----------

# MAGIC %run ./setup/05b_roteador_llm

# COMMAND ----------

etapa(11, "Databricks App + MCP Detetive de Produtos")

# COMMAND ----------

# MAGIC %run ./setup/06_app

# COMMAND ----------

etapa(12, "App próprio do MCP Detetive de Produtos (Playground)")

# COMMAND ----------

# MAGIC %run ./setup/06b_app_mcp

# COMMAND ----------

etapa(13, "Dashboard AI Gateway Usage Analytics")

# COMMAND ----------

# MAGIC %run ./setup/07_dashboard_ai_gateway

# COMMAND ----------

# MAGIC %md
# MAGIC ## 🎉 Pronto!
# MAGIC A célula abaixo mostra o resumo e o **link do App**. Abra, escolha um perfil em
# MAGIC *"Quem vai comprar?"* e explore:
# MAGIC - **Início**: vitrine com departamentos, incluindo *"Porque você comprou…"* e *"Quem comprou também comprou"*;
# MAGIC - **🔎 Detetive de Produtos**: busca visual — envie a foto de um produto e veja os parecidos da loja;
# MAGIC - **💬 Assistente**: chat com o agente (MCP + Vector Search + Genie);
# MAGIC - **🎛️ Estúdio**: cadastre produtos novos, suba fichas técnicas em PDF e sincronize os índices.

# COMMAND ----------

print(f"""
{'═'*70}
✅ {MARCA.upper()} INSTALADA em {int(time.time()-_t0)//60} min
{'═'*70}
 Marca ............ {MARCA}  (domínio dos clientes: {DOMINIO})
 Dados ............ {CATALOG}.{SCHEMA}
 Vector Search .... {VS_ENDPOINT}  (índices: produtos_index, ajuda_index)
 Genie ............ {GENIE_SPACE_ID}
 Lakebase ......... projeto {LAKEBASE_PROJETO or '—'} · pedidos ao vivo no Lakehouse: {CATALOG}.{SCHEMA}.vw_pedidos_todos
 Recomendador ..... {w.config.host.rstrip('/')}/ml/endpoints/{APP_NAME}-recomendador
 App .............. {APP_URL}
 MCP (na loja) .... {APP_URL}/mcp
 MCP (App próprio)  {MCP_URL}   → Playground: Tools → MCP servers → Databricks Apps → {MCP_APP}
   Teste no Playground (GPT OSS 120B): "tem na {MARCA} algo parecido com o produto da foto /Volumes/{CATALOG}/{SCHEMA}/midia/imagens_busca/<sua_foto>.jpg?"
 Dashboard ........ {DASHBOARD_URL}
 SAC por voz ...... {"Whisper: " + (estado_ler("whisper_endpoint") or "—") if ENTERPRISE else "desligado (enterprise: false)"}
{'═'*70}
 🖐️ Etapas manuais: veja as células abaixo (Google Calendar, Gmail, Playground e extras do workspace corporativo)
""")
displayHTML(f"""<div style="font-family:Inter,Arial;padding:18px;border-radius:14px;
  background:linear-gradient(120deg,#0B2026,#1B3139 45%,#FF3621);color:white">
  <div style="font-size:22px;font-weight:800">🛍️ {MARCA} está no ar</div>
  <div style="margin-top:8px"><a style="color:white;font-size:16px;font-weight:700" href="{APP_URL}" target="_blank">Abrir o App →</a></div>
  <div style="margin-top:6px"><a style="color:white" href="{DASHBOARD_URL}" target="_blank">📊 AI Gateway Usage Analytics</a></div>
  <div style="margin-top:6px;opacity:.9">MCP Detetive de Produtos: <code style="color:white">{MCP_URL}</code>
  (App <b>{MCP_APP}</b> — no Playground: Tools → MCP servers → Databricks Apps)</div></div>""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 🖐️ Etapas manuais (no final, pela interface)
# MAGIC A instalação automática terminou e o App já está no ar. O que vem abaixo é feito **por você, pela interface**,
# MAGIC depois de tudo: nada disso impede o App de funcionar.

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1) 📅 Google Calendar no App (necessário para a agenda)
# MAGIC A cada compra, o App cria **automaticamente** o evento **"📦 Chega hoje: pedido …"** no Google Calendar **de quem está
# MAGIC usando** (e há o botão *📅 Adicionar a chegada à minha agenda* em **Meus pedidos** e no Assistente). Para isso:
# MAGIC 1. **Conecte o seu Google Calendar** ao Unity Gateway (uma vez por usuário):
# MAGIC    *AI Gateway → MCP → `system.ai.google_calendar` → Connect* e faça login com a conta Google.
# MAGIC    Teste rápido: no **Playground**, adicione a tool `system.ai.google_calendar` e peça *"liste meus eventos de amanhã"*.
# MAGIC 2. **Libere o App para agir em seu nome** (autorização de usuário):
# MAGIC    *Compute → Apps → `brickstore` → Edit → **User authorization** → + Add scope → **`ai-gateway`*** → Save → **Deploy**.
# MAGIC    O `06_app` já tenta configurar isso; confira se o escopo aparece. Na primeira abertura, o Databricks pede o seu consentimento.
# MAGIC    ⚠️ Se você já estava com o App aberto **antes** de adicionar o escopo, o seu login antigo continua sem ele (recarregar não
# MAGIC    resolve): abra o App numa **janela anônima** (ou apague os cookies do App) e aceite o consentimento.
# MAGIC 3. **Teste**: no App, escolha um perfil → faça um pedido. O aviso de compra deve mostrar *"📅 Já está na sua agenda"*
# MAGIC    com o link do evento (ou abra **Meus pedidos** num pedido *Em transporte* → **📅 Adicionar a chegada à minha agenda**).
# MAGIC    No Assistente: *"coloca a chegada do meu pedido na minha agenda"*.
# MAGIC
# MAGIC > Sem os passos 1 e 2, o botão continua funcionando no modo reserva: link **"Google Agenda"** já preenchido e arquivo **.ics**.

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2) 📧 Genie One + Gmail
# MAGIC 1. Conecte o Gmail uma vez: *AI Gateway → MCP → `system.ai.gmail` → Connect* (login com a sua conta Google).
# MAGIC 2. Abra o **Genie One** (botão **Genie** no topo do workspace).
# MAGIC 3. Peça:
# MAGIC
# MAGIC    > Usando as tabelas de `brickstore.varejo`, calcule a receita por departamento dos últimos 30 dias e mande para mim um e-mail com esse resumo.
# MAGIC
# MAGIC 4. Confira a caixa de entrada. (Se você trocou catálogo/schema no `config.yaml`, ajuste o nome das tabelas.)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3) 🧪 MCP Detetive no Playground
# MAGIC O `06b_app_mcp` publicou o MCP como App próprio (`mcp-detetive-produtos`). Para usá-lo fora da loja:
# MAGIC 1. Abra **Playground** e escolha o modelo **GPT OSS 120B** (seletor no topo).
# MAGIC 2. **Tools → + Add tool → MCP servers → Databricks Apps → `mcp-detetive-produtos`** (aparece *Tools (1)*).
# MAGIC 3. **Busca visual:** suba a foto de um produto para o Volume `midia/imagens_busca/` (ou use uma que você já enviou na
# MAGIC    página *Detetive* do App, que também fica lá). Quem "enxerga" a foto é o próprio MCP. Cole e envie:
# MAGIC
# MAGIC    > tem na BrickStore algo parecido com o produto da foto /Volumes/brickstore/varejo/midia/imagens_busca/<sua_foto>.jpg?
# MAGIC
# MAGIC    (Se você trocou o catálogo ou o schema nos widgets, ajuste o caminho.)
# MAGIC    Se a conversa der erro, abra uma **conversa nova** (não use o Qwen3 Next aqui: ele às vezes escreve a chamada de ferramenta como texto).
# MAGIC 4. Outras ferramentas para testar:
# MAGIC    - *"Quem comprou o Sofá Modular 3 Lugares também comprou o quê?"*;
# MAGIC    - *"Monte um kit de corrida até R$ 800"*;
# MAGIC    - *"Mostre os pedidos do cliente C000001"*.

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ### 4) 🏢 Só no workspace corporativo (Beta)
# MAGIC ⚠️ **Antes, habilite os previews (Beta)** em *Settings → Previews* (admin do workspace):
# MAGIC **Unity Gateway Service Policies**, **Omnigent** e **Governed agentic app-building**.
# MAGIC
# MAGIC | Etapa manual | O que fazer | Passo a passo |
# MAGIC |--------------|-------------|---------------|
# MAGIC | **Service policies** (LLM-as-a-judge) | No model service `assistente_llm`: policies de escopo da loja e de concorrência, com prompts prontos | `docs/ENTERPRISE.md` → 1 |
# MAGIC | **Omnigent** | Sessão no repositório do lab com Smart Routing, MCPs e policies que o workspace já tem | `docs/ENTERPRISE.md` → 2 |
# MAGIC | **Genie App Builder** | App simples *Vendas da BrickStore* a partir de um pedido pronto | `docs/ENTERPRISE.md` → 3 |
# MAGIC
# MAGIC > O **SAC por voz com Whisper** não é manual: ele entra no próprio `INSTALAR` com `enterprise: true` no `config.yaml`.
