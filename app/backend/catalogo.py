"""
Cache em memória dos produtos + regras "quem comprou também comprou" e montagem da vitrine.

Os ~3 mil produtos e as regras de associação cabem folgados em memória: carregamos na subida do
App (e recarregamos quando o Estúdio altera algo). Assim a navegação fica instantânea e o
warehouse 2X-Small só atende o que é por cliente (pedidos e navegação) e as escritas.
"""
import logging
import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import servicos as S


def _T(nome):
    """Pedidos/itens para LEITURA: view Delta + Lakebase (pedidos novos do App) quando disponível."""
    from .lakebase import tabela
    return tabela(nome)

log = logging.getLogger("varejo")

import json
import os

FOTOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "fotos")


def _rgb(h: str):
    h = (h or "#888888").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (136, 136, 136)


def atribuir_fotos(produtos: dict):
    """Fotos reais CC0 (app/static/fotos): para cada produto, a foto do seu tipo com a cor mais parecida."""
    try:
        man = json.load(open(os.path.join(FOTOS_DIR, "manifest.json"), encoding="utf-8"))
    except Exception:
        return
    uso = Counter()
    for p in produtos.values():
        fotos = man.get(p.get("tipo")) or []
        if not fotos:
            continue
        alvo = _rgb(p.get("cor_hex"))
        # distância de cor + pequena penalidade de repetição (espalha as fotos entre os produtos do tipo)
        melhor = min(fotos, key=lambda f: sum((a - b) ** 2 for a, b in zip(_rgb(f["cor"]), alvo)) ** .5 + 18 * uso[f["arquivo"]])
        uso[melhor["arquivo"]] += 1
        p["foto_url"] = f"/static/fotos/{melhor['arquivo']}"


CAMPOS_RESUMO = ("foto_url", "produto_id", "nome", "marca_produto", "departamento", "tipo", "icone", "estilo_id", "cor", "cor_hex",
                 "preco", "preco_promocional", "parcelas_sem_juros", "avaliacao", "n_avaliacoes", "imagem_path",
                 "origem", "lancamento", "vendedor", "vendedor_reputacao", "frete_gratis")
ORDEM_DEPTOS = ["Moda", "Casa & Decoração", "Cozinha", "Eletrônicos", "Esporte & Lazer", "Beleza"]


def preco_efetivo(p: dict) -> float:
    return float(p.get("preco_promocional") or p.get("preco") or 0)


class Catalogo:
    def __init__(self):
        self.produtos: dict[str, dict] = {}
        self.por_nome: dict[str, str] = {}
        self.estilos: list[dict] = []
        self.perfis: list[dict] = []
        self.regras: dict[str, list[dict]] = {}
        self.mais_vendidos: list[str] = []
        self.icone_por_tipo: dict[str, str] = {}
        self.pronto = False
        self.origem_ml = None
        self.erro = None
        self.incompleto = []

    # ───────────── carga ─────────────
    def carregar(self):
        t0 = time.time()
        try:
            with ThreadPoolExecutor(5) as ex:
                f_prod = ex.submit(S.sql, f"SELECT * EXCEPT (texto_busca) FROM {S.fq('produtos')}")
                f_est = ex.submit(S.sql, f"SELECT * FROM {S.fq('estilos')} ORDER BY ordem")
                f_per = ex.submit(S.sql, f"SELECT * FROM {S.fq('perfis_demo')}")
                f_reg = ex.submit(S.sql, f"""SELECT item_a, item_b, n_juntos, confianca, lift, rank, mesmo_estilo
                                            FROM {S.fq('quem_comprou_tambem_comprou')}""")
                f_top = ex.submit(S.sql, f"""SELECT i.produto_id, SUM(i.quantidade) AS n
                                            FROM {_T('itens_pedido')} i JOIN {_T('pedidos')} p USING (pedido_id)
                                            WHERE p.data_pedido >= (SELECT max(data_pedido) FROM {_T('pedidos')}) - INTERVAL 30 DAYS
                                            GROUP BY i.produto_id ORDER BY n DESC LIMIT 60""")
                prod, est, per = f_prod.result(), f_est.result(), f_per.result()
                faltando = []
                try:
                    reg = f_reg.result()
                except Exception as e:  # tabela de regras ainda não criada (instalação em andamento)
                    reg, faltando = [], ["quem_comprou_tambem_comprou"]
                    log.warning("regras indisponíveis: %s", str(e)[:120])
                try:
                    top = f_top.result()
                except Exception:
                    top = []
            regras = {}
            for r in reg:
                regras.setdefault(r["item_a"], []).append(r)
            for v in regras.values():
                v.sort(key=lambda x: x["rank"])
            self.produtos = {p["produto_id"]: p for p in prod}
            atribuir_fotos(self.produtos)
            self.por_nome = {p["nome"].lower(): p["produto_id"] for p in prod}
            self.icone_por_tipo = {p["tipo"]: p["icone"] for p in prod if p.get("icone")}
            self.estilos, self.perfis, self.regras = est, per, regras
            self.mais_vendidos = [t["produto_id"] for t in top] or [
                p["produto_id"] for p in sorted(prod, key=lambda x: x.get("popularidade") or 0, reverse=True)[:60]]
            self.incompleto = faltando
            self.pronto, self.erro = True, None
            log.info("catálogo carregado: %d produtos, %d regras em %.1fs", len(prod), len(reg), time.time() - t0)
        except Exception as e:
            self.erro = str(e)
            log.exception("falha ao carregar catálogo")

    def carregar_em_background(self):
        """Carrega na subida e tenta de novo a cada 30 s enquanto faltar algo (ex.: instalação ainda rodando)."""
        def loop():
            while True:
                self.carregar()
                if self.pronto and not self.incompleto:
                    return
                time.sleep(30)
        threading.Thread(target=loop, daemon=True).start()

    # ───────────── consultas ─────────────
    def resumo(self, p: dict) -> dict:
        return {k: p.get(k) for k in CAMPOS_RESUMO}

    def estilo(self, estilo_id: str) -> dict | None:
        return next((e for e in self.estilos if e["estilo_id"] == estilo_id), None)

    def departamentos(self) -> list[dict]:
        c = Counter(p["departamento"] for p in self.produtos.values())
        return [{"nome": d, "n_produtos": c[d]}
                for d in sorted(c, key=lambda d: ORDEM_DEPTOS.index(d) if d in ORDEM_DEPTOS else 99)]

    def achar(self, ref: str) -> dict | None:
        """Aceita produto_id ou nome (exato ou parcial)."""
        if not ref:
            return None
        ref = ref.strip()
        if ref in self.produtos:
            return self.produtos[ref]
        pid = self.por_nome.get(ref.lower())
        if pid:
            return self.produtos[pid]
        cands = [p for p in self.produtos.values() if ref.lower() in p["nome"].lower()]
        return max(cands, key=lambda p: p.get("popularidade") or 0) if cands else None

    def tambem_compraram(self, produto_id: str, n: int = 12) -> list[dict]:
        out = []
        for r in self.regras.get(produto_id, [])[:n]:
            p = self.produtos.get(r["item_b"])
            if p:
                out.append({**self.resumo(p), "confianca": r["confianca"], "lift": r["lift"], "n_juntos": r["n_juntos"],
                            "mesmo_estilo": r.get("mesmo_estilo")})
        return out

    def compre_junto(self, produto_id: str, n: int = 2, desconto_pct: int = 10) -> dict:
        """Kit: o produto + os complementos mais associados (de tipos diferentes), com desconto no conjunto."""
        base = self.produtos.get(produto_id)
        if not base:
            return {"itens": [], "total": 0, "total_com_desconto": 0, "desconto_pct": 0}
        itens, tipos = [self.resumo(base)], {base["tipo"]}
        for r in self.tambem_compraram(produto_id, 20):
            if len(itens) > n:
                break
            if r["tipo"] not in tipos:
                itens.append(r)
                tipos.add(r["tipo"])
        total = round(sum(preco_efetivo(i) for i in itens), 2)
        pct = desconto_pct if len(itens) > 1 else 0
        return {"itens": itens, "total": total, "total_com_desconto": round(total * (1 - pct / 100), 2), "desconto_pct": pct}

    def do_estilo(self, estilo_id: str, n: int = 18, excluir=(), departamento: str | None = None) -> list[dict]:
        ps = [p for p in self.produtos.values() if p["estilo_id"] == estilo_id and p["produto_id"] not in excluir
              and (not departamento or p["departamento"] == departamento)]
        ps.sort(key=lambda p: (p.get("popularidade") or 0) * (p.get("avaliacao") or 4), reverse=True)
        return [self.resumo(p) for p in ps[:n]]

    def do_departamento(self, departamento: str, n: int = 18) -> list[dict]:
        ps = [p for p in self.produtos.values() if p["departamento"] == departamento]
        ps.sort(key=lambda p: (p.get("popularidade") or 0) * (p.get("avaliacao") or 4), reverse=True)
        return [self.resumo(p) for p in ps[:n]]

    def detalhe(self, produto_id: str) -> dict | None:
        p = self.produtos.get(produto_id)
        if not p:
            return None
        return {**p, "estilo": self.estilo(p["estilo_id"]), "tambem_compraram": self.tambem_compraram(produto_id),
                "compre_junto": self.compre_junto(produto_id),
                "mesmo_estilo": self.do_estilo(p["estilo_id"], 12, excluir={produto_id})}

    def recomendados_ml(self, cliente_id: str, n: int = 12) -> list[dict]:
        """Top-N do modelo híbrido: 1º o endpoint de Model Serving (etapa 03c); reserva = tabela recomendacoes_personalizadas."""
        linhas, origem = [], "tabela"
        if S.RECOMENDADOR:
            try:
                linhas, origem = S.recomendar_endpoint(cliente_id, n), "endpoint"
            except Exception as e:
                log.warning("recomendador (endpoint %s) indisponível: %s; usando a tabela", S.RECOMENDADOR, str(e)[:100])
        if not linhas:
            origem = "tabela"
            try:
                linhas = S.sql(f"""SELECT produto_id, rank, score, motivo, fonte FROM {S.fq('recomendacoes_personalizadas')}
                                   WHERE cliente_id = :c ORDER BY rank LIMIT {int(n)}""", {"c": cliente_id})
            except Exception:
                return []  # tabela ainda não criada (etapa de ML não executada)
        self.origem_ml = origem
        return [{**self.resumo(self.produtos[l["produto_id"]]), "motivo": l["motivo"], "score_ml": l["score"], "fonte": l["fonte"],
                 "origem_ml": origem} for l in linhas if l.get("produto_id") in self.produtos]

    # ───────────── vitrine personalizada ─────────────
    def vitrine(self, cliente_id: str | None) -> dict:
        perfil = next((p for p in self.perfis if p["cliente_id"] == cliente_id), None)
        fav = perfil["estilo_favorito"] if perfil else None
        comprados, vistos, recs_ml = [], [], []
        if cliente_id:
            with ThreadPoolExecutor(3) as ex:
                f1 = ex.submit(S.sql, f"""SELECT i.produto_id, max(p.data_pedido) AS quando
                                          FROM {_T('itens_pedido')} i JOIN {_T('pedidos')} p USING (pedido_id)
                                          WHERE p.cliente_id = :c GROUP BY i.produto_id ORDER BY quando DESC LIMIT 12""",
                               {"c": cliente_id})
                f2 = ex.submit(S.sql, f"""SELECT produto_id, max(data_hora) AS quando FROM {S.fq('eventos_navegacao')}
                                          WHERE cliente_id = :c GROUP BY produto_id ORDER BY quando DESC LIMIT 16""",
                               {"c": cliente_id})
                f3 = ex.submit(self.recomendados_ml, cliente_id)
                comprados, vistos, recs_ml = f1.result(), f2.result(), f3.result()

        fileiras = []
        if vistos:
            fileiras.append({"id": "vistos", "titulo": "Vistos recentemente",
                             "itens": [self.resumo(self.produtos[v["produto_id"]]) for v in vistos if v["produto_id"] in self.produtos]})
        if recs_ml:
            fileiras.insert(0, {"id": "para-voce", "titulo": "Recomendado para você", "estilo": "ml",
                                "subtitulo": "Regras + SVD + ranking de Machine Learning (Gradient Boosting)", "itens": recs_ml})
        ja_tem = {c["produto_id"] for c in comprados}
        for c in comprados[:2]:
            base = self.produtos.get(c["produto_id"])
            recs = [r for r in self.tambem_compraram(c["produto_id"], 16) if r["produto_id"] not in ja_tem]
            if base and recs:
                fileiras.append({"id": f"porque-{base['produto_id']}", "titulo": f"Porque você comprou «{base['nome']}»",
                                 "subtitulo": "Quem comprou também comprou", "estilo": "associacao",
                                 "base": base["produto_id"], "itens": recs})
        fileiras.append({"id": "mais-vendidos", "titulo": "Mais vendidos da semana", "estilo": "ranking",
                         "itens": [self.resumo(self.produtos[c]) for c in self.mais_vendidos[:10] if c in self.produtos]})
        ofertas = [p for p in self.produtos.values() if p.get("preco_promocional")]
        ofertas.sort(key=lambda p: (1 - preco_efetivo(p) / (p["preco"] or 1)) * (p.get("popularidade") or 0) ** .5, reverse=True)
        fileiras.append({"id": "ofertas", "titulo": "Ofertas do dia", "subtitulo": "Preços que valem o clique",
                         "estilo": "oferta", "itens": [self.resumo(p) for p in ofertas[:18]]})
        estudio = sorted([p for p in self.produtos.values() if p.get("origem") == "estudio"],
                         key=lambda p: str(p.get("data_cadastro")), reverse=True)
        if estudio:
            fileiras.append({"id": "estudio", "titulo": "Novidades do Estúdio",
                             "subtitulo": "Cadastradas agora a partir de fichas técnicas em PDF",
                             "estilo": "destaque", "itens": [self.resumo(p) for p in estudio[:18]]})
        if fav and self.estilo(fav):
            e = self.estilo(fav)
            fileiras.append({"id": f"estilo-{fav}", "titulo": f"Seu estilo: {e['nome']}", "subtitulo": e.get("descricao"),
                             "itens": self.do_estilo(fav)})
        for d in self.departamentos():
            fileiras.append({"id": f"dep-{d['nome']}", "titulo": d["nome"], "itens": self.do_departamento(d["nome"])})

        rnd = random.Random(cliente_id or "visitante")
        pool = [p for p in self.produtos.values() if (p["estilo_id"] == fav or not fav)
                and p["departamento"] in ("Casa & Decoração", "Eletrônicos", "Moda") and (p.get("avaliacao") or 0) >= 4.3]
        pool = sorted(pool, key=lambda p: p.get("popularidade") or 0, reverse=True)[:30] or list(self.produtos.values())[:30]
        destaques = [self.resumo(p) for p in rnd.sample(pool, min(4, len(pool)))]
        return {"perfil": perfil, "destaques": destaques, "fileiras": fileiras}


CATALOGO = Catalogo()
