# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "pyarrow"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 01 · Dados da BrickStore (varejo)
# MAGIC
# MAGIC Os dados **já vêm prontos no repositório**, na pasta [`dados/`](../dados) (arquivos Parquet + `manifesto.json`).
# MAGIC Este notebook só os **carrega no Unity Catalog** como tabelas Delta, com comentários, chaves primárias e
# MAGIC estrangeiras (que ajudam o Genie a entender os relacionamentos).
# MAGIC
# MAGIC | Tabela | Linhas | Destaques |
# MAGIC |--------|-------:|-----------|
# MAGIC | `estilos` | 13 | Estilos de decoração e moda (minimalista escandinavo, industrial, boho, gamer...) com paleta e materiais |
# MAGIC | `produtos` | 3.000 | 60 tipos em 6 departamentos, marcas próprias fictícias, fichas com especificações e **descrição visual** (estilo, cores, material, ambiente) |
# MAGIC | `clientes` | 20.000 | Programa de fidelidade (Bronze → Diamante); cada cliente tem 1–2 **estilos favoritos** latentes |
# MAGIC | `pedidos` | ~83 mil | Pedidos em 4 canais (site, app, loja física, marketplace) |
# MAGIC | `itens_pedido` | ~190 mil | **Cestas com complementos** (sofá + almofada + tapete; notebook + mouse + mochila) do mesmo estilo |
# MAGIC | `eventos_navegacao` | ~256 mil | Visualizações, adições ao carrinho e favoritos |
# MAGIC | `perfis_demo` | 7 | Perfis prontos para a tela "Quem está comprando?" do App |
# MAGIC
# MAGIC Como os gostos são latentes (estilo + departamento) e cada produto tem "parceiros" preferidos, as
# MAGIC cestas têm associações fortes (lift alto), ótimas para o "quem comprou também comprou".
# MAGIC
# MAGIC > **Quer outros dados?** Os arquivos são gerados de forma determinística por
# MAGIC > [`ferramentas/gerar_dados.py`](../ferramentas/gerar_dados.py) (pandas + numpy, sementes fixas). Edite o script,
# MAGIC > rode-o localmente e faça commit da pasta `dados/`.
# MAGIC
# MAGIC > Marcas, produtos e clientes são **100% fictícios**.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import json

import pandas as pd
from pyspark.sql import functions as F

# Catálogo, schema e volumes são criados na etapa 00_catalogo (rode-a antes se abrir este notebook sozinho).
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

DADOS = f"{REPO_FS}/dados"
MANIFESTO = json.load(open(f"{DADOS}/manifesto.json", encoding="utf-8"))
MARCA_DADOS = MANIFESTO.get("marca", "BrickStore")
print(f"dados em {DADOS} · {len(MANIFESTO['tabelas'])} tabelas · marca dos arquivos: {MARCA_DADOS}")

# COMMAND ----------

def limpar_nulos(pdf):
    """Colunas de texto: NaN/None viram None (NULL no Spark)."""
    pdf = pdf.copy()
    for c in pdf.columns:
        if pdf[c].dtype == object:
            pdf[c] = pdf[c].astype(object).where(pdf[c].notna(), None)
    return pdf


def trocar_marca(pdf):
    """Se a marca do config.yaml for outra, troca o nome nos textos (descrições, busca, e-mails)."""
    if MARCA == MARCA_DADOS:
        return pdf
    dominio_dados = MANIFESTO.get("dominio", "brickstore.com.br")
    for c in pdf.columns:
        if pdf[c].dtype == object and pdf[c].dropna().map(lambda v: isinstance(v, str)).all():
            pdf[c] = pdf[c].str.replace(MARCA_DADOS, MARCA, regex=False).str.replace(dominio_dados, DOMINIO, regex=False)
    return pdf


def gravar(pdf, tabela, comentario, duplos=(), inteiros=(), nulos_texto=(), cdf=False):
    """pandas → Delta. NaN vira NULL (nanvl) antes dos casts, porque o serverless roda em ANSI mode.
    Colunas só com nulos (ex.: imagem_path) não têm tipo inferível: entram como STRING nula."""
    sdf = spark.createDataFrame(limpar_nulos(pdf.drop(columns=list(nulos_texto), errors="ignore")))
    for c in nulos_texto:
        sdf = sdf.withColumn(c, F.lit(None).cast("string"))
    for c in duplos:
        sdf = sdf.withColumn(c, F.nanvl(F.col(c).cast("double"), F.lit(None).cast("double")))
    for c in inteiros:
        sdf = sdf.withColumn(c, F.nanvl(F.col(c).cast("double"), F.lit(None).cast("double")).cast("int"))
    escrita = sdf.write.mode("overwrite").option("overwriteSchema", "true")
    if cdf:
        escrita = escrita.option("delta.enableChangeDataFeed", "true")
    escrita.saveAsTable(fq(tabela))
    spark.sql(f"COMMENT ON TABLE {fq(tabela)} IS '{comentario.replace(MARCA_DADOS, MARCA)}'")
    return sdf


def chave_pk(tabela, coluna, nome_pk):
    for sql in [f"ALTER TABLE {fq(tabela)} ALTER COLUMN {coluna} SET NOT NULL",
                f"ALTER TABLE {fq(tabela)} ADD CONSTRAINT {nome_pk} PRIMARY KEY ({coluna})"]:
        try:
            spark.sql(sql)
        except Exception as e:
            if "already" not in str(e).lower() and "exists" not in str(e).lower():
                print("⚠️", sql[:80], "→", str(e)[:100])


def chave_fk(tabela, coluna, ref_tabela, ref_coluna, nome_fk):
    try:
        spark.sql(f"ALTER TABLE {fq(tabela)} ADD CONSTRAINT {nome_fk} FOREIGN KEY ({coluna}) "
                  f"REFERENCES {fq(ref_tabela)}({ref_coluna})")
    except Exception as e:
        if "already" not in str(e).lower() and "exists" not in str(e).lower():
            print("⚠️", nome_fk, "→", str(e)[:100])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Carga: Parquet do repositório → tabelas Delta

# COMMAND ----------

# Reinstalação: solta as FKs antigas antes de sobrescrever as tabelas referenciadas (elas são recriadas no fim)
for fk in MANIFESTO["fks"]:
    try:
        spark.sql(f"ALTER TABLE {fq(fk['tabela'])} DROP CONSTRAINT IF EXISTS {fk['nome']}")
    except Exception:
        pass   # tabela ainda não existe (primeira instalação)

for tabela, meta in MANIFESTO["tabelas"].items():
    pdf = trocar_marca(pd.read_parquet(f"{DADOS}/{tabela}.parquet"))
    gravar(pdf, tabela, meta["comentario"], duplos=meta["duplos"], inteiros=meta["inteiros"],
           nulos_texto=meta["nulos_texto"], cdf=meta["cdf"])
    print(f"✓ {fq(tabela):<45} {len(pdf):>9,} linhas")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Chaves primárias e estrangeiras (informativas)

# COMMAND ----------

for pk in MANIFESTO["pks"]:
    chave_pk(pk["tabela"], pk["coluna"], pk["nome"])
for fk in MANIFESTO["fks"]:
    chave_fk(fk["tabela"], fk["coluna"], fk["ref_tabela"], fk["ref_coluna"], fk["nome"])

display(spark.sql(f"SELECT apelido, estilo_favorito, n_pedidos FROM {fq('perfis_demo')} ORDER BY apelido"))
print("✅ etapa 1 concluída")
