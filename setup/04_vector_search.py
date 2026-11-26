# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 04 · Vector Search (AI Search)
# MAGIC
# MAGIC Cria dois índices **Delta Sync** com embeddings gerenciados:
# MAGIC
# MAGIC | Índice | Fonte | Coluna embedada | Usado por |
# MAGIC |--------|-------|-----------------|-----------|
# MAGIC | `produtos_index` | `produtos` | `texto_busca` (nome + tipo + departamento + descrição + **descrição visual**) | busca do App, **Detetive de Produtos**, agente |
# MAGIC | `ajuda_index` | `central_ajuda_chunks` | `conteudo` (chunks dos PDFs) | suporte (RAG) do agente |
# MAGIC
# MAGIC > Se o workspace permitir **só 1 endpoint** de Vector Search e já existir algum
# MAGIC > endpoint no workspace (de outro lab, por exemplo), ele é **reaproveitado** — os índices novos só
# MAGIC > são adicionados a ele.
# MAGIC
# MAGIC O modelo de embedding padrão é o `databricks-qwen3-embedding-0-6b`, **multilíngue** (bom em português).

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import time
from databricks.vector_search.client import VectorSearchClient

VS_OK = False
try:   # tolerante: sem Vector Search, a instalação segue (o App sobe; só a busca semântica fica indisponível)
    vsc = VectorSearchClient(disable_notice=True)
    existentes = [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]
    if VS_ENDPOINT in existentes:
        print(f"✅ endpoint {VS_ENDPOINT} já existe")
    else:
        try:
            print(f"Criando endpoint {VS_ENDPOINT} (leva alguns minutos)...")
            vsc.create_endpoint(name=VS_ENDPOINT, endpoint_type="STANDARD")
        except Exception as e:
            # workspace com limite de endpoints (ex.: só 1): reaproveita um existente; num workspace corporativo
            # sem limite, o endpoint próprio é criado normalmente e nada de outras pessoas é usado
            if not existentes:
                raise
            print(f"♻️ não pude criar {VS_ENDPOINT} ({str(e)[:120]}): reaproveitando '{existentes[0]}'")
            VS_ENDPOINT = existentes[0]
    vsc.wait_for_endpoint(VS_ENDPOINT, verbose=True)
    VS_OK = True
except Exception as e:
    print("⚠️ Vector Search indisponível (a instalação segue; busca semântica e Detetive ficam sem índice):", str(e)[:250])

# COMMAND ----------

IDX_PRODUTOS = fq("produtos_index")
IDX_AJUDA = fq("ajuda_index")
if VS_OK:   # sem Vector Search: célula pulada
    SPECS = {IDX_PRODUTOS: (fq("produtos"), "produto_id", "texto_busca"),
             IDX_AJUDA: (fq("central_ajuda_chunks"), "chunk_id", "conteudo")}

    def _criar(index_name):
        fonte, pk, coluna = SPECS[index_name]
        for tentativa in range(12):   # logo depois de apagar, o nome pode levar alguns segundos para ficar livre
            try:
                vsc.create_delta_sync_index(
                    endpoint_name=VS_ENDPOINT, index_name=index_name, source_table_name=fonte,
                    pipeline_type="TRIGGERED", primary_key=pk,
                    embedding_source_column=coluna, embedding_model_endpoint_name=EMBEDDING)
                print(f"＋ criando {index_name} sobre {fonte}.{coluna}")
                return
            except Exception as e:
                if tentativa == 11:
                    raise
                time.sleep(15)

    def recriar(index_name, motivo):
        """A etapa 01/02 reescreve a tabela de origem a cada instalação; a sincronização incremental pode quebrar
        (ONLINE_PIPELINE_FAILED). Recriar o índice faz a indexação completa de novo (poucos minutos)."""
        print(f"♻️ {index_name}: {motivo} → recriando o índice")
        try:
            vsc.delete_index(VS_ENDPOINT, index_name)
        except Exception as e:
            print("   (apagar):", str(e)[:100])
        time.sleep(20)
        _criar(index_name)

    def criar_ou_sincronizar(index_name, fonte, pk, coluna):
        nomes = [i["name"] for i in vsc.list_indexes(VS_ENDPOINT).get("vector_indexes", [])]
        if index_name in nomes:
            idx = vsc.get_index(VS_ENDPOINT, index_name)
            info = idx.describe()
            modelo = (info.get("delta_sync_index_spec", {}).get("embedding_source_columns") or [{}])[0].get("embedding_model_endpoint_name")
            estado = str((info.get("status") or {}).get("detailed_state", ""))
            if modelo and modelo != EMBEDDING:
                recriar(index_name, f"usa {modelo}; o configurado é {EMBEDDING}")
                return
            if "FAILED" in estado:
                recriar(index_name, f"sincronização anterior falhou ({estado})")
                return
            else:
                print(f"↻ {index_name} já existe — sincronizando")
                try:
                    idx.sync()
                except Exception as e:
                    print("  (sync já em andamento)", str(e)[:100])
                return
        _criar(index_name)


    criar_ou_sincronizar(IDX_PRODUTOS, fq("produtos"), "produto_id", "texto_busca")
    criar_ou_sincronizar(IDX_AJUDA, fq("central_ajuda_chunks"), "chunk_id", "conteudo")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Aguardando os índices ficarem prontos
# MAGIC A primeira indexação do catálogo (~3 mil produtos) leva alguns minutos.

# COMMAND ----------

if VS_OK:   # sem Vector Search: célula pulada
    esperado = {IDX_PRODUTOS: spark.table(fq("produtos")).count(), IDX_AJUDA: spark.table(fq("central_ajuda_chunks")).count()}
    pendentes, recriados = set(esperado), set()
    inicio = time.time()
    while pendentes and time.time() - inicio < 25 * 60:
        for nome in list(pendentes):
            st = vsc.get_index(VS_ENDPOINT, nome).describe().get("status", {})
            n = st.get("indexed_row_count") or 0
            estado = str(st.get("detailed_state", ""))
            if st.get("ready") and n >= esperado[nome]:
                print(f"✅ {nome} pronto ({n} linhas)")
                pendentes.discard(nome)
            elif "FAILED" in estado and nome not in recriados:   # falhou: recria UMA vez (indexação completa)
                recriar(nome, f"sincronização falhou ({estado})")
                recriados.add(nome)
            elif "FAILED" in estado:   # falhou de novo: não fica esperando à toa
                print(f"⚠️ {nome} continua falhando ({st.get('message', '')[:120]}); seguindo (o índice antigo segue online)")
                pendentes.discard(nome)
            else:
                print(f"… {nome}: {n}/{esperado[nome]} · {st.get('detailed_state', '')} {st.get('message', '')[:70]}")
        if pendentes:
            time.sleep(30)
    if pendentes:
        print("⚠️ Índices ainda sincronizando — o App funciona assim que terminarem:", pendentes)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Teste: busca semântica por descrição visual (é isso que a busca visual do Detetive faz com a foto)

# COMMAND ----------

if VS_OK:   # sem Vector Search: célula pulada
    res = vsc.get_index(VS_ENDPOINT, IDX_PRODUTOS).similarity_search(
        query_text="sala clara com sofá de linho e madeira",
        columns=["nome", "departamento", "tipo", "estilo_id", "preco"], num_results=6)
    for r in res.get("result", {}).get("data_array", []):
        print(f"• {r[0]:<60} {r[1]:<18} {r[2]:<16} {r[3]:<12} R$ {r[4]}  (score {r[-1]:.3f})")
    print("✅ etapa 4 concluída")

