# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "scikit-learn", "mlflow-skinny[databricks]", "pyarrow"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 03c · Modelo de recomendação SERVIDO (Model Serving)
# MAGIC
# MAGIC A etapa 03b treinou o ranking (Gradient Boosting) e pontuou todos os clientes em lote. Aqui empacotamos
# MAGIC o resultado como um **modelo MLflow pyfunc** no Unity Catalog e o publicamos num **endpoint de Model Serving**:
# MAGIC
# MAGIC ```
# MAGIC  POST /serving-endpoints/<app>-recomendador/invocations
# MAGIC  {"dataframe_records": [{"cliente_id": "C000123", "quantidade": 8}]}
# MAGIC        │
# MAGIC        ▼
# MAGIC  pyfunc «recomendador»  ── top-N do cliente (candidatos regras + SVD + estilo, ordenados pelo GBM)
# MAGIC                         ── cliente desconhecido → mais populares (cold start)
# MAGIC ```
# MAGIC
# MAGIC | Peça | Onde fica |
# MAGIC |------|-----------|
# MAGIC | Modelo pyfunc | `<catalog>.<schema>.recomendador` (Unity Catalog) |
# MAGIC | Endpoint | `<app>-recomendador` (CPU **Small**, **scale to zero**) |
# MAGIC | Artefatos | recomendações por cliente, populares e o modelo de ranking `modelo_recomendacao` (GBM) embutido |
# MAGIC
# MAGIC O App consulta o endpoint em "Recomendado para você" (com a tabela `recomendacoes_personalizadas` como reserva).
# MAGIC
# MAGIC > O endpoint escala a zero quando ocioso; a primeira chamada depois de um tempo parado
# MAGIC > pode levar alguns segundos (o App usa a tabela enquanto isso). Idempotente: rodar de novo cria uma
# MAGIC > nova versão do modelo e atualiza o endpoint.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import json
import os
import shutil
import tempfile
import time

import mlflow
import pandas as pd
import sklearn
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
mlflow.set_registry_uri("databricks-uc")
NOME_MODELO = fq("recomendador")
MODELO_RANKING = fq("modelo_recomendacao")
ENDPOINT = f"{APP_NAME}-recomendador"

recs = spark.sql(f"""
  SELECT r.cliente_id, r.produto_id, r.rank, r.score, r.motivo, r.fonte, p.nome, p.tipo, p.departamento,
         CAST(coalesce(p.preco_promocional, p.preco) AS DOUBLE) AS preco
  FROM {fq('recomendacoes_personalizadas')} r JOIN {fq('produtos')} p USING (produto_id)""").toPandas()
populares = spark.sql(f"""
  SELECT produto_id, nome, tipo, departamento, CAST(coalesce(preco_promocional, preco) AS DOUBLE) AS preco
  FROM {fq('produtos')} WHERE estoque > 0 ORDER BY popularidade DESC LIMIT 24""").toPandas()
populares["rank"] = range(1, len(populares) + 1)
populares["score"] = 0.0
populares["motivo"] = "Mais vendidos da loja"
populares["fonte"] = "popularidade"
recs.attrs, populares.attrs = {}, {}   # o toPandas do Spark Connect guarda métricas em .attrs (não serializáveis em parquet)
print(f"{len(recs):,} recomendações para {recs.cliente_id.nunique():,} clientes · {len(populares)} populares (cold start)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 1) O modelo pyfunc

# COMMAND ----------

COLUNAS = ["cliente_id", "produto_id", "rank", "score", "motivo", "fonte", "nome", "tipo", "departamento", "preco"]


class Recomendador(mlflow.pyfunc.PythonModel):
    """Entrada: cliente_id (+ quantidade opcional). Saída: top-N com produto, score e motivo."""

    def load_context(self, context):
        import json
        import os
        import pandas as pd
        recs = pd.read_parquet(context.artifacts["recomendacoes"])
        self.por_cliente = {c: g.sort_values("rank") for c, g in recs.groupby("cliente_id")}
        self.populares = pd.read_parquet(context.artifacts["populares"])
        info = os.path.join(context.artifacts["modelo_ranking"], "ranking.json")
        self.ranking = json.load(open(info)) if os.path.exists(info) else {}

    def predict(self, context, model_input, params=None):
        import pandas as pd
        saida = []
        for _, linha in model_input.iterrows():
            cid = str(linha.get("cliente_id") or "")
            q = linha.get("quantidade")
            n = max(1, min(int(q) if pd.notna(q) else 8, 12))
            g = self.por_cliente.get(cid)
            if g is None:  # cold start
                g = self.populares.assign(cliente_id=cid)
            saida.append(g.head(n))
        return pd.concat(saida, ignore_index=True)[COLUNAS] if saida else pd.DataFrame(columns=COLUNAS)


tmp = tempfile.mkdtemp()
recs.to_parquet(f"{tmp}/recomendacoes.parquet", index=False)
populares.assign(cliente_id="")[COLUNAS].to_parquet(f"{tmp}/populares.parquet", index=False)

# modelo de ranking (GBM) da etapa 03b, embutido como artefato (documenta de onde veio a ordem)
try:   # o 03b pode não ter registrado o modelo (falha de MLflow é tolerada lá): segue sem o artefato
    versoes = w.api_client.do("GET", "/api/2.1/unity-catalog/models/" + MODELO_RANKING + "/versions").get("model_versions", [])
except Exception as e:
    print("⚠️ modelo de ranking não encontrado no UC (segue sem o artefato):", str(e)[:120])
    versoes = []
v_rank = max(int(v["version"]) for v in versoes) if versoes else None
dir_rank = f"{tmp}/modelo_ranking"
if v_rank:
    mlflow.artifacts.download_artifacts(f"models:/{MODELO_RANKING}/{v_rank}", dst_path=dir_rank)
else:
    os.makedirs(dir_rank, exist_ok=True)
json.dump({"modelo": MODELO_RANKING, "versao": v_rank, "algoritmo": "HistGradientBoostingClassifier"},
          open(f"{tmp}/ranking.json", "w"))
shutil.copy(f"{tmp}/ranking.json", f"{dir_rank}/ranking.json")
print("ranking embutido:", MODELO_RANKING, "v", v_rank)

# COMMAND ----------

from mlflow.models import infer_signature

exemplo = pd.DataFrame([{"cliente_id": recs.cliente_id.iloc[0], "quantidade": 8}])
modelo_local = Recomendador()
ctx = type("Ctx", (), {"artifacts": {"recomendacoes": f"{tmp}/recomendacoes.parquet",
                                     "populares": f"{tmp}/populares.parquet", "modelo_ranking": dir_rank}})()
modelo_local.load_context(ctx)
saida_exemplo = modelo_local.predict(ctx, exemplo)
display(saida_exemplo)

try:
    mlflow.set_experiment(f"/Users/{USUARIO}/{APP_NAME}_recomendacao")
except Exception as e:
    print("experimento:", str(e)[:120])
VERSAO = None
try:
    with mlflow.start_run(run_name="recomendador_servido") as run:
        info = mlflow.pyfunc.log_model(
            name="recomendador", python_model=Recomendador(),
            artifacts={"recomendacoes": f"{tmp}/recomendacoes.parquet", "populares": f"{tmp}/populares.parquet",
                       "modelo_ranking": dir_rank},
            signature=infer_signature(exemplo, saida_exemplo), input_example=exemplo,
            pip_requirements=[f"pandas=={pd.__version__}", "pyarrow", f"scikit-learn=={sklearn.__version__}"],
            registered_model_name=NOME_MODELO)
        mlflow.log_params({"ranking_modelo": MODELO_RANKING, "ranking_versao": v_rank, "clientes": recs.cliente_id.nunique()})
    VERSAO = int(info.registered_model_version)
    print(f"✅ {NOME_MODELO} v{VERSAO} registrado")
except Exception as e:
    print("⚠️ não registrei o recomendador no UC (a instalação segue; o App usa a tabela):", str(e)[:250])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 2) Endpoint de Model Serving (CPU Small, scale to zero)

# COMMAND ----------

# Tolerante: qualquer falha aqui (modelo não registrado, endpoint de outra pessoa, cota, falha ao subir) só gera aviso;
# sem o endpoint, o App lê a tabela recomendacoes_personalizadas (mesmas recomendações)
REC_OK = False
try:
    config_ep = {"served_entities": [{"name": "recomendador", "entity_name": NOME_MODELO, "entity_version": str(VERSAO),
                                   "workload_size": "Small", "scale_to_zero_enabled": True}]}
    # endpoint ainda sendo apagado (99_limpar), atualização em andamento ou 409 "já existe" → espera e tenta de novo
    for tentativa in range(30):
        try:
            try:
                atual = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{ENDPOINT}")
            except Exception as e:
                if "does not exist" not in str(e).lower() and "not_found" not in str(e).lower() and "404" not in str(e):
                    raise
                atual = None
            if atual and atual.get("creator") not in (None, USUARIO):
                raise PermissionError(f"o endpoint {ENDPOINT} é de {atual.get('creator')}: use outro app_name no config.yaml")
            if atual:
                w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{ENDPOINT}/config", body=config_ep)
                print(f"↻ endpoint {ENDPOINT} → {NOME_MODELO} v{VERSAO}")
            else:
                w.api_client.do("POST", "/api/2.0/serving-endpoints", body={"name": ENDPOINT, "config": config_ep})
                print(f"＋ endpoint {ENDPOINT} criado")
            break
        except PermissionError:
            raise
        except Exception as e:
            if tentativa == 29:
                raise
            print(f"  … endpoint {ENDPOINT} ocupado ({str(e)[:100]}); nova tentativa em 20 s")
            time.sleep(20)

    inicio = time.time()
    while True:
        st = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{ENDPOINT}").get("state", {})
        print(f"  {int(time.time() - inicio):>4}s  ready={st.get('ready')}  config_update={st.get('config_update')}")
        if st.get("ready") == "READY" and st.get("config_update") in (None, "NOT_UPDATING"):
            REC_OK = True
            break
        if st.get("config_update") == "UPDATE_FAILED":
            raise RuntimeError(f"falha ao publicar o endpoint {ENDPOINT} (logs em Serving → {ENDPOINT})")
        if time.time() - inicio > 25 * 60:
            print("⏳ ainda publicando; o App usa a tabela até o endpoint ficar pronto")
            REC_OK = True
            break
        time.sleep(30)
except Exception as e:
    print("⚠️ recomendador servido indisponível (a instalação segue; o App usa a tabela recomendacoes_personalizadas):", str(e)[:250])

# COMMAND ----------

# MAGIC %md
# MAGIC ### 3) Teste: recomendações de um cliente de demonstração

# COMMAND ----------

cliente_demo = spark.sql(f"SELECT min(cliente_id) AS c FROM {fq('perfis_demo')}").first().c
try:
    if not REC_OK:
        raise RuntimeError("endpoint não publicado")
    r = w.api_client.do("POST", f"/serving-endpoints/{ENDPOINT}/invocations",
                        body={"dataframe_records": [{"cliente_id": cliente_demo, "quantidade": 5}]})
    display(pd.DataFrame(r.get("predictions", r)))
except Exception as e:
    print("⚠️ teste do endpoint:", str(e)[:300])
print(f"Endpoint: {w.config.host.rstrip('/')}/ml/endpoints/{ENDPOINT}")
print("✅ etapa concluída")
