# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "psycopg[binary]>=3.2"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 05c · Lakebase (Postgres OLTP) + Lakehouse: sync nos dois sentidos
# MAGIC
# MAGIC O App passa a gravar os **pedidos novos** e as **solicitações de pós-venda** no **Lakebase**, um Postgres
# MAGIC gerenciado e transacional (escrita em ~0,2 s). O Lakehouse continua sendo a fonte de análise, e **enxerga
# MAGIC esses dados na hora**:
# MAGIC
# MAGIC ```
# MAGIC                    ┌──────────── Delta → Postgres: synced tables (produtos, recomendações) ───────────┐
# MAGIC                    │                                                                                  ▼
# MAGIC  Lakehouse (Delta) brickstore.varejo                                        Lakebase  databricks_postgres
# MAGIC  pedidos / itens_pedido (histórico)                                          loja.pedidos / loja.itens_pedido
# MAGIC        │                                                                     loja.solicitacoes_atendimento
# MAGIC        │                                                                            ▲          │
# MAGIC        └──► vw_pedidos_todos = histórico Delta UNION ALL ◄── catálogo UC brickstore_loja ◄──┘  (registro do
# MAGIC             (Genie, Agente Analista, "Meus pedidos")            leitura AO VIVO (~1 s)       database no UC)
# MAGIC ```
# MAGIC
# MAGIC | Sentido | Como | Latência |
# MAGIC |---------|------|----------|
# MAGIC | **App → Lakebase** | `INSERT` transacional (psycopg + token OAuth da service principal) | ~0,2 s |
# MAGIC | **Lakebase → Lakehouse** | database registrado no Unity Catalog (`brickstore_loja`) + views `vw_*_todos` | o pedido aparece no SQL/Genie em ~1 s |
# MAGIC | **Lakehouse → Lakebase** | *synced tables* (snapshot) de `produtos` e `recomendacoes_personalizadas` | sob demanda |
# MAGIC
# MAGIC > Em workspaces com limites, o projeto fica com 1 CU e 512 MB por branch. O *Lakehouse Sync* (CDF para tabelas `lb_*_history`)
# MAGIC > **não funciona** em catálogos com Default Storage (`Lakebase CDF is not supported for catalogs using Default
# MAGIC > Storage`); por isso o caminho Postgres → Lakehouse é o registro no UC, que ainda é **ao vivo**.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import time

import psycopg
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
SCHEMA_PG = "loja"


def rest(metodo, caminho, corpo=None, query=None):
    return w.api_client.do(metodo, caminho, body=corpo, query=query)


def esperar(op, rotulo, limite=900):
    """Espera uma long-running operation da API de Postgres terminar."""
    t0 = time.time()
    while not op.get("done"):
        if time.time() - t0 > limite:
            raise TimeoutError(f"{rotulo}: tempo esgotado")
        time.sleep(8)
        op = rest("GET", f"/api/2.0/postgres/{op['name']}")
    if op.get("error"):
        raise RuntimeError(f"{rotulo}: {op['error']}")
    return op.get("response") or {}


# 1) Projeto NOVO a cada instalação (branch production + endpoint primary, scale to zero).
#    Nunca restaura nem reaproveita: usa o primeiro nome livre (<app_name>, <app_name>-2, ...). Um nome preso
#    (projeto na lixeira por 7 dias, projeto antigo ainda ativo) ou uma falha na criação passa para o próximo nome.
def _existe(pid):
    try:
        return rest("GET", f"/api/2.0/postgres/projects/{pid}")
    except Exception:
        return None


def _endpoint_pronto(endpoint, tentativas=60):
    for _ in range(tentativas):   # logo após criar, o endpoint leva alguns segundos para aparecer
        try:
            ep = rest("GET", f"/api/2.0/postgres/{endpoint}")
            st = ep.get("status") or {}
            if st.get("hosts", {}).get("host") and not st.get("disabled"):
                return ep
        except Exception:
            pass
        time.sleep(5)
    return None


PROJETO, proj, ep, falhas = None, None, None, []
for pid in [LAKEBASE_BASE] + [f"{LAKEBASE_BASE}-{n}" for n in range(2, 10)]:
    antigo = _existe(pid)
    if antigo:
        falhas.append(f"{pid}: já existe" + (" (na lixeira)" if antigo.get("delete_time") else "") + " → próximo nome")
        continue
    try:
        print(f"＋ criando o projeto Lakebase NOVO {pid} (Postgres 17)…")
        proj = esperar(rest("POST", "/api/2.0/postgres/projects", {"spec": {"display_name": f"{MARCA} · loja (OLTP)", "pg_version": 17}},
                            {"project_id": pid}), "create-project")
        ep = _endpoint_pronto(f"projects/{pid}/branches/production/endpoints/primary")
        if not ep:
            raise RuntimeError("endpoint primary não ficou disponível")
        PROJETO = pid
        break
    except Exception as e:
        falhas.append(f"{pid}: {str(e)[:160]}")
for f in falhas:
    print("   •", f)
if not PROJETO:
    # Tolerante: sem Lakebase (região sem o recurso, cota de projetos, permissão), a instalação SEGUE.
    # O App grava pedidos e solicitações no Delta e a memória do chat fica desligada.
    print("⚠️ Lakebase indisponível (motivos acima): seguindo SEM Lakebase. Para usá-lo depois, resolva o motivo e rode o INSTALAR de novo.")
    CATALOGO_LB = None
else:
    if not proj or not proj.get("status"):
        proj = _existe(PROJETO) or {}
    BRANCH = f"projects/{PROJETO}/branches/production"
    ENDPOINT = f"{BRANCH}/endpoints/primary"
    DATABASE = f"{BRANCH}/databases/databricks-postgres"     # Lakehouse sync / registro no UC exigem o databricks_postgres
    lim = (proj.get("status") or {})
    print(f"✅ projeto Lakebase {PROJETO} · limite por branch:", int(lim.get("branch_logical_size_limit_bytes", 0)) // 2**20, "MB ·",
          "CU:", (lim.get("default_endpoint_settings") or {}).get("autoscaling_limit_max_cu"))
    HOST = ep["status"]["hosts"]["host"]
    print("   endpoint:", HOST)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Tabelas OLTP no Postgres (schema `loja`)
# MAGIC Mesmas colunas das tabelas Delta, mais `conversas` (a **memória do Assistente**). `REPLICA IDENTITY FULL` deixa tudo pronto para o Lakehouse Sync (CDF) num
# MAGIC workspace pago com catálogo em storage externo.

# COMMAND ----------

if PROJETO:   # sem Lakebase: célula pulada
    def conectar():
        token = w.postgres.generate_database_credential(endpoint=ENDPOINT).token
        return psycopg.connect(host=HOST, dbname="databricks_postgres", user=USUARIO, password=token, sslmode="require", autocommit=True)


    with conectar() as c:
        c.execute(f"""
          CREATE SCHEMA IF NOT EXISTS {SCHEMA_PG};
          CREATE TABLE IF NOT EXISTS {SCHEMA_PG}.pedidos (
            pedido_id text PRIMARY KEY, cliente_id text NOT NULL, data_pedido timestamptz NOT NULL DEFAULT now(), canal text, loja text,
            forma_pagamento text, parcelas int, status text, valor_total double precision, frete double precision);
          CREATE TABLE IF NOT EXISTS {SCHEMA_PG}.itens_pedido (
            pedido_id text NOT NULL REFERENCES {SCHEMA_PG}.pedidos(pedido_id), produto_id text NOT NULL, quantidade int,
            preco_unitario double precision, desconto double precision, PRIMARY KEY (pedido_id, produto_id));
          CREATE TABLE IF NOT EXISTS {SCHEMA_PG}.solicitacoes_atendimento (
            protocolo text PRIMARY KEY, cliente_id text, pedido_id text, produto_id text, tipo text, motivo text, status text,
            prazo text, aberto_em timestamptz DEFAULT now());
          -- 🧠 memória do Assistente: cada turno do chat, por cliente e conversa (o App relê para lembrar do que foi perguntado)
          CREATE TABLE IF NOT EXISTS {SCHEMA_PG}.conversas (
            mensagem_id text PRIMARY KEY, conversa_id text NOT NULL, cliente_id text NOT NULL, papel text NOT NULL,
            conteudo text NOT NULL, agente text, modelo text, criado_em timestamptz NOT NULL DEFAULT now());
          ALTER TABLE {SCHEMA_PG}.conversas ADD COLUMN IF NOT EXISTS modelo text;
          CREATE INDEX IF NOT EXISTS ix_conversas_cliente ON {SCHEMA_PG}.conversas (cliente_id, criado_em DESC);
          CREATE INDEX IF NOT EXISTS ix_pedidos_cliente ON {SCHEMA_PG}.pedidos (cliente_id, data_pedido DESC);
          ALTER TABLE {SCHEMA_PG}.pedidos REPLICA IDENTITY FULL;
          ALTER TABLE {SCHEMA_PG}.itens_pedido REPLICA IDENTITY FULL;
          ALTER TABLE {SCHEMA_PG}.solicitacoes_atendimento REPLICA IDENTITY FULL;
          ALTER TABLE {SCHEMA_PG}.conversas REPLICA IDENTITY FULL;""")
        print("✅ tabelas:", [r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY 1", (SCHEMA_PG,)).fetchall()])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Lakebase → Lakehouse: database registrado no Unity Catalog + views unificadas
# MAGIC O catálogo `<catalog>_loja` lê o Postgres **ao vivo** pelo SQL warehouse. As views juntam o histórico (Delta)
# MAGIC com os pedidos novos (Lakebase) — é o que o Genie, o Agente Analista e o App consultam.

# COMMAND ----------

if PROJETO:   # sem Lakebase: célula pulada
    # Registro no UC: <catalog>_loja. Se o nome já aponta para um projeto antigo, refaz o registro; se não der, usa _loja_2...
    CATALOGO_LB = lakebase_catalogo(w, BRANCH)
    if CATALOGO_LB:
        print(f"↻ catálogo {CATALOGO_LB} já registrado para {PROJETO}")
    else:
        for i in range(1, 6):
            nome = f"{CATALOG}_loja" + ("" if i == 1 else f"_{i}")
            try:
                antigo = rest("GET", f"/api/2.0/postgres/catalogs/{nome}")
            except Exception:
                antigo = None
            if antigo:
                # só solta o nome se o registro antigo for de um projeto SEU (ou de um projeto que já não existe);
                # registro de outra pessoa num workspace compartilhado: pula para o próximo nome
                proj_antigo = (antigo.get("status") or {}).get("project") or "/".join(
                    ((antigo.get("spec") or {}).get("branch") or "").split("/")[:2])
                info = _existe(proj_antigo.split("/")[-1]) if proj_antigo else None
                dono = ((info or {}).get("status") or {}).get("owner")
                if dono and dono != USUARIO:
                    print(f"   • {nome} pertence a um projeto de {dono}: próximo nome")
                    continue
            try:
                if antigo:   # registro antigo seu: solta o nome e registra de novo para o projeto novo
                    print(f"   • {nome} apontava para {proj_antigo or 'outro projeto'}: refazendo o registro")
                    rest("DELETE", f"/api/2.0/postgres/catalogs/{nome}")
                    time.sleep(5)
                esperar(rest("POST", "/api/2.0/postgres/catalogs", {"spec": {"postgres_database": "databricks_postgres", "branch": BRANCH}},
                             {"catalog_id": nome}), "create-catalog")
                CATALOGO_LB = nome
                print(f"＋ database registrado no UC como {CATALOGO_LB}")
                break
            except Exception as e:
                print(f"   • {nome}: {str(e)[:160]} → próximo nome")
        if not CATALOGO_LB:   # tolerante: segue sem Lakebase (o App grava no Delta)
            print("⚠️ não consegui registrar o database do Lakebase no Unity Catalog: seguindo SEM Lakebase")
            PROJETO = None

    if CATALOGO_LB:
        # A tabela Delta de solicitações nasce no 05b (que roda depois); garante que ela exista para a view
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq('solicitacoes_atendimento')} (
          protocolo STRING, cliente_id STRING, pedido_id STRING, produto_id STRING, tipo STRING, motivo STRING,
          status STRING, prazo STRING, aberto_em TIMESTAMP)
          COMMENT 'Solicitacoes de pos-venda (troca, devolucao, garantia, reclamacao) abertas pelo Agente de Pos-venda'""")

        VIEWS = {
            "vw_pedidos_todos": ("Pedidos: historico (Delta) + novos do App ao vivo (Lakebase). Use esta view para pedidos.",
                                 "pedido_id, cliente_id, data_pedido, canal, loja, forma_pagamento, parcelas, status, valor_total, frete",
                                 "pedidos"),
            "vw_itens_pedido_todos": ("Itens dos pedidos: historico (Delta) + novos do App ao vivo (Lakebase).",
                                      "pedido_id, produto_id, quantidade, preco_unitario, desconto", "itens_pedido"),
            "vw_solicitacoes_todas": ("Solicitacoes de pos-venda: Delta + novas do App ao vivo (Lakebase).",
                                      "protocolo, cliente_id, pedido_id, produto_id, tipo, motivo, status, prazo, aberto_em",
                                      "solicitacoes_atendimento"),
        }
        for vw, (comentario, colunas, tab) in VIEWS.items():
            for tentativa in range(12):   # catálogo recém-registrado pode levar alguns segundos para responder
                try:
                    spark.sql(f"""CREATE OR REPLACE VIEW {fq(vw)} COMMENT '{comentario}' AS
                                  SELECT {colunas}, 'lakehouse' AS origem FROM {fq(tab)}
                                  UNION ALL
                                  SELECT {colunas}, 'lakebase' AS origem FROM {CATALOGO_LB}.{SCHEMA_PG}.{tab}""")
                    break
                except Exception as e:
                    if tentativa == 11:   # tolerante: sem as views, o 06_app não liga o Lakebase no App
                        print(f"⚠️ view {fq(vw)} não criada ({str(e)[:120]}): o App segue sem Lakebase")
                        spark.sql(f"DROP VIEW IF EXISTS {fq('vw_pedidos_todos')}")
                        break
                    print(f"   … {CATALOGO_LB}.{SCHEMA_PG}.{tab} ainda não visível ({str(e)[:90]}); nova tentativa em 10 s")
                    time.sleep(10)
            print("✅ view", fq(vw))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Lakehouse → Lakebase: synced tables (snapshot)
# MAGIC Cópias de `produtos` e `recomendacoes_personalizadas` dentro do Postgres, para leituras de baixa latência
# MAGIC (ex.: outro serviço OLTP). Rode de novo esta etapa para atualizar o snapshot.

# COMMAND ----------

if PROJETO:   # sem Lakebase: célula pulada
    SINCRONIZADAS = {"lb_produtos": ("produtos", ["produto_id"]),
                     "lb_recomendacoes": ("recomendacoes_personalizadas", ["cliente_id", "produto_id"])}
    for destino, (origem, pk) in SINCRONIZADAS.items():
        nome = fq(destino)
        try:
            st = rest("GET", f"/api/2.0/postgres/synced_tables/{nome}")
        except Exception:
            st = None
        if st and BRANCH in ((st.get("spec") or {}).get("branch"), (st.get("status") or {}).get("branch")):
            print(f"↻ {nome}: {(st.get('status') or {}).get('detailed_state')}")
            continue
        if st:   # sobrou de uma instalação anterior (outro projeto Lakebase): recria apontando para o projeto novo
            try:
                rest("DELETE", f"/api/2.0/postgres/synced_tables/{nome}")
                spark.sql(f"DROP TABLE IF EXISTS {nome}")
                time.sleep(5)
            except Exception as e:
                print(f"⚠️ synced table antiga {nome} não removida ({str(e)[:120]}): pulando")
                continue
        try:
            rest("POST", "/api/2.0/postgres/synced_tables", {"spec": {
                "source_table_full_name": fq(origem), "primary_key_columns": pk, "scheduling_policy": "SNAPSHOT",
                "branch": BRANCH, "postgres_database": "databricks_postgres", "create_database_objects_if_missing": True}},
                 {"synced_table_id": nome})
            print(f"＋ {nome} ← {fq(origem)} (snapshot em andamento; ~1-3 min)")
        except Exception as e:
            print(f"⚠️ synced table {nome} não criada: {str(e)[:200]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Permissões da service principal do App
# MAGIC Quando o App existe (etapa 06), ele ganha o recurso `postgres` e a SP vira um role no Postgres. Aqui ela recebe
# MAGIC leitura/escrita no schema `loja` e leitura no catálogo `<catalog>_loja` (para as views).

# COMMAND ----------

if PROJETO:   # sem Lakebase: célula pulada
    try:
        SP = rest("GET", f"/api/2.0/apps/{APP_NAME}").get("service_principal_client_id")
    except Exception:
        SP = None
    if SP:
        with conectar() as c:
            existe = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (SP,)).fetchone()
            if existe:
                c.execute(f'GRANT USAGE ON SCHEMA {SCHEMA_PG} TO "{SP}"')
                c.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {SCHEMA_PG} TO "{SP}"')
                c.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA_PG} GRANT SELECT, INSERT, UPDATE ON TABLES TO "{SP}"')
                c.execute(f'GRANT DELETE ON {SCHEMA_PG}.conversas TO "{SP}"')   # botão "esquecer" do chat
                print("✅ SP do App com acesso ao schema", SCHEMA_PG)
            else:
                print("• o role da SP ainda não existe no Postgres (o 06_app anexa o recurso e roda estes GRANTs de novo)")
        spark.sql(f"GRANT USE CATALOG ON CATALOG {CATALOGO_LB} TO `{SP}`")
        spark.sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOGO_LB}.{SCHEMA_PG} TO `{SP}`")
    else:
        print("• App ainda não existe: as permissões são aplicadas pelo setup/06_app")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Prova: um pedido gravado no Postgres aparece no Lakehouse na hora

# COMMAND ----------

if PROJETO:   # sem Lakebase: célula pulada
    try:   # demonstração: não derruba a instalação
        pid = "PDEMO" + time.strftime("%H%M%S")
        with conectar() as c:
            t0 = time.time()
            c.execute(f"""INSERT INTO {SCHEMA_PG}.pedidos (pedido_id, cliente_id, canal, status, valor_total, frete)
                          VALUES (%s, 'C000001', 'demo-05c', 'Em transporte', 99.9, 0)""", (pid,))
            print(f"escrita no Lakebase: {(time.time() - t0) * 1000:.0f} ms")
        t0 = time.time()
        display(spark.sql(f"SELECT origem, pedido_id, cliente_id, status, data_pedido FROM {fq('vw_pedidos_todos')} WHERE pedido_id = '{pid}'"))
        print(f"lido pela view do Lakehouse em {time.time() - t0:.1f} s")
    except Exception as e:
        print("⚠️ prova pulada:", str(e)[:200])
    finally:
        try:
            with conectar() as c:
                c.execute(f"DELETE FROM {SCHEMA_PG}.pedidos WHERE canal = 'demo-05c'")
        except Exception:
            pass

if not PROJETO:   # sem Lakebase: tira as views de uma instalação anterior (apontariam para um projeto antigo)
    for _vw in ("vw_pedidos_todos", "vw_itens_pedido_todos", "vw_solicitacoes_todas"):
        spark.sql(f"DROP VIEW IF EXISTS {fq(_vw)}")
    CATALOGO_LB = None
LAKEBASE_PROJETO, LAKEBASE_CATALOGO = (PROJETO or ""), CATALOGO_LB
print(f"✅ etapa concluída · projeto {PROJETO or '— (sem Lakebase)'} · catálogo {CATALOGO_LB or '—'}")

