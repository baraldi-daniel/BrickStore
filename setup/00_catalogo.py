# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Catálogo, schema e volumes (Unity Catalog)
# MAGIC
# MAGIC Cria a "casa" de tudo o que o lab vai gerar:
# MAGIC
# MAGIC | Objeto | Nome padrão | Para quê |
# MAGIC |--------|-------------|----------|
# MAGIC | **Catálogo** | `brickstore` | Nível mais alto do Unity Catalog. Se a conta não permitir criar catálogos, o `_config` usa `workspace` |
# MAGIC | **Schema** | `brickstore.varejo` | Tabelas Delta, views, modelos, índices de Vector Search e o model service do Unity Gateway |
# MAGIC | **Volume** | `documentos` | PDFs da central de ajuda e fichas técnicas (entrada do `ai_parse_document`) |
# MAGIC | **Volume** | `midia` | Imagens: fotos enviadas para a busca visual, figuras recortadas das fichas |
# MAGIC
# MAGIC Os nomes vêm dos widgets `catalog` e `schema` do `INSTALAR`.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import os

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'BrickStore varejo - lab de dados e IA'")
for vol, desc in [("documentos", "PDFs da central de ajuda e fichas tecnicas (entrada do ai_parse_document)"),
                  ("midia", "Fotos da busca visual e figuras recortadas das fichas")]:
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{vol} COMMENT '{desc}'")
for sub in ["imagens_busca", "fichas", "produtos", "fichas_exemplo"]:
    os.makedirs(f"/Volumes/{CATALOG}/{SCHEMA}/midia/{sub}", exist_ok=True)

display(spark.sql(f"SHOW VOLUMES IN {CATALOG}.{SCHEMA}"))
print(f"✅ catálogo {CATALOG} · schema {CATALOG}.{SCHEMA} · volumes documentos e midia prontos")
