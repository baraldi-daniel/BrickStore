# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 03 · "Quem comprou também comprou" (sem ML)
# MAGIC
# MAGIC Recomendação **explicável**, feita só com SQL: **regras de associação item → item** (a clássica
# MAGIC *market basket analysis*). A **cesta é o pedido**: dois produtos estão juntos quando aparecem no
# MAGIC mesmo pedido (pedidos cancelados ficam de fora).
# MAGIC
# MAGIC Para cada par de produtos (A, B):
# MAGIC
# MAGIC | Métrica | Fórmula | Leitura |
# MAGIC |---------|---------|---------|
# MAGIC | `n_juntos` | pedidos que têm A **e** B | força bruta do par |
# MAGIC | `suporte` | n_juntos / total de pedidos | quão comum é o par |
# MAGIC | `confianca` | n_juntos / pedidos com A | "de quem levou A, X% também levou B" |
# MAGIC | `lift` | confianca / (pedidos com B / total) | quantas vezes **acima do acaso**; > 1 = associação real |
# MAGIC
# MAGIC Guardamos os **20 melhores B para cada A**, ordenados por `n_juntos × ln(1 + lift)` (força × relevância).
# MAGIC O App e o MCP Detetive de Produtos leem essa tabela direto ("Porque você comprou «X»", "Compre junto").
# MAGIC Também criamos visões para o Genie responder perguntas como *"quais são as cestas mais fortes?"*.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

MIN_JUNTOS = 3   # pares com menos de 3 pedidos em comum são ruído

# O SQL fica em app/backend/recomendacao_sql.py (o mesmo usado pelo botão "Recalcular" do Estúdio).
import sys
sys.path.insert(0, f"{REPO_FS}/app")
from backend.recomendacao_sql import sql_regras

print(sql_regras(CATALOG, SCHEMA, MIN_JUNTOS))
spark.sql(sql_regras(CATALOG, SCHEMA, MIN_JUNTOS))
n = spark.table(fq("quem_comprou_tambem_comprou")).count()
print(f"✅ {n:,} regras em {fq('quem_comprou_tambem_comprou')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Exemplo: para o produto mais vendido, o que mais aparece junto?

# COMMAND ----------

top = spark.sql(f"""
SELECT item_a, nome_a FROM {fq('quem_comprou_tambem_comprou')}
GROUP BY item_a, nome_a ORDER BY max(pedidos_a) DESC LIMIT 1""").first()
display(spark.sql(f"""
SELECT rank, nome_b, tipo_b, estilo_b, n_juntos,
       concat(round(confianca*100,1), '%') AS de_quem_levou_A, lift, mesmo_estilo
FROM {fq('quem_comprou_tambem_comprou')} WHERE item_a = '{top.item_a}' ORDER BY rank LIMIT 10"""))
print("Produto A:", top.nome_a)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Visões de apoio (usadas pelo Genie e pela vitrine do App)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq('vw_cestas_mais_fortes')}
COMMENT 'Pares de produtos mais associados em pedidos (sem duplicar A-B e B-A), ordenados por forca da cesta'
AS SELECT nome_a, nome_b, tipo_b, estilo_b, n_juntos, confianca, lift
FROM {fq('quem_comprou_tambem_comprou')}
WHERE item_a < item_b
ORDER BY n_juntos * LN(1 + lift) DESC
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {fq('vw_vendas_produto')}
COMMENT 'Receita, unidades e pedidos por produto (pedidos cancelados fora)'
AS SELECT pr.produto_id, pr.nome, pr.marca_produto, pr.departamento, pr.tipo, pr.estilo_id,
          COUNT(DISTINCT i.pedido_id)                  AS pedidos,
          SUM(i.quantidade)                            AS unidades,
          ROUND(SUM(i.preco_unitario * i.quantidade), 2) AS receita,
          ROUND(SUM(i.desconto), 2)                    AS descontos
FROM {fq('itens_pedido')} i
JOIN {fq('pedidos')} p   ON p.pedido_id = i.pedido_id AND p.status <> 'Cancelado'
JOIN {fq('produtos')} pr ON pr.produto_id = i.produto_id
GROUP BY ALL
""")
display(spark.sql(f"SELECT * FROM {fq('vw_cestas_mais_fortes')} LIMIT 10"))
print("✅ etapa 3 concluída")
