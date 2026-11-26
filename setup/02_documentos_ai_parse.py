# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 02 · Central de ajuda e fichas de fornecedor com `ai_parse_document`
# MAGIC
# MAGIC A central de ajuda da loja nasce de **PDFs de verdade** (trocas, entrega e frete, pagamento e parcelamento,
# MAGIC garantia, programa de fidelidade, retirada em loja, privacidade do Detetive de Produtos e termos de uso),
# MAGIC que ficam na pasta `documentos/` do repositório.
# MAGIC
# MAGIC ```
# MAGIC  documentos/*.pdf ──► Volume UC ──► ai_parse_document() ──► documentos_parseados (VARIANT)
# MAGIC                                                                   │  chunk por seção
# MAGIC                                                                   ▼  (tabelas HTML → texto)
# MAGIC                                                       central_ajuda_chunks ──► Vector Search (ajuda_index)
# MAGIC ```
# MAGIC
# MAGIC O `ai_parse_document` extrai **títulos, seções, parágrafos e tabelas** (com página e posição) direto em
# MAGIC SQL, sem nenhuma biblioteca de OCR. Novos PDFs podem ser enviados depois pela aba **Estúdio → Documentos**
# MAGIC do App, que usa o mesmo fluxo.
# MAGIC
# MAGIC No fim do notebook, as **fichas técnicas de fornecedor** (`fichas/*.pdf`) mostram como o Estúdio cadastra
# MAGIC produtos a partir de PDF: foto principal, tabelas de especificações e grade de tamanhos, preços e condições.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import os, shutil

VOL_DOCS = f"/Volumes/{CATALOG}/{SCHEMA}/documentos"
origem = f"{REPO_FS}/documentos"
pdfs = sorted(f for f in os.listdir(origem) if f.lower().endswith(".pdf"))
for f in pdfs:
    shutil.copyfile(f"{origem}/{f}", f"{VOL_DOCS}/{f}")
print(f"✅ {len(pdfs)} PDFs da central de ajuda copiados para {VOL_DOCS}:")
for f in pdfs:
    print("   •", f)

# COMMAND ----------

# MAGIC %md
# MAGIC ### `ai_parse_document` em SQL
# MAGIC `read_files(..., format => 'binaryFile')` lê os PDFs como binário e `ai_parse_document` devolve um
# MAGIC **VARIANT** com `document.elements[]` (tipo, conteúdo, página, bounding box).

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {fq('documentos_parseados')}
COMMENT 'Saída bruta do ai_parse_document para cada PDF da central de ajuda'
AS
SELECT
  regexp_extract(path, '[^/]+$', 0)                     AS arquivo,
  path,
  ai_parse_document(content, map('version', '2.0'))    AS parsed,
  current_timestamp()                                   AS processado_em
FROM read_files('{VOL_DOCS}/', format => 'binaryFile', pathGlobFilter => '*.pdf')
""")

display(spark.sql(f"""
SELECT arquivo,
       size(cast(parsed:document:elements AS ARRAY<VARIANT>)) AS n_elementos,
       parsed:document:elements[0]:content::string            AS primeiro_elemento,
       parsed:error_status                                    AS erros
FROM {fq('documentos_parseados')} ORDER BY arquivo
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Exemplo: as **tabelas** que o `ai_parse_document` encontrou (em HTML)
# MAGIC Prazos de troca, frete por região, parcelas, níveis do programa de fidelidade e lojas com retirada.

# COMMAND ----------

display(spark.sql(f"""
SELECT arquivo, e:content::string AS tabela_html
FROM {fq('documentos_parseados')},
     LATERAL variant_explode(parsed:document:elements) AS t(pos, key, e)
WHERE e:type::string = 'table'
ORDER BY arquivo
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Chunking por seção
# MAGIC A função `chunkar_documento` fica em `app/backend/documentos.py` — **o mesmo código** é usado pelo App
# MAGIC quando você sobe um PDF novo no Estúdio.

# COMMAND ----------

import sys, json
sys.path.insert(0, f"{REPO_FS}/app")
from backend.documentos import chunkar_documento

linhas = spark.sql(f"SELECT arquivo, to_json(parsed) AS j FROM {fq('documentos_parseados')}").collect()
chunks = []
for r in linhas:
    chunks.extend(chunkar_documento(r["j"], r["arquivo"]))

import pandas as pd
df_chunks = pd.DataFrame(chunks)
novos = spark.createDataFrame(df_chunks)
mesclado = False
if spark.catalog.tableExists(fq("central_ajuda_chunks")):
    # reinstalação: MERGE em vez de overwrite. Reescrever a tabela quebra a sincronização incremental do
    # ajuda_index (Vector Search fica em ONLINE_PIPELINE_FAILED); com MERGE só as mudanças vão para o índice
    novos.createOrReplaceTempView("chunks_novos")
    try:
        spark.sql(f"""MERGE INTO {fq('central_ajuda_chunks')} t USING chunks_novos s ON t.chunk_id = s.chunk_id
                      WHEN MATCHED THEN UPDATE SET *
                      WHEN NOT MATCHED THEN INSERT *
                      WHEN NOT MATCHED BY SOURCE THEN DELETE""")
        mesclado = True
    except Exception as e:   # colunas mudaram: reescreve (a etapa 04 recria o índice se a sincronização quebrar)
        print("   • MERGE não deu (", str(e)[:100], "); reescrevendo a tabela")
if not mesclado:
    (novos.write.mode("overwrite").option("overwriteSchema", "true").option("delta.enableChangeDataFeed", "true")
          .saveAsTable(fq("central_ajuda_chunks")))
spark.sql(f"ALTER TABLE {fq('central_ajuda_chunks')} ALTER COLUMN chunk_id SET NOT NULL")
try:
    spark.sql(f"ALTER TABLE {fq('central_ajuda_chunks')} ADD CONSTRAINT pk_ajuda PRIMARY KEY (chunk_id)")
except Exception:
    pass
spark.sql(f"COMMENT ON TABLE {fq('central_ajuda_chunks')} IS 'Chunks da central de ajuda extraídos dos PDFs via ai_parse_document (fonte do ajuda_index)'")
print(f"✅ {len(df_chunks)} chunks de {len(linhas)} PDFs em {fq('central_ajuda_chunks')}")
display(spark.table(fq("central_ajuda_chunks")).select("chunk_id", "documento", "secao", "tem_tabela", "conteudo"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fichas técnicas de fornecedor: cadastro de produtos a partir de PDF
# MAGIC
# MAGIC A aba **Estúdio** do App cadastra produtos novos a partir de uma **ficha técnica em PDF** enviada pelo
# MAGIC fornecedor. Os exemplos da pasta `fichas/` (sofá, tênis de corrida e headset) vão para o Volume
# MAGIC `midia/fichas_exemplo/`. A tabela `fichas_parseadas` guarda cada ficha processada, com a saída do
# MAGIC `ai_parse_document` e o `produto_id` cadastrado.

# COMMAND ----------

VOL_FICHAS = f"/Volumes/{CATALOG}/{SCHEMA}/midia/fichas_exemplo"
os.makedirs(VOL_FICHAS, exist_ok=True)
fichas = sorted(f for f in os.listdir(f"{REPO_FS}/fichas") if f.lower().endswith(".pdf"))
for f in fichas:
    shutil.copyfile(f"{REPO_FS}/fichas/{f}", f"{VOL_FICHAS}/{f}")
    print("   •", f)
print(f"✅ {len(fichas)} fichas copiadas para {VOL_FICHAS}")

# Foto de exemplo para a busca visual no Playground (MCP Detetive): /Volumes/<catalog>/<schema>/midia/exemplos/
VOL_EXEMPLOS = f"/Volumes/{CATALOG}/{SCHEMA}/midia/exemplos"
os.makedirs(VOL_EXEMPLOS, exist_ok=True)
for f in sorted(os.listdir(f"{REPO_FS}/imagens_exemplo")):
    if f.lower().endswith((".jpg", ".jpeg", ".png")):
        shutil.copyfile(f"{REPO_FS}/imagens_exemplo/{f}", f"{VOL_EXEMPLOS}/{f}")
        print(f"✅ foto de exemplo: {VOL_EXEMPLOS}/{f}")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq('fichas_parseadas')} (
  chave STRING, arquivo STRING, path STRING, parsed VARIANT, produto_id STRING, processado_em TIMESTAMP)
  COMMENT 'Fichas técnicas de fornecedor processadas pelo Estúdio do App com ai_parse_document (PDF → produto)'""")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Demonstração: figuras e tabelas de uma ficha
# MAGIC Com `imageOutputPath`, cada **figura** é gravada como imagem no Volume (o App usa a bounding box para
# MAGIC recortar a foto do produto). Com `descriptionElementTypes = '*'`, o modelo também descreve cada figura
# MAGIC em linguagem natural. A **primeira figura** é sempre a foto principal.

# COMMAND ----------

amostra = f"{VOL_FICHAS}/{fichas[0]}"
PASTA_IMG = f"/Volumes/{CATALOG}/{SCHEMA}/midia/fichas_exemplo/_paginas/"
os.makedirs(PASTA_IMG, exist_ok=True)

try:   # demonstração (não alimenta o App): limite de LLM (429) ou cota não derrubam a instalação
    display(spark.sql(f"""
WITH p AS (
  SELECT ai_parse_document(content, map(
           'version', '2.0',
           'imageOutputPath', '{PASTA_IMG}',
           'descriptionElementTypes', '*')) AS parsed
  FROM read_files('{amostra}', format => 'binaryFile'))
SELECT e:type::string AS tipo,
       e:bbox[0]:page_id::int + 1 AS pagina,
       left(e:content::string, 120) AS conteudo,
       e:description::string AS descricao_da_imagem
FROM p, LATERAL variant_explode(parsed:document:elements) AS t(pos, key, e)
WHERE e:type::string IN ('figure', 'table', 'section_header', 'caption')
"""))
except Exception as e:
    print("⚠️ demonstração do ai_parse_document pulada:", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Tabela de grade de tamanhos (exemplo do tênis)
# MAGIC Tabelas de fichas viram HTML; o App converte para a grade de tamanhos do produto.

# COMMAND ----------

try:   # demonstração: não derruba a instalação
    display(spark.sql(f"""
WITH p AS (
  SELECT ai_parse_document(content, map('version', '2.0')) AS parsed
  FROM read_files('{VOL_FICHAS}/ficha_tenis_corrida_pulse.pdf', format => 'binaryFile'))
SELECT e:content::string AS tabela_html
FROM p, LATERAL variant_explode(parsed:document:elements) AS t(pos, key, e)
WHERE e:type::string = 'table'
"""))
except Exception as e:
    print("⚠️ demonstração da grade de tamanhos pulada:", str(e)[:200])
print("✅ etapa 2 concluída")
