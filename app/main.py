"""
Loja de varejo (BrickStore por padrão — nome em NB_MARCA) — Databricks App (FastAPI).

  /                → frontend (HTML/CSS/JS puro, sem build) estilo e-commerce
  /api/...         → API usada pelo frontend (contrato em docs/ESPEC_VAREJO.md)
  /mcp             → servidor MCP "Detetive de Produtos" (Streamable HTTP) para clientes externos
"""
import asyncio
import contextlib
import logging
import os
import re
import time

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings

from backend import agenda, agente, estudio, lakebase, memoria
from backend import servicos as S
from backend.catalogo import CATALOGO, preco_efetivo
from backend.mcp_detetive import buscar_produtos, investigar, mcp, salvar_imagem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("varejo")
AQUI = os.path.dirname(os.path.abspath(__file__))

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp", stateless_http=True, json_response=True,
    # O proxy do Databricks Apps já autentica e reescreve o Host: desligamos a checagem de DNS rebinding local.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@contextlib.asynccontextmanager
async def lifespan(_app):
    CATALOGO.carregar_em_background()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=S.MARCA, lifespan=lifespan)


def _pronto():
    if not CATALOGO.pronto:
        raise HTTPException(503, detail=CATALOGO.erro or "Carregando o catálogo... tente em alguns segundos.")


# ───────────────────────────── vitrine ─────────────────────────────
@app.get("/api/config")
def config():
    return {"marca": S.MARCA, "slogan": "Tudo para o seu estilo, com inteligência de dados", "dominio": S.dominio(),
            "memoria": memoria.ativa()}


@app.get("/api/saude")
def saude():
    return {"pronto": CATALOGO.pronto, "erro": CATALOGO.erro, "produtos": len(CATALOGO.produtos)}


@app.get("/api/perfis")
def perfis():
    _pronto()
    return {"perfis": CATALOGO.perfis, "estilos": CATALOGO.estilos, "departamentos": CATALOGO.departamentos()}


@app.get("/api/vitrine")
def vitrine(cliente_id: str | None = None):
    _pronto()
    return CATALOGO.vitrine(cliente_id)


@app.get("/api/produto/{produto_id}")
def produto(produto_id: str):
    _pronto()
    d = CATALOGO.detalhe(produto_id)
    if not d:
        raise HTTPException(404, "produto não encontrado")
    return d


@app.get("/api/busca")
def busca(q: str, departamento: str | None = None, preco_max: float | None = None):
    _pronto()
    return buscar_produtos(q, departamento, preco_max, 16)


@app.get("/api/departamento/{nome}")
def departamento(nome: str):
    _pronto()
    return {"departamento": nome, "produtos": CATALOGO.do_departamento(nome, 120)}


@app.get("/api/estilo/{estilo_id}")
def estilo(estilo_id: str):
    _pronto()
    return {"estilo": CATALOGO.estilo(estilo_id), "produtos": CATALOGO.do_estilo(estilo_id, 120)}


@app.post("/api/pedido")
def pedido(request: Request, cliente_id: str = Body(...), itens: list[dict] = Body(...)):
    """Fecha o carrinho: grava o pedido no Lakebase (OLTP; reserva: Delta) e devolve sugestões de 'quem comprou também comprou'."""
    _pronto()
    linhas = []
    for it in itens:
        p = CATALOGO.produtos.get(it.get("produto_id"))
        if p:
            linhas.append((p, max(1, int(it.get("quantidade") or 1))))
    if not linhas:
        raise HTTPException(400, "Carrinho vazio.")
    pid = "P" + time.strftime("%y%m%d%H%M%S")
    total = round(sum(preco_efetivo(p) * q for p, q in linhas), 2)
    frete = 0.0 if total >= 299 else 19.90
    parcelas = 1 if total < 200 else min(10, int(total // 100))
    gravado_em = "lakehouse"
    if lakebase.ativo():
        try:
            lakebase.gravar_pedido(pid, cliente_id or "VISITANTE", parcelas, total, frete,
                                   [(p["produto_id"], q, preco_efetivo(p)) for p, q in linhas])
            gravado_em = "lakebase"
        except Exception as e:
            log.warning("Lakebase indisponível (%s); gravando o pedido no Delta", str(e)[:150])
    if gravado_em == "lakehouse":
        S.sql(f"""INSERT INTO {S.fq('pedidos')} (pedido_id, cliente_id, data_pedido, canal, loja, forma_pagamento, parcelas,
                                                  status, valor_total, frete)
                  VALUES (:pid, :c, current_timestamp(), 'App', NULL, 'Cartão', :parc, 'Em transporte', :t, :f)""",
              {"pid": pid, "c": cliente_id or "VISITANTE", "parc": parcelas, "t": total, "f": frete})
        valores = ", ".join(f"(:pid, :p{i}, :q{i}, :v{i}, 0.0)" for i in range(len(linhas)))
        params = {"pid": pid}
        for i, (p, q) in enumerate(linhas):
            params.update({f"p{i}": p["produto_id"], f"q{i}": q, f"v{i}": preco_efetivo(p)})
        S.sql(f"INSERT INTO {S.fq('itens_pedido')} (pedido_id, produto_id, quantidade, preco_unitario, desconto) VALUES {valores}", params)
    no_carrinho = {p["produto_id"] for p, _ in linhas}
    sugestoes = {}
    for p, _ in linhas:
        for r in CATALOGO.tambem_compraram(p["produto_id"], 6):
            if r["produto_id"] not in no_carrinho:
                sugestoes.setdefault(r["produto_id"], r)
    # 📅 automático: já coloca a chegada na agenda do usuário (Google Calendar via MCP); se não der, o aviso traz link/.ics
    try:
        na_agenda = asyncio.run(agenda.agendar_entrega(pid, cliente_id, request.headers.get("x-forwarded-access-token")))
    except Exception as e:
        log.warning("agenda automática falhou: %s", str(e)[:150])
        na_agenda = None
    _OPCOES_PREV["v"] = None   # a lista de produtos da Previsão passa a incluir esta compra na próxima abertura
    return {"pedido_id": pid, "valor_total": total, "frete": frete, "agenda": na_agenda, "gravado_em": gravado_em,
            "previsao_entrega": agenda.previsao_entrega(pid, time.strftime("%Y-%m-%d"), "Em transporte"),
            "sugestoes": sorted(sugestoes.values(), key=lambda r: r["lift"] or 0, reverse=True)[:6]}


@app.get("/api/meus-pedidos")
def meus_pedidos(cliente_id: str):
    _pronto()
    consulta = """SELECT p.pedido_id, p.data_pedido, p.status, p.valor_total, i.produto_id, i.quantidade
                  FROM {ped} p JOIN {itens} i USING (pedido_id)
                  WHERE p.cliente_id = :c ORDER BY p.data_pedido DESC LIMIT 120"""
    try:   # histórico (Delta) + novos (Lakebase, ao vivo) pelas views do UC
        linhas = S.sql(consulta.format(ped=lakebase.tabela("pedidos"), itens=lakebase.tabela("itens_pedido")), {"c": cliente_id})
    except Exception as e:
        if not lakebase.views_ativas():
            raise
        log.warning("views Lakebase indisponíveis (%s); lendo só o Delta", str(e)[:150])
        linhas = S.sql(consulta.format(ped=S.fq("pedidos"), itens=S.fq("itens_pedido")), {"c": cliente_id})
    pedidos = {}
    for l in linhas:
        ped = pedidos.setdefault(l["pedido_id"], {k: l[k] for k in ("pedido_id", "data_pedido", "status", "valor_total")} | {
            "itens": [], "previsao_entrega": agenda.previsao_entrega(l["pedido_id"], l["data_pedido"], l["status"])})
        p = CATALOGO.produtos.get(l["produto_id"])
        if p:
            ped["itens"].append({**CATALOGO.resumo(p), "quantidade": l["quantidade"]})
    return {"pedidos": list(pedidos.values())[:25]}


@app.get("/api/imagem/{produto_id}")
def imagem(produto_id: str):
    p = CATALOGO.produtos.get(produto_id)
    if not p or not p.get("imagem_path"):
        raise HTTPException(404)
    try:
        return Response(S.download(p["imagem_path"]), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    except Exception:
        raise HTTPException(404)


@app.get("/api/midia")
def midia(caminho: str):
    """Serve imagens do Volume `midia` (figuras recortadas das fichas, fotos do Detetive)."""
    if not caminho.startswith(S.VOL_MIDIA) or ".." in caminho:
        raise HTTPException(403)
    ext = caminho.rsplit(".", 1)[-1].lower()
    tipo = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "png": "image/png", "pdf": "application/pdf"}.get(ext, "image/jpeg")
    return Response(S.download(caminho), media_type=tipo, headers={"Cache-Control": "public, max-age=3600"})


# ───────────── 📞 SAC por voz (Whisper · só workspace corporativo) ─────────────
# Só aparece no App com o endpoint do Whisper (NB_WHISPER, etapa 02b) e a tabela atendimentos_voz (etapa 05a).
_VOZ = {"t": 0.0, "ok": None}


def _voz_disponivel() -> bool:
    from backend import voz
    if not voz.disponivel():
        return False
    if _VOZ["ok"] is None or time.time() - _VOZ["t"] > 300:
        try:
            S.sql(f"SELECT 1 FROM {S.fq('atendimentos_voz')} LIMIT 1", timeout_s=60)
            _VOZ["ok"] = True
        except Exception:
            _VOZ["ok"] = False
        _VOZ["t"] = time.time()
    return bool(_VOZ["ok"])


def _audio_url(caminho: str | None) -> str | None:
    if not caminho:
        return None
    caminho = str(caminho).replace("dbfs:", "")
    if not caminho.startswith("/Volumes/"):
        caminho = f"{S.VOL_MIDIA}/audios_sac/{caminho.split('/')[-1]}"
    return f"/api/midia?caminho={caminho}" if caminho.startswith(S.VOL_MIDIA) else None


@app.get("/api/voz/disponivel")
def voz_disponivel():
    return {"disponivel": _voz_disponivel()}


@app.get("/api/voz/atendimentos")
def voz_atendimentos():
    from backend import voz
    if not _voz_disponivel():
        raise HTTPException(404, "SAC por voz não instalado: no workspace corporativo, use enterprise: true no config.yaml e rode o INSTALAR.")
    linhas = voz.atendimentos(None, 50)
    return {"atendimentos": [{**l, "audio_url": _audio_url(l.get("arquivo"))} for l in linhas]}


def _processar_audio(caminho: str, cliente_id: str | None, fonte: str, registrar: bool = True) -> dict:
    """Whisper → ai_classify / ai_analyze_sentiment / ai_extract (+ grava em atendimentos_voz)."""
    from backend import voz
    tr = voz.transcrever_volume(caminho)
    texto = (tr or {}).get("texto") or ""
    if not texto:
        raise HTTPException(422, "O Whisper não devolveu texto" + (f" ({tr.get('erro')})" if (tr or {}).get("erro") else "") + ".")
    analise = voz.analisar_atendimento(texto) or {}
    if registrar:
        try:
            voz.registrar(caminho, texto, tr.get("duracao_seg"), analise, cliente_id, fonte)
        except Exception as e:
            log.warning("SAC por voz: não gravou o atendimento (%s)", str(e)[:160])
    return {"arquivo": caminho, "audio_url": _audio_url(caminho), "transcricao": texto, "fonte_transcricao": fonte,
            "duracao_seg": tr.get("duracao_seg"), **analise}


@app.post("/api/voz")
async def voz_novo(audio: UploadFile = File(...), cliente_id: str | None = Form(None), origem: str = Form("arquivo")):
    """Áudio enviado ou GRAVADO no navegador (WAV) → Volume → Whisper + análise."""
    import uuid as _uuid
    if not _voz_disponivel():
        raise HTTPException(404, "SAC por voz não instalado: no workspace corporativo, use enterprise: true no config.yaml e rode o INSTALAR.")
    dados = await audio.read()
    if len(dados) > 15 * 1024 * 1024:
        raise HTTPException(413, "Áudio muito grande (máx. 15 MB).")
    ext = (audio.filename or "audio.wav").rsplit(".", 1)[-1].lower()
    if ext not in ("wav", "mp3", "m4a", "flac", "ogg"):
        raise HTTPException(400, "Formato não suportado: use .wav ou .mp3.")
    pasta = "gravados" if origem == "microfone" else "enviados"
    caminho = f"{S.VOL_MIDIA}/audios_sac/{pasta}/{_uuid.uuid4().hex[:10]}.{ext}"
    await asyncio.to_thread(S.upload, caminho, dados)
    fonte = "whisper · gravado no App" if origem == "microfone" else "whisper · enviado no App"
    return await asyncio.to_thread(_processar_audio, caminho, cliente_id, fonte)


RX_EXEMPLO_VOZ = re.compile(r"^sac_\d{2}_[a-z_]+\.mp3$")


@app.get("/api/voz/exemplos")
def voz_exemplos():
    """As ligações prontas do repositório (audios_sac/), já copiadas para o Volume pela etapa 05a."""
    import json as _json
    try:
        roteiros = _json.load(open(os.path.join(AQUI, "..", "audios_sac", "roteiros.json"), encoding="utf-8"))
    except Exception:
        roteiros = []
    nomes = [r["arquivo"] for r in roteiros if RX_EXEMPLO_VOZ.match(r.get("arquivo", ""))]
    return {"exemplos": [{"arquivo": n, "audio_url": _audio_url(n)} for n in nomes]}


@app.post("/api/voz/exemplo")
async def voz_exemplo(arquivo: str = Body(..., embed=True)):
    """Roda o Whisper AO VIVO numa ligação pronta (sem gravar de novo na tabela: ela já está lá)."""
    if not RX_EXEMPLO_VOZ.match(arquivo or ""):
        raise HTTPException(400, "ligação de exemplo inválida")
    return await asyncio.to_thread(_processar_audio, f"{S.VOL_MIDIA}/audios_sac/{arquivo}", None, "whisper · ao vivo", False)


# ───────────────────────────── Previsão de vendas (ai_forecast) ─────────────────────────────
_OPCOES_PREV = {"t": 0, "v": None}


@app.get("/api/previsao/opcoes")
def previsao_opcoes():
    from backend import previsao
    if not _OPCOES_PREV["v"] or time.time() - _OPCOES_PREV["t"] > 600:   # a consulta leva ~5 s: cache de 10 min
        _OPCOES_PREV.update(v=previsao.opcoes(), t=time.time())
    return _OPCOES_PREV["v"]


@app.post("/api/previsao")
def previsao_sob_demanda(filtro_tipo: str = Body("total", embed=True), valor: str | None = Body(None, embed=True),
                         metrica: str = Body("receita", embed=True), granularidade: str = Body("dia", embed=True),
                         historico_dias: int = Body(180, embed=True), horizonte: int = Body(30, embed=True)):
    """Monta a série de vendas escolhida e roda ai_forecast NA HORA no SQL warehouse."""
    from backend import previsao
    try:
        dias = horizonte * 7 if granularidade == "semana" else horizonte    # a tela fala em PERÍODOS; a função, em dias
        return previsao.prever(filtro_tipo, valor, metrica, granularidade, max(30, min(historico_dias, 730)), max(7, min(dias, 180)))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ───────────── progresso REAL de tarefas longas (a tela consulta enquanto espera a resposta) ─────────────
_PROGRESSO: dict[str, tuple[int, float]] = {}


def _marcador(tarefa: str | None):
    """Devolve progresso(n), que registra a etapa em que a tarefa está (em memória: o App roda numa instância)."""
    if not tarefa or not re.fullmatch(r"[A-Za-z0-9_-]{6,40}", tarefa):
        return lambda passo: None
    agora = time.time()
    for k in [k for k, (_, t) in _PROGRESSO.items() if agora - t > 900]:   # limpa tarefas antigas
        _PROGRESSO.pop(k, None)
    return lambda passo: _PROGRESSO.__setitem__(tarefa, (int(passo), time.time()))


@app.get("/api/progresso/{tarefa}")
def progresso(tarefa: str):
    passo, _ = _PROGRESSO.get(tarefa, (-1, 0))
    return {"passo": passo}


# ───────────────────────────── Detetive de Produtos ─────────────────────────────
@app.post("/api/detetive")
async def detetive(imagem: UploadFile = File(...), quantidade: int = Form(3), tarefa: str | None = Form(None)):
    _pronto()
    dados = await imagem.read()
    if len(dados) > 10 * 1024 * 1024:
        raise HTTPException(413, "Imagem maior que 10 MB")

    marcar = _marcador(tarefa)

    def rodar():
        marcar(0)
        caminho = salvar_imagem(dados)
        return {"caminho": caminho, **investigar(dados, quantidade, marcar)}
    return await asyncio.to_thread(rodar)


@app.post("/api/upload-imagem")
async def upload_imagem(imagem: UploadFile = File(...)):
    dados = await imagem.read()
    return {"caminho": await asyncio.to_thread(salvar_imagem, dados)}


# ───────────────────────────── Assistente (agente) ─────────────────────────────
@app.post("/api/chat")
def chat(request: Request, mensagens: list[dict] = Body(..., embed=True), imagem: str | None = Body(None, embed=True),
         cliente_id: str | None = Body(None, embed=True), conversa_id: str | None = Body(None, embed=True)):
    _pronto()
    return agente.conversar(mensagens, imagem, cliente_id, request.headers.get("x-forwarded-access-token"), conversa_id)


@app.get("/api/chat/memoria")
def chat_memoria(cliente_id: str):
    """🧠 Última conversa do cliente no Lakebase (loja.conversas), para reabrir o chat onde parou."""
    if not memoria.ativa():
        return {"ativa": False, "mensagens": []}
    try:
        return {"ativa": True, **memoria.ultima_conversa(cliente_id)}
    except Exception as e:
        log.warning("memória: leitura falhou (%s)", str(e)[:160])
        return {"ativa": True, "erro": str(e)[:200], "mensagens": []}


@app.delete("/api/chat/memoria")
def chat_esquecer(cliente_id: str):
    """Apaga a memória do cliente (direito de esquecimento / LGPD)."""
    if not memoria.ativa():
        raise HTTPException(400, "memória desligada (Lakebase não configurado)")
    memoria.esquecer(cliente_id)
    return {"ok": True}


# ───────────────────────────── Agenda: chegada do pedido ─────────────────────────────
@app.post("/api/agenda/entrega")
async def agenda_entrega(request: Request, pedido_id: str = Body(..., embed=True), cliente_id: str = Body(..., embed=True)):
    """Cria o evento 'Chega hoje' no Google Calendar do usuário (MCP system.ai.google_calendar) ou devolve link/.ics."""
    _pronto()
    return await agenda.agendar_entrega(pedido_id, cliente_id, request.headers.get("x-forwarded-access-token"))


@app.get("/api/agenda/entrega/{pedido_id}.ics")
def agenda_ics(pedido_id: str, cliente_id: str):
    _pronto()
    txt = agenda.ics_do_pedido(pedido_id, cliente_id)
    if not txt:
        raise HTTPException(404, "Pedido sem entrega prevista.")
    return Response(txt, media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="entrega_{pedido_id}.ics"'})


@app.get("/api/assistente/grafo")
def assistente_grafo():
    """Diagrama (Mermaid) do grafo LangGraph do Assistente: guardrails, supervisor e agentes."""
    from backend import grafo
    return {"mermaid": grafo.mermaid(), "mermaid_rotulado": grafo.mermaid_bonito()}


@app.get("/sair")
def sair(request: Request):
    """Logout: expira os cookies de sessão do proxy do Databricks Apps (__Host-databricksapps_*) e volta para a loja.
    No próximo acesso, o Databricks faz o login de novo e pede o consentimento dos escopos atuais (ex.: ai-gateway)."""
    nomes = [n for n in request.cookies if n.startswith("__Host-databricksapps")]
    log.info("logout: expirando %d cookie(s) do proxy", len(nomes))
    html = ("<!doctype html><meta charset='utf-8'><title>Saindo…</title>"
            "<script>try{localStorage.clear();sessionStorage.clear()}catch(e){};setTimeout(()=>location.replace('/'),400)</script>"
            "<p style='font-family:sans-serif'>Você saiu. Entrando de novo…</p>")
    resp = Response(html, media_type="text/html", headers={"Cache-Control": "no-store", "Clear-Site-Data": '"cookies", "storage"'})
    for n in nomes:
        resp.delete_cookie(n, path="/", secure=True, httponly=True, samesite="none")
    return resp


@app.get("/assistente/grafo")
def assistente_grafo_pagina():
    """Página que DESENHA o grafo LangGraph (Mermaid no navegador)."""
    from backend import grafo
    import html as _h
    return Response(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>{S.MARCA} · Grafo do Assistente (LangGraph)</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>body{{font-family:'DM Sans',sans-serif;background:#F9F7F4;color:#0B2026;margin:0}}
header{{background:#0B2026;color:#fff;padding:18px 28px}}header b{{color:#FF3621}}header small{{display:block;opacity:.75;margin-top:4px}}
main{{max-width:1100px;margin:24px auto;padding:0 20px}}.card{{background:#fff;border-radius:14px;padding:20px;box-shadow:0 1px 3px #0001}}
.leg span{{display:inline-block;margin-right:16px;font-size:13px}}.leg i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
pre.mermaid{{text-align:center}}</style></head><body>
<header><b>{S.MARCA}</b> · Grafo do Assistente (LangGraph)<small>Gerado do StateGraph compilado em app/backend/grafo.py · setas tracejadas = arestas condicionais</small></header>
<main><div class="card"><p class="leg"><span><i style="background:#FFF0EC;border:1px solid #FF3621"></i>Guardrails</span>
<span><i style="background:#EAF4FB;border:1px solid #2272B4"></i>Agentes e ferramentas</span>
<span><i style="background:#EEF7EE;border:1px solid #00A972"></i>Memória (Lakebase)</span></p>
<pre class="mermaid">{_h.escape(grafo.mermaid_bonito())}</pre></div></main>
<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({{startOnLoad:true, securityLevel:"loose", flowchart:{{htmlLabels:true, curve:"basis"}}, themeVariables:{{fontFamily:"DM Sans"}}}});</script>
</body></html>""", media_type="text/html")


@app.get("/api/mcp/ferramentas")
async def mcp_ferramentas():
    tools = await mcp.list_tools()
    return {"servidor": mcp.name, "endpoint": "/mcp",
            "ferramentas": [{"nome": t.name, "titulo": t.title, "descricao": t.description,
                             "parametros": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)} for t in tools]}


# ───────────────────────────── Estúdio (controle) ─────────────────────────────
@app.get("/api/estudio/status")
def estudio_status():
    return estudio.status()


@app.get("/api/estudio/produtos")
def estudio_produtos(q: str = "", origem: str = "", limite: int = 60):
    _pronto()
    ps = list(CATALOGO.produtos.values())
    if origem:
        ps = [p for p in ps if p.get("origem") == origem]
    if q:
        ps = [p for p in ps if q.lower() in p["nome"].lower() or q.lower() in p["produto_id"].lower()]
    ps.sort(key=lambda p: (p.get("origem") != "estudio", -(p.get("popularidade") or 0)))
    return {"total": len(ps), "produtos": ps[:limite]}


@app.put("/api/estudio/produtos/{produto_id}")
def estudio_atualizar(produto_id: str, dados: dict = Body(...)):
    try:
        return estudio.atualizar_produto(produto_id, dados)
    except KeyError:
        raise HTTPException(404, "produto não encontrado")


@app.delete("/api/estudio/produtos/{produto_id}")
def estudio_remover(produto_id: str):
    estudio.remover_produto(produto_id)
    return {"ok": True}


@app.post("/api/estudio/produtos/{produto_id}/imagem")
async def estudio_imagem(produto_id: str, imagem: UploadFile = File(...)):
    dados = await imagem.read()
    return {"imagem_path": await asyncio.to_thread(estudio.salvar_imagem_produto, produto_id, dados)}


@app.get("/api/estudio/fichas/exemplos")
def estudio_fichas_exemplo():
    return {"exemplos": estudio.fichas_exemplo()}


@app.post("/api/estudio/fichas")
async def estudio_ficha(arquivo: UploadFile | None = File(None), exemplo: str | None = Form(None),
                        tarefa: str | None = Form(None)):
    """Cadastro a partir de PDF: envia a ficha técnica do fornecedor (ou escolhe um exemplo) e recebe o rascunho."""
    _pronto()
    marcar = _marcador(tarefa)
    if exemplo:
        return await asyncio.to_thread(estudio.processar_ficha, exemplo.rsplit("/", 1)[-1], None, exemplo, marcar)
    if not arquivo:
        raise HTTPException(400, "Envie um PDF")
    dados = await arquivo.read()
    try:
        return await asyncio.to_thread(estudio.processar_ficha, arquivo.filename, dados, None, marcar)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/estudio/fichas/{chave}/publicar")
def estudio_publicar(chave: str, ficha: dict = Body(...), imagem_path: str | None = Body(None)):
    return estudio.publicar_ficha(chave, ficha, imagem_path)


@app.get("/api/estudio/documentos")
def estudio_documentos():
    return {"documentos": estudio.listar_documentos()}


@app.post("/api/estudio/documentos")
async def estudio_pdf(arquivo: UploadFile = File(...)):
    dados = await arquivo.read()
    try:
        return await asyncio.to_thread(estudio.processar_pdf, arquivo.filename, dados)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/estudio/documentos/{arquivo}")
def estudio_remover_doc(arquivo: str):
    estudio.remover_documento(arquivo)
    return {"ok": True}


@app.post("/api/estudio/sync/{qual}")
def estudio_sync(qual: str):
    idx = S.IDX_PRODUTOS if qual == "produtos" else S.IDX_AJUDA
    return {"indice": idx, "resultado": S.vs_sync(idx)}


@app.get("/api/estudio/ml")
def estudio_ml():
    return estudio.modelo_ml()


@app.get("/api/para-voce")
def para_voce(cliente_id: str):
    _pronto()
    return {"cliente_id": cliente_id, "produtos": CATALOGO.recomendados_ml(cliente_id, 24)}


@app.post("/api/estudio/recalcular")
def estudio_recalcular():
    return estudio.recalcular_recomendacoes()


@app.post("/api/estudio/recarregar")
def estudio_recarregar():
    CATALOGO.carregar()
    return {"produtos": len(CATALOGO.produtos)}


@app.exception_handler(Exception)
async def erro_generico(_req, exc):
    log.exception("erro não tratado")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {str(exc)[:400]}"})


# ───────────────────────────── frontend + MCP ─────────────────────────────
app.mount("/static", StaticFiles(directory=os.path.join(AQUI, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(AQUI, "static", "index.html"), headers={"Cache-Control": "no-cache"})


app.mount("/", mcp_app)  # expõe /mcp (precisa ser o último mount)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
