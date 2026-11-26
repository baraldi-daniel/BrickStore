# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "mlflow-skinny[databricks]", "huggingface_hub", "pandas"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 02b · Whisper servido no Model Serving (só workspace corporativo)
# MAGIC
# MAGIC Prepara a transcrição de áudio do **SAC por voz** com o **Whisper** (OpenAI, código aberto), em português:
# MAGIC
# MAGIC ```
# MAGIC  Hugging Face (whisper_modelo) ──► modelo MLflow pyfunc (setup/modelos/whisper_pyfunc.py) ──► UC <catalog>.<schema>.whisper
# MAGIC                                                                                              │
# MAGIC                                         endpoint <app_name>-whisper (CPU, scale to zero) ◄────┘
# MAGIC ```
# MAGIC
# MAGIC - Só roda com **`enterprise: true`** no `config.yaml`. Com `false` (padrão) a etapa é pulada e o App funciona igual,
# MAGIC   só sem a aba *SAC por voz*.
# MAGIC - Roda em **CPU** (padrão, `whisper_compute: CPU`); `GPU_SMALL` fica mais rápido em áudios longos.
# MAGIC - O endpoint é criado **sem esperar** (leva alguns minutos para subir) enquanto as próximas etapas rodam.
# MAGIC   A etapa `05a_sac_voz` espera ficar pronto e transcreve as ligações.
# MAGIC - Tolerante: se a GPU pedida não existir, cai para CPU; se nada der, a etapa é pulada (o App segue igual).

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import os
import time

import mlflow
import pandas as pd
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
WHISPER_OK = False
NOME_MODELO_WHISPER = fq("whisper")
if not ENTERPRISE:
    print("⏭️ SAC por voz desligado (config.yaml → enterprise: false). O App funciona igual, sem a aba SAC por voz.")
else:
    print(f"🎙️ Whisper: {WHISPER_MODELO} → {NOME_MODELO_WHISPER} → endpoint {WHISPER_ENDPOINT_NOME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1) Modelo no Unity Catalog (reaproveita a versão se o `whisper_modelo` não mudou)

# COMMAND ----------

VERSAO_WHISPER = None
if ENTERPRISE:
    mlflow.set_registry_uri("databricks-uc")
    cliente = mlflow.MlflowClient()
    try:
        atual = cliente.get_model_version_by_alias(NOME_MODELO_WHISPER, "atual")
        if (atual.tags or {}).get("hf_modelo") == WHISPER_MODELO:
            VERSAO_WHISPER = int(atual.version)
            print(f"↻ {NOME_MODELO_WHISPER} v{VERSAO_WHISPER} já registrado com {WHISPER_MODELO}")
    except Exception:
        pass
    if VERSAO_WHISPER is None:
        try:
            from huggingface_hub import snapshot_download
            from mlflow.models import infer_signature
            pasta = snapshot_download(WHISPER_MODELO, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
                                      local_dir=f"/tmp/whisper/{WHISPER_MODELO.replace('/', '_')}")
            print("✓ baixado do Hugging Face:", WHISPER_MODELO)
            assinatura = infer_signature(pd.DataFrame({"audio": ["<base64>"]}), [{"texto": "olá", "duracao_seg": 1.0}])
            try:
                mlflow.set_experiment(f"/Users/{USUARIO}/{APP_NAME}_whisper")
            except Exception as e:
                print("experimento:", str(e)[:120])
            with mlflow.start_run(run_name="whisper_servido"):
                info = mlflow.pyfunc.log_model(
                    name="whisper", python_model=f"{REPO_FS}/setup/modelos/whisper_pyfunc.py",   # models-from-code
                    artifacts={"modelo": pasta}, signature=assinatura,
                    pip_requirements=["torch==2.15.0", "transformers==5.23.0", "soundfile==0.14.0", "numpy==2.4.6",
                                      "pandas", "mlflow-skinny"],
                    registered_model_name=NOME_MODELO_WHISPER)
            VERSAO_WHISPER = int(info.registered_model_version)
            cliente.set_model_version_tag(NOME_MODELO_WHISPER, str(VERSAO_WHISPER), "hf_modelo", WHISPER_MODELO)
            cliente.set_registered_model_alias(NOME_MODELO_WHISPER, "atual", str(VERSAO_WHISPER))
            print(f"✅ {NOME_MODELO_WHISPER} v{VERSAO_WHISPER} registrado")
        except Exception as e:
            print("⚠️ não consegui registrar o Whisper (SAC por voz pulado):", str(e)[:300])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2) Endpoint `<app_name>-whisper` (CPU por padrão, scale to zero; sem esperar)

# COMMAND ----------

if VERSAO_WHISPER:
    try:
        existente = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{WHISPER_ENDPOINT_NOME}")
    except Exception:
        existente = None
    if existente and existente.get("creator") not in (None, USUARIO):
        print(f"⚠️ o endpoint {WHISPER_ENDPOINT_NOME} é de {existente.get('creator')}: use outro app_name (SAC por voz pulado)")
    elif existente and any(str(e.get("entity_version")) == str(VERSAO_WHISPER)
                           for e in ((existente.get("config") or {}).get("served_entities") or [])):
        WHISPER_OK = True
        estado_gravar("whisper_endpoint", WHISPER_ENDPOINT_NOME)
        print(f"↻ endpoint {WHISPER_ENDPOINT_NOME} já serve {NOME_MODELO_WHISPER} v{VERSAO_WHISPER}")
    else:
        # config.yaml → whisper_compute: CPU (padrão, mais barato) ou GPU_SMALL; se a GPU não existir, cai para CPU
        opcoes = [("CPU", "Medium")] if WHISPER_COMPUTE == "CPU" else [(WHISPER_COMPUTE, "Small"), ("CPU", "Medium")]
        for carga, tamanho in opcoes:
            config = {"served_entities": [{"name": "whisper", "entity_name": NOME_MODELO_WHISPER, "entity_version": str(VERSAO_WHISPER),
                                           "workload_type": carga, "workload_size": tamanho, "scale_to_zero_enabled": True}]}
            try:
                if existente:
                    w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{WHISPER_ENDPOINT_NOME}/config", body=config)
                else:
                    w.api_client.do("POST", "/api/2.0/serving-endpoints", body={"name": WHISPER_ENDPOINT_NOME, "config": config})
                WHISPER_OK = True
                estado_gravar("whisper_endpoint", WHISPER_ENDPOINT_NOME)
                print(f"＋ endpoint {WHISPER_ENDPOINT_NOME} ({carga}) publicando em segundo plano; a etapa 05a espera ficar pronto")
                break
            except Exception as e:
                print(f"   • {carga}: {str(e)[:160]}")
        if not WHISPER_OK:
            print("⚠️ não consegui publicar o endpoint do Whisper: SAC por voz pulado (o App segue igual)")
print("✅ etapa concluída" + ("" if WHISPER_OK else " (sem SAC por voz)"))
