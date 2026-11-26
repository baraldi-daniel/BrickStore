# 🔎 MCP "Detetive de Produtos"

Servidor **MCP (Model Context Protocol)** de **busca visual**: a partir da foto de um produto (um tênis, uma
poltrona, um headset...), ele identifica o que é (tipo, cor, material, estilo) e encontra os produtos parecidos da loja.

- **Nome:** `brickstore-detetive-de-produtos`
- **Endpoint:** `https://<url-do-app>/mcp` (transporte *Streamable HTTP*, modo *stateless*, respostas JSON)
- **Onde está publicado:**
  - no **App próprio `mcp-detetive-produtos`** (etapa `setup/06b_app_mcp`, entrada [`app/mcp_main.py`](../app/mcp_main.py)). O prefixo `mcp-` faz o servidor aparecer no **AI Playground**; a raiz do App mostra uma página com as ferramentas;
  - dentro do App da loja, em `/mcp`, usado pelo Assistente.
- **Código:** [`app/backend/mcp_detetive.py`](../app/backend/mcp_detetive.py), com o SDK oficial `mcp` 2.x (`MCPServer`)

## Como a busca visual funciona

```
foto do produto (Volume / data URI / base64)
   │  normalização (JPEG ≤ 1024 px)
   ▼
Llama 4 Maverick (visão) ── identifica o produto em destaque
   │
   ▼
LAUDO (JSON): tipo · descricao · cor · cores_hex[] · material · estilo_provavel · atributos[]
              produto_reconhecido · veredito · consulta_busca
   │  "descrição + tipo + cor + material + estilo"
   ▼
Vector Search (produtos_index, filtro por tipo) → reranking (+ mesmo estilo, + cor parecida)
   │
   ▼
produtos[{..., compatibilidade, pistas[]}]   (os parecidos do catálogo)
```

Toda imagem enviada pelo App fica arquivada em `/Volumes/<catalog>/<schema>/midia/imagens_busca/` (governança do Unity Catalog).

## Ferramentas

| Ferramenta | Parâmetros | Retorno |
|------------|------------|---------|
| `investigar_imagem` | `imagem: str`, `quantidade: int = 6` | `{laudo, produtos[]}` (busca visual) |
| `analisar_imagem` | `imagem: str` | laudo do produto da foto (sem buscar no catálogo) |
| `buscar_produtos` | `consulta: str`, `departamento: str \| None`, `preco_max: float \| None`, `quantidade: int = 8` | `{consulta, produtos[]}` |
| `quem_comprou_tambem_comprou` | `produto: str` (nome ou produto_id), `quantidade: int = 8` | `{produto_base, produtos[{..., confianca, lift, leitura}]}` |
| `compre_junto` | `produto: str` | `{produto_base, itens[], total, total_com_desconto, desconto_pct}` |
| `ficha_produto` | `produto: str` | ficha completa + top 5 comprados junto |

## Usando o MCP

### 1. Dentro do App (já pronto)
O assistente cria um `mcp.client.Client(mcp)` **em memória** a cada conversa, chama `tools/list` e
converte os *input schemas* para o formato de *tool calling* do LLM. As chamadas usam `tools/call`, ou seja,
o protocolo MCP de verdade, sem rede.

### 2. AI Playground
**Playground** → modelo com tools (ex.: GPT OSS 120B ou Llama 4 Maverick) → **Tools → + Add tool → MCP servers →
Databricks Apps → `mcp-detetive-produtos`**. Prompts de exemplo: *"tem na BrickStore algo parecido com o produto da
foto /Volumes/brickstore/varejo/midia/imagens_busca/<sua_foto>.jpg?"* e *"Busque uma luminária de piso até R$ 400 e diga
o que costuma ser comprado junto."* Combine com os MCPs gerenciados do
Unity Gateway, por exemplo `system.ai.google_calendar` (*"ache uma luminária para minha sala escandinava e
agende a entrega para sábado"*) ou `system.ai.gmail` (*"rascunhe um e-mail com o kit compre junto do sofá"*).

### 3. Clientes externos (Claude Code, Cursor, scripts)
O App exige um token OAuth do Databricks (U2M):

```python
import asyncio
from databricks.sdk import WorkspaceClient
from mcp.client.client import Client
from mcp.client.streamable_http import streamablehttp_client

w = WorkspaceClient(profile="<seu-perfil>")           # databricks auth login
token = w.config.authenticate()["Authorization"]
URL = "https://<url-do-app>/mcp"

async def main():
    async with streamablehttp_client(URL, headers={"Authorization": token}) as (r, w_, _):
        async with Client((r, w_)) as c:
            print([t.name for t in (await c.list_tools()).tools])
            res = await c.call_tool("buscar_produtos", {"consulta": "luminária de piso para sala escandinava"})
            print(res.content[0].text[:500])

asyncio.run(main())
```

Teste rápido com `curl`:

```bash
TOKEN=$(databricks auth token --profile <seu-perfil> | jq -r .access_token)
curl -s -X POST "https://<url-do-app>/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
```

## Estendendo

```python
@mcp.tool(title="Lista de presentes", description="Monta uma lista de presentes até um valor, no estilo da imagem")
def lista_de_presentes(imagem: str, valor_max: float) -> dict:
    ...
```

O agente do App e os clientes externos passam a ver a ferramenta automaticamente, via `tools/list`.
