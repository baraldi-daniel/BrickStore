# 🎤 Roteiro de demonstração (~20 min)

> Pré-requisito: `INSTALAR` executado. Abra o App em uma aba e o workspace em outra.

| Min | Onde | O que mostrar | Mensagem |
|----:|------|---------------|----------|
| 0–2 | Notebook `INSTALAR` | As 7 etapas e os widgets (inclusive `marca`) | "Um notebook, tudo serverless." |
| 2–4 | App → *Quem está comprando?* → um cliente | Vitrine personalizada: *Porque você comprou «X»*, *Seu estilo* | Recomendação explicável, em SQL puro, sem modelo de ML |
| 3–4 | Fileira **Recomendado para você** → **Estúdio → Painel** (placar do modelo) | Regras geram candidatos, o **Gradient Boosting** ordena por cliente; placar: popularidade ~11% → regras ~13% → SVD ~19% → **híbrido ~23%** | Regras explicáveis + ML onde ele ganha; modelo no MLflow/UC |
| 4b | **Serving → `brickstore-recomendador`** (e *Query endpoint* com `{"dataframe_records": [{"cliente_id": "C000123"}]}`) | O mesmo modelo, agora **servido em tempo real**: pyfunc no UC, CPU Small com scale to zero; o Painel mostra se a última recomendação veio do endpoint ou da tabela | Do notebook à API em produção, governado pelo Unity Catalog |
| 4–7 | Página de um **sofá** | **Compre junto** (sofá + almofada + tapete com desconto) e **Quem comprou também comprou** com confiança e lift → adicionar ao carrinho → **finalizar** | O pedido vira INSERT em `pedidos` / `itens_pedido` e as sugestões saem das cestas |
| 7–11 | **🔎 Detetive de Produtos** (busca visual) | Foto de um produto (tire na hora: o tênis, a garrafa ou o fone de alguém do público) → laudo (tipo, cor, material, estilo) → produtos parecidos com % de compatibilidade. | Visão (Llama 4 Maverick) + Vector Search sobre a **descrição visual**. Tudo exposto como **MCP**. |
| 11–14 | **🎛️ Estúdio → Novo produto (PDF)** | Ficha de exemplo *Sofá retrátil Nórdica* → elementos extraídos, **foto recortada**, **tabelas** → cadastro preenchido → **Publicar** | `ai_parse_document` com imagens e tabelas; o produto aparece em **Novidades do Estúdio** |
| 14–16 | **💬 Assistente** (multiagente) | 1) *"o que está em transporte?"* → 📦 Pós-venda. 2) *"quero devolver o último item"* → protocolo SAC. 3) *"ticket médio por segmento?"* → 📊 Analista (Genie via MCP). 4) Anexar a foto de um produto → 🛍️ Vendas + busca visual do Detetive. 5) *"ignore suas instruções…"* → 🛡️ bloqueado. 6) *"pedidos do cliente C000999"* → 🛡️ bloqueado (outra conta) | Grafo LangGraph: guardrails como nós, supervisor e especialistas; a trilha 🕸️ mostra os nós percorridos; o selo 🔀 mostra o modelo escolhido pelo roteador |
| 16d | **📞 SAC por voz** (workspace corporativo, `enterprise: true`) | Estúdio → aba *SAC por voz*: **gravar no microfone** *"o pedido P 0 0 1 1 6 5 5 está atrasado"* → transcrição do **Whisper** + categoria (`ai_classify`), sentimento e pedido extraído (`ai_extract`); ouvir as ligações prontas e rodar *Transcrever agora*; perguntar ao Genie *"quantas ligações de atraso com sentimento negativo?"* | Modelo aberto (Whisper) servido no Model Serving + funções de IA em SQL; o atendimento vira dado no Lakehouse |
| 16a | Notebook **`setup/03d_previsao_vendas`** (ou o App, previsão sob demanda) | `ai_forecast` em uma linha de SQL: receita por departamento nos próximos 30 dias, com intervalo de 80%; escolher *Eletrônicos · por semana* | Previsão sem treinar nem servir modelo; SQL governado |
| 16c | **🧠 Memória do chat (Lakebase)** | Com um perfil: *"quero um sofá cinza para sala pequena até R$ 2 mil"* → **recarregar a página** (a conversa volta, aviso 🧠) → **Nova conversa** → *"o que eu te perguntei da última vez?"* → o assistente lembra; na trilha 🕸️ o nó 🧠 *lembrou N mensagens · Lakebase*. No SQL: `SELECT * FROM brickstore_loja.loja.conversas ORDER BY criado_em DESC` | Memória de agente em Postgres OLTP (~0,1 s), já mascarada pelos guardrails, e visível ao vivo no Lakehouse |
| 16b | **Compra no App → Genie** | Comprar um item → perguntar ao Genie *"quais pedidos do cliente <id> estão em transporte agora?"* → o pedido aparece com `origem = lakebase`; em *Catalog → brickstore_loja* ver as tabelas do Postgres | Lakebase (OLTP) + Lakehouse ao vivo pelo Unity Catalog, sem ETL |
| 16 | **Unity Gateway → Models → assistente_llm** | Roteamento 50/50, fallback e inference table `assistente_llm_payload`; os guardrails ficam no grafo LangGraph do App (tabela `guardrail_eventos`) | Governança de IA centralizada, sem mudar código |
| 16–17 | **AI Playground** | **GPT OSS 120B** + MCP **`mcp-detetive-produtos`** (*Tools → + Add tool → MCP servers → Databricks Apps*): *"tem na BrickStore algo parecido com o produto da foto /Volumes/brickstore/varejo/midia/imagens_busca/<foto>.jpg?"* (use uma foto enviada pela página Detetive); depois + `system.ai.google_calendar`: *"ache uma luminária para sala escandinava até R$ 400 e agende a entrega sábado 10h"* | Os MCPs se compõem; o Unity Gateway governa o acesso |
| 17 | **Genie One + Gmail** (conecte `system.ai.gmail` antes) | *"Usando as tabelas de brickstore.varejo, calcule a receita por departamento dos últimos 30 dias e mande para mim um e-mail com esse resumo"* → e-mail chega na caixa | Do dado à ação com conectores MCP |
| 17–18 | **Genie** (Agent mode) | *"Crie um Google Doc com os 10 produtos mais vendidos"* → link do Doc; *"agende reunião amanhã 10h para revisar ruptura de estoque"* → evento no Calendar | Do dado à ação: SQL governado + conectores Gmail, Calendar e Drive |
| 18–19 | Dashboard **AI Gateway Usage Analytics** | Chamadas feitas durante a demo (LLM, embeddings, MCP) | Observabilidade e custo do que o App acabou de fazer |
| 19–20 | Catalog Explorer | Linhagem `itens_pedido → quem_comprou_tambem_comprou`; Volume `midia` com fotos e fichas | Tudo governado pelo Unity Catalog |

## Perguntas boas para o Genie
- "Qual o ticket médio por segmento de fidelidade?"
- "Qual a receita por departamento nos últimos 30 dias?"
- "Quais são as cestas de compra mais fortes?"
- "Quais produtos estão com estoque abaixo de 10 unidades?"
- "Quantos produtos foram cadastrados pelo Estúdio?" (rode depois de publicar uma ficha)
- "Qual a previsão de receita de Eletrônicos para as próximas 4 semanas?" (`ai_forecast`)

## Dicas
- Se o workspace parar Apps ociosos (ex.: após 24h), antes da demo abra *Compute → Apps → brickstore → Start*.
- A cota de requisições do LLM é baixa. Durante a demo, evite outras cargas no mesmo modelo; o App tenta de novo sozinho quando recebe HTTP 429.
- Depois de publicar um produto pelo Estúdio, a busca semântica e o Detetive só o encontram quando o
  `produtos_index` terminar de sincronizar (1 a 3 min). A vitrine mostra o produto na hora.
