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


def _sql_serie(filtro_tipo: str, metrica: str, granularidade: str, historico_dias: int) -> str:
    col_data, _ = GRANULARIDADES[granularidade]
    coluna = FILTROS[filtro_tipo]
    where = f" AND {coluna} = :valor" if coluna else ""
    corte = "date_trunc('WEEK', current_date())" if granularidade == "semana" else "current_date()"
    base = (f"SELECT {col_data} AS data, CAST({METRICAS[metrica]} AS DOUBLE) AS valor, "
            f"count(DISTINCT CAST(p.data_pedido AS DATE)) AS dias "
            f"FROM {_T('pedidos')} p JOIN {_T('itens_pedido')} i USING (pedido_id) JOIN {S.fq('produtos')} pr USING (produto_id) "
            f"WHERE p.status <> 'Cancelado' AND p.data_pedido >= date_sub(current_date(), {int(historico_dias)}) "
            f"AND p.data_pedido < {corte}{where} GROUP BY 1")
    # semana: só semanas completas (a primeira e a última da janela costumam vir pela metade)
    return f"SELECT data, valor FROM ({base}) WHERE {'dias >= 7' if granularidade == 'semana' else 'true'}"


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
    serie_sql = _sql_serie(filtro_tipo, metrica, granularidade, historico_dias)
    params = {"valor": valor} if FILTROS[filtro_tipo] else None
    sql_forecast = (f"SELECT CAST(data AS STRING) AS data, valor_forecast AS valor, valor_lower AS inferior, valor_upper AS superior "
                    f"FROM ai_forecast(observed => TABLE({serie_sql}), horizon => '{fim.isoformat()}', time_col => 'data', "
                    f"value_col => 'valor', prediction_interval_width => 0.8, frequency => '{freq}', seed => 7, "
                    f"parameters => '{{\"global_floor\": 0}}') ORDER BY data")
    t0 = time.perf_counter()
    real = S.sql(f"SELECT CAST(data AS STRING) AS data, round(valor, 2) AS valor FROM ({serie_sql}) ORDER BY data", params)
    t1 = time.perf_counter()
    if len(real) < 8:
        return {"serie_real": real, "previsao": [], "erro": "histórico curto demais para prever (menos de 8 pontos)",
                "parametros": locals_params(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte, fim), "sql": sql_forecast}
    prev = S.sql(sql_forecast, params, timeout_s=300)
    t2 = time.perf_counter()
    ultimo_real = real[-1]["data"]
    previsao = [{"data": l["data"], "valor": round(float(l["valor"] or 0), 2), "inferior": round(float(l["inferior"] or 0), 2),
                 "superior": round(float(l["superior"] or 0), 2)} for l in prev if l["data"] > ultimo_real]
    return {"serie_real": real, "previsao": previsao,
            "parametros": locals_params(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte, fim),
            "sql": sql_forecast, "ms": {"serie": round((t1 - t0) * 1000), "ai_forecast": round((t2 - t1) * 1000)}}


def locals_params(filtro_tipo, valor, metrica, granularidade, historico_dias, horizonte, fim) -> dict:
    return {"filtro_tipo": filtro_tipo, "valor": valor, "metrica": metrica, "granularidade": granularidade,
            "historico_dias": historico_dias, "horizonte": horizonte, "ate": fim.isoformat(), "intervalo": 0.8}


def opcoes() -> dict:
    """Valores para os seletores do App: departamentos, tipos e top 50 produtos por receita (últimos 180 dias)."""
    deps = S.sql(f"SELECT DISTINCT departamento FROM {S.fq('produtos')} ORDER BY departamento")
    tipos = S.sql(f"SELECT departamento, tipo, count(*) AS n FROM {S.fq('produtos')} GROUP BY ALL ORDER BY departamento, tipo")
    top = S.sql(f"""SELECT pr.produto_id, pr.nome, pr.departamento, round(sum(i.quantidade * i.preco_unitario), 2) AS receita
                    FROM {_T('pedidos')} p JOIN {_T('itens_pedido')} i USING (pedido_id) JOIN {S.fq('produtos')} pr USING (produto_id)
                    WHERE p.status <> 'Cancelado' AND p.data_pedido >= date_sub(current_date(), 180)
                    GROUP BY ALL ORDER BY receita DESC LIMIT 50""")
    return {"filtros": list(FILTROS), "metricas": list(METRICAS), "granularidades": list(GRANULARIDADES),
            "departamentos": [d["departamento"] for d in deps],
            "tipos": [{"tipo": t["tipo"], "departamento": t["departamento"]} for t in tipos],
            "produtos": top}
