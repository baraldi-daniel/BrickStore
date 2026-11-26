# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 03d · Previsão de vendas com `ai_forecast`
# MAGIC
# MAGIC `ai_forecast` é uma função de tabela do Databricks SQL: recebe a série histórica e devolve a previsão
# MAGIC com **intervalo de confiança**. Não há modelo para treinar, registrar ou servir.
# MAGIC
# MAGIC | Entrada | Saída |
# MAGIC |---------|-------|
# MAGIC | Receita e itens vendidos **por dia e por departamento** (últimos 180 dias, sem pedidos cancelados) | Próximos **30 dias**: `receita_prevista`, `receita_inferior`, `receita_superior` (intervalo de 80%) e `itens_previstos` |
# MAGIC
# MAGIC Resultado: tabela `previsao_vendas` e a view `vw_vendas_previsao`, que junta o real (últimos 60 dias) e o
# MAGIC previsto para desenhar o gráfico no App e responder no Genie
# MAGIC (*"qual a previsão de receita de Eletrônicos para as próximas 4 semanas?"*).
# MAGIC
# MAGIC > `ai_forecast` roda no **SQL warehouse**; no compute serverless de notebooks ele pode estar desabilitado
# MAGIC > (*"AI function ai_forecast is in preview and currently disabled in this environment"*). Por isso a previsão
# MAGIC > roda no warehouse, pela API de Statement Execution. É o mesmo caminho que o App usa na previsão sob demanda.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient

HORIZONTE_DIAS = 30
JANELA_HIST = 180
w = WorkspaceClient()
WAREHOUSE_ID = escolher_warehouse(w)


def sql_warehouse(q: str, timeout_s: int = 600):
    """Executa no SQL warehouse (onde ai_forecast está habilitado) e espera terminar."""
    r = w.statement_execution.execute_statement(warehouse_id=WAREHOUSE_ID, statement=q, wait_timeout="50s")
    t0 = time.time()
    while r.status.state.value in ("PENDING", "RUNNING"):
        if time.time() - t0 > timeout_s:
            raise TimeoutError("ai_forecast demorou demais")
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(r.status.error.message if r.status.error else r.status.state)
    return r


SQL_VENDAS = f"""
SELECT CAST(p.data_pedido AS DATE) AS data, pr.departamento,
       sum(i.quantidade * i.preco_unitario) AS receita, sum(i.quantidade) AS itens
FROM {fq('pedidos')} p
JOIN {fq('itens_pedido')} i USING (pedido_id)
JOIN {fq('produtos')} pr USING (produto_id)
WHERE p.status <> 'Cancelado'
  AND p.data_pedido >= date_sub(current_date(), {JANELA_HIST})
  AND CAST(p.data_pedido AS DATE) < current_date()          -- o dia de hoje ainda está incompleto
GROUP BY ALL"""
spark.sql("CREATE OR REPLACE TEMP VIEW vendas_diarias AS " + SQL_VENDAS)
print("warehouse:", WAREHOUSE_ID)
display(spark.sql("SELECT departamento, count(*) AS dias, round(sum(receita)) AS receita FROM vendas_diarias GROUP BY ALL ORDER BY receita DESC"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### `ai_forecast`: uma série por departamento, para receita e para itens (uma chamada por métrica)

# COMMAND ----------

PREV_OK = False
try:   # tolerante: sem ai_forecast (warehouse, região, cota), a instalação segue; o App tem a previsão sob demanda
    t0 = time.time()
    sql_warehouse(f"""
    CREATE OR REPLACE TABLE {fq('previsao_vendas')}
    COMMENT 'Previsão diária de receita e itens por departamento para os próximos 30 dias, gerada com ai_forecast (intervalo de 80%)'
    AS
    WITH r AS (
      SELECT * FROM ai_forecast(
        observed => TABLE(SELECT data, departamento, receita FROM ({SQL_VENDAS})),
        horizon => CAST(date_add(current_date(), {HORIZONTE_DIAS}) AS STRING),
        time_col => 'data', value_col => 'receita', group_col => 'departamento',
        prediction_interval_width => 0.8, frequency => 'D', seed => 7, parameters => '{{"global_floor": 0}}')
    ), q AS (
      SELECT * FROM ai_forecast(
        observed => TABLE(SELECT data, departamento, CAST(itens AS DOUBLE) AS itens FROM ({SQL_VENDAS})),
        horizon => CAST(date_add(current_date(), {HORIZONTE_DIAS}) AS STRING),
        time_col => 'data', value_col => 'itens', group_col => 'departamento',
        prediction_interval_width => 0.8, frequency => 'D', seed => 7, parameters => '{{"global_floor": 0}}')
    )
    SELECT r.departamento, r.data,
           round(r.receita_forecast, 2) AS receita_prevista,
           round(r.receita_lower, 2)    AS receita_inferior,
           round(r.receita_upper, 2)    AS receita_superior,
           round(q.itens_forecast, 1)   AS itens_previstos,
           'previsto'                   AS tipo,
           current_timestamp()          AS gerado_em
    FROM r JOIN q USING (departamento, data)
    WHERE r.data > (SELECT max(CAST(data_pedido AS DATE)) FROM {fq('pedidos')} WHERE CAST(data_pedido AS DATE) < current_date())""")
    print(f"✅ ai_forecast no warehouse em {time.time() - t0:.0f}s:", spark.table(fq("previsao_vendas")).count(), "linhas")

    spark.sql(f"""
    CREATE OR REPLACE VIEW {fq('vw_vendas_previsao')}
    COMMENT 'Receita diária por departamento: real (últimos 60 dias) + previsto pelo ai_forecast (próximos 30 dias), pronta para gráfico'
    AS
    SELECT departamento, data, round(receita, 2) AS receita, CAST(NULL AS DOUBLE) AS receita_inferior,
           CAST(NULL AS DOUBLE) AS receita_superior, CAST(itens AS DOUBLE) AS itens, 'real' AS tipo
    FROM (SELECT CAST(p.data_pedido AS DATE) AS data, pr.departamento,
                 sum(i.quantidade * i.preco_unitario) AS receita, sum(i.quantidade) AS itens
          FROM {fq('pedidos')} p JOIN {fq('itens_pedido')} i USING (pedido_id) JOIN {fq('produtos')} pr USING (produto_id)
          WHERE p.status <> 'Cancelado' AND p.data_pedido >= date_sub(current_date(), 60) AND CAST(p.data_pedido AS DATE) < current_date()
          GROUP BY ALL)
    UNION ALL
    SELECT departamento, data, receita_prevista, receita_inferior, receita_superior, itens_previstos, tipo
    FROM {fq('previsao_vendas')}""")
    PREV_OK = True
except Exception as e:
    print("⚠️ ai_forecast indisponível agora (a instalação segue; a tela Previsão do Estúdio tenta de novo sob demanda):", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Resumo: próximas 4 semanas vs. últimas 4 semanas

# COMMAND ----------

if PREV_OK:
    display(spark.sql(f"""
    WITH lim AS (SELECT max(data) AS ultimo_real FROM {fq('vw_vendas_previsao')} WHERE tipo = 'real'),
         prox AS (SELECT departamento, sum(receita_prevista) AS prevista, sum(receita_inferior) AS inferior, sum(receita_superior) AS superior
                  FROM {fq('previsao_vendas')}, lim WHERE data > ultimo_real AND data <= date_add(ultimo_real, 28) GROUP BY ALL),
         ult  AS (SELECT departamento, sum(receita) AS realizada FROM {fq('vw_vendas_previsao')}, lim
                  WHERE tipo = 'real' AND data > date_sub(ultimo_real, 28) GROUP BY ALL)
    SELECT departamento, round(realizada) AS receita_ultimas_4_semanas, round(prevista) AS receita_prevista_4_semanas,
           concat(round(inferior), ' – ', round(superior)) AS intervalo_80pct,
           round(100 * (prevista / realizada - 1), 1) AS variacao_pct
    FROM prox JOIN ult USING (departamento) ORDER BY receita_prevista_4_semanas DESC"""))
print("✅ etapa concluída")
