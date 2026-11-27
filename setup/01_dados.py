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


FONTES_VS = {"produtos": "produto_id"}   # tabelas que alimentam índices do Vector Search (etapa 04) → chave do MERGE


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
    if tabela in FONTES_VS and spark.catalog.tableExists(fq(tabela)):
        # reinstalação de uma tabela que alimenta o Vector Search: MERGE em vez de overwrite. Reescrever a tabela
        # quebra a sincronização incremental do índice (ONLINE_PIPELINE_FAILED); com MERGE só as mudanças vão para ele
        chave = FONTES_VS[tabela]
        sdf.createOrReplaceTempView(f"novos_{tabela}")
        try:
            spark.sql(f"""MERGE INTO {fq(tabela)} t USING novos_{tabela} s ON t.{chave} = s.{chave}
                          WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT * WHEN NOT MATCHED BY SOURCE THEN DELETE""")
            spark.sql(f"COMMENT ON TABLE {fq(tabela)} IS '{comentario.replace(MARCA_DADOS, MARCA)}'")
            return sdf
        except Exception as e:   # colunas mudaram: reescreve (a etapa 04 recria o índice se a sincronização quebrar)
            print(f"   • MERGE em {tabela} não deu ({str(e)[:100]}); reescrevendo a tabela")
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

# 📅 As datas dos Parquet são fixas (os dados foram gerados uma vez). Na carga, pedidos, navegação e cadastros andam o
# MESMO número de dias, para o último pedido cair em ONTEM: a previsão (ai_forecast) não vê "dias sem venda" que são só
# falta de dado, e os prazos (troca em 30 dias, entrega prevista, "em transporte") e os "mais vendidos da semana" ficam atuais.
# As datas de cadastro dos PRODUTOS não mudam (a tabela alimenta o Vector Search; mexer nela ressincronizaria o índice).
_fim_dados = pd.read_parquet(f"{DADOS}/pedidos.parquet", columns=["data_pedido"])["data_pedido"].max().normalize()
DESLOCAR_DIAS = max(0, ((pd.Timestamp.today().normalize() - pd.Timedelta(days=1)) - _fim_dados).days)
COLUNAS_DATA = {"pedidos": ["data_pedido"], "eventos_navegacao": ["data_hora"], "clientes": ["data_cadastro"]}


def deslocar_datas(pdf, tabela):
    for c in COLUNAS_DATA.get(tabela, []):
        if DESLOCAR_DIAS and c in pdf.columns:
            if pd.api.types.is_datetime64_any_dtype(pdf[c]):
                pdf[c] = pdf[c] + pd.Timedelta(days=DESLOCAR_DIAS)
            else:   # texto 'AAAA-MM-DD'
                d = pd.to_datetime(pdf[c], errors="coerce") + pd.Timedelta(days=DESLOCAR_DIAS)
                pdf[c] = d.dt.strftime("%Y-%m-%d").where(d.notna(), pdf[c])
    return pdf


# reinstalação: tira a tag de dados sensíveis (etapa 05d) antes de regravar clientes; a 05d põe de volta
for _col in ("nome", "email"):
    try:
        spark.sql(f"ALTER TABLE {fq('clientes')} ALTER COLUMN {_col} UNSET TAGS ('dados_sensiveis')")
    except Exception:
        pass   # primeira instalação ou sem a tag

print(f"📅 datas dos dados deslocadas em {DESLOCAR_DIAS} dia(s): o último pedido fica em "
      f"{(_fim_dados + pd.Timedelta(days=DESLOCAR_DIAS)).date():%d/%m/%Y}")
for tabela, meta in MANIFESTO["tabelas"].items():
    pdf = deslocar_datas(trocar_marca(pd.read_parquet(f"{DADOS}/{tabela}.parquet")), tabela)
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
