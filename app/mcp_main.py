"""
App PRÓPRIO do MCP "Detetive de Produtos" (Databricks App `mcp-detetive-produtos`).

Mesmo servidor MCP que o App da loja monta em /mcp (backend/mcp_detetive.py), publicado sozinho para aparecer
em **Playground → Tools → MCP servers → Databricks Apps** (o prefixo `mcp-` no nome do App deixa ele visível lá).

  /            → página explicando o servidor e listando as ferramentas
  /mcp         → servidor MCP (Streamable HTTP, stateless, respostas JSON)
  /api/saude   → catálogo carregado?
"""
import contextlib
import html
import logging
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from mcp.server.transport_security import TransportSecuritySettings

from backend import servicos as S
from backend.catalogo import CATALOGO
from backend.mcp_detetive import mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp", stateless_http=True, json_response=True,
    # O proxy do Databricks Apps já autentica e reescreve o Host: desligamos a checagem de DNS rebinding local.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@contextlib.asynccontextmanager
async def lifespan(_app):
    CATALOGO.carregar_em_background()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=f"{S.MARCA} · MCP Detetive de Produtos", lifespan=lifespan)


@app.get("/api/saude")
def saude():
    return {"pronto": CATALOGO.pronto, "erro": CATALOGO.erro, "produtos": len(CATALOGO.produtos)}


@app.get("/", response_class=HTMLResponse)
async def index():
    ferramentas = await mcp.list_tools()
    linhas = "".join(
        f"<tr><td><code>{html.escape(t.name)}</code></td><td>{html.escape(t.description or '')}</td></tr>" for t in ferramentas)
    status = "✅ catálogo carregado" if CATALOGO.pronto else "⏳ carregando o catálogo..."
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>MCP Detetive de Produtos</title>
<style>body{{font-family:'DM Sans',Arial,sans-serif;max-width:960px;margin:40px auto;padding:0 20px;color:#0B2026}}
h1{{margin:0}} .tag{{color:#FF3621;font-weight:700;letter-spacing:.08em;font-size:12px}}
table{{border-collapse:collapse;width:100%;margin-top:16px}} td{{border-top:1px solid #e5e5e5;padding:8px;vertical-align:top;font-size:14px}}
code{{background:#f3f3f1;padding:2px 6px;border-radius:4px}} .box{{background:#f7f7f5;border-left:4px solid #FF3621;padding:12px 16px;margin:16px 0}}</style>
</head><body>
<div class="tag">{html.escape(S.MARCA.upper())} · SERVIDOR MCP</div>
<h1>🔎 Detetive de Produtos</h1>
<p>Servidor <b>MCP</b> (Model Context Protocol) da loja {html.escape(S.MARCA)}. Ele faz <b>busca visual</b> (foto de um
produto → produtos parecidos), busca no catálogo (Vector Search), aplica o "quem comprou também comprou", recomenda com o modelo de ML
e consulta/abre solicitações de pós-venda. {status} ({len(CATALOGO.produtos)} produtos).</p>
<div class="box"><b>Endpoint MCP:</b> <code>/mcp</code> (Streamable HTTP)<br>
<b>Usar no Playground:</b> Playground → modelo com tools (ex.: GPT OSS 120B) → <i>Tools</i> → <i>+ Add tool</i> →
<i>MCP servers</i> → <i>Databricks Apps</i> → <code>mcp-detetive-produtos</code>.</div>
<h3>Ferramentas ({len(ferramentas)})</h3><table>{linhas}</table>
</body></html>"""


app.mount("/", mcp_app)  # expõe /mcp (precisa ser o último mount)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
