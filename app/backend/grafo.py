"""
🕸️ Assistente da loja como um GRAFO LangGraph: guardrails + supervisor + 3 agentes especialistas.

Cada guardrail é um NÓ do grafo. Um bloqueio desvia o fluxo para o nó `bloqueio` e o LLM principal nem é chamado.

    START
      │
      ▼
    🧠 memoria_carregar           lê no Lakebase (loja.conversas) o que este cliente já conversou antes
      │
      ▼
    🛡️ guardrail_pii_entrada      mascara CPF / cartão / telefone (regex) antes de qualquer LLM
      │
      ▼
    🛡️ guardrail_jailbreak        regras determinísticas: "ignore as instruções", "prompt do sistema",
      │                            pedir dados de OUTRO cliente...   ──(bloqueia)──► ⛔ bloqueio ──► END
      ▼
    🛡️ guardrail_juiz             LLM-juiz (Llama 3.3 70B): ok | jailbreak | ofensivo | fora_do_escopo
      │  (+ supervisor: escolhe o agente)                              ──(bloqueia)──► ⛔ bloqueio
      ├──────────────┬──────────────────┐
      ▼              ▼                  ▼
    🛍️ vendas      📦 pos_venda       📊 analista          ◄────────────┐
      │ (pediu ferramenta?)                                              │
      ├──── sim ──► 🛡️ guardrail_ferramentas ──► 🔧 ferramentas ─────────┘
      │             (só ferramentas do agente; cliente_id forçado = cliente logado)
      ▼ não
    🛡️ guardrail_saida            mascara dados sensíveis, impede vazar o prompt, sinaliza resposta sem fundamentação
      │
      ▼
    🧠 memoria_gravar             grava a pergunta (já mascarada) e a resposta no Lakebase
      │
      ▼
     END

Tudo que um guardrail faz (mascarar, bloquear, corrigir) vira um evento na tabela Delta `guardrail_eventos`.
"""
import asyncio
import inspect
import json
import logging
import operator
import re
import time
import unicodedata
import uuid
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from mcp.client.client import Client

from . import guardrail as G
from . import memoria as M
from . import servicos as S
from .agente import ESPECIALISTAS, FERRAMENTAS_LOCAIS
from .mcp_detetive import ferramentas_openai, mcp, texto_resultado

log = logging.getLogger("varejo")
MAX_RODADAS = 6


class Estado(TypedDict, total=False):
    # entrada
    mensagens: list[dict]                 # histórico do chat (user/assistant)
    imagem: str | None
    conversa_id: str | None               # id da conversa (o navegador gera; "Nova conversa" troca)
    memoria: list[dict]                   # 🧠 mensagens de conversas anteriores (Lakebase)
    memoria_info: dict
    cliente_id: str | None
    # guardrails / supervisor
    permitido: bool
    categoria: str
    motivo: str
    agente: str
    eventos: Annotated[list[dict], operator.add]
    trilha: Annotated[list[str], operator.add]
    passos: Annotated[list[dict], operator.add]   # trilha detalhada: nó, status, detalhe, ms
    # agente
    msgs: list[dict]                      # conversa com o LLM (system + histórico + tool calls)
    pendentes: list[dict]                 # tool calls aguardando execução
    rodada: int
    usadas: Annotated[list[str], operator.add]
    produtos: dict
    laudo: Any
    genie: Any
    agenda: Any
    modelos: list[str]
    # saída
    resposta: str
    bloqueado: bool


def _ultima(estado: Estado) -> str:
    m = estado.get("mensagens") or []
    return str(m[-1]["content"]) if m and m[-1].get("role") == "user" else ""


def _evento(estado: Estado, fase: str, categoria: str, acao: str, detalhe: str, trecho: str = "") -> dict:
    G.registrar(estado.get("cliente_id"), fase, categoria, acao, trecho or detalhe)
    return {"fase": fase, "categoria": categoria, "acao": acao, "detalhe": detalhe}


# ───────────────────────────── 🧠 memória (Lakebase) ─────────────────────────────
async def memoria_carregar(estado: Estado) -> dict:
    cliente = estado.get("cliente_id")
    if not cliente:
        return {"memoria": [], "memoria_info": {"status": "sem cliente logado"}, "trilha": ["memoria_carregar"]}
    if not M.ativa():
        return {"memoria": [], "memoria_info": {"status": "Lakebase desligado"}, "trilha": ["memoria_carregar"]}
    try:
        mem = await asyncio.to_thread(M.anteriores, cliente, estado.get("conversa_id"))
        info = {"status": "ok", "mensagens": len(mem), "conversas": len({m["conversa_id"] for m in mem})}
    except Exception as e:
        log.warning("memória: leitura falhou (%s)", str(e)[:160])
        mem, info = [], {"status": "erro", "erro": str(e)[:160]}
    return {"memoria": mem, "memoria_info": info, "trilha": ["memoria_carregar"]}


async def memoria_gravar(estado: Estado) -> dict:
    cliente, conversa = estado.get("cliente_id"), estado.get("conversa_id")
    info = dict(estado.get("memoria_info") or {})
    if cliente and conversa and M.ativa() and not estado.get("bloqueado"):
        try:
            await asyncio.to_thread(M.gravar, conversa, cliente,
                                    [("user", _ultima(estado), None), ("assistant", estado.get("resposta") or "", estado.get("agente"))])
            info["gravado"] = True
        except Exception as e:
            log.warning("memória: gravação falhou (%s)", str(e)[:160])
            info["gravado"], info["erro_gravar"] = False, str(e)[:160]
    return {"memoria_info": info, "trilha": ["memoria_gravar"]}


# ───────────────────────────── 🛡️ guardrails de entrada ─────────────────────────────
def guardrail_pii_entrada(estado: Estado) -> dict:
    """Mascara dados sensíveis em TODO o histórico (o navegador reenvia as mensagens antigas a cada turno)."""
    mensagens, achados_ultima = [], []
    historico = estado.get("mensagens") or []
    for i, m in enumerate(historico):
        mascarado, achados = G.mascarar(str(m.get("content") or ""))
        mensagens.append({**m, "content": mascarado} if achados else m)
        if achados and i == len(historico) - 1:
            achados_ultima = achados
    saida = {"mensagens": mensagens, "trilha": ["guardrail_pii_entrada"]}
    if achados_ultima:
        saida["eventos"] = [_evento(estado, "entrada", "dados_sensiveis", "mascarado", ", ".join(achados_ultima), mensagens[-1]["content"])]
    return saida


def guardrail_jailbreak(estado: Estado) -> dict:
    texto = _ultima(estado)
    v = G.regras_bloqueio(texto, estado.get("cliente_id"))
    if not v:
        return {"permitido": True, "trilha": ["guardrail_jailbreak"]}
    return {"permitido": False, "categoria": v["categoria"], "motivo": v["motivo"], "trilha": ["guardrail_jailbreak"],
            "eventos": [_evento(estado, "entrada", v["categoria"], "bloqueado", v["motivo"], texto)]}


async def guardrail_juiz(estado: Estado) -> dict:
    texto = _ultima(estado)
    if estado.get("imagem"):  # foto de produto: vai direto para a busca visual do Detetive (Vendas)
        return {"permitido": True, "categoria": "ok", "agente": "vendas", "motivo": "imagem anexada", "trilha": ["guardrail_juiz"]}
    historico = "\n".join(f"{m['role']}: {str(m['content'])[:200]}" for m in (estado.get("mensagens") or [])[-5:-1]) or "(início)"
    if estado.get("memoria"):
        historico = ("(conversas anteriores, da memória)\n" + "\n".join(f"{m['papel']}: {str(m['conteudo'])[:160]}"
                                                                     for m in estado["memoria"][-4:]) + "\n(conversa atual)\n" + historico)
    v = await asyncio.to_thread(G.julgar, texto, historico)
    saida = {"permitido": v["permitido"], "categoria": v["categoria"], "agente": v["agente"], "motivo": v.get("motivo", ""),
             "trilha": ["guardrail_juiz"]}
    if not v["permitido"]:
        saida["eventos"] = [_evento(estado, "entrada", v["categoria"], "bloqueado", v.get("motivo", ""), texto)]
    return saida


def bloqueio(estado: Estado) -> dict:
    return {"resposta": G.RESPOSTA_BLOQUEIO.get(estado.get("categoria"), G.RESPOSTA_BLOQUEIO["fora_do_escopo"]),
            "bloqueado": True, "agente": estado.get("agente") or "vendas", "trilha": ["bloqueio"]}


def rota_entrada(estado: Estado) -> str:
    return "seguir" if estado.get("permitido", True) else "bloqueio"


def rota_supervisor(estado: Estado) -> str:
    if not estado.get("permitido", True):
        return "bloqueio"
    return estado.get("agente") if estado.get("agente") in G.AGENTES else "vendas"


# ───────────────────────────── 🤖 agentes especialistas ─────────────────────────────
def _msgs_iniciais(estado: Estado, esp: dict) -> list[dict]:
    msgs = [{"role": "system", "content": esp["prompt"] + M.texto_para_prompt(estado.get("memoria") or [])}]
    for m in (estado.get("mensagens") or [])[-12:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": str(m["content"])[:6000]})
    if msgs[-1]["role"] == "user":
        if estado.get("cliente_id"):
            from .catalogo import CATALOGO
            perfil = next((x for x in CATALOGO.perfis if x.get("cliente_id") == estado["cliente_id"]), {})
            nome = str(perfil.get("nome") or perfil.get("apelido") or "").split(" ")[0]
            msgs[-1]["content"] += (f"\n\n[cliente logado: {estado['cliente_id']}" + (f" · primeiro nome: {nome}" if nome else "")
                                    + " — chame o cliente pelo primeiro nome; nunca escreva o código do cliente na resposta]")
        if estado.get("imagem"):
            msgs[-1]["content"] += f"\n\n[imagem anexada: {estado['imagem']}]"
    return msgs


def _ferramentas_do(agente: str, config: RunnableConfig) -> list[dict]:
    todas = config["configurable"]["ferramentas"]
    permitidas = ESPECIALISTAS[agente]["ferramentas"]
    return [t for t in todas if t["function"]["name"] in permitidas]


RX_CHAMADA_TEXTO = re.compile(r"\[?\b([a-z_]{4,40})\(([^()]*)\)\]?")
RX_PEDIDO_AGENDA = re.compile(r"agenda|calend[aá]rio|lembr|lembre|avis[ae] quando", re.I)


def _tool_call_em_texto(conteudo: str, nomes: set):
    """Alguns modelos 'escrevem' a chamada de ferramenta no texto (JSON ou nome(arg=valor)). Recupera esses casos."""
    d = S.extrair_json(conteudo or "")
    nome = d.get("name") or d.get("function")
    if nome in nomes:
        return nome, d.get("parameters") or d.get("arguments") or {}
    for m in RX_CHAMADA_TEXTO.finditer(conteudo or ""):
        if m.group(1) in nomes:
            args = {}
            for par in m.group(2).split(","):
                if "=" in par:
                    k, v = par.split("=", 1)
                    v = v.strip().strip("'\"")
                    if re.fullmatch(r"[\d.\s+\-*/]+", v):      # "3000 - 551.9" → 2448.1
                        try:
                            v = round(float(eval(v, {"__builtins__": {}}, {})), 2)
                        except Exception:
                            pass
                    args[k.strip()] = v
            return m.group(1), args
    return None


def _no_agente(agente: str):
    async def no(estado: Estado, config: RunnableConfig) -> dict:
        esp = ESPECIALISTAS[agente]
        msgs = list(estado.get("msgs") or _msgs_iniciais(estado, esp))
        rodada = estado.get("rodada", 0)
        if rodada >= MAX_RODADAS:
            return {"resposta": "Fiz várias consultas mas não consegui fechar a resposta. Pode reformular?",
                    "pendentes": [], "msgs": msgs, "trilha": [agente]}
        tools = _ferramentas_do(agente, config)
        nomes = {t["function"]["name"] for t in tools}
        ultima = _ultima(estado)
        # 1ª rodada: obriga o uso de ferramenta (dados reais, nada inventado), exceto saudações curtas
        forcar = rodada == 0 and bool(tools) and len(ultima.strip()) > 12
        # pediu para pôr na agenda e a ferramenta ainda não rodou: obriga a chamada também nas rodadas seguintes
        if ("agendar_entrega" in nomes and RX_PEDIDO_AGENDA.search(ultima.split("\n\n[")[0])
                and "agendar_entrega" not in (estado.get("usadas") or []) and rodada < 3):
            forcar = True
        resp, modelo = await asyncio.to_thread(S.chat_assistente, msgs, tools, 1400, 0.2, "required" if forcar else None)
        modelos = list(estado.get("modelos") or [])
        if modelo not in modelos:
            modelos.append(modelo)
        msg = resp.choices[0].message
        # 🛡️ service policy do Unity Gateway (workspace corporativo): o bloqueio volta com HTTP 200 e o objeto
        # databricks_service_policy (motivo); a mensagem do assistente já diz qual policy bloqueou
        politica = getattr(resp, "databricks_service_policy", None) or (getattr(resp, "model_extra", None) or {}).get(
            "databricks_service_policy")
        if politica:
            motivo = (politica.get("reason") if isinstance(politica, dict) else str(politica)) or "service policy do Unity Gateway"
            return {"resposta": msg.content or f"Não posso seguir com esse pedido ({motivo}).", "pendentes": [], "msgs": msgs,
                    "modelos": modelos, "rodada": rodada + 1, "agente": agente, "trilha": [agente], "bloqueado": True,
                    "eventos": [_evento(estado, "gateway", "unity_gateway", "bloqueado", str(motivo)[:200], _ultima(estado))]}
        chamadas = [{"id": tc.id, "nome": tc.function.name, "argumentos": tc.function.arguments} for tc in (msg.tool_calls or [])]
        if not chamadas and (rec := _tool_call_em_texto(msg.content, nomes)):
            chamadas = [{"id": f"call_{uuid.uuid4().hex[:8]}", "nome": rec[0], "argumentos": json.dumps(rec[1])}]
        if not chamadas:
            return {"resposta": msg.content or "(sem resposta)", "pendentes": [], "msgs": msgs, "modelos": modelos,
                    "rodada": rodada + 1, "agente": agente, "trilha": [agente]}
        msgs.append({"role": "assistant", "content": msg.content or "",
                     "tool_calls": [{"id": c["id"], "type": "function",
                                     "function": {"name": c["nome"], "arguments": c["argumentos"] or "{}"}} for c in chamadas]})
        return {"pendentes": chamadas, "msgs": msgs, "modelos": modelos, "rodada": rodada + 1, "agente": agente, "trilha": [agente]}
    no.__name__ = agente
    return no


def rota_agente(estado: Estado) -> str:
    return "guardrail_ferramentas" if estado.get("pendentes") else "guardrail_saida"


def rota_volta(estado: Estado) -> str:
    return estado.get("agente", "vendas")


# ───────────────────────────── 🛡️ guardrail de ferramentas + execução ─────────────────────────────
COM_CLIENTE = {"pedidos_do_cliente", "abrir_solicitacao", "recomendar_para_cliente", "agendar_entrega"}


def guardrail_ferramentas(estado: Estado) -> dict:
    """Antes de executar: só ferramentas do agente atual e, nas ferramentas de cliente, SEMPRE o cliente logado."""
    agente, logado = estado.get("agente", "vendas"), estado.get("cliente_id")
    permitidas = ESPECIALISTAS[agente]["ferramentas"]
    pendentes, eventos = [], []
    for c in estado.get("pendentes") or []:
        try:
            args = json.loads(c["argumentos"] or "{}") if isinstance(c["argumentos"], str) else (c["argumentos"] or {})
        except json.JSONDecodeError:
            args = {}
        c = {**c, "args": args, "negado": None}
        if c["nome"] not in permitidas:
            c["negado"] = f"A ferramenta {c['nome']} não é permitida para o {G.AGENTES[agente]['nome']}."
            eventos.append(_evento(estado, "ferramenta", "ferramenta_nao_permitida", "negado", f"{agente} → {c['nome']}"))
        elif c["nome"] in COM_CLIENTE:
            if not logado:
                c["negado"] = "Nenhum cliente logado. Peça para o cliente escolher um perfil no topo da página."
                eventos.append(_evento(estado, "ferramenta", "sem_cliente", "negado", c["nome"]))
            elif args.get("cliente_id") not in (None, "", logado):
                eventos.append(_evento(estado, "ferramenta", "acesso_outro_cliente", "corrigido",
                                       f"{c['nome']}: {args.get('cliente_id')} → {logado}"))
                c["args"] = {**args, "cliente_id": logado}
            else:
                c["args"] = {**args, "cliente_id": logado}
        if c["nome"] == "investigar_imagem" and estado.get("imagem") and not str(args.get("imagem", "")).startswith(("/Volumes", "data:")):
            c["args"]["imagem"] = estado["imagem"]
        pendentes.append(c)
    return {"pendentes": pendentes, "eventos": eventos, "trilha": ["guardrail_ferramentas"]}


def _suporte(pergunta: str) -> dict:
    hits = S.vs_query(S.IDX_AJUDA, ["chunk_id", "documento", "secao", "conteudo", "arquivo"], pergunta, 4)
    return {"trechos": [{"documento": h["documento"], "secao": h["secao"], "arquivo": h["arquivo"],
                         "conteudo": h["conteudo"]} for h in hits]}


async def _executar(cliente: Client, nome: str, args: dict, token_usuario: str | None = None) -> dict:
    try:
        if nome == "agendar_entrega":
            from . import agenda
            return await agenda.agendar_entrega(args.get("pedido_id", ""), args.get("cliente_id"), token_usuario)
        if nome == "suporte":
            return await asyncio.to_thread(_suporte, args.get("pergunta", ""))
        if nome == "consultar_dados":
            if not S.GENIE_SPACE_ID:
                return {"erro": "Genie não configurado."}
            try:  # 1ª opção: servidor MCP gerenciado do Genie Agent
                return await S.perguntar_genie_mcp(args.get("pergunta", ""))
            except Exception as e:  # reserva: Conversation API (REST)
                log.warning("Genie via MCP falhou (%s); usando a Conversation API", str(e)[:120])
                return await asyncio.to_thread(S.perguntar_genie, args.get("pergunta", ""))
        return texto_resultado(await cliente.call_tool(nome, args))
    except Exception as e:
        log.exception("ferramenta %s falhou", nome)
        return {"erro": f"{type(e).__name__}: {str(e)[:300]}"}


def _coletar_produtos(resultado: dict, acumulado: dict):
    def add(p):
        if isinstance(p, dict) and p.get("produto_id"):
            acumulado.setdefault(p["produto_id"], p)
    for chave in ("produtos", "itens", "tambem_compraram"):
        for p in resultado.get(chave) or []:
            add(p)
    add(resultado.get("produto_base"))


async def ferramentas(estado: Estado, config: RunnableConfig) -> dict:
    cliente: Client = config["configurable"]["mcp"]
    msgs, produtos = list(estado["msgs"]), dict(estado.get("produtos") or {})
    laudo, genie, usadas, agenda_res = estado.get("laudo"), estado.get("genie"), [], estado.get("agenda")
    for c in estado.get("pendentes") or []:
        resultado = ({"erro": c["negado"]} if c.get("negado")
                     else await _executar(cliente, c["nome"], c["args"], config["configurable"].get("token_usuario")))
        if not c.get("negado"):
            usadas.append(c["nome"])
        _coletar_produtos(resultado, produtos)
        if c["nome"] in ("investigar_imagem", "analisar_imagem") and not c.get("negado"):
            laudo = resultado.get("laudo", resultado)
        if c["nome"] == "consultar_dados" and not c.get("negado"):
            genie = resultado
        if c["nome"] == "agendar_entrega" and not c.get("negado") and not resultado.get("erro"):
            agenda_res = resultado
        msgs.append({"role": "tool", "tool_call_id": c["id"],
                     "content": json.dumps(resultado, ensure_ascii=False, default=str)[:12000]})
    return {"msgs": msgs, "pendentes": [], "produtos": produtos, "laudo": laudo, "genie": genie, "usadas": usadas, "agenda": agenda_res,
            "trilha": ["ferramentas"]}


# ───────────────────────────── 🛡️ guardrail de saída ─────────────────────────────
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _trechos_do_prompt() -> list[str]:
    frases = set()
    for esp in ESPECIALISTAS.values():
        for f in re.split(r"[\n.]", esp["prompt"]):
            n = _norm(f)
            if len(n) >= 45:
                frases.add(n[:60])
    return sorted(frases)


def guardrail_saida(estado: Estado) -> dict:
    texto, eventos = estado.get("resposta") or "", []
    # 0) chamadas de ferramenta "escritas" no texto (o modelo às vezes descreve em vez de chamar)
    texto = re.sub(r"\[?\b[a-z_]{4,40}\([^()]*=[^()]*\)\]?", "", texto).strip()
    # 1) vazamento do prompt do sistema
    n = _norm(texto)
    if any(f in n for f in TRECHOS_PROMPT):
        eventos.append(_evento(estado, "saida", "vazamento_prompt", "bloqueado", "resposta continha instruções internas", texto))
        texto = G.RESPOSTA_BLOQUEIO["jailbreak"]
    # 2) dados sensíveis na resposta (inclui o código interno do cliente, que não deve aparecer)
    texto = re.sub(r",?\s*\b(?:cliente\s+)?C\d{6}\b", "", texto)
    texto, achados = G.mascarar(texto)
    if achados:
        eventos.append(_evento(estado, "saida", "dados_sensiveis", "mascarado", ", ".join(achados), texto))
    # 3) fundamentação: preço ou número de pedido sem nenhuma ferramenta consultada
    if not estado.get("usadas") and re.search(r"R\$\s?\d|\bP\d{7}\b", texto):
        eventos.append(_evento(estado, "saida", "sem_fundamentacao", "sinalizado", "valores citados sem consultar ferramentas", texto))
        texto += "\n\n_⚠️ Não confirmei esses valores no catálogo agora; confira na página do produto._"
    return {"resposta": texto, "eventos": eventos, "trilha": ["guardrail_saida"]}


# ───────────────────────────── trilha detalhada (o que cada nó decidiu) ─────────────────────────────
ROTULOS = {"dados_sensiveis": "dados sensíveis", "vazamento_prompt": "vazamento do prompt", "sem_fundamentacao": "sem fundamentação",
           "fora_do_escopo": "fora do escopo", "outro_cliente": "dados de outra conta",
           "unity_gateway": "service policy do Unity Gateway"}


def _detalhe(no: str, antes: Estado, out: dict) -> str:
    ev = out.get("eventos") or []
    if no == "memoria_carregar":
        i = out.get("memoria_info") or {}
        if i.get("status") != "ok":
            return ("Lakebase indisponível" if i.get("status") == "erro" else i.get("status", "")) + " · seguiu sem memória"
        if not i.get("mensagens"):
            return "nenhuma conversa anterior no Lakebase"
        return f"lembrou {i['mensagens']} mensagem(ns) de {i['conversas']} conversa(s) anterior(es) · Lakebase"
    if no == "memoria_gravar":
        i = out.get("memoria_info") or {}
        if i.get("gravado"):
            return "turno gravado em loja.conversas (Lakebase)"
        if i.get("gravado") is False:
            return "falha ao gravar no Lakebase"
        return "nada a gravar (" + (i.get("status") or "sem cliente") + ")"
    if no == "guardrail_pii_entrada":
        return "mascarou " + ev[0]["detalhe"].replace("cartao", "cartão").upper() if ev else "nenhum dado sensível"
    if no == "guardrail_jailbreak":
        return out.get("motivo") if out.get("permitido") is False else "nenhuma regra violada"
    if no == "guardrail_juiz":
        if out.get("permitido") is False:
            return f"bloqueou: {ROTULOS.get(out.get('categoria'), out.get('categoria', ''))}" + (f" ({out['motivo']})" if out.get("motivo") else "")
        return f"ok · encaminhou para o {G.AGENTES.get(out.get('agente'), G.AGENTES['vendas'])['nome']}"
    if no == "bloqueio":
        return "resposta padrão de segurança"
    if no in G.AGENTES:
        if out.get("bloqueado"):
            return "bloqueado por uma service policy do Unity Gateway: " + ((out.get("eventos") or [{}])[0].get("detalhe") or "")
        modelo = ((out.get("modelos") or [""])[-1]).split(" (via")[0]
        if out.get("pendentes"):
            return "pediu " + ", ".join(c["nome"] for c in out["pendentes"]) + (f" · {modelo}" if modelo else "")
        return "redigiu a resposta" + (f" · {modelo}" if modelo else "")
    if no == "guardrail_ferramentas":
        pend = out.get("pendentes") or []
        neg = sum(1 for c in pend if c.get("negado"))
        cor = sum(1 for e in ev if e.get("acao") == "corrigido")
        partes = [f"{len(pend) - neg} liberada(s)"] + ([f"{neg} negada(s)"] if neg else []) + ([f"{cor} corrigida(s): cliente logado"] if cor else [])
        return ", ".join(partes)
    if no == "ferramentas":
        return "executou " + (", ".join(out.get("usadas") or []) or "nada (negadas)")
    if no == "guardrail_saida":
        return "; ".join(f"{e['acao']}: {ROTULOS.get(e['categoria'], e['categoria'])}" for e in ev) if ev else "resposta revisada: ok"
    return ""


def _status(no: str, out: dict) -> str:
    acoes = {e.get("acao") for e in out.get("eventos") or []}
    if no.startswith("memoria") and ((out.get("memoria_info") or {}).get("status") == "erro"
                                     or (out.get("memoria_info") or {}).get("gravado") is False):
        return "corrigido"   # Lakebase indisponível: o chat seguiu sem memória
    if no == "bloqueio" or out.get("permitido") is False or acoes & {"bloqueado", "negado"}:
        return "bloqueado"
    if acoes & {"mascarado", "corrigido", "sinalizado"}:
        return "corrigido"
    return "ok"


def _medido(no: str, fn):
    async def wrapper(estado: Estado, config: RunnableConfig) -> dict:
        t0 = time.perf_counter()
        args = (estado, config) if len(inspect.signature(fn).parameters) == 2 else (estado,)
        out = fn(*args)
        if inspect.isawaitable(out):
            out = await out
        out = dict(out or {})
        out["passos"] = [{"no": no, "status": _status(no, out), "detalhe": _detalhe(no, estado, out),
                          "ms": round((time.perf_counter() - t0) * 1000)}]
        return out
    wrapper.__name__ = no
    return wrapper


# ───────────────────────────── montagem do grafo ─────────────────────────────
def montar_grafo():
    g = StateGraph(Estado)
    g.add_node("memoria_carregar", _medido("memoria_carregar", memoria_carregar))
    g.add_node("memoria_gravar", _medido("memoria_gravar", memoria_gravar))
    g.add_node("guardrail_pii_entrada", _medido("guardrail_pii_entrada", guardrail_pii_entrada))
    g.add_node("guardrail_jailbreak", _medido("guardrail_jailbreak", guardrail_jailbreak))
    g.add_node("guardrail_juiz", _medido("guardrail_juiz", guardrail_juiz))
    g.add_node("bloqueio", _medido("bloqueio", bloqueio))
    for a in G.AGENTES:
        g.add_node(a, _medido(a, _no_agente(a)))
    g.add_node("guardrail_ferramentas", _medido("guardrail_ferramentas", guardrail_ferramentas))
    g.add_node("ferramentas", _medido("ferramentas", ferramentas))
    g.add_node("guardrail_saida", _medido("guardrail_saida", guardrail_saida))

    g.add_edge(START, "memoria_carregar")
    g.add_edge("memoria_carregar", "guardrail_pii_entrada")
    g.add_edge("guardrail_pii_entrada", "guardrail_jailbreak")
    g.add_conditional_edges("guardrail_jailbreak", rota_entrada, {"seguir": "guardrail_juiz", "bloqueio": "bloqueio"})
    g.add_conditional_edges("guardrail_juiz", rota_supervisor, {"bloqueio": "bloqueio", **{a: a for a in G.AGENTES}})
    for a in G.AGENTES:
        g.add_conditional_edges(a, rota_agente, {"guardrail_ferramentas": "guardrail_ferramentas", "guardrail_saida": "guardrail_saida"})
    g.add_edge("guardrail_ferramentas", "ferramentas")
    g.add_conditional_edges("ferramentas", rota_volta, {a: a for a in G.AGENTES})
    g.add_edge("guardrail_saida", "memoria_gravar")
    g.add_edge("memoria_gravar", END)
    g.add_edge("bloqueio", END)
    return g.compile()


TRECHOS_PROMPT = _trechos_do_prompt()
GRAFO = montar_grafo()


def mermaid() -> str:
    return GRAFO.get_graph().draw_mermaid()


ROTULOS_NOS = {"__start__": "▶ mensagem do cliente", "__end__": "✔ resposta",
               "memoria_carregar": "🧠 Memória: lembrar<br/><small>conversas anteriores · Lakebase</small>",
               "memoria_gravar": "🧠 Memória: gravar<br/><small>loja.conversas · Lakebase</small>",
               "guardrail_pii_entrada": "🛡️ Dados sensíveis<br/><small>mascara CPF, cartão, telefone</small>",
               "guardrail_jailbreak": "🛡️ Regras de segurança<br/><small>jailbreak · dados de outra conta</small>",
               "guardrail_juiz": "⚖️ Juiz + supervisor<br/><small>LLM classifica e escolhe o agente</small>",
               "bloqueio": "⛔ Bloqueio<br/><small>resposta padrão</small>",
               "vendas": "🛍️ Agente de Vendas", "pos_venda": "📦 Agente de Pós-venda", "analista": "📊 Agente Analista",
               "guardrail_ferramentas": "🛡️ Permissões das ferramentas<br/><small>só as do agente · cliente logado</small>",
               "ferramentas": "🔧 Ferramentas<br/><small>MCP Detetive · Genie MCP · Calendar MCP</small>",
               "guardrail_saida": "🛡️ Revisão da resposta<br/><small>PII · vazamento · fundamentação</small>"}


def mermaid_bonito() -> str:
    """Mermaid gerado a partir do PRÓPRIO grafo compilado (nós e arestas reais), com rótulos amigáveis."""
    g = GRAFO.get_graph()
    linhas = ["flowchart TD"]
    for no in g.nodes:
        rot = ROTULOS_NOS.get(no, no)
        forma = f'(["{rot}"])' if no.startswith("__") else f'["{rot}"]'
        linhas.append(f"  {no}{forma}")
    for e in g.edges:
        seta = "-.->" if e.conditional else "-->"
        linhas.append(f"  {e.source} {seta} {e.target}")
    linhas += ["  classDef guard fill:#FFF0EC,stroke:#FF3621,color:#0B2026",
               "  classDef agente fill:#EAF4FB,stroke:#2272B4,color:#0B2026",
               "  classDef fim fill:#0B2026,stroke:#0B2026,color:#fff",
               "  classDef memoria fill:#EEF7EE,stroke:#00A972,color:#0B2026",
               "  class memoria_carregar,memoria_gravar memoria",
               "  class guardrail_pii_entrada,guardrail_jailbreak,guardrail_juiz,guardrail_ferramentas,guardrail_saida,bloqueio guard",
               "  class vendas,pos_venda,analista,ferramentas agente", "  class __start__,__end__ fim"]
    return "\n".join(linhas)


def _ordenar_produtos(produtos: dict, resposta: str) -> list[dict]:
    """Cartões do chat: primeiro os produtos citados na resposta (na ordem em que aparecem), depois os demais."""
    txt = resposta.lower()
    citados = sorted((p for p in produtos.values() if (p.get("nome") or "").lower() in txt),
                     key=lambda p: txt.find(p["nome"].lower()))
    return citados + [p for p in produtos.values() if p not in citados]


async def executar(mensagens: list[dict], imagem: str | None, cliente_id: str | None, token_usuario: str | None = None,
                   conversa_id: str | None = None) -> dict:
    async with Client(mcp) as cliente:
        tools = ferramentas_openai((await cliente.list_tools()).tools) + FERRAMENTAS_LOCAIS
        final = await GRAFO.ainvoke(
            {"mensagens": mensagens, "imagem": imagem, "cliente_id": cliente_id, "conversa_id": conversa_id,
             "eventos": [], "trilha": [], "passos": [], "usadas": []},
            config={"configurable": {"mcp": cliente, "ferramentas": tools, "token_usuario": token_usuario}, "recursion_limit": 40})
    agente = final.get("agente") if final.get("agente") in G.AGENTES else "vendas"
    return {"resposta": final.get("resposta") or "(sem resposta)", "ferramentas": final.get("usadas") or [],
            "produtos": _ordenar_produtos(final.get("produtos") or {}, final.get("resposta") or "")[:12], "laudo": final.get("laudo"),
            "genie": final.get("genie"), "modelos": final.get("modelos") or [], "bloqueado": bool(final.get("bloqueado")),
            "agente": {"id": agente, **G.AGENTES[agente]}, "guardrail": final.get("eventos") or [],
            "trilha": final.get("trilha") or [], "passos": final.get("passos") or [],
            "agenda": final.get("agenda"), "memoria": final.get("memoria_info") or {}}
