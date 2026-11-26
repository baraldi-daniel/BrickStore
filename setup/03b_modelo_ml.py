# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# dependencies = ["databricks-sdk>=0.169.0", "databricks-vectorsearch", "scikit-learn", "scipy", "mlflow-skinny[databricks]"]
# ///

# COMMAND ----------

# MAGIC %md
# MAGIC # 03b · Regras + Machine Learning: recomendação híbrida
# MAGIC
# MAGIC A etapa 03 gerou as **regras de associação** ("quem comprou também comprou"). Aqui elas viram a
# MAGIC primeira camada de um **sistema híbrido**, no mesmo desenho usado pelos grandes marketplaces:
# MAGIC
# MAGIC ```
# MAGIC  1) CANDIDATOS  ─ regras de associação (SQL)  +  SVD (fatoração de matrizes, "clientes parecidos")
# MAGIC                   +  populares no estilo favorito do cliente
# MAGIC  2) RANKING     ─ Gradient Boosting (scikit-learn): "dado este cliente e este candidato,
# MAGIC                   qual a chance de ele comprar?"  → ordem personalizada por cliente
# MAGIC  3) AVALIAÇÃO   ─ último pedido de cada cliente separado como teste: hit-rate@10, precision@10, NDCG@10
# MAGIC  4) PUBLICAÇÃO  ─ MLflow (experimento + modelo no Unity Catalog) e pontuação em LOTE na tabela
# MAGIC                   recomendacoes_personalizadas (o App só lê — sem endpoint de serving)
# MAGIC ```
# MAGIC
# MAGIC > Sem vazamento de dados: para avaliar, as regras e o SVD são recalculados **só com os pedidos
# MAGIC > anteriores** ao pedido de teste.

# COMMAND ----------

# MAGIC %run ../_config

# COMMAND ----------

import math
import time

import numpy as np
import pandas as pd

t0 = time.time()
itens = spark.sql(f"""
  SELECT p.cliente_id, p.pedido_id, p.data_pedido, i.produto_id
  FROM {fq('itens_pedido')} i JOIN {fq('pedidos')} p USING (pedido_id)
  WHERE p.status <> 'Cancelado'""").toPandas()
produtos = spark.table(fq("produtos")).select(
    "produto_id", "nome", "tipo", "departamento", "estilo_id", "preco", "preco_promocional", "avaliacao",
    "n_avaliacoes", "popularidade", "frete_gratis", "estoque").toPandas()
clientes = spark.table(fq("clientes")).select("cliente_id", "segmento").toPandas()
print(f"{len(itens):,} itens | {itens.pedido_id.nunique():,} pedidos | {itens.cliente_id.nunique():,} clientes | {time.time()-t0:.0f}s")

# ordem temporal dos pedidos de cada cliente (1 = mais recente)
ordem = (itens[["cliente_id", "pedido_id", "data_pedido"]].drop_duplicates("pedido_id")
         .sort_values(["cliente_id", "data_pedido"]))
ordem["rev"] = ordem.groupby("cliente_id").cumcount(ascending=False) + 1
itens = itens.merge(ordem[["pedido_id", "rev"]], on="pedido_id")
P = produtos.set_index("produto_id")
P["preco_ef"] = P["preco_promocional"].fillna(P["preco"])
P["desconto"] = (1 - P["preco_ef"] / P["preco"]).fillna(0)
SEG = {"Bronze": 0, "Prata": 1, "Ouro": 2, "Diamante": 3}
seg = clientes.set_index("cliente_id")["segmento"].map(SEG)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1) Geradores de candidatos
# MAGIC Funções que recebem um **histórico** (pedidos até um ponto no tempo) e devolvem candidatos por cliente.

# COMMAND ----------

from scipy.sparse import csr_matrix
from sklearn.decomposition import TruncatedSVD


def regras_de(hist: pd.DataFrame, min_juntos: int = 3, top: int = 20) -> pd.DataFrame:
    """Mesma lógica do SQL da etapa 03 (cesta = pedido), em pandas, só com o histórico informado."""
    cestas = hist[["pedido_id", "produto_id"]].drop_duplicates()
    pares = cestas.merge(cestas, on="pedido_id")
    pares = pares[pares.produto_id_x != pares.produto_id_y]
    n = pares.groupby(["produto_id_x", "produto_id_y"]).size().rename("n_juntos").reset_index()
    n = n[n.n_juntos >= min_juntos]
    freq = cestas.groupby("produto_id").size()
    total = cestas.pedido_id.nunique()
    n["confianca"] = n.n_juntos / n.produto_id_x.map(freq)
    n["lift"] = n.confianca / (n.produto_id_y.map(freq) / total)
    n = n[n.lift > 1]
    n["score_regra"] = n.n_juntos * np.log1p(n.lift)
    n = n.sort_values("score_regra", ascending=False).groupby("produto_id_x").head(top)
    return n.rename(columns={"produto_id_x": "item_a", "produto_id_y": "item_b"})


def svd_de(hist: pd.DataFrame, k: int = 48):
    """Fatoração de matrizes (SVD truncado) da matriz cliente × produto (compras implícitas)."""
    cli = pd.Index(sorted(hist.cliente_id.unique()))
    prd = pd.Index(produtos.produto_id)
    g = hist.groupby(["cliente_id", "produto_id"]).size().reset_index(name="n")
    m = csr_matrix((np.log1p(g.n.values).astype(np.float32), (cli.get_indexer(g.cliente_id), prd.get_indexer(g.produto_id))),
                   shape=(len(cli), len(prd)))
    svd = TruncatedSVD(n_components=k, random_state=7).fit(m)
    return cli, prd, svd.transform(m).astype(np.float32), svd.components_.astype(np.float32), m


def candidatos(hist: pd.DataFrame, clientes_alvo, n_svd: int = 25, n_estilo: int = 10) -> pd.DataFrame:
    """Une os 3 geradores e calcula as features de cada par (cliente, candidato)."""
    regras = regras_de(hist)
    comprados = hist[["cliente_id", "produto_id"]].drop_duplicates()
    comprados = comprados[comprados.cliente_id.isin(clientes_alvo)]

    # (a) regras: a partir de cada item já comprado
    r = comprados.merge(regras, left_on="produto_id", right_on="item_a")
    r = r.sort_values("score_regra", ascending=False)
    ag = r.groupby(["cliente_id", "item_b"]).agg(
        max_lift=("lift", "max"), max_conf=("confianca", "max"), sum_n=("n_juntos", "sum"),
        n_bases=("item_a", "nunique"), score_regra=("score_regra", "max"), base=("item_a", "first")).reset_index()
    ag = ag.rename(columns={"item_b": "produto_id"})

    # (b) SVD: top-N por cliente (em blocos, para caber na memória)
    cli, prd, U, V, m = svd_de(hist)
    blocos = []
    alvo_idx = cli.get_indexer(pd.Index(clientes_alvo).intersection(cli))
    for i in range(0, len(alvo_idx), 2000):
        idx = alvo_idx[i:i + 2000]
        s = U[idx] @ V
        s[m[idx].nonzero()] = -np.inf                     # não recomenda o que já comprou
        top = np.argpartition(-s, n_svd, axis=1)[:, :n_svd]
        for linha, cols in zip(idx, top):
            blocos.append(pd.DataFrame({"cliente_id": cli[linha], "produto_id": prd[cols], "svd_rank": 1}))
    sv = pd.concat(blocos) if blocos else pd.DataFrame(columns=["cliente_id", "produto_id", "svd_rank"])

    # (c) populares no estilo predominante do cliente
    hist_e = comprados.merge(P[["estilo_id"]], left_on="produto_id", right_index=True)
    estilo_fav = hist_e.groupby("cliente_id")["estilo_id"].agg(lambda x: x.value_counts().index[0])
    pop = P.reset_index().sort_values("popularidade", ascending=False).groupby("estilo_id").head(n_estilo)[["estilo_id", "produto_id"]]
    pe = estilo_fav.rename("estilo_id").reset_index().merge(pop, on="estilo_id")[["cliente_id", "produto_id"]]
    pe["pop_estilo"] = 1

    c = (ag.merge(sv, on=["cliente_id", "produto_id"], how="outer")
           .merge(pe, on=["cliente_id", "produto_id"], how="outer"))
    c = c.merge(comprados.assign(ja=1), on=["cliente_id", "produto_id"], how="left")
    c = c[c.ja.isna()].drop(columns="ja")

    # score do SVD para TODOS os candidatos (feature contínua)
    ci, pi = cli.get_indexer(c.cliente_id), prd.get_indexer(c.produto_id)
    ok = (ci >= 0) & (pi >= 0)
    c["svd_score"] = 0.0
    c.loc[ok, "svd_score"] = np.einsum("ij,ji->i", U[ci[ok]], V[:, pi[ok]])

    # afinidades do cliente (estilo / departamento / tipo) a partir do histórico
    h = comprados.merge(P[["estilo_id", "departamento", "tipo"]], left_on="produto_id", right_index=True)
    tot = h.groupby("cliente_id").size().rename("n_hist")
    c = c.merge(P[["estilo_id", "departamento", "tipo", "preco_ef", "desconto", "avaliacao", "n_avaliacoes", "popularidade",
                   "frete_gratis", "estoque"]], left_on="produto_id", right_index=True)
    for col in ("estilo_id", "departamento", "tipo"):
        af = h.groupby(["cliente_id", col]).size().rename(f"af_{col}").reset_index()
        c = c.merge(af, on=["cliente_id", col], how="left")
    c = c.merge(tot, left_on="cliente_id", right_index=True, how="left")
    for col in ("af_estilo_id", "af_departamento", "af_tipo"):
        c[col] = c[col].fillna(0) / c["n_hist"].clip(lower=1)
    c["segmento"] = c.cliente_id.map(seg).fillna(0)
    c["em_regras"] = c.score_regra.notna().astype(int)
    c["em_svd"] = c.svd_rank.notna().astype(int)
    c["em_estilo"] = c.pop_estilo.notna().astype(int)
    for col in ("max_lift", "max_conf", "sum_n", "n_bases", "score_regra"):
        c[col] = c[col].fillna(0)
    c["log_aval"] = np.log1p(c.n_avaliacoes)
    c["frete_gratis"] = c.frete_gratis.astype(int)
    return c


FEATURES = ["max_lift", "max_conf", "sum_n", "n_bases", "score_regra", "svd_score", "em_regras", "em_svd", "em_estilo",
            "af_estilo_id", "af_departamento", "af_tipo", "n_hist", "segmento", "preco_ef", "desconto", "avaliacao",
            "log_aval", "popularidade", "frete_gratis"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2) Conjuntos de treino e teste (divisão temporal)
# MAGIC - **Treino**: histórico = todos os pedidos menos os 2 últimos de cada cliente; alvo = penúltimo pedido.
# MAGIC - **Teste**: histórico = todos menos o último; alvo = último pedido (nunca visto no treino).

# COMMAND ----------

def montar(hist_rev_min: int, alvo_rev: int):
    hist = itens[itens.rev >= hist_rev_min]
    alvo = itens[itens.rev == alvo_rev][["cliente_id", "produto_id"]].drop_duplicates().assign(y=1)
    clientes_alvo = alvo.cliente_id.unique()
    c = candidatos(hist, clientes_alvo)
    c = c[c.cliente_id.isin(clientes_alvo)].merge(alvo, on=["cliente_id", "produto_id"], how="left")
    c["y"] = c.y.fillna(0).astype(int)
    return c, alvo


t = time.time()
treino, alvo_treino = montar(hist_rev_min=3, alvo_rev=2)
teste, alvo_teste = montar(hist_rev_min=2, alvo_rev=1)
print(f"treino: {len(treino):,} pares ({treino.y.mean():.2%} positivos) · teste: {len(teste):,} pares · {time.time()-t:.0f}s")
print(f"cobertura dos candidatos no teste: {teste.groupby('cliente_id').y.max().mean():.1%} dos clientes têm o item certo entre os candidatos")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3) Treino do ranking (Gradient Boosting) + MLflow

# COMMAND ----------

import mlflow
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

mlflow.set_registry_uri("databricks-uc")
EXPERIMENTO = f"/Users/{USUARIO}/{APP_NAME}_recomendacao"
try:
    mlflow.set_experiment(EXPERIMENTO)
except Exception as e:
    print("experimento:", str(e)[:120])

modelo = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0,
                                        class_weight="balanced", random_state=7)
modelo.fit(treino[FEATURES], treino.y)
teste["p_ml"] = modelo.predict_proba(teste[FEATURES])[:, 1]
auc = roc_auc_score(teste.y, teste.p_ml)
print(f"AUC no teste: {auc:.3f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4) Avaliação: o placar
# MAGIC Para cada cliente de teste ordenamos os candidatos por cada abordagem e verificamos se o que ele
# MAGIC **realmente comprou no último pedido** aparece no **top 10**.

# COMMAND ----------

def metricas(df: pd.DataFrame, coluna: str, k: int = 10, n_clientes: int | None = None):
    top = df.sort_values(["cliente_id", coluna], ascending=[True, False]).groupby("cliente_id").head(k).copy()
    top["pos"] = top.groupby("cliente_id").cumcount() + 1
    acertos = top.groupby("cliente_id").y.max()
    n = n_clientes or alvo_teste.cliente_id.nunique()
    dcg = (top.y / np.log2(top.pos + 1)).groupby(top.cliente_id).sum()
    return {"hit_rate_10": acertos.sum() / n, "precision_10": top.y.sum() / (n * k), "ndcg_10": dcg.sum() / n}


# baseline de popularidade: os mais populares que o cliente ainda não comprou
pop_rank = teste.copy()
pop_rank["pop"] = pop_rank.popularidade
placar = [
    ("Popularidade (mais vendidos)", "pop", pop_rank),
    ("Regras de associação (SQL)", "score_regra", teste[teste.em_regras == 1]),
    ("SVD (fatoração de matrizes)", "svd_score", teste),
    ("Híbrido: regras + SVD + ranking ML", "p_ml", teste),
]
linhas = []
for nome, col, df in placar:
    m = metricas(df, col)
    linhas.append({"abordagem": nome, **{k: round(float(v), 4) for k, v in m.items()}})
avaliacao = pd.DataFrame(linhas)
avaliacao["auc_modelo"] = [None, None, None, round(float(auc), 4)]
display(avaliacao)

# COMMAND ----------

# MAGIC %md
# MAGIC ### O que o modelo aprendeu (importância por permutação)

# COMMAND ----------

from sklearn.inspection import permutation_importance

amostra = teste.sample(min(30000, len(teste)), random_state=1)
imp = permutation_importance(modelo, amostra[FEATURES], amostra.y, scoring="roc_auc", n_repeats=3, random_state=1)
importancias = (pd.DataFrame({"feature": FEATURES, "importancia": imp.importances_mean})
                .sort_values("importancia", ascending=False).round(4))
display(importancias)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Registro no MLflow + Unity Catalog

# COMMAND ----------

RUN_ID, VERSAO = None, None
NOME_MODELO = fq("modelo_recomendacao")
try:
    from mlflow.models import infer_signature
    with mlflow.start_run(run_name="ranking_hibrido") as run:
        mlflow.log_params({"modelo": "HistGradientBoostingClassifier", "max_iter": 300, "learning_rate": 0.08,
                           "svd_componentes": 48, "candidatos": "regras+svd+estilo", "features": len(FEATURES)})
        for _, r in avaliacao.iterrows():
            chave = r["abordagem"].split(" ")[0].lower().replace(":", "")
            mlflow.log_metrics({f"{chave}_hit_rate_10": r.hit_rate_10, f"{chave}_ndcg_10": r.ndcg_10})
        mlflow.log_metric("auc", auc)
        mlflow.log_table(importancias, "importancia_features.json")
        info = mlflow.sklearn.log_model(modelo, name="modelo", input_example=teste[FEATURES].head(5),
                                        signature=infer_signature(teste[FEATURES].head(50), modelo.predict_proba(teste[FEATURES].head(50))[:, 1]),
                                        registered_model_name=NOME_MODELO)
        RUN_ID = run.info.run_id
        VERSAO = getattr(info, "registered_model_version", None)
    print(f"✅ MLflow run {RUN_ID} · modelo {NOME_MODELO} v{VERSAO}")
except Exception as e:
    print("⚠️ registro no MLflow/UC não concluído (o placar e as recomendações seguem):", str(e)[:200])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5) Pontuação em lote: recomendações para TODOS os clientes
# MAGIC Usa o histórico completo, as regras e o SVD de todos os pedidos e grava o top 12 por cliente com o
# MAGIC **motivo** de cada recomendação (para o App explicar a sugestão).

# COMMAND ----------

t = time.time()
todos = candidatos(itens, itens.cliente_id.unique())
todos["score"] = modelo.predict_proba(todos[FEATURES])[:, 1]
todos = todos.sort_values(["cliente_id", "score"], ascending=[True, False])
# diversidade: no máximo 2 do mesmo tipo por cliente
todos["n_tipo"] = todos.groupby(["cliente_id", "tipo"]).cumcount()
top = todos[todos.n_tipo < 2].groupby("cliente_id").head(12).copy()
top["rank"] = top.groupby("cliente_id").cumcount() + 1
nomes = P["nome"]
estilos_nome = spark.table(fq("estilos")).select("estilo_id", "nome").toPandas().set_index("estilo_id")["nome"]


def motivo(r):
    if r.n_bases > 0 and isinstance(r.base, str):
        return f"Porque você comprou {nomes.get(r.base, 'um item parecido')}"
    if r.em_svd:
        return "Clientes com gosto parecido com o seu compraram"
    return f"Combina com seu estilo {estilos_nome.get(r.estilo_id, '')}".strip()


top["motivo"] = top.apply(motivo, axis=1)
top["fonte"] = np.select([top.em_regras == 1, top.em_svd == 1], ["regras", "svd"], "estilo")
saida = top[["cliente_id", "produto_id", "rank", "score", "motivo", "base", "fonte"]].rename(columns={"base": "base_produto_id"})
saida["score"] = saida.score.round(5)
saida["base_produto_id"] = saida.base_produto_id.where(saida.base_produto_id.notna(), None).astype(object)
(spark.createDataFrame(saida).write.mode("overwrite").option("overwriteSchema", "true")
      .saveAsTable(fq("recomendacoes_personalizadas")))
spark.sql(f"COMMENT ON TABLE {fq('recomendacoes_personalizadas')} IS 'Top 12 recomendacoes por cliente: candidatos de regras + SVD + estilo, ordenados pelo modelo de ranking (Gradient Boosting)'")
print(f"✅ {len(saida):,} recomendações para {saida.cliente_id.nunique():,} clientes em {time.time()-t:.0f}s")

aval = avaliacao.copy()
aval["n_clientes_teste"] = int(alvo_teste.cliente_id.nunique())
aval["mlflow_run_id"] = str(RUN_ID or "")          # string vazia (não None): coluna só com nulos não tem tipo no Spark
aval["experimento"] = str(EXPERIMENTO or "")
aval["modelo_uc"] = f"{NOME_MODELO} v{VERSAO}" if VERSAO else ""
aval["executado_em"] = pd.Timestamp.now()
spark.createDataFrame(aval.astype({"auc_modelo": "float64"})).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fq("avaliacao_recomendacao"))
spark.createDataFrame(importancias).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fq("importancia_features_recomendacao"))
display(spark.sql(f"""SELECT r.cliente_id, r.rank, p.nome, r.motivo, round(r.score, 3) AS score
                      FROM {fq('recomendacoes_personalizadas')} r JOIN {fq('produtos')} p USING (produto_id)
                      WHERE r.cliente_id = (SELECT min(cliente_id) FROM {fq('perfis_demo')}) ORDER BY r.rank"""))
print(f"✅ etapa concluída em {time.time()-t0:.0f}s")
