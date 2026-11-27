"""
🎛️ Estúdio — a aba de controle do App.

  • Cadastro de produto A PARTIR DA FICHA TÉCNICA DO FORNECEDOR (PDF): ai_parse_document extrai texto,
    TABELAS (especificações, medidas, grade, preços) e IMAGENS (foto do produto); o LLM estrutura a ficha;
    a foto é recortada da página pela bounding box; você revisa e publica
  • Editar / remover produtos e trocar a foto (grava direto na tabela Delta `produtos`)
  • Enviar PDFs para a central de ajuda → `ai_parse_document` → chunks → `ajuda_index`
  • Sincronizar índices de Vector Search e recalcular "quem comprou também comprou"
"""
import io
import json
import logging
import re
import threading
import time
from datetime import date

from . import servicos as S


def _T(nome):
    """Pedidos/itens para LEITURA: view Delta + Lakebase (pedidos novos do App) quando disponível."""
    from .lakebase import tabela
    return tabela(nome)
from .catalogo import CATALOGO
from .documentos import chunkar_documento, tabela_html_para_texto
from .recomendacao_sql import sql_regras

log = logging.getLogger("varejo")

CAMPOS_EDITAVEIS = ["nome", "marca_produto", "departamento", "categoria", "tipo", "icone", "estilo_id", "cor", "cor_hex",
                    "material", "descricao", "descricao_visual", "especificacoes", "tamanhos", "preco", "preco_promocional",
                    "parcelas_sem_juros", "avaliacao", "n_avaliacoes", "estoque", "lancamento"]
INTS = {"parcelas_sem_juros", "n_avaliacoes", "estoque"}
FLOATS = {"preco", "preco_promocional", "avaliacao"}
BOOLS = {"lancamento"}

_sync_pendente = {"produtos": False, "ajuda": False}


def _sync_atrasado(qual: str, idx: str, atraso: int = 4):
    """Agrupa várias edições seguidas numa única sincronização do índice."""
    if _sync_pendente[qual]:
        return
    _sync_pendente[qual] = True

    def run():
        time.sleep(atraso)
        _sync_pendente[qual] = False
        log.info("sync %s: %s", idx, S.vs_sync(idx))
    threading.Thread(target=run, daemon=True).start()


def _normalizar(dados: dict) -> dict:
    out = {}
    for k in CAMPOS_EDITAVEIS:
        if k not in dados:
            continue
        v = dados[k]
        if v in ("", None):
            out[k] = None
        elif k in INTS:
            out[k] = int(float(v))
        elif k in FLOATS:
            out[k] = float(str(v).replace("R$", "").replace(".", "").replace(",", ".")) if isinstance(v, str) and "," in v else float(v)
        elif k in BOOLS:
            out[k] = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "sim", "on")
        else:
            out[k] = str(v).strip()
    if out.get("tipo") and not out.get("icone"):
        out["icone"] = CATALOGO.icone_por_tipo.get(out["tipo"], "frasco")
    return out


def _descricao_visual(p: dict) -> str:
    e = CATALOGO.estilo(p.get("estilo_id")) or {}
    return (f"Estilo: {e.get('nome', p.get('estilo_id') or '')}. Cores: {p.get('cor') or ''}. Material: {p.get('material') or ''}. "
            f"Ocasião/ambiente: {e.get('ocasiao', '')}.")


def _texto_busca(p: dict) -> str:
    return (f"{p.get('nome')}. {p.get('tipo')} · {p.get('departamento')}. {p.get('descricao') or ''} "
            f"{p.get('descricao_visual') or ''}").strip()


def criar_produto(dados: dict) -> dict:
    p = _normalizar(dados)
    if not p.get("nome"):
        raise ValueError("Informe o nome do produto.")
    p.setdefault("departamento", "Casa & Decoração")
    p["descricao_visual"] = p.get("descricao_visual") or _descricao_visual(p)
    p["produto_id"] = "SKU9" + time.strftime("%H%M%S")[-5:]
    p["origem"] = "estudio"
    p["data_cadastro"] = date.today().isoformat()
    p["popularidade"] = 5.0
    p.setdefault("avaliacao", 5.0)
    p.setdefault("n_avaliacoes", 0)
    p.setdefault("estoque", 50)
    p.setdefault("lancamento", True)
    p.setdefault("vendedor", f"Loja Oficial {p.get('marca_produto') or S.MARCA}")
    p.setdefault("vendedor_reputacao", 5.0)
    p["frete_gratis"] = float(p.get("preco_promocional") or p.get("preco") or 0) >= 99
    p["texto_busca"] = _texto_busca(p)
    cols = list(p.keys())
    S.sql(f"INSERT INTO {S.fq('produtos')} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
          .replace(":data_cadastro", "CAST(:data_cadastro AS DATE)"), p)
    CATALOGO.produtos[p["produto_id"]] = {"imagem_path": None, **p}
    CATALOGO.por_nome[p["nome"].lower()] = p["produto_id"]
    _sync_atrasado("produtos", S.IDX_PRODUTOS)
    return CATALOGO.produtos[p["produto_id"]]


def atualizar_produto(produto_id: str, dados: dict) -> dict:
    atual = CATALOGO.produtos.get(produto_id)
    if not atual:
        raise KeyError(produto_id)
    p = _normalizar(dados)
    novo = {**atual, **p}
    p["texto_busca"] = _texto_busca(novo)
    sets = ", ".join(f"{c} = :{c}" for c in p)
    S.sql(f"UPDATE {S.fq('produtos')} SET {sets} WHERE produto_id = :pid", {**p, "pid": produto_id})
    CATALOGO.produtos[produto_id] = novo
    _sync_atrasado("produtos", S.IDX_PRODUTOS)
    return novo


def remover_produto(produto_id: str):
    S.sql(f"DELETE FROM {S.fq('produtos')} WHERE produto_id = :pid", {"pid": produto_id})
    p = CATALOGO.produtos.pop(produto_id, None)
    if p:
        CATALOGO.por_nome.pop(p["nome"].lower(), None)
    _sync_atrasado("produtos", S.IDX_PRODUTOS)


def salvar_imagem_produto(produto_id: str, dados: bytes) -> str:
    caminho = f"{S.VOL_MIDIA}/produtos/{produto_id}.jpg"
    S.upload(caminho, S.normalizar_imagem(dados, 900))
    S.sql(f"UPDATE {S.fq('produtos')} SET imagem_path = :p WHERE produto_id = :pid", {"p": caminho, "pid": produto_id})
    if produto_id in CATALOGO.produtos:
        CATALOGO.produtos[produto_id]["imagem_path"] = caminho
    return caminho


# ───────────────────────── ficha técnica do fornecedor (PDF) ─────────────────────────
PROMPT_FICHA = """Você recebeu o conteúdo de uma FICHA TÉCNICA DE FORNECEDOR extraída por ai_parse_document (texto,
tabelas convertidas para 'coluna: valor' e descrições das imagens). Preencha o cadastro do produto no e-commerce.
Responda APENAS com JSON válido, em português, com estas chaves (null quando não houver a informação):
{{"nome": "nome comercial completo, ex.: 'Sofá Retrátil 3 Lugares Linho Cinza — Nórdica Home'", "marca_produto": str,
  "departamento": "UM destes: {departamentos}", "tipo": "UM destes: {tipos}", "estilo_id": "UM destes: {estilos}",
  "cor": str, "cor_hex": "#rrggbb", "material": str, "descricao": "2 a 3 frases de vitrine, persuasivas",
  "especificacoes": "pares 'chave: valor; chave: valor' com as especificações e medidas", "tamanhos": str ou null,
  "preco": float, "preco_promocional": float ou null, "parcelas_sem_juros": int, "estoque": int ou null}}

CONTEÚDO DA FICHA:
{conteudo}"""


def _texto_elementos(elementos: list) -> str:
    partes = []
    for e in elementos:
        tipo, c = e.get("type"), (e.get("content") or "").strip()
        if tipo == "table":
            partes.append("[TABELA]\n" + tabela_html_para_texto(c))
        elif tipo == "figure":
            partes.append(f"[IMAGEM] {c} — {e.get('description') or ''}".strip())
        elif tipo in ("title", "section_header"):
            partes.append(f"## {c}")
        elif c:
            partes.append(c)
    return "\n".join(partes)


def _recortar_figuras(parsed: dict, chave: str) -> list[dict]:
    """Recorta cada figura (bbox) da imagem da página que o ai_parse_document gravou no Volume."""
    from PIL import Image
    paginas = {p["id"]: p.get("image_uri") for p in parsed.get("document", {}).get("pages", [])}
    cache, out = {}, []
    figs = [e for e in parsed.get("document", {}).get("elements", []) if e.get("type") == "figure"]
    for n, e in enumerate(figs):
        bb = (e.get("bbox") or [{}])[0]
        uri = paginas.get(bb.get("page_id"))
        if not uri or not bb.get("coord"):
            continue
        if uri not in cache:
            cache[uri] = Image.open(io.BytesIO(S.download(uri))).convert("RGB")
        recorte = cache[uri].crop(tuple(bb["coord"]))
        buf = io.BytesIO()
        recorte.save(buf, "JPEG", quality=90)
        caminho = f"{S.VOL_MIDIA}/fichas/{chave}/figura_{n + 1}.jpg"
        S.upload(caminho, buf.getvalue())
        out.append({"caminho": caminho, "pagina": bb.get("page_id", 0) + 1, "largura": recorte.width, "altura": recorte.height,
                    "retrato": recorte.height > recorte.width, "descricao": e.get("description"), "texto": e.get("content")})
    return out


def processar_ficha(nome_arquivo: str, dados: bytes | None = None, caminho_existente: str | None = None,
                    progresso=lambda passo: None) -> dict:
    """PDF da ficha técnica → ai_parse_document (texto + tabelas + imagens) → cadastro estruturado pelo LLM → rascunho.
    `progresso(n)` é chamado no início de cada etapa REAL (0 envio, 1 ai_parse_document, 2 figuras, 3 LLM, 4 fim)."""
    chave = "ft" + time.strftime("%y%m%d%H%M%S")
    progresso(0)
    if caminho_existente:
        caminho = caminho_existente
    else:
        nome = re.sub(r"[^A-Za-z0-9_.-]+", "_", nome_arquivo)
        if not nome.lower().endswith(".pdf"):
            raise ValueError("Envie um arquivo .pdf")
        caminho = f"{S.VOL_MIDIA}/fichas/{chave}/{nome}"
        S.upload(caminho, dados)
    t0 = time.time()
    progresso(1)
    linhas = S.sql(f"""SELECT to_json(ai_parse_document(content, map(
                          'version', '2.0', 'imageOutputPath', :img, 'descriptionElementTypes', '*'))) AS j
                       FROM read_files(:p, format => 'binaryFile')""",
                   {"p": caminho, "img": f"{S.VOL_MIDIA}/fichas/{chave}/paginas/"}, timeout_s=300)
    parsed = json.loads(linhas[0]["j"])
    seg = round(time.time() - t0, 1)
    elementos = parsed.get("document", {}).get("elements", [])
    progresso(2)
    figuras = _recortar_figuras(parsed, chave)
    conteudo = _texto_elementos(elementos)
    progresso(3)
    r = S.chat([{"role": "user", "content": PROMPT_FICHA.format(
        departamentos=", ".join(d["nome"] for d in CATALOGO.departamentos()), tipos=", ".join(sorted(CATALOGO.icone_por_tipo)),
        estilos=", ".join(e["estilo_id"] for e in CATALOGO.estilos), conteudo=conteudo[:14000])}], max_tokens=1000, temperature=0)
    ficha = S.extrair_json(r.choices[0].message.content or "")
    ficha["icone"] = CATALOGO.icone_por_tipo.get(ficha.get("tipo"), "frasco")
    ficha["lancamento"] = True
    ficha["descricao_visual"] = _descricao_visual(ficha) + (
        " Fotos da ficha: " + " ".join(f["descricao"] for f in figuras[:2] if f.get("descricao")) if figuras else "")
    tipos = {}
    for e in elementos:
        tipos[e.get("type")] = tipos.get(e.get("type"), 0) + 1
    S.sql(f"INSERT INTO {S.fq('fichas_parseadas')} SELECT :c, :a, :p, parse_json(:j), NULL, current_timestamp()",
          {"c": chave, "a": nome_arquivo, "p": caminho, "j": linhas[0]["j"]})
    foto = figuras[0]["caminho"] if figuras else None  # a 1ª figura da ficha é a foto principal
    progresso(4)
    return {"chave": chave, "arquivo": nome_arquivo, "caminho": caminho, "segundos_parse": seg, "elementos": tipos,
            "tabelas_html": [e.get("content") for e in elementos if e.get("type") == "table"], "figuras": figuras,
            "imagem_path": foto, "ficha": ficha, "texto_extraido": conteudo[:6000]}


def publicar_ficha(chave: str, ficha: dict, imagem_path: str | None) -> dict:
    p = criar_produto(ficha)
    if imagem_path and imagem_path.startswith(S.VOL_MIDIA):
        destino = f"{S.VOL_MIDIA}/produtos/{p['produto_id']}.jpg"
        S.upload(destino, S.download(imagem_path))
        S.sql(f"UPDATE {S.fq('produtos')} SET imagem_path = :i WHERE produto_id = :pid", {"i": destino, "pid": p["produto_id"]})
        CATALOGO.produtos[p["produto_id"]]["imagem_path"] = destino
    S.sql(f"UPDATE {S.fq('fichas_parseadas')} SET produto_id = :pid WHERE chave = :k", {"pid": p["produto_id"], "k": chave})
    return CATALOGO.produtos[p["produto_id"]]


def fichas_exemplo() -> list[dict]:
    try:
        itens = list(S.ws().files.list_directory_contents(f"{S.VOL_MIDIA}/fichas_exemplo"))
        return [{"nome": i.name, "caminho": i.path} for i in itens if (i.name or "").endswith(".pdf")]
    except Exception:
        return []


# ───────────────────────────── documentos de ajuda (PDF) ─────────────────────────────
def listar_documentos() -> list[dict]:
    return S.sql(f"""SELECT arquivo, max(documento) AS documento, count(*) AS chunks, max(tem_tabela) AS tem_tabela
                     FROM {S.fq('central_ajuda_chunks')} GROUP BY arquivo ORDER BY arquivo""")


def processar_pdf(nome_arquivo: str, dados: bytes) -> dict:
    nome = re.sub(r"[^A-Za-z0-9_.-]+", "_", nome_arquivo)
    if not nome.lower().endswith(".pdf"):
        raise ValueError("Envie um arquivo .pdf")
    caminho = f"{S.VOL_DOCS}/{nome}"
    S.upload(caminho, dados)
    t0 = time.time()
    linhas = S.sql("""SELECT to_json(ai_parse_document(content, map('version', '2.0'))) AS j
                      FROM read_files(:p, format => 'binaryFile')""", {"p": caminho}, timeout_s=300)
    parsed = json.loads(linhas[0]["j"])
    chunks = chunkar_documento(parsed, nome)
    S.sql(f"DELETE FROM {S.fq('central_ajuda_chunks')} WHERE arquivo = :a", {"a": nome})
    S.sql(f"DELETE FROM {S.fq('documentos_parseados')} WHERE arquivo = :a", {"a": nome})
    S.sql(f"INSERT INTO {S.fq('documentos_parseados')} SELECT :a, :p, parse_json(:j), current_timestamp()",
          {"a": nome, "p": caminho, "j": linhas[0]["j"]})
    for c in chunks:
        S.sql(f"""INSERT INTO {S.fq('central_ajuda_chunks')} (chunk_id, arquivo, documento, secao, pagina, tem_tabela, conteudo)
                  VALUES (:chunk_id, :arquivo, :documento, :secao, :pagina, :tem_tabela, :conteudo)""", c)
    _sync_atrasado("ajuda", S.IDX_AJUDA, 1)
    tipos = {}
    for e in parsed.get("document", {}).get("elements", []):
        tipos[e.get("type")] = tipos.get(e.get("type"), 0) + 1
    return {"arquivo": nome, "caminho": caminho, "segundos_parse": round(time.time() - t0, 1), "elementos": tipos,
            "chunks": chunks, "erros": parsed.get("error_status")}


def remover_documento(arquivo: str):
    S.sql(f"DELETE FROM {S.fq('central_ajuda_chunks')} WHERE arquivo = :a", {"a": arquivo})
    _sync_atrasado("ajuda", S.IDX_AJUDA, 1)


# ───────────────────────────── status / manutenção ─────────────────────────────
def status() -> dict:
    c = S.sql(f"""SELECT
        (SELECT count(*) FROM {S.fq('produtos')})                          AS produtos,
        (SELECT count(*) FROM {S.fq('produtos')} WHERE origem='estudio')   AS produtos_estudio,
        (SELECT count(*) FROM {S.fq('clientes')})                          AS clientes,
        (SELECT count(*) FROM {_T('pedidos')})                           AS pedidos,
        (SELECT count(*) FROM {S.fq('quem_comprou_tambem_comprou')})       AS regras,
        (SELECT count(*) FROM {S.fq('central_ajuda_chunks')})              AS chunks""")[0]
    return {"contagens": c, "indices": [S.vs_status(S.IDX_PRODUTOS), S.vs_status(S.IDX_AJUDA)],
            "config": {"marca": S.MARCA, "catalogo": f"{S.CATALOG}.{S.SCHEMA}", "llm": S.LLM, "embedding": S.EMBEDDING,
                       "vs_endpoint": S.VS_ENDPOINT, "genie": S.GENIE_SPACE_ID, "warehouse": S.warehouse_id()}}


def modelo_ml() -> dict:
    """Placar do modelo híbrido (etapa 03b) + importância das features + link do experimento no MLflow."""
    try:
        placar = S.sql(f"SELECT * FROM {S.fq('avaliacao_recomendacao')}")
        imp = S.sql(f"SELECT * FROM {S.fq('importancia_features_recomendacao')} ORDER BY importancia DESC LIMIT 10")
    except Exception as e:
        return {"disponivel": False, "mensagem": "Rode a etapa setup/03b_modelo_ml para treinar o modelo.", "erro": str(e)[:160]}
    exp = next((p.get("experimento") for p in placar if p.get("experimento")), None)
    host = S.ws().config.host.rstrip("/")
    endpoint = S.estado_endpoint(S.RECOMENDADOR) if S.RECOMENDADOR else None
    if endpoint:
        endpoint["ultima_origem"] = CATALOGO.origem_ml
    return {"disponivel": True, "placar": placar, "importancias": imp, "modelo_uc": next((p.get("modelo_uc") for p in placar if p.get("modelo_uc")), None),
            "experimento": exp, "experimento_url": f"{host}/ml/experiments?searchFilter={exp}" if exp else None,
            "endpoint": endpoint}


def recalcular_recomendacoes() -> dict:
    t0 = time.time()
    from .lakebase import tabela   # views Delta + Lakebase: as compras feitas no App entram nas regras
    S.sql(sql_regras(S.CATALOG, S.SCHEMA, pedidos=tabela("pedidos"), itens=tabela("itens_pedido")), timeout_s=600)
    CATALOGO.carregar()
    return {"segundos": round(time.time() - t0, 1), "regras": sum(len(v) for v in CATALOGO.regras.values())}
