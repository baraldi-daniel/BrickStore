# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 05b · IA governada: roteador de LLM no Unity Gateway + tabelas de guardrail e atendimento
# MAGIC
# MAGIC Cria o **model service** `<catalog>.<schema>.assistente_llm` no **Unity Gateway**. É ele que o
# MAGIC Assistente do App chama (pela API unificada `/ai-gateway/mlflow/v1`, com o nome de 3 partes do UC):
# MAGIC
# MAGIC | Recurso | Configuração | Para quê |
# MAGIC |---------|--------------|----------|
# MAGIC | **Roteamento** | 50% `system.ai.llama-4-maverick` · 50% `system.ai.qwen3-next-80b-a3b-instruct` | A/B de modelos sem mudar o código do App |
# MAGIC | **Fallback** | `system.ai.gpt-oss-120b` | Se o destino falhar ou estourar a cota (HTTP 429, comum com cota baixa), o gateway tenta o próximo |
# MAGIC | **Inference table** | `<catalog>.<schema>.assistente_llm_payload` | Toda requisição e resposta gravada no Unity Catalog (auditoria, avaliação, custo) |
# MAGIC
# MAGIC Os três destinos suportam *tool calling*. O **Detetive de Produtos** continua chamando o
# MAGIC Llama 4 Maverick direto, porque precisa de **visão**.
# MAGIC
# MAGIC > Idempotente: se o serviço já existe, só os destinos de roteamento e fallback são atualizados
# MAGIC > (a inference table não pode ser alterada depois de criada).

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import json
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
SERVICO = "assistente_llm"
ROTEADOR_LLM = fq(SERVICO)


def destino(nome, modelo, pct=None):
    d = {"name": nome, "destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL",
         "pay_per_token_config": {"model": f"models/{modelo}"}}
    if pct is not None:
        d["traffic_percentage"] = pct
    return d


def _nome(modelo):  # "system.ai.llama-4-maverick" → "llama-4-maverick"
    return modelo.split(".")[-1][:40]


# destinos e percentuais vêm do config.yaml (roteador_destino_a/b, *_pct, roteador_fallback)
ROTEAMENTO = {
    "destinations": [destino(_nome(ROTEADOR["a"]), ROTEADOR["a"], ROTEADOR["a_pct"]),
                     destino(_nome(ROTEADOR["b"]), ROTEADOR["b"], ROTEADOR["b_pct"])],
    "fallback": {"destinations": [destino(_nome(ROTEADOR["fallback"]), ROTEADOR["fallback"])]},
}
corpo = {"comment": f"{MARCA}: LLM do Assistente com roteamento ({_nome(ROTEADOR['a'])} {ROTEADOR['a_pct']}% / "
                    f"{_nome(ROTEADOR['b'])} {ROTEADOR['b_pct']}%), fallback {_nome(ROTEADOR['fallback'])} e inference table",
         "config": {"routing": ROTEAMENTO,
                    "inference_table": {"parent": f"schemas/{CATALOG}.{SCHEMA}", "table_name_prefix": SERVICO}}}

try:
    atual = w.api_client.do("GET", f"/api/2.1/unity-catalog/model-services/{ROTEADOR_LLM}")
except Exception:
    atual = None

try:
    if atual:
        for mascara, valor in (("config.routing.destinations", {"config": {"routing": {"destinations": ROTEAMENTO["destinations"]}}}),
                               ("config.routing.fallback.destinations", {"config": {"routing": {"fallback": ROTEAMENTO["fallback"]}}})):
            w.api_client.do("PATCH", f"/api/2.1/unity-catalog/model-services/{ROTEADOR_LLM}",
                            query={"update_mask": mascara}, body=valor)
        print(f"↻ model service {ROTEADOR_LLM} atualizado")
    else:
        w.api_client.do("POST", "/api/2.1/unity-catalog/model-services",
                        query={"model_service_id": SERVICO, "parent": f"schemas/{CATALOG}.{SCHEMA}"}, body=corpo)
        print(f"＋ model service {ROTEADOR_LLM} criado")
except Exception as e:
    print("⚠️ não foi possível criar/atualizar o roteador (o App usa o LLM direto como reserva):", str(e)[:300])
    ROTEADOR_LLM = ""

# COMMAND ----------

# MAGIC %md
# MAGIC ### Teste: 6 chamadas pelo roteador (repare no campo `model` de cada resposta)

# COMMAND ----------

if ROTEADOR_LLM:
    from collections import Counter
    import requests
    host = w.config.host.rstrip("/")
    cab = {**w.config.authenticate(), "Content-Type": "application/json"}
    contagem = Counter()
    for i in range(6):
        try:   # teste: cota baixa (429) ou resposta não-JSON não derrubam a instalação
            r = requests.post(f"{host}/ai-gateway/mlflow/v1/chat/completions", headers=cab, timeout=60, json={
                "model": ROTEADOR_LLM, "max_tokens": 60,
                "messages": [{"role": "user", "content": "Em uma frase: qual a vantagem de comprar móveis online?"}]}).json()
        except Exception as e:
            r = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
        contagem[r.get("model", "erro")] += 1
        print(f"{i + 1}. {r.get('model')}: {((r.get('choices') or [{}])[0].get('message') or {}).get('content', r.get('error'))!s:.90}")
    print("\nDistribuição:", dict(contagem))
    print(f"Inference table: {fq(SERVICO + '_payload')} (os registros aparecem alguns minutos depois)")
# COMMAND ----------

# MAGIC %md
# MAGIC ### Tabelas de governança do Assistente
# MAGIC - `guardrail_eventos`: cada mascaramento de dado sensível ou bloqueio (jailbreak, fora do escopo, ofensivo) feito pelo App.
# MAGIC - `solicitacoes_atendimento`: trocas, devoluções, garantias e reclamações abertas pelo **Agente de Pós-venda**.

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq('guardrail_eventos')} (
  data_hora TIMESTAMP, cliente_id STRING, fase STRING, categoria STRING, acao STRING, trecho STRING)
  COMMENT 'Eventos dos guardrails do Assistente: mascaramento de dados sensiveis e bloqueios'""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq('solicitacoes_atendimento')} (
  protocolo STRING, cliente_id STRING, pedido_id STRING, produto_id STRING, tipo STRING, motivo STRING,
  status STRING, prazo STRING, aberto_em TIMESTAMP)
  COMMENT 'Solicitacoes de pos-venda (troca, devolucao, garantia, reclamacao) abertas pelo Agente de Pos-venda'""")
print("✅ tabelas guardrail_eventos e solicitacoes_atendimento prontas")
print("✅ etapa concluída")
