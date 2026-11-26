"""
Transforma a saída do `ai_parse_document` (versão 2.0) em *chunks* prontos para o Vector Search.

Usado em dois lugares (mesmo código, uma única fonte):
  • notebook `setup/02_documentos_ai_parse` — processa os PDFs iniciais da central de ajuda;
  • App (aba Estúdio → Documentos) — processa PDFs novos enviados pelo usuário.

Estratégia: um chunk por **seção** (cada `section_header` abre uma seção nova). Tabelas
(que o ai_parse_document devolve em HTML) viram texto "coluna: valor" linha a linha, para que o
embedding entenda o conteúdo.
"""
import html
import json
import re

IGNORAR = {"page_header", "page_footer", "page_number"}


def tabela_html_para_texto(conteudo_html: str) -> str:
    """<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table> → 'A: 1; B: 2'."""
    linhas = re.findall(r"<tr[^>]*>(.*?)</tr>", conteudo_html or "", flags=re.S | re.I)
    celulas = [[html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", l, flags=re.S | re.I)] for l in linhas]
    celulas = [c for c in celulas if any(c)]
    if not celulas:
        return re.sub(r"<[^>]+>", " ", conteudo_html or "").strip()
    cab, corpo = celulas[0], celulas[1:]
    if not corpo:
        return " | ".join(cab)
    return "\n".join("; ".join(f"{h}: {v}" for h, v in zip(cab, l) if v) for l in corpo)


def chunkar_documento(parsed, arquivo: str):
    """Recebe o VARIANT/JSON do ai_parse_document e devolve uma lista de dicts (chunks)."""
    if isinstance(parsed, str):
        parsed = json.loads(parsed)
    elementos = (parsed or {}).get("document", {}).get("elements", []) or []
    titulo_doc = next((e.get("content", "").strip() for e in elementos if e.get("type") == "title"), arquivo)
    chunks, atual = [], None

    def fechar():
        if atual and atual["partes"]:
            texto = "\n".join(atual["partes"]).strip()
            minimo = 140 if atual["secao"] == "Introdução" else 20   # ignora só o subtítulo/disclaimer
            if len(texto) > minimo:
                chunks.append(dict(
                    chunk_id=f"{arquivo}#{len(chunks) + 1:02d}", arquivo=arquivo, documento=titulo_doc,
                    secao=atual["secao"], pagina=atual["pagina"] + 1, tem_tabela=atual["tabela"],
                    conteudo=f"{titulo_doc} — {atual['secao']}\n{texto}"))

    for e in elementos:
        tipo, conteudo = e.get("type"), (e.get("content") or "").strip()
        pagina = ((e.get("bbox") or [{}])[0] or {}).get("page_id", 0) or 0
        if tipo in IGNORAR or not conteudo:
            continue
        if tipo == "title":
            continue
        if tipo == "section_header" or atual is None:
            fechar()
            atual = dict(secao=conteudo if tipo == "section_header" else "Introdução", partes=[],
                         pagina=pagina, tabela=False)
            if tipo == "section_header":
                continue
        if tipo == "table":
            atual["partes"].append(tabela_html_para_texto(conteudo))
            atual["tabela"] = True
        else:
            atual["partes"].append(re.sub(r"\s*\n\s*", " ", conteudo))
    fechar()
    return chunks
