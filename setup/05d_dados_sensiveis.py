# Databricks notebook source
# MAGIC %md
# MAGIC # 05d · Dados sensíveis com ABAC (governed tag + column mask)
# MAGIC
# MAGIC Os dados pessoais dos clientes (`clientes.nome` e `clientes.email`) ficam protegidos por **ABAC** (controle de
# MAGIC acesso por atributos) do Unity Catalog:
# MAGIC
# MAGIC ```
# MAGIC  governed tag  dados_sensiveis  ──►  colunas clientes.nome, clientes.email
# MAGIC  policy ABAC   mascara_dados_sensiveis (ON SCHEMA)  ──►  COLUMN MASK mascara_penultima
# MAGIC                MATCH COLUMNS has_tag('dados_sensiveis')         "Gustavo Dias" → "**********a*"
# MAGIC ```
# MAGIC
# MAGIC A policy vale para **todas as colunas com a tag**. Por isso, **revogar** o acesso é **colocar** a tag na coluna e
# MAGIC **liberar** é **tirar** a tag: a máscara passa a valer (ou deixa de valer) na hora, para o App, o Genie, o SQL
# MAGIC editor e qualquer outra ferramenta. O App faz isso no **Estúdio → 📊 Dados** (botões *Revogar* e *Liberar*):
# MAGIC o botão dispara o job **`<app_name> · acesso a dados sensíveis`**, criado aqui, que roda **como quem instalou**
# MAGIC (dono da tabela e da governed tag). O App só tem permissão para disparar o job: nada de consentimento extra.
# MAGIC
# MAGIC A máscara deixa só a **penúltima letra** visível. A instalação termina com o acesso **revogado** (protegido).
# MAGIC
# MAGIC **Tolerante:** sem ABAC ou sem permissão para criar governed tags, a etapa avisa e o App segue sem a parte de acesso.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import json
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
TAG = "dados_sensiveis"                 # governed tag (vale para a conta toda; é reaproveitada se já existir)
COLUNAS = [("clientes", "nome"), ("clientes", "email")]
FUNCAO = f"{CATALOG}.{SCHEMA}.mascara_penultima"
POLICY = "mascara_dados_sensiveis"
ABAC_OK, VALOR_TAG, erro_policy = False, None, ""

# 1) governed tag (tag policy): cria se não existir; se já existir com valores permitidos, usa o primeiro
try:
    tp = w.api_client.do("GET", f"/api/2.1/tag-policies/{TAG}")
    valores = [v.get("name") for v in (tp.get("values") or []) if v.get("name")]
    VALOR_TAG = valores[0] if valores else None
    print(f"↻ governed tag {TAG} já existe" + (f" (valor usado: {VALOR_TAG})" if VALOR_TAG else ""))
except Exception:
    try:
        w.api_client.do("POST", "/api/2.1/tag-policies", body={
            "tag_key": TAG, "description": "Dados pessoais (LGPD) protegidos por ABAC no lab BrickStore: a policy "
                                            "mascara_dados_sensiveis mascara as colunas com esta tag."})
        estado_gravar("abac_tag_criada", TAG)
        print(f"＋ governed tag {TAG}")
    except Exception as e:
        print(f"⚠️ não consegui criar a governed tag {TAG} (sem ABAC neste workspace ou sem permissão CREATE): {str(e)[:200]}")
        TAG = None

# 2) função de máscara: tudo vira * menos a PENÚLTIMA letra ("Gustavo Dias" → "**********a*")
if TAG:
    try:
        spark.sql(f"""CREATE OR REPLACE FUNCTION {FUNCAO}(v STRING) RETURNS STRING
                      COMMENT 'ABAC: mascara tudo menos a penúltima letra (ex.: Gustavo Dias → **********a*)'
                      RETURN CASE WHEN v IS NULL THEN NULL
                                  WHEN char_length(v) < 2 THEN repeat('*', char_length(v))
                                  ELSE concat(repeat('*', char_length(v) - 2), substr(v, char_length(v) - 1, 1), '*') END""")
        print(f"＋ função {FUNCAO}")
    except Exception as e:
        try:      # reinstalação: a função em uso pela policy pode não aceitar REPLACE; a que já existe serve
            spark.sql(f"DESCRIBE FUNCTION {FUNCAO}")
            print(f"↻ função {FUNCAO} já existe (em uso pela policy)")
        except Exception:
            print(f"⚠️ função de máscara: {str(e)[:200]}")
            TAG = None

# 3) policy ABAC no schema: qualquer coluna com a tag é mascarada para todos
if TAG:
    for principal in ("`account users`", "'All Users'"):
        try:
            spark.sql(f"""CREATE OR REPLACE POLICY {POLICY} ON SCHEMA {CATALOG}.{SCHEMA}
                          COMMENT 'Mascara (tudo menos a penúltima letra) as colunas com a governed tag {TAG}'
                          COLUMN MASK {FUNCAO}
                          TO {principal}
                          FOR TABLES
                          MATCH COLUMNS has_tag('{TAG}') AS c
                          ON COLUMN c""")
            ABAC_OK = True
            print(f"＋ policy ABAC {POLICY} em {CATALOG}.{SCHEMA} (TO {principal})")
            break
        except Exception as e:
            erro_policy = str(e)[:240]
    if not ABAC_OK:
        print(f"⚠️ não consegui criar a policy ABAC (o workspace precisa de ABAC e de serverless/DBR 16.4+): {erro_policy}")

# 4) começa PROTEGIDO: põe a tag nas colunas (no App, "Liberar" tira a tag)
if ABAC_OK:
    tag_sql = f"'{TAG}' = '{VALOR_TAG}'" if VALOR_TAG else f"'{TAG}'"
    for tabela, coluna in COLUNAS:
        try:
            spark.sql(f"ALTER TABLE {fq(tabela)} ALTER COLUMN {coluna} SET TAGS ({tag_sql})")
            print(f"   🔒 {fq(tabela)}.{coluna}")
        except Exception as e:
            print(f"   ⚠️ {tabela}.{coluna}: {str(e)[:160]}")
    # 5) job que põe/tira a tag COMO QUEM INSTALOU (o App só dispara o job; não precisa de consentimento nem de ASSIGN)
    import base64
    cmd_liberar = [f"ALTER TABLE {fq(t)} ALTER COLUMN {c} UNSET TAGS ('{TAG}')" for t, c in COLUNAS]
    cmd_revogar = [f"ALTER TABLE {fq(t)} ALTER COLUMN {c} SET TAGS ({tag_sql})" for t, c in COLUNAS]
    fonte = "\n".join([
        "# Databricks notebook source",
        "# Gerado pela etapa setup/05d_dados_sensiveis: o App dispara este job para liberar/revogar os dados sensíveis (ABAC).",
        'dbutils.widgets.text("liberar", "false")',
        'liberar = dbutils.widgets.get("liberar").strip().lower() == "true"',
        f"LIBERAR = {cmd_liberar!r}",
        f"REVOGAR = {cmd_revogar!r}",
        "for c in (LIBERAR if liberar else REVOGAR):",
        "    spark.sql(c)",
        "    print(c)",
        'dbutils.notebook.exit("liberado" if liberar else "revogado")'])
    PASTA_JOB = f"/Users/{USUARIO}/.{APP_NAME}"
    NB_JOB = f"{PASTA_JOB}/acesso_dados_sensiveis"
    JOB_ID = None
    try:
        w.api_client.do("POST", "/api/2.0/workspace/mkdirs", body={"path": PASTA_JOB})
        w.api_client.do("POST", "/api/2.0/workspace/import", body={
            "path": NB_JOB, "format": "SOURCE", "language": "PYTHON", "overwrite": True,
            "content": base64.b64encode(fonte.encode()).decode()})
        cfg_job = {"name": f"{APP_NAME} · acesso a dados sensíveis (ABAC)", "max_concurrent_runs": 1,
                   "parameters": [{"name": "liberar", "default": "false"}],
                   "tasks": [{"task_key": "acesso", "notebook_task": {"notebook_path": NB_JOB, "source": "WORKSPACE"}}]}
        antigo = json.loads(estado_ler("abac") or "{}").get("job_id") if (estado_ler("abac") or "").startswith("{") else None
        if antigo:
            try:   # reinstalação: atualiza o job desta instalação (nunca um de outra pessoa)
                j = w.api_client.do("GET", "/api/2.2/jobs/get", query={"job_id": antigo})
                if j.get("creator_user_name") in (None, USUARIO):
                    w.api_client.do("POST", "/api/2.2/jobs/reset", body={"job_id": antigo, "new_settings": cfg_job})
                    JOB_ID = antigo
            except Exception:
                pass
        if not JOB_ID:
            JOB_ID = w.api_client.do("POST", "/api/2.2/jobs/create", body=cfg_job)["job_id"]
        print(f"＋ job {JOB_ID} «{cfg_job['name']}» (roda como {USUARIO}; o App só dispara)")
    except Exception as e:
        print(f"⚠️ não consegui criar o job de acesso (o App tenta com o próprio service principal): {str(e)[:200]}")
    estado_gravar("abac", json.dumps({"tag": TAG, "valor": VALOR_TAG, "policy": POLICY, "funcao": FUNCAO, "job_id": JOB_ID,
                                      "colunas": [f"{t}.{c}" for t, c in COLUNAS]}))
    try:
        amostra = spark.sql(f"SELECT nome, email FROM {fq('clientes')} LIMIT 3").toPandas()
        print("Amostra (já mascarada pela policy):"); print(amostra.to_string(index=False))
    except Exception as e:
        print("   (amostra indisponível:", str(e)[:120], ")")
else:
    estado_gravar("abac", "")
ABAC_INFO = estado_ler("abac") or ""
print("✅ etapa concluída" + ("" if ABAC_OK else " (sem ABAC: o App segue sem a parte de acesso a dados sensíveis)"))
