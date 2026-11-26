# Arquitetura — BrickStore

## Visão geral

```
                         ┌────────────────────────── Databricks App "brickstore" ──────────────────────────┐
  Navegador ───────────► │  FastAPI (main.py)                                                                   │
  (HTML/CSS/JS puro)     │   ├─ /            frontend estilo streaming (static/)                                │
                         │   ├─ /api/*       vitrine · produto · busca · pedido · detetive · chat · estúdio      │
  Clientes MCP ────────► │   └─ /mcp         servidor MCP "brickstore-detetive-de-produtos"       │
  (Playground, Claude…)  │                                                                                      │
                         │  backend/                                                                            │
                         │   catalogo.py ── cache em memória (produtos, estilos, regras, mais vendidos)                │
                         │   mcp_detetive.py ── ferramentas MCP ◄── agente.py (cliente MCP em memória)          │
                         │   estudio.py ── ficha técnica PDF → produto · CRUD · PDFs de ajuda · sync                 │
                         └───────┬──────────────┬───────────────┬──────────────┬───────────────┬───────────────┘
                                 │ SQL          │ query/sync    │ chat/visão   │ files         │ conversation
                                 ▼              ▼               ▼              ▼               ▼
                          SQL Warehouse   Vector Search    Model Serving    Volumes UC        Genie
                          (2X-Small)      produtos_index   Llama 4 Maverick  midia/           Agent
                                │         ajuda_index      Qwen3 embedding   documentos/
                                ▼
                     Delta / Unity Catalog: produtos · pedidos · itens_pedido · clientes · eventos_navegacao · quem_comprou_tambem_comprou
                                            central_ajuda_chunks · documentos_parseados · fichas_parseadas
```

## Fluxos principais

### 1. "Quem comprou também comprou" e "Compre junto"
1. `itens_pedido` tem uma linha por item de cada pedido. Os gostos latentes por **estilo** e os **complementos** por tipo
   (sofá → almofada/tapete/mesa de centro; notebook → mouse/mochila; console → headset...) criam associações reais.
2. `backend/recomendacao_sql.py` gera o SQL de *market basket* com **cesta = pedido**:
   - pares via *self-join* em `itens_pedido`;
   - suporte = pedidos com A e B / total de pedidos;
   - confiança = pedidos com A e B / pedidos com A;
   - lift = confiança / (pedidos com B / total).
3. Guardamos o **top 20 por produto**. O App carrega tudo em memória e monta *"Porque você comprou «X»"*, o bloco do
   produto e o kit **Compre junto**: o produto + complementos de tipos diferentes, com desconto no conjunto.
4. Pedidos feitos no App entram em `pedidos`/`itens_pedido`. **Estúdio → Painel → Recalcular** roda o mesmo SQL de novo.

### 2. Central de ajuda (RAG) com `ai_parse_document`
1. Os PDFs de `documentos/` vão para o Volume `documentos`.
2. `ai_parse_document(content, map('version','2.0'))` devolve um VARIANT com `document.elements[]`
   (`title`, `section_header`, `text`, `table` em HTML, `figure`, `caption`...), com página e bounding box.
3. `backend/documentos.py` agrupa por seção e converte tabelas HTML em texto `coluna: valor`.
4. `central_ajuda_chunks`, com Change Data Feed ligado, alimenta o `ajuda_index`. A ferramenta `suporte` do agente consulta esse índice.

### 3. Estúdio: produto a partir da ficha técnica do fornecedor (PDF com foto e tabelas)
1. Upload do PDF para `midia/fichas/<chave>/`.
2. `ai_parse_document` com `imageOutputPath` (grava a imagem de cada página no Volume) e
   `descriptionElementTypes='*'` (descreve cada figura).
3. Cada `figure` é recortada da página pela bounding box. A primeira é a foto principal do produto.
4. Texto, tabelas (especificações, medidas/grade, preços) e descrições das figuras vão para o LLM, que devolve o
   cadastro em JSON: nome, marca, departamento, tipo, estilo, cor, material, especificações, preço, parcelas...
5. O usuário revisa e publica: `INSERT` em `produtos` (`origem='estudio'`), foto em `midia/produtos/`, linhagem em
   `fichas_parseadas` e sync do `produtos_index`.

### 3b. Recomendação servida (Model Serving)
- `setup/03b_modelo_ml` treina o ranking (Gradient Boosting) e grava o top 12 de cada cliente em `recomendacoes_personalizadas`.
- `setup/03c_servir_modelo` empacota isso num **pyfunc MLflow** `recomendador` (UC), com o GBM `modelo_recomendacao` embutido e cold start
  por popularidade, e publica no endpoint **`<app>-recomendador`** (CPU Small, scale to zero).
- `catalogo.recomendados_ml()` chama `/serving-endpoints/<app>-recomendador/invocations` (timeout de 6 s) e cai para a tabela se o
  endpoint estiver frio ou fora do ar; cada item carrega `origem_ml` (`endpoint` ou `tabela`), exibida no Estúdio → Painel.
- O App recebe o endpoint como *resource* `recomendador` (CAN_QUERY) e a variável `NB_RECOMENDADOR`.

### 3c. Previsão de vendas com `ai_forecast`
- `setup/03d_previsao_vendas`: série diária de receita e itens por departamento (180 dias, sem cancelados) → `ai_forecast`
  (horizonte de 30 dias, intervalo de 80%, `global_floor = 0`) → `previsao_vendas` + `vw_vendas_previsao` (real + previsto).
- O `ai_forecast` roda no **SQL warehouse** (no serverless de notebooks ele pode estar desabilitado). A etapa executa a
  previsão no warehouse via Statement Execution; cada chamada aceita uma métrica, então receita e itens são duas chamadas unidas por `JOIN`.
- `app/backend/previsao.py`:
  - `previsao_vendas(departamento)` lê a view (séries + resumo de 4 semanas);
  - `prever(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte)` roda o `ai_forecast` **na hora**, com filtro
    total, departamento, tipo ou produto; receita ou quantidade; dia ou semana (`frequency => 'day' | 'week'`; semanas incompletas
    são descartadas). Colunas e métricas ficam numa whitelist, e o valor do filtro vai como parâmetro nomeado;
  - `opcoes()` devolve departamentos, tipos e produtos para os seletores, em ordem alfabética: os 300 de maior receita
    + tudo o que foi comprado no App (o cache é zerado a cada compra).

### 3d. Lakebase (OLTP) + Lakehouse ao vivo
- `setup/05c_lakebase`: projeto Lakebase **novo a cada instalação** (`<app_name>`, ou `<app_name>-2`… se o nome estiver preso; Postgres 17, 1 CU, scale to zero), schema `loja` com `pedidos`,
  `itens_pedido`, `solicitacoes_atendimento` e `conversas` (memória do chat) (`REPLICA IDENTITY FULL`).
- **Memória do Assistente:** `app/backend/memoria.py` + nós `memoria_carregar` / `memoria_gravar` do grafo. Cada turno
  (pergunta já mascarada + resposta) vai para `loja.conversas`; a cada pergunta o agente recebe as conversas anteriores do
  cliente; `GET/DELETE /api/chat/memoria` reabre a última conversa e apaga a memória.
- **Escrita:** `/api/pedido` e a ferramenta `abrir_solicitacao` gravam no Postgres (`app/backend/lakebase.py`: psycopg,
  token OAuth da SP via `w.postgres.generate_database_credential`, 1 reconexão). Reserva: `INSERT` no Delta.
- **Leitura ao vivo:** o database está registrado no UC como `<catalog>_loja`; as views `vw_pedidos_todos`,
  `vw_itens_pedido_todos` e `vw_solicitacoes_todas` unem Delta + Postgres. *Meus pedidos*, `pedidos_do_cliente`, a agenda
  e o Genie leem essas views (pedido visível em ~1 s).
- **Delta → Postgres:** synced tables `lb_produtos` e `lb_recomendacoes` (snapshot).
- Lakehouse Sync (CDF) exige catálogo com armazenamento externo; com Default Storage o lab usa a leitura ao vivo pelo catálogo registrado.
- App: recurso `postgres` (`CAN_CONNECT_AND_CREATE`) + env `NB_LAKEBASE`, `NB_LAKEBASE_CATALOG`, `NB_LAKEBASE_ENDPOINT`;
  a SP recebe `USAGE`/`SELECT, INSERT, UPDATE` no schema `loja` e `USE CATALOG`/`SELECT` no catálogo registrado.

### 4. Detetive de Produtos
Veja [MCP_DETETIVE.md](MCP_DETETIVE.md).

### 5. Assistente: grafo LangGraph com guardrails, supervisor e agentes
A orquestração é um `StateGraph` do **LangGraph** (`backend/grafo.py`). Cada guardrail é um nó; um bloqueio desvia para o nó
`bloqueio` e o LLM principal nem é chamado:

```
guardrail_pii_entrada → guardrail_jailbreak ─┬─► bloqueio → END
                                             └─► guardrail_juiz (supervisor) ─┬─► bloqueio
                                                                              └─► vendas | pos_venda | analista
agente ─(tool calls)─► guardrail_ferramentas → ferramentas ─► volta ao mesmo agente   (até 6 rodadas)
agente ─(resposta)──► guardrail_saida → END
```

- **Nós de guardrail** (funções em `backend/guardrail.py`):
  - `guardrail_pii_entrada`: regex mascara CPF, cartão e telefone em todo o histórico;
  - `guardrail_jailbreak`: regras determinísticas (mudar/revelar instruções, dados de outro cliente);
  - `guardrail_juiz`: LLM-juiz Llama 3.3 70B (cota separada) classifica ok/jailbreak/ofensivo/fora do escopo e escolhe o **agente**;
  - `guardrail_ferramentas`: allowlist de ferramentas por agente e `cliente_id` forçado para o cliente logado;
  - `guardrail_saida`: mascara dados sensíveis, impede vazamento do prompt e sinaliza valores sem fundamentação.
- **Agentes** (prompts e ferramentas em `backend/agente.py`):
  - 🛍️ **Vendas**: Detetive, busca, regras, compre junto, recomendação ML;
  - 📦 **Pós-venda**: `pedidos_do_cliente`, `abrir_solicitacao` (grava em `solicitacoes_atendimento`) e a central de ajuda;
  - 📊 **Analista**: Genie pelo **MCP gerenciado do Genie**, com a Conversation API como reserva.
- O nó `ferramentas` usa um `mcp.client.Client` em memória ligado ao mesmo `MCPServer` exposto em `/mcp` (descoberta por `tools/list`).
- Os agentes chamam o LLM pelo **roteador do Unity Gateway** (`assistente_llm`: routing 50/50 + fallback + inference table), com o LLM direto como reserva.
- Todo evento de guardrail vai para `guardrail_eventos`.
- O chat mostra o agente, as ferramentas, o modelo escolhido pelo roteador, os selos 🛡️ e a trilha 🕸️ dos nós percorridos.
- `GET /api/assistente/grafo` devolve o diagrama Mermaid gerado pelo LangGraph.

## Autenticação e permissões

O App usa a **service principal** dele, com credenciais injetadas pelo Databricks Apps. O `setup/06_app` cuida de:

| Recurso | Como a SP ganha acesso |
|---------|------------------------|
| SQL Warehouse | *resource* `sql-warehouse` (CAN_USE) |
| LLM e embedding | *resources* `serving_endpoint` (CAN_QUERY) |
| Genie | *resource* `genie_space` (CAN_RUN) |
| Roteador de LLM | *resource* `uc_securable` MODEL_SERVICE (EXECUTE) em `assistente_llm` |
| Juiz do guardrail | *resource* `serving_endpoint` (CAN_QUERY) em `databricks-meta-llama-3-3-70b-instruct` |
| Volumes `midia` e `documentos` | *resources* `uc_securable` (WRITE_VOLUME) + GRANT READ/WRITE VOLUME |
| Tabelas do schema | `GRANT USE CATALOG`, `USE SCHEMA, SELECT, MODIFY ON SCHEMA` |
| Endpoint de Vector Search | permissão `CAN_MANAGE`, para consultar e sincronizar os índices |

Clientes externos do `/mcp` passam pelo OAuth do Databricks Apps: só usuários do workspace com acesso ao App conseguem chamar.

## Decisões de design

- **Sem endpoint de agente em Model Serving.** O número de endpoints pode ser limitado, e o
  `agents.deploy` cria um endpoint e uma SP a mais. Com o agente embutido no App, o lab cabe na cota.
- **Frontend sem build.** HTML/CSS/JS puro: quem clona o repositório não precisa de Node nem de npm.
- **Arte de produto procedural em SVG.** Cada tipo de produto tem um desenho, colorido pela cor do produto e pelo
  estilo, gerado de forma determinística. Não há download externo, o que importa porque o workspace pode restringir a
  saída de internet. Produtos do Estúdio usam a foto recortada da ficha.
- **Fonte única para código compartilhado.** O chunking (`documentos.py`) e o SQL de recomendação
  (`recomendacao_sql.py`) são importados tanto pelos notebooks de setup quanto pelo App.
- **Cache em memória.** Os produtos e as regras cabem com folga na memória do App. Assim o warehouse
  2X-Small só atende o que é por perfil (compras, histórico) e as escritas.
