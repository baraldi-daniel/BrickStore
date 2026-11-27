"""
📈 Previsão de vendas (ai_forecast) para gráfico: lê a view vw_vendas_previsao (real + previsto por departamento).

  previsao_vendas(departamento=None) -> {"departamentos": [...], "series": {depto: [{data, receita, inferior, superior, tipo}]},
                                         "resumo": [{departamento, real_4s, previsto_4s, inferior_4s, superior_4s, variacao_pct}]}
Sem departamento, devolve todos (e a série "Total" somada).
"""
from . import servicos as S


def _T(nome):
    """Pedidos/itens para LEITURA: view Delta + Lakebase (pedidos novos do App) quando disponível."""
    from .lakebase import tabela
    return tabela(nome)


def previsao_vendas(departamento: str | None = None) -> dict:
    filtro = "WHERE departamento = :d" if departamento else ""
    linhas = S.sql(f"""SELECT departamento, CAST(data AS STRING) AS data, receita, receita_inferior, receita_superior, tipo
                       FROM {S.fq('vw_vendas_previsao')} {filtro} ORDER BY departamento, data""",
                   {"d": departamento} if departamento else None)
    series: dict[str, list[dict]] = {}
    total: dict[tuple, dict] = {}
    for l in linhas:
        ponto = {"data": l["data"], "receita": l["receita"], "inferior": l["receita_inferior"],
                 "superior": l["receita_superior"], "tipo": l["tipo"]}
        series.setdefault(l["departamento"], []).append(ponto)
        t = total.setdefault((l["data"], l["tipo"]), {"data": l["data"], "receita": 0.0, "inferior": None, "superior": None, "tipo": l["tipo"]})
        t["receita"] += float(l["receita"] or 0)
        for k in ("inferior", "superior"):
            if ponto[k] is not None:
                t[k] = (t[k] or 0.0) + float(ponto[k])
    if not departamento and series:
        series["Total"] = sorted(total.values(), key=lambda p: p["data"])
    resumo = []
    for dep, pts in series.items():
        reais = [p for p in pts if p["tipo"] == "real"][-28:]
        prev = [p for p in pts if p["tipo"] == "previsto"][:28]
        r4 = sum(float(p["receita"] or 0) for p in reais)
        p4 = sum(float(p["receita"] or 0) for p in prev)
        resumo.append({"departamento": dep, "real_4s": round(r4, 2), "previsto_4s": round(p4, 2),
                       "inferior_4s": round(sum(float(p["inferior"] or 0) for p in prev), 2),
                       "superior_4s": round(sum(float(p["superior"] or 0) for p in prev), 2),
                       "variacao_pct": round(100 * (p4 / r4 - 1), 1) if r4 else None})
    resumo.sort(key=lambda r: -r["previsto_4s"])
    return {"departamentos": sorted(d for d in series if d != "Total"), "series": series, "resumo": resumo}


# ───────────────────────────── previsão SOB DEMANDA (ai_forecast na hora) ─────────────────────────────
import time
from datetime import date, timedelta

FILTROS = {"total": None, "departamento": "pr.departamento", "tipo": "pr.tipo", "produto": "pr.produto_id"}
METRICAS = {"receita": "sum(i.quantidade * i.preco_unitario)", "quantidade": "sum(i.quantidade)"}
GRANULARIDADES = {"dia": ("CAST(p.data_pedido AS DATE)", "day"), "semana": ("CAST(date_trunc('WEEK', p.data_pedido) AS DATE)", "week")}


def _sql_serie(filtro_tipo: str, metrica: str, granularidade: str, historico_dias: int, ate: date,
               incluir_hoje: bool = False) -> str:
    """Série com CALENDÁRIO COMPLETO: dia (ou semana) sem venda entra como 0. Sem isso, um produto que vende pouco
    (ex.: 30 dias com venda em 180) pareceria vender todo dia e a previsão sairia várias vezes acima do real.

    - a janela termina em `ate`, o ÚLTIMO DIA COM DADOS da loja (antes de hoje): dias depois dele não são "dias sem venda",
      são falta de dado, e entrar com 0 faria o ai_forecast prever queda (ex.: a loja inteira "caindo" a zero);
    - `incluir_hoje=True` acrescenta hoje (dia incompleto) só para MOSTRAR no gráfico a compra que acabou de ser feita;
      o modelo nunca treina com ele;
    - semana: só semanas INTEIRAS (7 dias dentro da janela).
    """
    coluna = FILTROS[filtro_tipo]
    where = f" AND {coluna} = :valor" if coluna else ""
    h = int(historico_dias)
    ate_sql = f"DATE'{ate.isoformat()}'"
    hoje_dia = incluir_hoje and granularidade == "dia"
    filtro_data = (f"(CAST(p.data_pedido AS DATE) <= {ate_sql} OR CAST(p.data_pedido AS DATE) = current_date())" if hoje_dia
                   else f"CAST(p.data_pedido AS DATE) <= {ate_sql}")
    vendas = (f"SELECT CAST(p.data_pedido AS DATE) AS dia, CAST({METRICAS[metrica]} AS DOUBLE) AS valor "
              f"FROM {_T('pedidos')} p JOIN {_T('itens_pedido')} i USING (pedido_id) JOIN {S.fq('produtos')} pr USING (produto_id) "
              f"WHERE p.status <> 'Cancelado' AND p.data_pedido >= date_sub({ate_sql}, {h}) AND {filtro_data}{where} GROUP BY 1")
    calendario = f"SELECT explode(sequence(date_sub({ate_sql}, {h}), {ate_sql}, INTERVAL 1 DAY)) AS dia"
    if hoje_dia and ate < date.today():
        calendario += " UNION ALL SELECT current_date() AS dia"
    if granularidade == "semana":
        return (f"SELECT CAST(date_trunc('WEEK', c.dia) AS DATE) AS data, sum(coalesce(v.valor, 0)) AS valor "
                f"FROM ({calendario}) c LEFT JOIN ({vendas}) v USING (dia) "
                f"GROUP BY 1 HAVING count(*) = 7")
    return f"SELECT c.dia AS data, coalesce(v.valor, 0) AS valor FROM ({calendario}) c LEFT JOIN ({vendas}) v USING (dia)"


def ultimo_dia_com_dados() -> date:
    """Último dia (antes de hoje) com algum pedido na loja; sem dados, ontem."""
    ontem = date.today() - timedelta(days=1)
    try:
        l = S.sql(f"""SELECT CAST(max(CAST(data_pedido AS DATE)) AS STRING) AS d FROM {_T('pedidos')}
                      WHERE status <> 'Cancelado' AND CAST(data_pedido AS DATE) < current_date()""")
        return min(ontem, date.fromisoformat(l[0]["d"])) if l and l[0].get("d") else ontem
    except Exception:
        return ontem


def prever(filtro_tipo: str = "total", valor: str | None = None, metrica: str = "receita", granularidade: str = "dia",
           historico_dias: int = 180, horizonte: int = 30) -> dict:
    """Monta a série de vendas escolhida pelo usuário e roda ai_forecast no warehouse, na hora.

    filtro_tipo ∈ total | departamento | tipo | produto (valor obrigatório exceto em total)
    metrica ∈ receita | quantidade · granularidade ∈ dia | semana · horizonte em dias (semana: arredonda para semanas)
    Tudo whitelistado; o único valor livre (`valor`) vai como parâmetro nomeado do statement execution.
    """
    if filtro_tipo not in FILTROS:
        raise ValueError(f"filtro_tipo deve ser um de {list(FILTROS)}")
    if metrica not in METRICAS:
        raise ValueError(f"metrica deve ser um de {list(METRICAS)}")
    if granularidade not in GRANULARIDADES:
        raise ValueError(f"granularidade deve ser um de {list(GRANULARIDADES)}")
    if FILTROS[filtro_tipo] and not valor:
        raise ValueError(f"informe o valor para o filtro «{filtro_tipo}»")
    historico_dias = max(28, min(int(historico_dias), 730))
    horizonte = max(1, min(int(horizonte), 180))
    freq = GRANULARIDADES[granularidade][1]
    hoje = date.today()
    fim = hoje + timedelta(days=horizonte)
    if granularidade == "semana":
        fim = hoje - timedelta(days=hoje.weekday()) + timedelta(weeks=max(1, round(horizonte / 7)))
    ate = ultimo_dia_com_dados()
    serie_sql = _sql_serie(filtro_tipo, metrica, granularidade, historico_dias, ate)                        # treina o modelo
    serie_tela = _sql_serie(filtro_tipo, metrica, granularidade, historico_dias, ate, incluir_hoje=True)    # mostra (inclui hoje)
    params = {"valor": valor} if FILTROS[filtro_tipo] else None
    sql_forecast = (f"SELECT CAST(data AS STRING) AS data, valor_forecast AS valor, valor_lower AS inferior, valor_upper AS superior "
                    f"FROM ai_forecast(observed => TABLE({serie_sql}), horizon => '{fim.isoformat()}', time_col => 'data', "
                    f"value_col => 'valor', prediction_interval_width => 0.8, frequency => '{freq}', seed => 7, "
                    f"parameters => '{{\"global_floor\": 0}}') ORDER BY data")
    t0 = time.perf_counter()
    real = S.sql(f"SELECT CAST(data AS STRING) AS data, round(valor, 2) AS valor FROM ({serie_tela}) ORDER BY data", params)
    t1 = time.perf_counter()
    for l in real:   # hoje está incompleto (só as compras feitas agora no App): a tela mostra como ponto à parte
        if l["data"] == hoje.isoformat():
            l["parcial"] = True
    com_venda = sum(1 for l in real if float(l["valor"] or 0) > 0 and not l.get("parcial"))
    erro = ("histórico curto demais para prever (menos de 8 períodos)" if len(real) < 8 else
            "sem vendas no período escolhido" if com_venda == 0 else
            "poucas vendas no período (menos de 3 períodos com venda) para uma previsão útil" if com_venda < 3 else None)
    if erro:
        return {"serie_real": real, "previsao": [], "erro": erro,
                "parametros": locals_params(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte, fim), "sql": sql_forecast}
    prev = S.sql(sql_forecast, params, timeout_s=300)
    t2 = time.perf_counter()
    ultimo_real = real[-1]["data"]
    previsao = [{"data": l["data"], "valor": round(float(l["valor"] or 0), 2), "inferior": round(float(l["inferior"] or 0), 2),
                 "superior": round(float(l["superior"] or 0), 2)} for l in prev if l["data"] > ultimo_real]
    # venda esparsa (ex.: produto com venda em poucos dias): a previsão vira uma média baixa com intervalo largo
    aviso = (f"venda esparsa: só {com_venda} de {len(real)} períodos tiveram venda; a previsão é uma média com incerteza alta"
             if com_venda < 0.3 * len(real) else None)
    return {"serie_real": real, "previsao": previsao, "aviso": aviso,
            "parametros": locals_params(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte, fim),
            "sql": sql_forecast, "ms": {"serie": round((t1 - t0) * 1000), "ai_forecast": round((t2 - t1) * 1000)}}


def locals_params(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte, fim) -> dict:
    return {"filtro_tipo": filtro_tipo, "valor": valor, "metrica": metrica, "granularidade": granularidade,
            "historico_dias": historico_dias, "horizonte": horizonte, "ate": fim.isoformat(), "intervalo": 0.8}


def opcoes() -> dict:
    """Valores para os seletores do App: departamentos, tipos e produtos (em ordem alfabética): os 300 de maior receita
    nos últimos 180 dias + todo produto comprado agora no App (com ou sem Lakebase). Os pedidos do App têm id
    P + data/hora (ex.: P261126164110); os do histórico, P + 7 dígitos (ex.: P0011655)."""
    no_app = "p.pedido_id RLIKE '^P[0-9]{12}$'"
    deps = S.sql(f"SELECT DISTINCT departamento FROM {S.fq('produtos')} ORDER BY departamento")
    tipos = S.sql(f"SELECT departamento, tipo, count(*) AS n FROM {S.fq('produtos')} GROUP BY ALL ORDER BY departamento, tipo")
    top = S.sql(f"""WITH vendas AS (
                      SELECT pr.produto_id, pr.nome, pr.departamento, round(sum(i.quantidade * i.preco_unitario), 2) AS receita,
                             max(CASE WHEN {no_app} THEN 1 ELSE 0 END) AS comprado_no_app
                      FROM {_T('pedidos')} p JOIN {_T('itens_pedido')} i USING (pedido_id) JOIN {S.fq('produtos')} pr USING (produto_id)
                      WHERE p.status <> 'Cancelado' AND p.data_pedido >= date_sub(current_date(), 180)
                      GROUP BY ALL)
                    SELECT produto_id, nome, departamento, receita FROM vendas
                    QUALIFY row_number() OVER (ORDER BY receita DESC) <= 300 OR comprado_no_app = 1
                    ORDER BY nome""")
    return {"filtros": list(FILTROS), "metricas": list(METRICAS), "granularidades": list(GRANULARIDADES),
            "departamentos": [d["departamento"] for d in deps],
            "tipos": [{"tipo": t["tipo"], "departamento": t["departamento"]} for t in tipos],
            "produtos": top}
