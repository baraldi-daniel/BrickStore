"""
🔎 MCP "Detetive de Produtos" — servidor MCP (Model Context Protocol) da loja.

Ideia: BUSCA VISUAL. O cliente mostra a FOTO DE UM PRODUTO (um tênis, uma poltrona, um headset...) e o
Detetive identifica o que é (tipo, cor, material, estilo, detalhes) e encontra no catálogo os produtos parecidos.

Pipeline de `investigar_imagem`:

    foto do produto ──► Llama 4 Maverick (visão) ──► LAUDO (JSON: tipo, cor, material, estilo, atributos)
                                                       │
                                                       ▼
                         Vector Search (produtos_index, filtro por tipo) + reranking por estilo/cor
                                                       │
                                                       ▼
                                     produtos parecidos + compatibilidade + pistas

O mesmo servidor é usado de duas formas:
  1. pelo agente do chat do App, via cliente MCP **em memória** (protocolo MCP de verdade);
  2. por qualquer cliente MCP externo (AI Playground, Claude, Cursor...) em  <url-do-app>/mcp.
"""
import json
import logging
import re
import uuid

from mcp.server.mcpserver import MCPServer

from . import servicos as S
from . import lakebase
from .agenda import previsao_entrega
from .catalogo import CATALOGO

log = logging.getLogger("varejo")

mcp = MCPServer(
    name="brickstore-detetive-de-produtos",
    title=f"Detetive de Produtos · {S.MARCA}",
    instructions=(
        f"Ferramentas da loja {S.MARCA} para encontrar produtos pela FOTO de um produto (busca visual) e por texto, "
        "e para recomendar 'quem comprou também comprou' e kits 'compre junto'. Use investigar_imagem quando o usuário "
        "mostrar a foto de um produto; buscar_produtos para pedidos em texto; quem_comprou_tambem_comprou, compre_junto e "
        "ficha_produto para um produto específico. Imagens: caminho no Volume de mídia da loja (/Volumes/<catalog>/<schema>/midia/...), data URI ou base64."),
    version="1.0.0",
)

PROMPT_LAUDO = """Você é o DETETIVE DE PRODUTOS da loja {marca} e faz BUSCA VISUAL: a foto mostra um produto.
Identifique o produto em destaque (se houver vários objetos, escolha o principal) e devolva APENAS um JSON válido
(sem texto fora do JSON), em português:
{{
  "tipo": "UM destes tipos: {tipos}",
  "descricao": "ex.: tênis de corrida azul com solado branco e detalhes verde-limão",
  "cor": "cor principal",
  "cores_hex": ["2 a 4 cores do produto em hexadecimal, ex. #d9d4cc"],
  "material": "material principal",
  "estilo_provavel": "UM destes ids: {estilos}",
  "atributos": ["até 5 detalhes visíveis: formato, acabamento, padrão, uso"],
  "produto_reconhecido": "marca/modelo se for um produto real claramente identificável, senão null",
  "veredito": "uma frase curta e natural, como de um vendedor, dizendo o que é o produto e para que serve (sem prefixos nem bordões)",
  "consulta_busca": "uma frase rica descrevendo o produto para buscar similares no catálogo"
}}"""


# ───────────────────────────── utilidades ─────────────────────────────
def _carregar_imagem(imagem: str) -> bytes:
    import base64
    import posixpath
    imagem = (imagem or "").strip()
    if imagem.startswith("/Volumes/"):
        # só o Volume de mídia do lab (a service principal do App não deve ler outros Volumes a pedido de um cliente MCP)
        caminho = posixpath.normpath(imagem)
        if not caminho.startswith(S.VOL_MIDIA.rstrip("/") + "/"):
            raise ValueError(f"imagem fora do Volume de mídia da loja ({S.VOL_MIDIA})")
        return S.download(caminho)
    if imagem.startswith("data:"):
        return base64.b64decode(imagem.split(",", 1)[1])
    if imagem.startswith(("http://", "https://")):
        raise ValueError("URLs externas não são aceitas: envie a foto para o Volume de mídia ou mande em data URI/base64")
    return base64.b64decode(imagem)


def salvar_imagem(dados: bytes) -> str:
    """Normaliza e grava a imagem no Volume (governança UC). Devolve o caminho."""
    caminho = f"{S.VOL_MIDIA}/imagens_busca/{uuid.uuid4().hex}.jpg"
    S.upload(caminho, S.normalizar_imagem(dados))
    return caminho


def laudo_da_imagem(dados: bytes) -> dict:
    jpeg = S.normalizar_imagem(dados)
    estilos = ", ".join(e["estilo_id"] for e in CATALOGO.estilos)
    tipos = ", ".join(sorted(CATALOGO.icone_por_tipo))
    resp = S.chat([{"role": "user", "content": [
        {"type": "text", "text": PROMPT_LAUDO.format(marca=S.MARCA, estilos=estilos, tipos=tipos)},
        {"type": "image_url", "image_url": {"url": S.data_uri(jpeg)}}]}], max_tokens=600, temperature=0.1)
    laudo = S.extrair_json(resp.choices[0].message.content or "")
    if not laudo:
        laudo = {"consulta_busca": resp.choices[0].message.content or "", "veredito": ""}
    laudo["veredito"] = re.sub(r"^\s*elementar[^:]*:\s*", "", str(laudo.get("veredito") or ""), flags=re.I).strip()
    laudo["veredito"] = laudo["veredito"][:1].upper() + laudo["veredito"][1:]
    if laudo.get("estilo_provavel") not in {e["estilo_id"] for e in CATALOGO.estilos}:
        laudo["estilo_provavel"] = None
    e = CATALOGO.estilo(laudo.get("estilo_provavel"))
    laudo["estilo_nome"] = e["nome"] if e else None
    if laudo.get("tipo") not in CATALOGO.icone_por_tipo:
        laudo["tipo"] = None
    laudo["atributos"] = [str(a) for a in (laudo.get("atributos") or [])][:5]
    return laudo


def _palavras(txt) -> set:
    return set(re.findall(r"[a-zà-ú]{4,}", str(txt or "").lower()))


def _pistas(laudo: dict, item: dict, p: dict) -> list[str]:
    pistas = []
    if laudo.get("estilo_provavel") and laudo["estilo_provavel"] == p.get("estilo_id"):
        pistas.append(f"Mesmo estilo: {laudo.get('estilo_nome')}")
    if _palavras(item.get("cor")) & _palavras(f"{p.get('cor')} {p.get('nome')}"):
        pistas.append(f"Cor parecida: {p.get('cor')}")
    mat = _palavras(item.get("material")) & _palavras(f"{p.get('material')} {p.get('nome')}")
    if mat:
        pistas.append(f"Material: {p.get('material')}")
    if not pistas:
        pistas.append(f"{p.get('tipo')} parecido com o da foto")
    return pistas


def _buscar_item(laudo: dict, item: dict, n: int) -> list[dict]:
    tipo = item.get("tipo") if item.get("tipo") in CATALOGO.icone_por_tipo else None
    consulta = (f"{item.get('consulta_busca') or item.get('descricao') or ''} {item.get('tipo') or ''} {item.get('cor') or ''} "
                f"{item.get('material') or ''} estilo {laudo.get('estilo_nome') or ''}")
    try:
        hits = S.vs_query(S.IDX_PRODUTOS, ["produto_id"], consulta, 12, {"tipo": tipo} if tipo else None)
    except Exception:
        hits = S.vs_query(S.IDX_PRODUTOS, ["produto_id"], consulta, 12)
    ranq = []
    for h in hits:
        p = CATALOGO.produtos.get(h["produto_id"])
        if not p:
            continue
        sc = float(h.get("score") or 0)
        if laudo.get("estilo_provavel") == p["estilo_id"]:
            sc += 0.10
        if _palavras(item.get("cor")) & _palavras(p.get("cor")):
            sc += 0.05
        ranq.append((sc, p))
    ranq.sort(key=lambda x: x[0], reverse=True)
    if not ranq:
        return []
    topo = ranq[0][0] or 1
    return [{**CATALOGO.resumo(p), "compatibilidade": min(99, round(100 * sc / topo * 0.97)),
             "pistas": _pistas(laudo, item, p)} for sc, p in ranq[:n]]


def investigar(dados: bytes, quantidade: int = 6, progresso=lambda passo: None) -> dict:
    """Busca visual: laudo do produto da foto + produtos parecidos do catálogo.
    `progresso(n)`: 1 modelo de visão, 2 Vector Search + ranking, 3 fim (o 0, envio da foto, é marcado por quem chama)."""
    progresso(1)
    laudo = laudo_da_imagem(dados)
    progresso(2)
    produtos = _buscar_item(laudo, laudo, quantidade)
    progresso(3)
    return {"laudo": laudo, "produtos": produtos}


# ───────────────────────────── ferramentas MCP ─────────────────────────────
import functools


def _compacto(obj):
    """Respostas enxutas para o LLM: remove campos vazios (None) em qualquer nível."""
    if isinstance(obj, dict):
        return {k: _compacto(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_compacto(v) for v in obj]
    return obj


def ferramenta(**kw):
    """@mcp.tool + resposta compacta."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            return _compacto(fn(*a, **k))
        return mcp.tool(**kw)(wrapper)
    return deco


@ferramenta(title="Investigar imagem",
          description="BUSCA VISUAL: use quando o cliente mandar a FOTO de um produto ('tem algo parecido com isto?', "
                      "'quero um desses'). Recebe a IMAGEM (caminho /Volumes/..., data URI ou base64) e, em UMA chamada, devolve "
                      "o laudo do produto (tipo, cor, material, estilo, atributos) e os produtos PARECIDOS do catálogo, com "
                      "compatibilidade e pistas. Normalmente dispensa outras buscas.")
def investigar_imagem(imagem: str, quantidade: int = 6) -> dict:
    return investigar(_carregar_imagem(imagem), max(1, min(quantidade, 10)))


@ferramenta(title="Analisar imagem (só o laudo)",
          description="Só o laudo da FOTO de um produto (tipo, cor, material, estilo, atributos), SEM buscar no catálogo. Use "
                      "apenas quando o usuário quiser só a análise; para achar produtos parecidos use investigar_imagem.")
def analisar_imagem(imagem: str) -> dict:
    return laudo_da_imagem(_carregar_imagem(imagem))


@ferramenta(title="Buscar produtos",
          description="Busca semântica (Vector Search) no catálogo por descrição, estilo, ambiente ou uso. Ex.: 'luminária de "
                      "piso para sala escandinava', 'tênis leve para correr 10 km'. 'departamento' e 'preco_max' são opcionais.")
def buscar_produtos(consulta: str, departamento: str | None = None, preco_max: float | None = None, quantidade: int = 8) -> dict:
    filtros = {"departamento": departamento} if departamento else None
    hits = S.vs_query(S.IDX_PRODUTOS, ["produto_id"], consulta, 40 if preco_max else max(24, min(quantidade, 16) * 3), filtros)
    out, nomes = [], set()
    termos = {t for t in _palavras(consulta) if len(t) > 3}
    for h in hits:
        p = CATALOGO.produtos.get(h["produto_id"])
        if p and p["nome"] not in nomes and (not preco_max or (p.get("preco_promocional") or p["preco"]) <= preco_max):
            nomes.add(p["nome"])  # variações com o mesmo nome aparecem uma vez só
            texto = _palavras(f"{p['nome']} {p.get('cor', '')} {p.get('estilo_id', '')} {p.get('tipo', '')}")
            bonus = 0.04 * len(termos & texto)        # "sofá cinza escandinavo" → sobe o que é cinza e escandinavo
            out.append({**CATALOGO.resumo(p), "score": round(float(h.get("score") or 0) + bonus, 3)})
    out.sort(key=lambda x: -x["score"])
    return {"consulta": consulta, "produtos": out[:quantidade]}


@ferramenta(title="Quem comprou também comprou",
          description="Recomendações por cesta de pedido (market basket): para um produto (nome ou produto_id), devolve o que "
                      "mais aparece no mesmo pedido, com confiança (% dos pedidos com A que também têm B) e lift (vezes acima do acaso).")
def quem_comprou_tambem_comprou(produto: str, quantidade: int = 8) -> dict:
    p = CATALOGO.achar(produto)
    if not p:
        return {"erro": f"Produto '{produto}' não encontrado."}
    recs = CATALOGO.tambem_compraram(p["produto_id"], max(1, min(quantidade, 20)))
    return {"produto_base": CATALOGO.resumo(p),
            "produtos": [{**r, "leitura": f"{round(r['confianca'] * 100)}% dos pedidos com o item também têm este · lift {r['lift']}"}
                         for r in recs]}


@ferramenta(title="Compre junto",
          description="Monta um kit 'compre junto' para um produto (nome ou produto_id): o produto + os complementos mais "
                      "comprados no mesmo pedido, com o total e o total com desconto do kit.")
def compre_junto(produto: str) -> dict:
    p = CATALOGO.achar(produto)
    if not p:
        return {"erro": f"Produto '{produto}' não encontrado."}
    return {"produto_base": CATALOGO.resumo(p), **CATALOGO.compre_junto(p["produto_id"])}


@ferramenta(title="Ficha do produto",
          description="Ficha completa de um produto (nome ou produto_id): preço, parcelamento, especificações, tamanhos, "
                      "estilo, descrição e os 5 produtos mais comprados junto.")
def ficha_produto(produto: str) -> dict:
    p = CATALOGO.achar(produto)
    if not p:
        return {"erro": f"Produto '{produto}' não encontrado."}
    d = CATALOGO.detalhe(p["produto_id"])
    campos = ("produto_id", "nome", "marca_produto", "vendedor", "vendedor_reputacao", "frete_gratis", "departamento", "tipo", "estilo_id", "cor", "material", "preco",
              "preco_promocional", "parcelas_sem_juros", "avaliacao", "n_avaliacoes", "estoque", "tamanhos",
              "especificacoes", "descricao", "descricao_visual")
    return {**{k: d.get(k) for k in campos},
            "tambem_compraram": [{"nome": r["nome"], "produto_id": r["produto_id"], "confianca": r["confianca"], "lift": r["lift"]}
                                 for r in d["tambem_compraram"][:5]]}


@ferramenta(title="Recomendar para cliente (ML)",
          description="Recomendações personalizadas de um cliente (cliente_id, ex.: C000123) geradas pelo modelo híbrido: "
                      "candidatos de regras de associação + SVD, ordenados por um ranking de Gradient Boosting, com o motivo.")
def recomendar_para_cliente(cliente_id: str, quantidade: int = 8) -> dict:
    return {"cliente_id": cliente_id, "produtos": CATALOGO.recomendados_ml(cliente_id, max(1, min(quantidade, 12)))}


@ferramenta(title="Pedidos do cliente",
          description="Lista os pedidos de um cliente (cliente_id, ex.: C000123) com status (Entregue, Em transporte, "
                      "Cancelado, Devolvido), data, valor e itens. Use para 'meu pedido', 'o que está em transporte', "
                      "'quando chega', 'o que comprei'. 'status' é opcional para filtrar.")
def pedidos_do_cliente(cliente_id: str, status: str | None = None, quantidade: int = 10) -> dict:
    filtro = "AND p.status = :s" if status else ""
    params = {"c": cliente_id, **({"s": status} if status else {})}
    consulta = """SELECT p.pedido_id, CAST(p.data_pedido AS DATE) AS data, p.status, p.valor_total, p.frete, p.canal,
                         i.produto_id, i.quantidade, i.preco_unitario
                  FROM {ped} p JOIN {itens} i USING (pedido_id)
                  WHERE p.cliente_id = :c {filtro} ORDER BY p.data_pedido DESC LIMIT 80"""
    try:   # histórico (Delta) + pedidos novos do App (Lakebase, ao vivo) pelas views do UC
        linhas = S.sql(consulta.format(ped=lakebase.tabela("pedidos"), itens=lakebase.tabela("itens_pedido"), filtro=filtro), params)
    except Exception as e:
        if not lakebase.views_ativas():
            raise
        log.warning("views Lakebase indisponíveis (%s); lendo só o Delta", str(e)[:120])
        linhas = S.sql(consulta.format(ped=S.fq("pedidos"), itens=S.fq("itens_pedido"), filtro=filtro), params)
    pedidos = {}
    for l in linhas:
        ped = pedidos.setdefault(l["pedido_id"], {k: l[k] for k in ("pedido_id", "data", "status", "valor_total", "frete", "canal")} | {
            "itens": [], "previsao_entrega": previsao_entrega(l["pedido_id"], l["data"], l["status"]) if l["status"] == "Em transporte" else None})
        p = CATALOGO.produtos.get(l["produto_id"])
        ped["itens"].append({"produto_id": l["produto_id"], "nome": p["nome"] if p else l["produto_id"],
                             "quantidade": l["quantidade"], "preco_unitario": l["preco_unitario"]})
    lista = list(pedidos.values())[:max(1, min(quantidade, 25))]
    resumo = {}
    for ped in pedidos.values():
        resumo[ped["status"]] = resumo.get(ped["status"], 0) + 1
    return {"cliente_id": cliente_id, "total_pedidos": len(pedidos), "por_status": resumo, "pedidos": lista}


@ferramenta(title="Abrir solicitação de pós-venda",
          description="Abre uma solicitação de TROCA, DEVOLUÇÃO, GARANTIA ou RECLAMAÇÃO para um pedido do cliente e devolve o "
                      "protocolo. Grava no Lakebase (OLTP), visível no Lakehouse na hora. tipo: Troca | Devolução | Garantia | Reclamação.")
def abrir_solicitacao(cliente_id: str, tipo: str, pedido_id: str, motivo: str, produto_id: str | None = None) -> dict:
    import time as _t
    tipo = tipo if tipo in ("Troca", "Devolução", "Garantia", "Reclamação") else "Reclamação"
    sql_ped = "SELECT pedido_id, status, CAST(data_pedido AS DATE) AS data FROM {t} WHERE pedido_id = :p AND cliente_id = :c"
    try:
        ped = S.sql(sql_ped.format(t=lakebase.tabela("pedidos")), {"p": pedido_id, "c": cliente_id})
    except Exception:
        ped = S.sql(sql_ped.format(t=S.fq("pedidos")), {"p": pedido_id, "c": cliente_id})
    if not ped:
        return {"erro": f"Pedido {pedido_id} não encontrado para o cliente {cliente_id}."}
    protocolo = "SAC" + _t.strftime("%y%m%d%H%M%S")
    prazo = {"Troca": "até 10 dias úteis", "Devolução": "estorno em até 2 faturas ou 5 dias úteis no PIX",
             "Garantia": "análise técnica em até 30 dias", "Reclamação": "resposta em até 2 dias úteis"}[tipo]
    gravado_em = "lakehouse"
    if lakebase.ativo():
        try:
            lakebase.gravar_solicitacao(protocolo, cliente_id, pedido_id, produto_id, tipo, motivo, "Aberta", prazo)
            gravado_em = "lakebase"
        except Exception as e:
            log.warning("Lakebase indisponível (%s); gravando a solicitação no Delta", str(e)[:120])
    if gravado_em == "lakehouse":
        S.sql(f"""INSERT INTO {S.fq('solicitacoes_atendimento')} (protocolo, cliente_id, pedido_id, produto_id, tipo, motivo, status, prazo, aberto_em)
                  VALUES (:pr, :c, :p, :prod, :t, :m, 'Aberta', :pz, current_timestamp())""",
              {"pr": protocolo, "c": cliente_id, "p": pedido_id, "prod": produto_id, "t": tipo, "m": motivo[:500], "pz": prazo})
    return {"protocolo": protocolo, "tipo": tipo, "pedido": ped[0], "status": "Aberta", "prazo": prazo, "gravado_em": gravado_em}


def ferramentas_openai(tools) -> list[dict]:
    """Converte a lista de ferramentas MCP (tools/list) para o formato de *tool calling* do LLM."""
    out = []
    for t in tools:
        schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}
        schema = {k: v for k, v in schema.items() if k != "title"}
        out.append({"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": schema}})
    return out


def texto_resultado(res) -> dict:
    """Extrai o JSON de um CallToolResult do MCP."""
    if getattr(res, "structured_content", None):
        return res.structured_content
    txt = "\n".join(getattr(c, "text", "") for c in (res.content or []) if getattr(c, "text", ""))
    try:
        return json.loads(txt)
    except Exception:
        return {"resultado": txt, "erro": bool(getattr(res, "is_error", False))}
