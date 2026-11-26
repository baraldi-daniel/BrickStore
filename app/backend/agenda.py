"""
📅 Chegada do pedido na agenda do cliente.

1ª opção: cria o evento DE VERDADE no Google Calendar de quem está usando o App, pelo conector MCP gerenciado
         `system.ai.google_calendar` do Unity Gateway (ferramenta `calendar_event_create`). A chamada usa o token
         do PRÓPRIO usuário (autorização de usuário do Databricks Apps), então o evento cai na agenda dele.
Reserva: se o usuário não conectou o Google ou o App não tem o token dele, devolve um link "Adicionar ao Google
         Agenda" já preenchido e um arquivo .ics (funciona em qualquer calendário).
"""
import hashlib
import json
import logging
import urllib.parse
from datetime import date, datetime, timedelta

import httpx

from . import lakebase
from . import servicos as S

log = logging.getLogger("varejo")
CONECTOR = "system.ai.google_calendar"


def _dia_util(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def previsao_entrega(pedido_id: str, data_pedido, status: str | None = None) -> str | None:
    """Previsão determinística: 3 a 7 dias úteis após o pedido (o 'prazo da transportadora' do lab)."""
    if status in ("Cancelado", "Devolvido"):
        return None
    if isinstance(data_pedido, str):
        data_pedido = datetime.fromisoformat(data_pedido[:19].replace("T", " ")).date() if data_pedido else date.today()
    elif isinstance(data_pedido, datetime):
        data_pedido = data_pedido.date()
    dias = 3 + int(hashlib.md5(str(pedido_id).encode()).hexdigest(), 16) % 5
    prev = _dia_util(data_pedido or date.today(), dias)
    if status == "Em transporte" and prev <= date.today():   # ainda em trânsito: chega no próximo dia útil
        prev = _dia_util(date.today(), 1)
    return prev.isoformat()


def _pedido(pedido_id: str, cliente_id: str) -> dict | None:
    linhas = S.sql(f"""SELECT p.pedido_id, p.data_pedido, p.status, p.valor_total, i.produto_id, i.quantidade
                       FROM {lakebase.tabela('pedidos')} p JOIN {lakebase.tabela('itens_pedido')} i USING (pedido_id)
                       WHERE p.pedido_id = :p AND p.cliente_id = :c""", {"p": pedido_id, "c": cliente_id})
    if not linhas:
        return None
    from .catalogo import CATALOGO
    itens = []
    for l in linhas:
        prod = CATALOGO.produtos.get(l["produto_id"])
        itens.append(f"{int(l['quantidade'] or 1)}× {prod['nome'] if prod else l['produto_id']}")
    l0 = linhas[0]
    return {"pedido_id": pedido_id, "status": l0["status"], "valor_total": l0["valor_total"], "itens": itens,
            "previsao": previsao_entrega(pedido_id, l0["data_pedido"], l0["status"])}


def _evento(ped: dict) -> dict:
    dia = date.fromisoformat(ped["previsao"])
    titulo = f"📦 Chega hoje: pedido {S.MARCA} {ped['pedido_id']}"
    descricao = (f"Previsão de entrega do seu pedido {ped['pedido_id']} na {S.MARCA}.\n\nItens:\n- " + "\n- ".join(ped["itens"][:10])
                 + f"\n\nValor: R$ {float(ped['valor_total'] or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                 + f"\nAcompanhe em https://{S.dominio()}/pedidos")
    return {"titulo": titulo, "descricao": descricao, "inicio": dia.isoformat(), "fim": (dia + timedelta(days=1)).isoformat()}


def link_google(ev: dict) -> str:
    datas = f"{ev['inicio'].replace('-', '')}/{ev['fim'].replace('-', '')}"
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        {"action": "TEMPLATE", "text": ev["titulo"], "dates": datas, "details": ev["descricao"]})


def ics(ev: dict, uid: str) -> str:
    def esc(t):
        return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    agora = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{S.MARCA}//Entrega//PT-BR", "BEGIN:VEVENT",
                        f"UID:{uid}@{S.dominio()}", f"DTSTAMP:{agora}", f"DTSTART;VALUE=DATE:{ev['inicio'].replace('-', '')}",
                        f"DTEND;VALUE=DATE:{ev['fim'].replace('-', '')}", f"SUMMARY:{esc(ev['titulo'])}",
                        f"DESCRIPTION:{esc(ev['descricao'])}", "BEGIN:VALARM", "TRIGGER:-PT12H", "ACTION:DISPLAY",
                        "DESCRIPTION:Seu pedido chega amanhã", "END:VALARM", "END:VEVENT", "END:VCALENDAR", ""])


def _escopos(token: str) -> str:
    """Só para diagnóstico: lê o claim 'scope' do JWT (o token em si nunca é registrado)."""
    try:
        import base64
        corpo = token.split(".")[1]
        corpo += "=" * (-len(corpo) % 4)
        return str(json.loads(base64.urlsafe_b64decode(corpo)).get("scope", "?"))
    except Exception:
        return "?"


async def _mcp_calendar(token: str, ev: dict) -> dict:
    """Chama calendar_event_create no MCP gerenciado do Google Calendar (Unity Gateway), como o usuário."""
    url = f"{S.ws().config.host.rstrip('/')}/ai-gateway/mcp-services/{CONECTOR}"
    cab = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    def corpo(r: httpx.Response) -> dict:
        txt = r.text
        if "data:" in txt[:50]:
            txt = [l[5:] for l in txt.splitlines() if l.startswith("data:")][-1]
        return json.loads(txt)

    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(url, headers=cab, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": S.MARCA.lower(), "version": "1"}}})
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} · escopos do token: {_escopos(token)} · {r.text[:300]}")
        if r.headers.get("mcp-session-id"):
            cab["mcp-session-id"] = r.headers["mcp-session-id"]
        await c.post(url, headers=cab, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = await c.post(url, headers=cab, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "calendar_event_create",
            "arguments": {"summary": ev["titulo"], "description": ev["descricao"], "start": ev["inicio"], "end": ev["fim"]}}})
        r.raise_for_status()
        res = corpo(r)
    if "error" in res:
        raise RuntimeError(res["error"].get("message", str(res["error"]))[:300])
    resultado = res.get("result") or {}
    texto = " ".join(c.get("text", "") for c in resultado.get("content") or [] if isinstance(c, dict))
    if resultado.get("isError"):
        raise RuntimeError(texto[:300] or "erro no calendar_event_create")
    try:
        dados = resultado.get("structuredContent") or json.loads(texto)
    except Exception:
        dados = {"resposta": texto[:300]}
    return dados


async def agendar_entrega(pedido_id: str, cliente_id: str | None, token_usuario: str | None) -> dict:
    if not cliente_id:
        return {"erro": "Nenhum cliente logado."}
    import asyncio
    ped = await asyncio.to_thread(_pedido, pedido_id, cliente_id)
    if not ped:
        return {"erro": f"Pedido {pedido_id} não encontrado para este cliente."}
    if not ped["previsao"]:
        return {"erro": f"O pedido {pedido_id} está {ped['status'].lower()} e não tem entrega prevista."}
    ev = _evento(ped)
    base = {"pedido_id": pedido_id, "previsao_entrega": ped["previsao"], "titulo": ev["titulo"],
            "link_google": link_google(ev), "ics_url": f"/api/agenda/entrega/{pedido_id}.ics?cliente_id={cliente_id}"}
    if not token_usuario:
        base["aviso"] = ("O App ainda não tem permissão para usar sua agenda (escopo «ai-gateway» na autorização de usuário). "
                         "Por enquanto, use o link abaixo.")
    else:
        try:
            dados = await _mcp_calendar(token_usuario, ev)
            link = dados.get("htmlLink") or dados.get("html_link") or (dados.get("event") or {}).get("htmlLink")
            return {**base, "criado": True, "via": f"MCP {CONECTOR}", "evento_link": link, "detalhe": dados}
        except Exception as e:
            log.warning("Google Calendar via MCP falhou: %s", str(e)[:600])
            msg = str(e)
            if ("403" in msg or "401" in msg) and "ai-gateway" not in _escopos(token_usuario):
                base["aviso"] = ("Seu login no App ainda não tem a permissão «ai-gateway». Se o admin já adicionou o escopo "
                                 "(Compute → Apps → Edit → User authorization), abra o App numa janela anônima (ou apague os "
                                 "cookies do App) e aceite o consentimento. Por enquanto, use o link abaixo.")
            elif "403" in msg or "401" in msg:
                base["aviso"] = ("Sem acesso ao Google Calendar: conecte sua conta em AI Gateway → MCP → Google Calendar → Connect. "
                                 "Por enquanto, use o link abaixo.")
            elif any(t in msg.lower() for t in ("auth", "login", "credential", "connect", "oauth")):
                base["aviso"] = ("Conecte seu Google Calendar: AI Gateway → MCP → Google Calendar → Connect. "
                                 "Por enquanto, use o link abaixo.")
            else:
                base["aviso"] = "Não consegui criar direto na sua agenda agora. Use o link abaixo."
            base["erro_mcp"] = str(e)[:200]
    return {**base, "criado": False, "via": "link"}


def ics_do_pedido(pedido_id: str, cliente_id: str) -> str | None:
    ped = _pedido(pedido_id, cliente_id)
    if not ped or not ped["previsao"]:
        return None
    return ics(_evento(ped), pedido_id)
