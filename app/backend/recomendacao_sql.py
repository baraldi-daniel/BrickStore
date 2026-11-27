"""
SQL do "quem comprou também comprou" (regras de associação item→item: suporte, confiança, lift).

Cesta = PEDIDO: dois produtos estão "juntos" quando aparecem no mesmo pedido (pedidos cancelados ficam de fora).

Fonte única usada pelo notebook `setup/03_quem_comprou_tambem_comprou` e pelo botão
"Recalcular recomendações" da aba Estúdio do App.

Ranking dentro de cada produto A: `n_juntos * LN(1 + lift)` (força bruta × força relativa), para que pares
com 3 pedidos e lift enorme não ocupem o topo sobre complementos fortes com dezenas de pedidos em comum.
"""


def sql_regras(catalog: str, schema: str, min_juntos: int = 3, top_n: int = 20,
               pedidos: str | None = None, itens: str | None = None) -> str:
    # pedidos/itens: as tabelas Delta (instalação) ou as views Delta + Lakebase (App: inclui as compras feitas agora)
    pedidos = pedidos or f"{catalog}.{schema}.pedidos"
    itens = itens or f"{catalog}.{schema}.itens_pedido"
    produtos = f"{catalog}.{schema}.produtos"
    destino = f"{catalog}.{schema}.quem_comprou_tambem_comprou"
    return f"""
CREATE OR REPLACE TABLE {destino}
COMMENT 'Regras de associacao item a item por pedido (suporte, confianca, lift). Top 20 por produto.'
AS
WITH cestas AS (                       -- 1 linha por (pedido, produto); cesta = pedido, sem cancelados
  SELECT DISTINCT i.pedido_id, i.produto_id
  FROM {itens} i
  JOIN {pedidos} p ON p.pedido_id = i.pedido_id
  WHERE p.status <> 'Cancelado'
),
total AS (SELECT COUNT(DISTINCT pedido_id) AS n_pedidos FROM cestas),
freq AS (SELECT produto_id, COUNT(*) AS n_pedidos_item FROM cestas GROUP BY produto_id),
pares AS (
  SELECT a.produto_id AS item_a, b.produto_id AS item_b, COUNT(*) AS n_juntos
  FROM cestas a JOIN cestas b ON a.pedido_id = b.pedido_id AND a.produto_id <> b.produto_id
  GROUP BY a.produto_id, b.produto_id
  HAVING COUNT(*) >= {min_juntos}
),
metricas AS (
  SELECT p.item_a, p.item_b, p.n_juntos,
         fa.n_pedidos_item                                              AS pedidos_a,
         fb.n_pedidos_item                                              AS pedidos_b,
         ROUND(p.n_juntos / t.n_pedidos, 6)                             AS suporte,
         ROUND(p.n_juntos / fa.n_pedidos_item, 4)                       AS confianca,
         ROUND((p.n_juntos / fa.n_pedidos_item) / (fb.n_pedidos_item / t.n_pedidos), 2) AS lift
  FROM pares p
  JOIN freq fa ON fa.produto_id = p.item_a
  JOIN freq fb ON fb.produto_id = p.item_b
  CROSS JOIN total t
),
ranqueado AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY item_a ORDER BY n_juntos * LN(1 + lift) DESC, n_juntos DESC, item_b) AS rank
  FROM metricas WHERE lift > 1
)
SELECT r.item_a, pa.nome AS nome_a, r.item_b, pb.nome AS nome_b,
       pb.tipo AS tipo_b, pb.estilo_id AS estilo_b,
       r.n_juntos, r.pedidos_a, r.pedidos_b, r.suporte, r.confianca, r.lift, r.rank,
       (pa.estilo_id = pb.estilo_id) AS mesmo_estilo
FROM ranqueado r
JOIN {produtos} pa ON pa.produto_id = r.item_a
JOIN {produtos} pb ON pb.produto_id = r.item_b
WHERE r.rank <= {top_n}
"""
