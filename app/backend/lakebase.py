"""
🐘 Lakebase (Postgres OLTP) — onde o App grava os pedidos NOVOS, as solicitações de pós-venda e a MEMÓRIA do Assistente
(loja.conversas, veja backend/memoria.py).

  App ──INSERT (~0,2 s)──► Lakebase  loja.pedidos / loja.itens_pedido / loja.solicitacoes_atendimento
                              │
                              │  database registrado no Unity Catalog como catálogo <catalog>_loja (leitura AO VIVO)
                              ▼
  Lakehouse  <catalog>.<schema>.vw_pedidos_todos = histórico Delta  UNION ALL  <catalog>_loja.loja.pedidos
             (o Genie, o Agente Analista e "Meus pedidos" leem estas views: o pedido aparece em ~1 s)

Conexão: endpoint em NB_LAKEBASE_ENDPOINT (app.yaml) ou LAKEBASE_ENDPOINT/PGHOST/PGUSER (quando a plataforma injeta);
usuário = service principal do App; senha = token OAuth (vale 1 h — renovamos a cada 40 min).
Se o Lakebase não estiver configurado ou falhar, quem chama usa a reserva: gravar/ler no Delta pelo SQL warehouse.
"""
import logging
import os
import threading
import time

from . import servicos as S

log = logging.getLogger("varejo")

SCHEMA_PG = os.environ.get("NB_LAKEBASE", "").strip()            # ex.: "loja" (vazio = Lakebase desligado)
CATALOGO_UC = os.environ.get("NB_LAKEBASE_CATALOG", "").strip()  # ex.: "brickstore_loja"
# endpoint: injetado pela plataforma (LAKEBASE_ENDPOINT) ou definido no app.yaml (NB_LAKEBASE_ENDPOINT)
ENDPOINT = (os.environ.get("LAKEBASE_ENDPOINT") or os.environ.get("NB_LAKEBASE_ENDPOINT") or "").strip()
_lock = threading.Lock()
_estado = {"conn": None, "desde": 0.0, "host": os.environ.get("PGHOST", "")}


def ativo() -> bool:
    return bool(SCHEMA_PG and ENDPOINT)


def _host() -> str:
    if not _estado["host"]:
        _estado["host"] = S.ws().postgres.get_endpoint(name=ENDPOINT).status.hosts.host
    return _estado["host"]


def views_ativas() -> bool:
    """As views vw_*_todos (Delta + Lakebase) existem quando o database está registrado no UC."""
    return bool(CATALOGO_UC)


def tabela(nome: str) -> str:
    """Nome UC para LER: a view unificada (histórico + novos) se o Lakebase estiver no UC; senão a tabela Delta."""
    return S.fq({"pedidos": "vw_pedidos_todos", "itens_pedido": "vw_itens_pedido_todos",
                 "solicitacoes_atendimento": "vw_solicitacoes_todas"}[nome]) if views_ativas() else S.fq(nome)


def _conectar():
    import psycopg
    token = S.ws().postgres.generate_database_credential(endpoint=ENDPOINT).token
    usuario = os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID")   # role da service principal do App
    return psycopg.connect(host=_host(), port=int(os.environ.get("PGPORT", "5432")),
                           dbname=os.environ.get("PGDATABASE", "databricks_postgres"), user=usuario,
                           password=token, sslmode="require", autocommit=False, connect_timeout=10,
                           options="-c statement_timeout=8000")   # nenhuma consulta segura o lock por mais de 8 s


def _descartar():
    if _estado["conn"] is not None:
        try:
            _estado["conn"].close()
        except Exception:
            pass
    _estado["conn"] = None


def _rodar(fn):
    """Roda fn(conexão) numa transação. Reconecta 1 vez só se a CONEXÃO falhou (queda, token vencido);
    erro de SQL (tabela ausente, constraint) sobe direto, sem gastar outra conexão."""
    import psycopg
    for tentativa in range(2):
        with _lock:
            try:
                if _estado["conn"] is None or _estado["conn"].closed or time.time() - _estado["desde"] > 2400:
                    _descartar()
                    _estado.update(conn=_conectar(), desde=time.time())
                c = _estado["conn"]
                with c.transaction():
                    return fn(c)
            except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                _descartar()
                if tentativa == 1:
                    raise
                log.warning("Lakebase: reconectando (%s)", str(e)[:120])
            except Exception:
                if _estado["conn"] is not None and _estado["conn"].broken:
                    _descartar()
                raise


def executar(comandos: list[tuple[str, dict | tuple | None]]) -> None:
    """Executa os comandos numa única transação."""
    def fn(c):
        for sql, params in comandos:
            c.execute(sql, params)
    _rodar(fn)


def consultar(sql: str, params: dict | tuple | None = None) -> list[dict]:
    """SELECT no Postgres. Devolve linhas como dicionários."""
    def fn(c):
        cur = c.execute(sql, params)
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, linha)) for linha in cur.fetchall()]
    return _rodar(fn)


def gravar_pedido(pid: str, cliente_id: str, parcelas: int, total: float, frete: float, itens: list[tuple[str, int, float]]):
    s = SCHEMA_PG
    cmds = [(f"""INSERT INTO {s}.pedidos (pedido_id, cliente_id, data_pedido, canal, loja, forma_pagamento, parcelas, status,
                                         valor_total, frete)
                 VALUES (%s, %s, now(), 'App', NULL, 'Cartão', %s, 'Em transporte', %s, %s)""",
             (pid, cliente_id, parcelas, total, frete))]
    cmds += [(f"INSERT INTO {s}.itens_pedido (pedido_id, produto_id, quantidade, preco_unitario, desconto) VALUES (%s, %s, %s, %s, 0.0)",
              (pid, prod, q, v)) for prod, q, v in itens]
    executar(cmds)


def gravar_solicitacao(protocolo: str, cliente_id: str, pedido_id: str, produto_id: str | None, tipo: str, motivo: str,
                       status: str, prazo: str):
    executar([(f"""INSERT INTO {SCHEMA_PG}.solicitacoes_atendimento (protocolo, cliente_id, pedido_id, produto_id, tipo, motivo,
                                                                     status, prazo, aberto_em)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())""",
                (protocolo, cliente_id, pedido_id, produto_id, tipo, motivo[:500], status, prazo))])
