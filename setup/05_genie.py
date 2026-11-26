# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 05 · Genie Agent (perguntas em linguagem natural sobre os dados)
# MAGIC
# MAGIC O Genie é criado **pela API** com tudo configurado: tabelas, descrições de colunas, instruções de negócio,
# MAGIC joins e perguntas de exemplo. O agente do App usa este Genie na ferramenta `consultar_dados`.
# MAGIC
# MAGIC Além das tabelas, o Genie recebe **conectores MCP** gerenciados pelo Unity Gateway — **Gmail**,
# MAGIC **Google Calendar** e **Google Drive** — para, no **Agent mode**, transformar análise em ação:
# MAGIC *"crie um Google Doc com os 10 produtos mais vendidos"*, *"rascunhe um e-mail para o time comercial com as
# MAGIC cestas mais fortes"*, *"agende uma reunião para revisar o estoque dos produtos com ruptura"*. Cada usuário faz
# MAGIC login no Google (OAuth) na primeira vez que o conector é usado.
# MAGIC
# MAGIC Se já existir um Genie com o mesmo título, ele é **atualizado** (idempotente).

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import json, uuid
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
WAREHOUSE_ID = escolher_warehouse(w)
print("SQL Warehouse:", WAREHOUSE_ID)

_n = [0]
def nid():
    """IDs determinísticos (32 hex) e crescentes — o Genie exige listas ordenadas por id."""
    _n[0] += 1
    return f"{_n[0]:032x}"

TABELAS = {
    "produtos": ("Catálogo de produtos (um registro por SKU)", [
        ("tipo", "Tipo do produto, por exemplo Sofá, Tênis de corrida ou Notebook. O departamento fica em departamento."),
        ("departamento", "Moda, Casa & Decoração, Cozinha, Eletrônicos, Esporte & Lazer ou Beleza."),
        ("estilo_id", "Estilo de decoração ou moda. Junte com estilos.estilo_id para ver o nome do estilo."),
        ("preco", "Preço de tabela em R$."),
        ("preco_promocional", "Preço em promoção em R$. Nulo = sem promoção."),
        ("estoque", "Unidades em estoque. Zero = ruptura."),
        ("avaliacao", "Nota média dos clientes (1 a 5)."),
        ("marca_produto", "Marca própria (fictícia) do produto."),
        ("texto_busca", None), ("popularidade", None), ("imagem_path", None), ("origem", None)]),
    "clientes": ("Clientes do programa de fidelidade", [
        ("segmento", "Bronze, Prata, Ouro ou Diamante, pelo gasto em pedidos não cancelados."),
        ("canal_preferido", "Canal de compra preferido: Site, App, Loja física ou Marketplace."),
        ("email", None)]),
    "pedidos": ("Pedidos (cada pedido é uma cesta de compra)", [
        ("status", "Entregue, Em transporte, Cancelado ou Devolvido. Receita e ticket médio ignoram Cancelado."),
        ("canal", "Site, App, Loja física ou Marketplace."),
        ("loja", "Cidade da loja física (nulo quando a compra foi online)."),
        ("forma_pagamento", "Cartão, PIX ou Boleto."),
        ("parcelas", "Número de parcelas (no cartão)."),
        ("valor_total", "Valor pago em R$, com frete."),
        ("frete", "Frete em R$. Zero em loja física ou em compras acima de R$ 199.")]),
    "itens_pedido": ("Itens de cada pedido", [
        ("quantidade", "Unidades do produto no pedido."),
        ("preco_unitario", "Preço praticado em R$, já com promoção."),
        ("desconto", "Desconto em R$ em relação ao preço de tabela.")]),
    "eventos_navegacao": ("Eventos de navegação na loja online", [
        ("evento", "visualizou, adicionou_carrinho ou favoritou."),
        ("dispositivo", "Celular, Desktop ou Tablet.")]),
    "quem_comprou_tambem_comprou": ("Regras de associação item a item (cesta = pedido)", [
        ("item_a", "Código do produto A (junte com produtos.produto_id)."),
        ("confianca", "Fração de quem levou A que também levou B (0 a 1)."),
        ("lift", "Quantas vezes acima do acaso A e B aparecem juntos; maior que 1 = associação real.")]),
    "estilos": ("Estilos de decoração e moda", []),
    "vw_vendas_produto": ("Receita, unidades e pedidos por produto (sem pedidos cancelados)", []),
    "vw_cestas_mais_fortes": ("Pares de produtos mais associados em pedidos", []),
    "previsao_vendas": ("Previsão diária de receita e itens por departamento para os próximos 30 dias (ai_forecast, intervalo de 80%)", [
        ("receita_prevista", "Receita prevista em R$ para o dia."),
        ("receita_inferior", "Limite inferior do intervalo de 80% da previsão."),
        ("receita_superior", "Limite superior do intervalo de 80% da previsão."),
        ("gerado_em", None)]),
    "vw_vendas_previsao": ("Receita diária por departamento: real (últimos 60 dias, tipo = real) + previsão (tipo = previsto)", []),
    # Lakebase (etapa 05c): histórico Delta + pedidos/solicitações feitos AGORA no App, lidos ao vivo do Postgres
    "vw_pedidos_todos": ("TODOS os pedidos: histórico (Delta) + novos do App ao vivo (Lakebase). Use para status atual e pedidos recentes", [
        ("origem", "lakehouse = histórico; lakebase = pedido novo feito no App (aparece em ~1 s)."),
        ("status", "Entregue, Em transporte, Cancelado ou Devolvido.")]),
    "vw_itens_pedido_todos": ("TODOS os itens de pedido: histórico (Delta) + novos do App ao vivo (Lakebase)", [
        ("origem", "lakehouse = histórico; lakebase = item de pedido novo feito no App.")]),
    "vw_solicitacoes_todas": ("Solicitações de pós-venda (troca, devolução, garantia, reclamação), incluindo as abertas agora no App", [
        ("origem", "lakehouse = histórico; lakebase = aberta agora pelo Agente de Pós-venda.")]),
    # SAC por voz (etapa 05a, Whisper): só existe no workspace corporativo (enterprise: true)
    "atendimentos_voz": ("Ligações do SAC transcritas com Whisper e estruturadas com ai_classify, ai_analyze_sentiment e ai_extract", [
        ("categoria", "troca, atraso, defeito, elogio, garantia ou cancelamento."),
        ("sentimento", "positive, negative, neutral ou mixed."),
        ("pedido_id", "Pedido citado na ligação (junte com pedidos.pedido_id).")]),
}
# tabelas opcionais (etapas 03d e 05a) só entram se existirem
TABELAS = {t: v for t, v in TABELAS.items() if spark.catalog.tableExists(fq(t))}

tables = []
for t, (desc, cols) in sorted(TABELAS.items(), key=lambda kv: fq(kv[0])):
    cc = []
    for col, d in sorted(cols, key=lambda c: c[0]):
        cc.append({"column_name": col, "exclude": True} if d is None else {"column_name": col, "description": [d]})
    entry = {"identifier": fq(t)}
    if cc:
        entry["column_configs"] = cc
    tables.append(entry)

INSTRUCOES = [
    f"Este Genie responde perguntas sobre a {MARCA}, uma loja de departamentos fictícia (moda, casa e decoração, cozinha, "
    "eletrônicos, esporte e lazer, beleza), com venda online e em loja física. Responda sempre em português do Brasil.",
    "Receita: SUM(itens_pedido.preco_unitario * itens_pedido.quantidade), ou a view vw_vendas_produto. Sempre exclua pedidos "
    "com status 'Cancelado'. Ticket médio = receita dividida pelo número de pedidos não cancelados.",
    "Recompra: um cliente recorrente tem 2 ou mais pedidos não cancelados. Taxa de recompra = clientes recorrentes / clientes com pelo menos 1 pedido.",
    "Segmentos de fidelidade: clientes.segmento = Bronze, Prata, Ouro ou Diamante. Ao falar de segmento, mostre o número de clientes e a receita juntos.",
    "Conversão: taxa de carrinho de um produto = eventos 'adicionou_carrinho' dividido pelos eventos 'visualizou' do mesmo produto em eventos_navegacao.",
    "Para 'quem comprou X também comprou', use quem_comprou_tambem_comprou filtrando nome_a (ou item_a) e ordenando por rank. "
    "Os nomes dos produtos estão em nome_a e nome_b.",
    "Ruptura de estoque: produtos.estoque = 0. Para pedidos de reposição, liste os produtos em ruptura ordenados pelas unidades "
    "vendidas em vw_vendas_produto.",
    "Estilos: produtos.estilo_id junta com estilos.estilo_id. O nome do estilo está em estilos.nome.",
    "Pedidos AO VIVO: para status atual, 'o que está em transporte', pedidos de hoje ou pedidos de um cliente, use "
    "vw_pedidos_todos e vw_itens_pedido_todos (incluem os pedidos feitos agora no App, gravados no Lakebase e lidos ao vivo; "
    "coluna origem). Para solicitações de troca/devolução use vw_solicitacoes_todas. Prefira estas views também para receita recente.",
    "Previsão de vendas: use previsao_vendas (receita_prevista com intervalo receita_inferior–receita_superior, por departamento e dia). "
    "Para próximas N semanas, some receita_prevista de current_date() até current_date() + 7*N. Para comparar com o realizado use "
    "vw_vendas_previsao (tipo = real ou previsto). Sempre mostre o intervalo junto da previsão.",
    "Conectores (Agent mode): para criar documentos, planilhas ou apresentações use o Google Drive; para e-mails use o Gmail "
    "(o conector cria RASCUNHOS — avise o usuário que ele precisa revisar e enviar); para agendar reuniões ou lembretes use o "
    "Google Calendar (fuso America/Sao_Paulo; duração padrão de 1 hora, salvo indicação do usuário). "
    "Sempre consulte as tabelas primeiro e use os dados reais no documento, e-mail ou evento.",
]
# Conectores MCP gerenciados pelo Unity Gateway (system.ai.*) — usados no Agent mode do Genie
MCP_CONECTORES = ["system.ai.gmail", "system.ai.google_calendar", "system.ai.google_drive"]

def join(left, right, cond, rt):
    return {"id": nid(), "left": {"identifier": fq(left), "alias": left}, "right": {"identifier": fq(right), "alias": right},
            "sql": [cond, f"--rt=FROM_RELATIONSHIP_TYPE_{rt}--"]}

joins = [
    join("vw_itens_pedido_todos", "vw_pedidos_todos", "`vw_itens_pedido_todos`.`pedido_id` = `vw_pedidos_todos`.`pedido_id`", "MANY_TO_ONE"),
    join("vw_itens_pedido_todos", "produtos", "`vw_itens_pedido_todos`.`produto_id` = `produtos`.`produto_id`", "MANY_TO_ONE"),
    join("itens_pedido", "pedidos", "`itens_pedido`.`pedido_id` = `pedidos`.`pedido_id`", "MANY_TO_ONE"),
    join("itens_pedido", "produtos", "`itens_pedido`.`produto_id` = `produtos`.`produto_id`", "MANY_TO_ONE"),
    join("pedidos", "clientes", "`pedidos`.`cliente_id` = `clientes`.`cliente_id`", "MANY_TO_ONE"),
    join("eventos_navegacao", "clientes", "`eventos_navegacao`.`cliente_id` = `clientes`.`cliente_id`", "MANY_TO_ONE"),
    join("eventos_navegacao", "produtos", "`eventos_navegacao`.`produto_id` = `produtos`.`produto_id`", "MANY_TO_ONE"),
    join("produtos", "estilos", "`produtos`.`estilo_id` = `estilos`.`estilo_id`", "MANY_TO_ONE"),
    join("quem_comprou_tambem_comprou", "produtos", "`quem_comprou_tambem_comprou`.`item_a` = `produtos`.`produto_id`", "MANY_TO_ONE"),
]
joins = [j for j in joins if j["left"]["alias"] in TABELAS and j["right"]["alias"] in TABELAS]   # views opcionais (05c)

exemplos = [
    {"id": nid(), "question": ["Quais os 10 produtos com maior receita?"],
     "sql": [f"SELECT nome, departamento, unidades, receita FROM {fq('vw_vendas_produto')} ORDER BY receita DESC LIMIT 10"]},
    {"id": nid(), "question": ["Qual a receita por departamento?"],
     "sql": [f"SELECT p.departamento, ROUND(SUM(i.preco_unitario * i.quantidade), 2) AS receita, COUNT(DISTINCT i.pedido_id) AS pedidos "
             f"FROM {fq('itens_pedido')} i JOIN {fq('pedidos')} pe ON pe.pedido_id = i.pedido_id AND pe.status <> 'Cancelado' "
             f"JOIN {fq('produtos')} p ON p.produto_id = i.produto_id GROUP BY p.departamento ORDER BY receita DESC"]},
    {"id": nid(), "question": ["Qual a previsão de receita de Eletrônicos para as próximas 4 semanas?"],
     "sql": [f"SELECT ROUND(SUM(receita_prevista), 2) AS receita_prevista, ROUND(SUM(receita_inferior), 2) AS minimo_80pct, "
             f"ROUND(SUM(receita_superior), 2) AS maximo_80pct FROM {fq('previsao_vendas')} "
             f"WHERE departamento = 'Eletrônicos' AND data < date_add(current_date(), 28)"]},
    {"id": nid(), "question": ["O que as pessoas compram junto com um sofá?"],
     "sql": [f"SELECT nome_a, nome_b, tipo_b, n_juntos, confianca, lift FROM {fq('quem_comprou_tambem_comprou')} "
             f"WHERE nome_a LIKE 'Sofá%' ORDER BY rank LIMIT 10"]},
]
exemplos = [e for e in exemplos if all(t in TABELAS for t in ("previsao_vendas",) if fq(t) in e["sql"][0])]

perguntas = ["Quais os 10 produtos com maior receita?", "Qual a receita por departamento?",
             "Qual o ticket médio por segmento de fidelidade?", "Quais produtos estão com ruptura de estoque?",
             "Quais são as cestas de compra mais fortes?", "O que as pessoas compram junto com uma cafeteira?",
             "Qual a taxa de carrinho por estilo?", "Quantos produtos existem por departamento?",
             "Qual a previsão de receita de Eletrônicos para as próximas 4 semanas?",
             "Crie um Google Doc com os 10 produtos mais vendidos",
             "Rascunhe um e-mail para o time comercial com as 5 cestas mais fortes",
             "Agende uma reunião amanhã às 10h para revisar o estoque dos produtos com ruptura"]

espaco = {
    "version": 2,
    "config": {"sample_questions": [{"id": nid(), "question": [q]} for q in perguntas]},
    "data_sources": {"tables": tables,
                     "mcp_connections": [{"connection_name": c} for c in sorted(MCP_CONECTORES)]},
    "instructions": {
        "text_instructions": [{"id": nid(), "content": [l + "\n" for l in INSTRUCOES]}],
        "example_question_sqls": exemplos,
        "join_specs": joins,
    },
}
SERIALIZED = json.dumps(espaco, ensure_ascii=False)
espaco_sem_mcp = json.loads(SERIALIZED)
espaco_sem_mcp["data_sources"].pop("mcp_connections")
SERIALIZED_SEM_MCP = json.dumps(espaco_sem_mcp, ensure_ascii=False)

# COMMAND ----------

# O Genie desta instalação é achado pelo id gravado em _lab_estado (não pelo título: num workspace compartilhado
# outra pessoa pode ter um Genie com o mesmo nome). Se o id sumiu (apagado), cria outro.
existente = estado_ler("genie_space_id")
if existente:
    try:
        w.api_client.do("GET", f"/api/2.0/genie/spaces/{existente}")
    except Exception:
        existente = None

def salvar(serializado):
    corpo = {"title": GENIE_TITLE, "warehouse_id": WAREHOUSE_ID, "serialized_space": serializado,
             "description": f"Dados da {MARCA} (produtos, clientes, pedidos, cestas e navegação) "
                            "+ conectores Gmail, Google Calendar e Google Drive no Agent mode."}
    if existente:
        w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{existente}", body=corpo)
        return existente, "↻ Genie atualizado"
    return w.api_client.do("POST", "/api/2.0/genie/spaces", body=corpo)["space_id"], "＋ Genie criado"


try:
    GENIE_SPACE_ID, msg = salvar(SERIALIZED)
    print(msg, GENIE_SPACE_ID, "com conectores", MCP_CONECTORES)
except Exception as e:
    print("⚠️ conectores MCP indisponíveis neste workspace (", str(e)[:150], ") — criando o Genie só com as tabelas")
    try:
        GENIE_SPACE_ID, msg = salvar(SERIALIZED_SEM_MCP)
        print(msg, GENIE_SPACE_ID)
    except Exception as e2:   # tolerante: sem Genie, o Agente Analista do App avisa que não há dados disponíveis
        GENIE_SPACE_ID = ""
        print("⚠️ Genie não criado (a instalação segue):", str(e2)[:250])
if GENIE_SPACE_ID:
    estado_gravar("genie_space_id", GENIE_SPACE_ID)

HOST = w.config.host.rstrip("/")
displayHTML(f"""<a href="{HOST}/genie/rooms/{GENIE_SPACE_ID}" target="_blank" style="font-size:15px;font-weight:700">🧞 Abrir o Genie "{GENIE_TITLE}"</a>
<p>Para usar Gmail / Calendar / Drive: ative o <b>Agent mode</b> na conversa e faça login no Google quando o conector pedir.</p>""")

# COMMAND ----------

# Teste rápido
try:
    msg = w.genie.start_conversation_and_wait(GENIE_SPACE_ID, "Quantos produtos existem por departamento?")
    for a in msg.attachments or []:
        if a.query:
            print("SQL gerado:", a.query.query[:200])
        if a.text:
            print("Resposta:", a.text.content[:200])
except Exception as e:
    print("⚠️ teste do Genie falhou (o Space foi criado mesmo assim):", str(e)[:200])
print("✅ etapa 5 concluída")
