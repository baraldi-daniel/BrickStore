# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "requests"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 05a · SAC por voz: Whisper + funções de IA (só workspace corporativo)
# MAGIC
# MAGIC Seis **ligações de clientes** (MP3 em `audios_sac/`) viram atendimentos estruturados:
# MAGIC
# MAGIC ```
# MAGIC  áudio (Volume) ──Whisper (endpoint <app_name>-whisper)──► texto em português
# MAGIC                ──ai_classify──────────► troca | atraso | defeito | elogio | garantia | cancelamento
# MAGIC                ──ai_analyze_sentiment─► positive | negative | neutral | mixed
# MAGIC                ──ai_extract───────────► pedido_id, produto, motivo
# MAGIC                ──JOIN pedidos─────────► cliente_id  ──►  tabela atendimentos_voz (Genie, App)
# MAGIC ```
# MAGIC
# MAGIC Depende da etapa `02b_whisper` (endpoint publicado). Só roda com **`enterprise: true`** no `config.yaml`; sem
# MAGIC isso, ou se o endpoint não ficar pronto, a etapa é pulada e o App funciona igual, só sem a aba *SAC por voz*.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import base64
import json
import os
import shutil
import time

import requests
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
SAC_OK = False
ENDPOINT_WHISPER = estado_ler("whisper_endpoint") if ENTERPRISE else None
if not ENDPOINT_WHISPER:
    print("⏭️ SAC por voz pulado (" + ("config.yaml → enterprise: false" if not ENTERPRISE else "endpoint do Whisper não publicado na etapa 02b")
          + "). O App funciona igual, sem a aba SAC por voz.")
else:
    inicio = time.time()
    while time.time() - inicio < 45 * 60:   # endpoint novo leva alguns minutos (GPU: até ~30 min)
        st = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{ENDPOINT_WHISPER}").get("state", {})
        if st.get("ready") == "READY" and st.get("config_update") in (None, "NOT_UPDATING"):
            SAC_OK = True
            break
        if st.get("config_update") == "UPDATE_FAILED":
            print(f"⚠️ o endpoint {ENDPOINT_WHISPER} falhou ao subir (veja Serving → {ENDPOINT_WHISPER} → Logs)")
            break
        print(f"  {int(time.time() - inicio):>5}s  ready={st.get('ready')}  config_update={st.get('config_update')}")
        time.sleep(30)
    if not SAC_OK:
        print("⏭️ o Whisper ainda não está pronto: SAC por voz pulado por enquanto. Rode esta etapa de novo mais tarde.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1) Ligações no Volume + transcrição com o Whisper

# COMMAND ----------

if SAC_OK:
    VOL_AUDIOS = f"/Volumes/{CATALOG}/{SCHEMA}/midia/audios_sac"
    os.makedirs(VOL_AUDIOS, exist_ok=True)
    origem = f"{REPO_FS}/audios_sac"
    roteiros = json.load(open(f"{origem}/roteiros.json", encoding="utf-8"))
    host = w.config.host.rstrip("/")
    linhas = []
    for r in roteiros:
        shutil.copyfile(f"{origem}/{r['arquivo']}", f"{VOL_AUDIOS}/{r['arquivo']}")
        corpo = {"dataframe_split": {"columns": ["audio"],
                                     "data": [[base64.b64encode(open(f"{origem}/{r['arquivo']}", "rb").read()).decode()]]}}
        for tentativa in range(4):   # scale to zero: a 1ª chamada pode esperar o endpoint acordar
            try:
                resp = requests.post(f"{host}/serving-endpoints/{ENDPOINT_WHISPER}/invocations", json=corpo, timeout=300,
                                     headers={**w.config.authenticate(), "Content-Type": "application/json"})
                resp.raise_for_status()
                pred = (resp.json().get("predictions") or [{}])[0]
                break
            except Exception as e:
                if tentativa == 3:
                    print(f"⚠️ {r['arquivo']}: {str(e)[:160]}")
                    pred = {}
                time.sleep(20)
        texto = (pred.get("texto") if isinstance(pred, dict) else str(pred or "")) or ""
        linhas.append((r["arquivo"], float(pred.get("duracao_seg") or 0) if isinstance(pred, dict) else None, texto.strip(),
                       r["cliente_id"]))
        print(f"🎙️ {r['arquivo']}: {texto[:100]}")
    linhas = [l for l in linhas if len(l[2]) > 10]
    if not linhas:
        SAC_OK = False
        print("⚠️ o Whisper não devolveu texto: SAC por voz pulado")
    else:
        spark.createDataFrame(linhas, "arquivo STRING, duracao_seg DOUBLE, transcricao STRING, cliente_ligacao STRING") \
             .createOrReplaceTempView("sac_texto")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2) Classificação, sentimento e extração (`ai_classify`, `ai_analyze_sentiment`, `ai_extract`)

# COMMAND ----------

if SAC_OK:
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
    spark.sql(f"""
    CREATE OR REPLACE TABLE {fq('atendimentos_voz')}
    COMMENT 'Ligações do SAC transcritas com Whisper e estruturadas com ai_classify, ai_analyze_sentiment e ai_extract'
    AS
    WITH a AS (
      SELECT *, ai_classify(transcricao, '{CATEGORIAS}', map('version', '2.0', 'instructions', 'Ligações de clientes para o SAC de uma loja de varejo')) AS c,
                ai_analyze_sentiment(transcricao) AS sentimento,
                ai_extract(transcricao, '{CAMPOS}', map('version', '2.1', 'instructions', 'Ligação de cliente para o SAC de uma loja de varejo')) AS e
      FROM sac_texto
    ), b AS (
      SELECT arquivo, duracao_seg, transcricao, cliente_ligacao,
             c:response[0]::string AS categoria, sentimento,
             upper(regexp_replace(coalesce(e:response.pedido_id.value::string, e:response.pedido_id::string, ''), '[^A-Za-z0-9]', '')) AS pedido_id,
             coalesce(e:response.produto.value::string, e:response.produto::string) AS produto,
             coalesce(e:response.motivo.value::string, e:response.motivo::string) AS motivo
      FROM a
    )
    SELECT b.arquivo, b.duracao_seg, b.transcricao, 'whisper' AS fonte_transcricao, b.categoria, b.sentimento,
           nullif(b.pedido_id, '') AS pedido_id, b.produto, b.motivo,
           coalesce(p.cliente_id, b.cliente_ligacao) AS cliente_id, p.status AS status_pedido,
           CAST(NULL AS STRING) AS protocolo,   -- preenchido quando a ligação é cadastrada no SAC pelo App
           current_timestamp() AS processado_em
    FROM b LEFT JOIN {fq('pedidos')} p ON p.pedido_id = b.pedido_id
    """)
    display(spark.sql(f"""SELECT arquivo, categoria, sentimento, pedido_id, status_pedido, cliente_id, produto, motivo
                          FROM {fq('atendimentos_voz')} ORDER BY arquivo"""))
print("✅ etapa concluída" + ("" if SAC_OK else " (sem SAC por voz)"))
