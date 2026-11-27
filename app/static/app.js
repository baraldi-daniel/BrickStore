/* ═══════════════════════════════════════════════════════════════════
   Frontend do marketplace (JavaScript puro, sem build). Marca vem de GET /api/config.
   Rotas por hash: #/inicio · #/departamento/<nome> · #/estilos · #/estilo/<id>
     #/produto/<id> · #/busca?q=… · #/pedidos · #/detetive · #/estudio/<aba>
   Contrato da API: docs/ESPEC_VAREJO.md ("API do App (JSON)").
   Carrinho e perfil ficam em localStorage (bm_carrinho, bm_perfil).
   ═══════════════════════════════════════════════════════════════════ */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const lerJSON = (k, fb) => { try { return JSON.parse(localStorage.getItem(k)) ?? fb; } catch { return fb; } };

const E = {
  marca: { marca: "Loja", slogan: "", dominio: "" },   // nome real vem de GET /api/config
  perfil: lerJSON("bm_perfil", null),
  perfis: [], estilos: [], departamentos: [],
  carrinho: lerJSON("bm_carrinho", []),
  cache: {},          // produto_id → produto (alimentado por todas as respostas)
  tok: 0,             // token da navegação atual (descarta respostas atrasadas)
  chat: [], anexo: null,
  admin: localStorage.getItem("bm_admin") === "1",   // modo admin: mostra o Estúdio (dados de todos os clientes)
};

const LOGO_SVG = `<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 4 28 10.5 16 17 4 10.5Z" fill="#FF3621"/><path d="M4 15.5 16 22 28 15.5" fill="none" stroke="#FF5F46" stroke-width="3.2" stroke-linejoin="round"/><path d="M4 21.2 16 27.7 28 21.2" fill="none" stroke="#FF3621" stroke-width="3.2" stroke-linejoin="round" opacity=".7"/></svg>`;
const ICO = {
  busca: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  sacola: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M5 8h14l-1 12.5H6z"/><path d="M9 8V6.5a3 3 0 0 1 6 0V8"/></svg>',
  seta: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  setaE: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
  fechar: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  chev: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg>',
  caminhao: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M2 6h12v10H2zM14 10h4l3 3v3h-7z"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>',
  troca: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9a8 8 0 0 1 14-3l2 2M20 15a8 8 0 0 1-14 3l-2-2"/><path d="M20 4v4h-4M4 20v-4h4"/></svg>',
  cartao: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19M6 15h4"/></svg>',
  upload: '<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4M7 9l5-5 5 5"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/></svg>',
  doc: '<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/></svg>',
};

/* ───────────── utilidades ───────────── */
const ROTULO_CATEGORIA = {jailbreak: "tentativa de jailbreak", outro_cliente: "dados de outra conta", fora_do_escopo: "fora do escopo",
  ofensivo: "conteúdo ofensivo", vazamento_prompt: "vazamento do prompt", sem_cliente: "sem cliente logado",
  ferramenta_nao_permitida: "ferramenta não permitida", acesso_outro_cliente: "acesso a outra conta", sem_fundamentacao: "sem fundamentação",
  unity_gateway: "service policy do Unity Gateway"};
function rotuloGuardrail(g) {
  const cat = ROTULO_CATEGORIA[g.categoria] || (g.categoria || "").replaceAll("_", " ");
  if (g.categoria === "dados_sensiveis") return `Dados sensíveis mascarados (${g.detalhe || ""})${g.fase === "saida" ? " na resposta" : ""}`;
  return {bloqueado: "Bloqueado", negado: "Negado", corrigido: "Corrigido", sinalizado: "Sinalizado"}[g.acao] + ": " + cat;
}

async function api(caminho, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) { o.method = o.method || "POST"; o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(o.json); delete o.json; }
  let r;
  try { r = await fetch(caminho, o); } catch { throw new Error("Sem conexão com o servidor."); }
  if (!r.ok) {
    let msg = `Erro ${r.status}`;
    try {
      const j = await r.json(); const d = j.detail ?? j.erro ?? j.message;
      if (d) msg = typeof d === "string" ? d : (Array.isArray(d) ? d.map(x => x.msg || JSON.stringify(x)).join("; ") : JSON.stringify(d));
    } catch { }
    throw new Error(msg);
  }
  return r.json();
}
const apiForm = (caminho, fd) => api(caminho, { method: "POST", body: fd });
// Progresso REAL de tarefas longas: o backend registra a etapa em que está; a tela consulta enquanto espera
function acompanhar(aoPasso) {
  const tarefa = "t" + Math.random().toString(36).slice(2, 12);
  let ativo = true, ultimo = -1;
  (async () => {
    while (ativo) {
      try { const r = await api("/api/progresso/" + tarefa); if (ativo && r.passo !== ultimo && r.passo >= 0) { ultimo = r.passo; aoPasso(r.passo); } } catch { }
      await new Promise(ok => setTimeout(ok, 700));
    }
  })();
  return { tarefa, parar: () => { ativo = false; } };
}
const primeiroNome = a => String(a || "").split(/[\s·]+/)[0];
const iniciais = nome => String(nome || "?").replace(/[^A-Za-zÀ-ÿ ]/g, " ").split(" ").filter(Boolean).slice(0, 2).map(s => s[0]).join("").toUpperCase() || "?";
const nomeEstiloOuId = id => nomeEstilo(id);

function toast(html, ms = 4200, classe = "") {
  const t = document.createElement("div");
  t.className = "toast " + classe;
  t.innerHTML = `${html}<button class="toast-x" data-fechar aria-label="Fechar">${ICO.fechar}</button>`;
  $("#toasts").appendChild(t);
  if (ms) setTimeout(() => { t.classList.add("saindo"); setTimeout(() => t.remove(), 300); }, ms);
  return t;
}
const dataEntrega = iso => { const d = new Date(iso + "T12:00:00"); return isNaN(d) ? iso : d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" }); };
const botaoAgenda = pid => `<button class="btn btn-agenda" data-agendar="${escHTML(pid)}">Adicionar a chegada à minha agenda</button>`;
async function agendarEntrega(pid, botao) {
  if (!E.perfil || !E.perfil.cliente_id) { telaPerfis(); return; }
  const txt = botao ? botao.innerHTML : "";
  if (botao) { botao.disabled = true; botao.innerHTML = `<span class="spin"></span> Criando o evento…`; }
  try {
    const r = await api("/api/agenda/entrega", { json: { pedido_id: pid, cliente_id: E.perfil.cliente_id } });
    if (r.erro) throw new Error(r.erro);
    toast(agendaHTML(r), 15000, r.criado ? "sucesso" : "");
    if (botao) { botao.innerHTML = r.criado ? "Na sua agenda" : txt; botao.disabled = !!r.criado; }
  } catch (e) { toastErro(e); if (botao) { botao.disabled = false; botao.innerHTML = txt; } }
}
function agendaHTML(r) {
  const quando = dataEntrega(r.previsao_entrega);
  if (r.criado) return `<div class="toast-txt agenda-ok"><b>Evento criado no seu Google Agenda</b><span>«${escHTML(r.titulo)}» em ${escHTML(quando)} · via ${escHTML(r.via)}</span>
    ${r.evento_link ? `<a class="btn btn-sm" href="${escHTML(r.evento_link)}" target="_blank" rel="noopener">Abrir o evento</a>` : ""}</div>`;
  return `<div class="toast-txt"><b>Chegada prevista: ${escHTML(quando)}</b><span>${escHTML(r.aviso || "Adicione o lembrete à sua agenda:")}</span>
    <div class="agenda-acoes"><a class="btn btn-sm btn-lava" href="${escHTML(r.link_google)}" target="_blank" rel="noopener">Google Agenda</a>
    <a class="btn btn-sm" href="${escHTML(r.ics_url)}">Baixar .ics</a></div></div>`;
}
const toastErro = e => toast(`<div class="toast-txt"><b>Algo deu errado</b><span>${escHTML(e.message || e)}</span></div>`, 6000, "erro");

function reg(lista) {
  (lista || []).forEach(p => { if (p && p.produto_id) E.cache[p.produto_id] = { ...(E.cache[p.produto_id] || {}), ...p }; });
  return lista || [];
}
const cards = (lista, opts = {}) => reg(lista).map((p, i) => produtoHTML(p, typeof opts === "function" ? opts(p, i) : opts)).join("");
async function buscarProduto(id) {
  const p = await api("/api/produto/" + encodeURIComponent(id));
  reg([p]); return p;
}

/* markdown mínimo (respostas do assistente) */
function md(txt) {
  const linhas = escHTML(txt || "").split("\n"); let html = "", lista = null, tabela = [];
  const inline = s => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<i>$2</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  const fecharLista = () => { if (lista) { html += `</${lista}>`; lista = null; } };
  const fecharTabela = () => {
    if (!tabela.length) return;
    const rows = tabela.filter(l => !/^\s*\|?\s*:?-{2,}/.test(l)).map(l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => inline(c.trim())));
    html += "<div class='tab-wrap'><table>" + rows.map((r, i) => "<tr>" + r.map(c => i ? `<td>${c}</td>` : `<th>${c}</th>`).join("") + "</tr>").join("") + "</table></div>"; tabela = [];
  };
  for (const l of linhas) {
    if (/^\s*\|.*\|\s*$/.test(l)) { fecharLista(); tabela.push(l); continue; } else fecharTabela();
    let m;
    if ((m = l.match(/^\s*[-•*]\s+(.*)/))) { if (lista !== "ul") { fecharLista(); html += "<ul>"; lista = "ul"; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (lista !== "ol") { fecharLista(); html += "<ol>"; lista = "ol"; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = l.match(/^#{1,4}\s+(.*)/))) { fecharLista(); html += `<p><b>${inline(m[1])}</b></p>`; }
    else if (l.trim()) { fecharLista(); html += `<p>${inline(l)}</p>`; }
  }
  fecharLista(); fecharTabela(); return html;
}

/* ───────────── blocos reutilizáveis ───────────── */
const carregandoHTML = () => `<div class="carregando"><span class="spin"></span><span>Carregando…</span></div>`;
const erroPagina = e => `<div class="container pagina"><div class="vazio-grande"><b>Não foi possível carregar esta página</b><span>${escHTML(e.message || e)}</span><a class="btn btn-borda" href="#/inicio">Voltar para a loja</a></div></div>`;
function cabecalhoPagina({ kicker = "", titulo = "", sub = "", extra = "" }) {
  return `<header class="cab-pagina"><div class="container">
    ${kicker ? `<span class="kicker">${escHTML(kicker)}</span>` : ""}
    <h1>${titulo}</h1>${sub ? `<p>${escHTML(sub)}</p>` : ""}${extra}</div></header>`;
}
function trilhoHTML(itens) {
  return `<div class="trilho-wrap"><button class="seta esq" aria-label="Anterior">${ICO.setaE}</button><div class="trilho">${itens}</div><button class="seta dir" aria-label="Próximo">${ICO.seta}</button></div>`;
}
function ligarTrilhos(raiz = document) {
  $$(".trilho-wrap", raiz).forEach(w => {
    const t = $(".trilho", w);
    const estado = () => { w.classList.toggle("tem-esq", t.scrollLeft > 8); w.classList.toggle("tem-dir", t.scrollLeft < t.scrollWidth - t.clientWidth - 8); };
    t.addEventListener("scroll", estado, { passive: true });
    requestAnimationFrame(estado);
    $(".seta.esq", w).onclick = () => t.scrollBy({ left: -t.clientWidth * .8, behavior: "smooth" });
    $(".seta.dir", w).onclick = () => t.scrollBy({ left: t.clientWidth * .8, behavior: "smooth" });
  });
}
function fileiraHTML(f) {
  if (!f.itens || !f.itens.length) return "";
  reg(f.itens);
  const tipo = f.estilo || "";
  const tag = { associacao: "Quem comprou também comprou", destaque: "Novidade do Estúdio", oferta: "Ofertas", ranking: "Ranking", ml: "IA · Machine Learning" }[tipo] || "";
  const base = f.base && E.cache[f.base];
  const itens = f.itens.map((p, i) => produtoHTML(p, {
    rank: tipo === "ranking" ? i + 1 : null, classe: tipo === "ranking" ? "com-rank" : "",
    novo: tipo === "destaque", semAssoc: false,
  })).join("");
  return `<section class="fileira f-${escHTML(tipo || "padrao")}">
    <header class="fileira-cab"><div><h2>${escHTML(f.titulo)}</h2>
      ${f.subtitulo || base ? `<p>${base ? `Com base em <b>${escHTML(base.nome)}</b>` : escHTML(f.subtitulo)}</p>` : ""}</div>
      ${tag ? `<span class="tag-f">${tag}</span>` : ""}</header>
    ${trilhoHTML(itens)}</section>`;
}
function rodapeHTML() {
  return `<footer class="rodape"><div class="container rodape-in">
    <div class="rodape-marca"><span class="logo-mark">${LOGO_SVG}</span><div><b>${escHTML(E.marca.marca || "Loja")}</b><p>${escHTML(E.marca.slogan || "")}</p></div></div>
    <p class="rodape-nota">Dados 100% fictícios · Databricks (Delta, Unity Catalog, Vector Search, Genie, Apps e MCP)</p>
  </div></footer>`;
}
const chipsHTML = () => `<div class="bloco-chips">
  <div class="chips-linha">${E.departamentos.map(d => `<a class="chip" href="#/departamento/${encodeURIComponent(d.nome)}">${escHTML(d.nome)}</a>`).join("")}</div>
  <div class="chips-linha">${E.estilos.map(e => { const c = coresEstilo(e.estilo_id); return `<a class="chip est" href="#/estilo/${encodeURIComponent(e.estilo_id)}" style="--c0:${c[0]};--c1:${c[1]};--c2:${c[2]}"><i></i>${escHTML(e.nome)}</a>`; }).join("")}</div></div>`;

/* filtros (preço, ordenação, tipo) para grades de departamento / estilo */
function filtrosGrade(lista) {
  const tipos = [...new Set(lista.map(p => p.tipo).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  const maxP = Math.max(10, Math.ceil(Math.max(0, ...lista.map(precoVigente)) / 10) * 10);
  return `<div class="container">
    <div class="barra-filtros" data-filtros>
      <div class="chips-tipo">${tipos.length > 1 ? `<button class="chip-f ativo" data-tipo="">Todos</button>${tipos.map(t => `<button class="chip-f" data-tipo="${escHTML(t)}">${escHTML(t)}</button>`).join("")}` : ""}</div>
      <div class="filtros-dir">
        <label class="campo-f">Até <input type="range" min="10" max="${maxP}" step="10" value="${maxP}" data-precomax><output>${reais(maxP)}</output></label>
        <label class="campo-f">Ordenar <select data-ordem>
          <option value="rel">Relevância</option><option value="menor">Menor preço</option><option value="maior">Maior preço</option>
          <option value="nota">Melhor avaliação</option><option value="novo">Lançamentos</option></select></label>
      </div></div>
    <p class="contagem" data-contagem></p>
    <div class="grade" data-grade></div>
    <p class="vazio oculto" data-vazio>Nenhum produto com esses filtros.</p></div>`;
}
function ligarFiltros(raiz, lista) {
  const barra = $("[data-filtros]", raiz), grade = $("[data-grade]", raiz);
  let tipo = "";
  const ordenar = {
    menor: (a, b) => precoVigente(a) - precoVigente(b), maior: (a, b) => precoVigente(b) - precoVigente(a),
    nota: (a, b) => (b.avaliacao || 0) - (a.avaliacao || 0), novo: (a, b) => (b.lancamento ? 1 : 0) - (a.lancamento ? 1 : 0),
  };
  const aplicar = () => {
    const max = Number($("[data-precomax]", raiz).value), ord = $("[data-ordem]", raiz).value;
    let r = lista.filter(p => (!tipo || p.tipo === tipo) && precoVigente(p) <= max);
    if (ordenar[ord]) r = [...r].sort(ordenar[ord]);
    grade.innerHTML = cards(r);
    $("[data-vazio]", raiz).classList.toggle("oculto", r.length > 0);
    $("[data-contagem]", raiz).textContent = `${numPT(r.length)} de ${numPT(lista.length)} produtos`;
  };
  barra.addEventListener("click", e => {
    const b = e.target.closest("[data-tipo]"); if (!b) return;
    tipo = b.dataset.tipo; $$(".chip-f", barra).forEach(x => x.classList.toggle("ativo", x === b)); aplicar();
  });
  $("[data-precomax]", raiz).oninput = e => { $("output", barra).textContent = reais(e.target.value); aplicar(); };
  $("[data-ordem]", raiz).onchange = aplicar;
  aplicar();
}

/* ───────────── carrinho (localStorage) ───────────── */
const salvarCarrinho = () => { localStorage.setItem("bm_carrinho", JSON.stringify(E.carrinho)); atualizarContador(); renderGaveta(); };
const totalItens = () => E.carrinho.reduce((s, i) => s + i.quantidade, 0);
const subtotal = () => E.carrinho.reduce((s, i) => s + precoVigente(i) * i.quantidade, 0);
const FRETE_GRATIS_ACIMA = 199, FRETE_TAXA = 19.9;
const frete = () => {
  if (!E.carrinho.length || subtotal() >= FRETE_GRATIS_ACIMA || E.carrinho.every(i => i.frete_gratis)) return 0;
  return FRETE_TAXA;
};
function atualizarContador() { const n = totalItens(); const el = $("#contador"); el.textContent = n; el.classList.toggle("oculto", !n); }
function addCarrinho(p, { qtd = 1, tamanho = null, aviso = true } = {}) {
  if (!p) return;
  const i = E.carrinho.find(x => x.produto_id === p.produto_id);
  if (i) { i.quantidade += qtd; if (tamanho) i.tamanho = tamanho; }
  else E.carrinho.push({
    produto_id: p.produto_id, nome: p.nome, marca_produto: p.marca_produto, departamento: p.departamento, tipo: p.tipo,
    icone: p.icone, cor_hex: p.cor_hex, estilo_id: p.estilo_id, preco: Number(p.preco),
    preco_promocional: p.preco_promocional ?? null, imagem_path: p.imagem_path ?? null, origem: p.origem,
    quantidade: qtd, tamanho, frete_gratis: p.frete_gratis === true, vendedor: p.vendedor ?? null,
  });
  salvarCarrinho();
  if (aviso) toast(`<div class="toast-add"><div class="toast-foto">${fotoHTML(p)}</div><div class="toast-txt"><b>Adicionado à sacola</b><span>${escHTML(p.nome)}</span>
    <button class="link" data-abrir-sacola>Ver sacola (${totalItens()})</button></div></div>`, 3800);
}
function alterarQtd(pid, delta) {
  const i = E.carrinho.find(x => x.produto_id === pid); if (!i) return;
  i.quantidade += delta;
  if (i.quantidade < 1) E.carrinho = E.carrinho.filter(x => x !== i);
  salvarCarrinho();
}
function renderGaveta() {
  const g = $("#gaveta-itens"), r = $("#gaveta-resumo");
  if (!E.carrinho.length) {
    g.innerHTML = `<div class="gaveta-vazia">${ICO.sacola}<b>Sua sacola está vazia</b><span>Explore os departamentos ou mande a foto de um produto para o Detetive.</span>
      <a class="btn btn-lava" href="#/inicio" data-fechar-gaveta>Continuar comprando</a></div>`;
    r.innerHTML = ""; return;
  }
  g.innerHTML = E.carrinho.map(i => `<div class="g-item">
      <div class="g-foto">${fotoHTML(i)}</div>
      <div class="g-txt"><b>${escHTML(i.nome)}</b><span>${escHTML(i.marca_produto || "")}${i.tamanho ? ` · Tam. ${escHTML(i.tamanho)}` : ""}</span>
        <div class="g-linha"><div class="qtd sm"><button data-qtd="-1" data-pid="${escHTML(i.produto_id)}" aria-label="Diminuir">−</button><output>${i.quantidade}</output><button data-qtd="1" data-pid="${escHTML(i.produto_id)}" aria-label="Aumentar">+</button></div>
        <div class="g-preco">${reais(precoVigente(i) * i.quantidade)}</div></div>
        <button class="link-x" data-remover="${escHTML(i.produto_id)}">Remover</button></div></div>`).join("");
  const f = frete();
  r.innerHTML = `<div class="res-linha"><span>Subtotal</span><b>${reais(subtotal())}</b></div>
    <div class="res-linha"><span>Frete</span><b>${f ? reais(f) : "Grátis"}</b></div>
    ${f ? `<p class="res-nota">Frete grátis acima de ${reais(FRETE_GRATIS_ACIMA)} ou em produtos com frete grátis.</p>` : ""}
    <div class="res-total"><span>Total</span><b>${reais(subtotal() + f)}</b></div>
    <button class="btn btn-lava btn-grande btn-cheio" data-finalizar>Finalizar pedido</button>`;
}
function abrirGaveta() { renderGaveta(); $("#gaveta").classList.add("aberta"); $("#gaveta-fundo").classList.add("aberta"); }
function fecharGaveta() { $("#gaveta").classList.remove("aberta"); $("#gaveta-fundo").classList.remove("aberta"); }

async function finalizarPedido() {
  if (!E.carrinho.length) return;
  if (!E.perfil || !E.perfil.cliente_id) {
    fecharGaveta(); toast(`<div class="toast-txt"><b>Escolha quem está comprando</b><span>Para finalizar o pedido, selecione um perfil de cliente.</span></div>`);
    telaPerfis(); return;
  }
  const b = $("[data-finalizar]"); if (b) { b.disabled = true; b.innerHTML = `<span class="spin"></span> Finalizando…`; }
  try {
    const r = await api("/api/pedido", { json: { cliente_id: E.perfil.cliente_id, itens: E.carrinho.map(i => ({ produto_id: i.produto_id, quantidade: i.quantidade })) } });
    E.carrinho = []; salvarCarrinho(); fecharGaveta();
    const sug = reg(r.sugestoes || []).slice(0, 3);
    toast(`<div class="toast-pedido"><div class="tp-cab"><span class="ok-bolinha">✓</span><div><b>Pedido ${escHTML(r.pedido_id)} confirmado</b><span>Total ${reais(r.valor_total)} · acompanhe em Meus pedidos</span></div></div>
      ${r.previsao_entrega ? `<p class="tp-entrega">Chega ${escHTML(dataEntrega(r.previsao_entrega))}</p>` + (r.agenda && r.agenda.criado
        ? `<p class="tp-agenda-ok">Já está na sua agenda${r.agenda.evento_link ? ` · <a href="${escHTML(r.agenda.evento_link)}" target="_blank" rel="noopener">abrir o evento</a>` : ""}</p>`
        : botaoAgenda(r.pedido_id)) : ""}
      ${sug.length ? `<p class="tp-sug">Quem comprou também levou</p><div class="tp-lista">${sug.map(p => miniProdutoHTML(p)).join("")}</div>` : ""}</div>`, 15000, "sucesso");
  } catch (e) { toastErro(e); renderGaveta(); }
}

/* ───────────── perfil ───────────── */
function avatarHTML(p, tam = "") {
  return `<span class="avatar ${tam}" style="--cor:${hexOK(p?.cor, "#7a8792")}">${escHTML(iniciais(p?.apelido || p?.nome))}</span>`;
}
/* ───────────── modo admin ───────────── */
function aplicarAdmin() {
  document.body.classList.toggle("admin", E.admin);
  const cb = $("#modo-admin"); if (cb) cb.checked = E.admin;
}
$("#modo-admin").onchange = e => {
  E.admin = e.target.checked; localStorage.setItem("bm_admin", E.admin ? "1" : "0"); aplicarAdmin();
  if (!E.admin && location.hash.startsWith("#/estudio")) location.hash = "#/inicio"; else if (E.admin) rotear();
};
function atualizarPerfil() {
  const b = $("#btn-perfil");
  b.innerHTML = avatarHTML(E.perfil);
  b.title = `Quem está comprando: ${E.perfil?.apelido || "Visitante"} (trocar)`;
}
function fecharPerfis() { $("#tela-perfis").classList.remove("aberta"); }
function telaPerfis() {
  $("#tela-perfis").classList.add("aberta");
  $("#fechar-perfis").classList.toggle("oculto", !E.perfil);   // só dá para fechar se já houver um perfil escolhido
  $("#lista-perfis").innerHTML = E.perfis.map(p => `<button class="perfil" data-cliente="${escHTML(p.cliente_id)}">
      ${avatarHTML(p, "grande")}<b>${escHTML(p.apelido)}</b><small>${escHTML(p.nome || "")}</small>
      <em>${escHTML(nomeEstilo(p.estilo_favorito))} · ${numPT(p.n_pedidos)} pedidos</em></button>`).join("")
    + `<button class="perfil visitante" data-cliente=""><span class="avatar grande vis">+</span><b>Visitante</b><small>navegar sem histórico</small><em>&nbsp;</em></button>`;
}
function escolherPerfil(id) {
  const trocou = (E.perfil?.cliente_id ?? "") !== (id ?? "");
  if (trocou && E.chat && (E.chat.length || $("#chat-msgs").children.length)) {   // conversa é de um cliente: troca de perfil → começa de novo
    E.chat = []; E.conversaId = null; $("#chat-msgs").innerHTML = "";
  }
  E.perfil = id ? E.perfis.find(p => p.cliente_id === id) : { cliente_id: null, apelido: "Visitante", nome: "", cor: "#7a8792" };
  localStorage.setItem("bm_perfil", JSON.stringify(E.perfil));
  $("#tela-perfis").classList.remove("aberta");
  atualizarPerfil(); rotear();
  if (trocou && !$("#chat").classList.contains("oculto")) abrirChat();
}

/* ───────────── roteador ───────────── */
const ROTAS = {
  inicio: paginaInicio, departamento: paginaDepartamento, estilos: paginaEstilos, estilo: paginaEstilo,
  produto: paginaProduto, busca: paginaBusca, pedidos: paginaPedidos, detetive: paginaDetetive, estudio: paginaEstudio,
};
function lerRota() {
  const h = location.hash.replace(/^#\/?/, ""); const [cam, qs = ""] = h.split("?");
  const partes = cam.split("/").filter(Boolean).map(s => { try { return decodeURIComponent(s); } catch { return s; } });
  return { rota: partes[0] || "inicio", args: partes.slice(1), q: Object.fromEntries(new URLSearchParams(qs)) };
}
function montar(tok, html) {
  if (tok !== E.tok) return false;
  app.innerHTML = html;
  app.classList.remove("entrar"); void app.offsetWidth; app.classList.add("entrar");
  return true;
}
function rotear() {
  if (!E.perfil) return;
  const { rota, args, q } = lerRota();
  const fn = ROTAS[rota] || paginaInicio;
  $$("[data-rota]").forEach(a => a.classList.toggle("ativo", a.dataset.rota === rota));
  $("#dd-dep").classList.remove("aberto");
  const tok = ++E.tok;
  window.scrollTo({ top: 0 });
  Promise.resolve().then(() => fn(args, q, tok)).catch(e => { if (tok === E.tok) app.innerHTML = erroPagina(e); });
}

/* ───────────── início (vitrine) ───────────── */
function bannerHTML(lista) {
  if (!lista.length) return "";
  const slides = lista.map((p, i) => {
    const c = coresEstilo(p.estilo_id);
    const d = descontoPct(p);
    return `<article class="slide ${i === 0 ? "ativo" : ""}" style="--c0:${c[0]};--c1:${c[1]};--c2:${c[2]}">
      <div class="slide-txt">
        <span class="kicker">${escHTML(p.departamento || "Destaque")} · ${escHTML(nomeEstiloOuId(p.estilo_id))}</span>
        <h2>${escHTML(p.nome)}</h2>
        <p>${escHTML(p.marca_produto || "")}${p.tipo ? ` · ${escHTML(p.tipo)}` : ""}</p>
        <div class="slide-preco">${temPromo(p) ? `<s>${reais(p.preco)}</s>` : ""}<b>${reais(precoVigente(p))}</b>${d ? `<span class="off">-${d}%</span>` : ""}</div>
        ${parcelaHTML(p)}
        <div class="botoes"><a class="btn btn-lava" href="#/produto/${encodeURIComponent(p.produto_id)}">Ver produto</a>
          <button class="btn btn-vidro" data-add="${escHTML(p.produto_id)}">Adicionar à sacola</button></div>
      </div>
      <a class="slide-arte" href="#/produto/${encodeURIComponent(p.produto_id)}" aria-label="${escHTML(p.nome)}">${fotoHTML(p)}</a>
    </article>`;
  }).join("");
  return `<section class="banner" aria-label="Destaques">
    <div class="slides">${slides}</div>
    <button class="seta-banner ant" aria-label="Destaque anterior">${ICO.setaE}</button>
    <button class="seta-banner prox" aria-label="Próximo destaque">${ICO.seta}</button>
    <div class="bolinhas">${lista.map((_, i) => `<button data-b="${i}" class="${i === 0 ? "ativo" : ""}" aria-label="Destaque ${i + 1}"></button>`).join("")}</div>
  </section>`;
}
function iniciarBanner() {
  const b = $(".banner"); if (!b) return;
  const slides = $$(".slide", b), bolas = $$(".bolinhas button", b);
  let i = 0, timer = null;
  const ir = n => { i = (n + slides.length) % slides.length; slides.forEach((s, k) => s.classList.toggle("ativo", k === i)); bolas.forEach((s, k) => s.classList.toggle("ativo", k === i)); };
  const reiniciar = () => { clearInterval(timer); timer = setInterval(() => { if (!document.body.contains(b)) return clearInterval(timer); ir(i + 1); }, 6500); };
  $(".ant", b).onclick = () => { ir(i - 1); reiniciar(); };
  $(".prox", b).onclick = () => { ir(i + 1); reiniciar(); };
  bolas.forEach((bt, k) => bt.onclick = () => { ir(k); reiniciar(); });
  b.onmouseenter = () => clearInterval(timer);
  b.onmouseleave = reiniciar;
  reiniciar();
}
async function paginaInicio(_a, _q, tok) {
  montar(tok, carregandoHTML());
  const qs = E.perfil?.cliente_id ? `?cliente_id=${encodeURIComponent(E.perfil.cliente_id)}` : "";
  const v = await api("/api/vitrine" + qs);
  (v.fileiras || []).forEach(f => reg(f.itens));
  const destaques = reg(v.destaques || []);
  const ok = montar(tok, `${bannerHTML(destaques)}
    <div class="container">
      ${E.perfil?.cliente_id ? `<p class="saudacao">Olá, <b>${escHTML(primeiroNome(E.perfil.apelido))}</b>. Separamos estas seleções com base no seu histórico.</p>` : `<p class="saudacao">Bem-vindo à loja. Explore os departamentos ou escolha um estilo para o seu espaço.</p>`}
      ${chipsHTML()}
      <div class="vitrine">${(v.fileiras || []).map(fileiraHTML).join("")}</div>
    </div>${rodapeHTML()}`);
  if (ok) { iniciarBanner(); ligarTrilhos(app); }
}

/* ───────────── departamento, estilos ───────────── */
async function paginaDepartamento([nome], _q, tok) {
  montar(tok, carregandoHTML());
  const d = await api("/api/departamento/" + encodeURIComponent(nome));
  const lista = reg(d.produtos || []);
  const ok = montar(tok, cabecalhoPagina({ kicker: "Departamento", titulo: escHTML(d.departamento || nome), sub: `${numPT(lista.length)} produtos` }) + filtrosGrade(lista) + rodapeHTML());
  if (ok) ligarFiltros(app, lista);
}
function paginaEstilos(_a, _q, tok) {
  montar(tok, cabecalhoPagina({ kicker: "Compre o look", titulo: "Estilos", sub: "Escolha um ambiente ou estilo e veja tudo que combina com ele." }) + `
    <div class="container"><div class="estilos-grade">${E.estilos.map(e => { const c = coresEstilo(e.estilo_id); return `<a class="estilo-card" href="#/estilo/${encodeURIComponent(e.estilo_id)}" style="--c0:${c[0]};--c1:${c[1]};--c2:${c[2]}">
      <div class="estilo-sw"><i></i><i></i><i></i></div><b>${escHTML(e.nome)}</b><span>${escHTML(e.descricao || "")}</span><small>${escHTML(e.materiais || "")}</small></a>`; }).join("")}</div></div>${rodapeHTML()}`);
}
async function paginaEstilo([id], _q, tok) {
  montar(tok, carregandoHTML());
  const d = await api("/api/estilo/" + encodeURIComponent(id));
  const lista = reg(d.produtos || []);
  const e = d.estilo || {}; const c = coresEstilo(e.estilo_id || id);
  const ok = montar(tok, `<section class="estilo-hero" style="--c0:${c[0]};--c1:${c[1]};--c2:${c[2]}"><div class="container">
      <span class="kicker">Estilo e ambientação</span><h1>${escHTML(e.nome || id)}</h1><p>${escHTML(e.descricao || "")}</p>
      <dl class="estilo-ficha"><div><dt>Paleta</dt><dd>${escHTML(e.paleta || "—")}</dd></div><div><dt>Materiais</dt><dd>${escHTML(e.materiais || "—")}</dd></div><div><dt>Ocasião</dt><dd>${escHTML(e.ocasiao || "—")}</dd></div></dl>
      <div class="swatches">${c.map(x => `<i style="background:${x}" title="${x}"></i>`).join("")}</div></div></section>` + filtrosGrade(lista) + rodapeHTML());
  if (ok) ligarFiltros(app, lista);
}

/* ───────────── produto ───────────── */
function listaTamanhos(t) {
  if (!t) return [];
  const s = String(t).trim();
  const m = s.match(/^(\d+)\s*[–-]\s*(\d+)$/);
  if (m) { const a = +m[1], b = +m[2]; if (b >= a && b - a < 30) return Array.from({ length: b - a + 1 }, (_, i) => String(a + i)); }
  return s.split(/[,;/]/).map(x => x.trim()).filter(Boolean);
}
function parseSpecs(txt) {
  return String(txt || "").split(";").map(s => s.trim()).filter(Boolean).map(s => {
    const i = s.indexOf(":");
    return i > 0 ? [s.slice(0, i).trim(), s.slice(i + 1).trim()] : ["Detalhe", s];
  });
}
const fotoMini = p => `<div class="cj-foto">${fotoHTML(p)}</div>`;
function compreJuntoHTML(p, junto) {
  const itens = junto.itens || [];
  const total = junto.total ?? (precoVigente(p) + itens.reduce((s, i) => s + precoVigente(i), 0));
  const com = junto.total_com_desconto ?? total;
  const pct = Math.round(fracao(junto.desconto_pct) * 100);
  return `<section class="secao compre-junto">
    <header class="sec-cab"><div><span class="kicker">Compre junto</span><h2>Monte o conjunto</h2>
      <p>Os complementos que mais saem junto com este produto. Leve o conjunto e economize.</p></div></header>
    <div class="cj-wrap"><div class="cj-lista">
      <div class="cj-item">${fotoMini(p)}<div><b>${escHTML(p.nome)}</b><span>${reais(precoVigente(p))}</span></div></div>
      ${itens.map(i => `<span class="cj-mais">+</span><div class="cj-item">${fotoMini(i)}<div><b>${escHTML(i.nome)}</b><span>${reais(precoVigente(i))}</span></div></div>`).join("")}
    </div>
    <aside class="cj-resumo">
      <div class="res-linha"><span>Total separado</span><s>${reais(total)}</s></div>
      <div class="res-total"><span>Total com desconto</span><b>${reais(com)}</b></div>
      ${pct ? `<em class="cj-econ">Economia de ${reais(total - com)} (${pct}%)</em>` : ""}
      <button class="btn btn-lava btn-grande btn-cheio" data-add-junto="${escHTML(p.produto_id)}">Adicionar todos à sacola</button>
    </aside></div></section>`;
}
function blocoVendedor(p) {
  if (!p.vendedor) return "";
  const rep = p.vendedor_reputacao != null ? Number(p.vendedor_reputacao) : null;
  const medalha = rep != null && rep >= 4.7 ? `<span class="medalha platinum">Loja Platinum</span>` : "";
  return `<div class="vendido-por"><span>Vendido por</span><b>${escHTML(p.vendedor)}</b>
    ${rep != null ? `<span class="rep">${estrelasHTML(rep)}<i>${rep.toFixed(1).replace(".", ",")}</i></span>` : ""}${medalha}</div>`;
}
async function paginaProduto([id], _q, tok) {
  montar(tok, carregandoHTML());
  const p = await api("/api/produto/" + encodeURIComponent(id));
  if (tok !== E.tok) return;
  const junto = p.compre_junto || {}; const itensJunto = junto.itens || [];
  reg([p, ...(p.tambem_compraram || []), ...itensJunto, ...(p.mesmo_estilo || [])]);
  const est = p.estilo || {}; const c = coresEstilo(p.estilo_id);
  const tams = listaTamanhos(p.tamanhos);
  const dep = p.departamento || "";
  const d = descontoPct(p);
  const estoque = Number(p.estoque ?? 0);
  const estoqueTxt = estoque <= 0 ? "Indisponível no momento" : estoque <= 5 ? `Últimas ${estoque} unidades` : "Em estoque";
  const ok = montar(tok, `<div class="container pagina">
    <nav class="migalhas"><a href="#/inicio">Início</a><span>/</span><a href="#/departamento/${encodeURIComponent(dep)}">${escHTML(dep)}</a><span>/</span><span>${escHTML(p.tipo || p.nome)}</span></nav>
    <div class="pd-topo">
      <div class="pd-foto">${fotoHTML(p)}${d ? `<span class="selo-p oferta grande">-${d}%</span>` : ""}${p.lancamento ? `<span class="selo-p novo grande">Lançamento</span>` : ""}</div>
      <div class="pd-info">
        <span class="prod-marca">${escHTML(p.marca_produto || "")}</span>
        <h1>${escHTML(p.nome)}</h1>
        ${p.avaliacao != null ? `<div class="pd-aval">${estrelasHTML(p.avaliacao, p.n_avaliacoes)}<span>${Number(p.avaliacao).toFixed(1).replace(".", ",")} de 5</span></div>` : ""}
        ${blocoVendedor(p)}
        <div class="pd-preco">${precoHTML(p, true)}${d ? `<span class="off">${d}% OFF</span>` : ""}</div>
        ${parcelaHTML(p)}
        ${p.frete_gratis === true ? `<span class="frete-gratis lg">Frete grátis para este produto</span>` : ""}
        ${tams.length ? `<div class="pd-bloco"><div class="rotulo">Tamanho <b data-tam-txt>escolha</b></div>
          <div class="tamanhos">${tams.map(t => `<button data-tam="${escHTML(t)}">${escHTML(t)}</button>`).join("")}</div></div>` : ""}
        <div class="pd-bloco"><div class="rotulo">Cor <b class="cor-nome"><i style="background:${hexOK(p.cor_hex)}"></i>${escHTML(p.cor || "")}</b></div></div>
        <div class="pd-compra">
          <div class="qtd"><button data-q="-1" aria-label="Diminuir">−</button><output data-qtd-out>1</output><button data-q="1" aria-label="Aumentar">+</button></div>
          <button class="btn btn-lava btn-grande" data-add-pd>Adicionar à sacola</button>
        </div>
        <p class="pd-estoque ${estoque > 0 && estoque <= 5 ? "baixo" : ""}">${estoqueTxt}</p>
        <ul class="pd-garantias">
          <li>${ICO.caminhao}<span>Entrega em até 7 dias úteis</span></li>
          <li>${ICO.troca}<span>Troca em até 30 dias</span></li>
          <li>${ICO.cartao}<span>${Number(p.parcelas_sem_juros || 0) > 1 ? `Parcelamento em ${p.parcelas_sem_juros}x sem juros` : "Pagamento em cartão, PIX ou boleto"}</span></li>
        </ul>
      </div>
    </div>
    <div class="pd-duas">
      <section class="pd-desc"><h2>Descrição</h2><p>${escHTML(p.descricao || "Sem descrição cadastrada.")}</p></section>
      <section class="pd-specs"><h2>Especificações</h2>${parseSpecs(p.especificacoes).length
        ? `<dl class="specs">${parseSpecs(p.especificacoes).map(([k, v]) => `<div><dt>${escHTML(k)}</dt><dd>${escHTML(v)}</dd></div>`).join("")}</dl>`
        : `<p class="assoc-legenda">Sem especificações cadastradas.</p>`}</section>
    </div>
    <section class="pd-estilo" style="--c0:${c[0]};--c1:${c[1]};--c2:${c[2]}">
      <div class="pd-estilo-txt">
        <span class="kicker">Estilo e ambientação</span>
        <h2>${escHTML(est.nome || nomeEstilo(p.estilo_id))}</h2>
        <p>${escHTML(est.descricao || "")}</p>
        ${p.descricao_visual ? `<p class="visual">${escHTML(p.descricao_visual)}</p>` : ""}
        <dl class="estilo-ficha"><div><dt>Materiais</dt><dd>${escHTML(est.materiais || "—")}</dd></div><div><dt>Ocasião</dt><dd>${escHTML(est.ocasiao || "—")}</dd></div></dl>
        <a class="btn btn-borda" href="#/estilo/${encodeURIComponent(p.estilo_id)}">Ver mais de ${escHTML(est.nome || "este estilo")}</a>
      </div>
      <div class="swatches-grande">${c.map(x => `<i style="background:${x}" title="${x}"></i>`).join("")}</div>
    </section>
    ${itensJunto.length ? compreJuntoHTML(p, junto) : ""}
    ${(p.tambem_compraram || []).length ? `<section class="secao">
      <header class="sec-cab"><div><h2>Quem comprou também comprou</h2>
        <p>Confiança é a fração de quem levou o produto junto; o lift mede o quanto isso supera o acaso.</p></div></header>
      ${trilhoHTML(p.tambem_compraram.map(r => `<div class="assoc-item">${produtoHTML(r, { semAssoc: true })}
        <div class="barra-lift"><i style="width:${Math.min(100, fracao(r.confianca) * 100 * 2)}%"></i></div>
        <p class="assoc-legenda"><b>${pctTxt(r.confianca)}</b> de quem comprou levou · lift <b>${Number(r.lift).toFixed(1)}×</b></p></div>`).join(""))}
    </section>` : ""}
    ${(p.mesmo_estilo || []).length ? `<section class="secao">
      <header class="sec-cab"><div><h2>Do mesmo estilo</h2><p>${escHTML(est.nome || nomeEstilo(p.estilo_id))}</p></div></header>
      ${trilhoHTML(cards(p.mesmo_estilo))}</section>` : ""}
  </div>${rodapeHTML()}`);
  if (!ok) return;
  ligarTrilhos(app);
  let tam = null, qtd = 1;
  $$("[data-tam]").forEach(b => b.onclick = () => {
    tam = b.dataset.tam; $$("[data-tam]").forEach(x => x.classList.toggle("ativo", x === b)); $("[data-tam-txt]").textContent = tam;
  });
  $$("[data-q]").forEach(b => b.onclick = () => { qtd = Math.min(20, Math.max(1, qtd + Number(b.dataset.q))); $("[data-qtd-out]").textContent = qtd; });
  $("[data-add-pd]").onclick = () => {
    if (tams.length && !tam) { toast(`<div class="toast-txt"><b>Escolha um tamanho</b><span>Selecione o tamanho antes de adicionar à sacola.</span></div>`, 3500, "erro"); return; }
    addCarrinho(p, { qtd, tamanho: tam });
  };
  const aj = $("[data-add-junto]");
  if (aj) aj.onclick = () => {
    addCarrinho(p, { aviso: false }); itensJunto.forEach(i => addCarrinho(i, { aviso: false }));
    toast(`<div class="toast-txt"><b>Conjunto na sacola</b><span>${1 + itensJunto.length} produtos adicionados.</span><button class="link" data-abrir-sacola>Ver sacola</button></div>`, 4500);
  };
}

/* ───────────── busca ───────────── */
async function paginaBusca(_a, q, tok) {
  const termo = q.q || "", dep = q.departamento || "", pmax = q.preco_max || "";
  const precos = [["", "Qualquer preço"], ["100", "Até R$ 100"], ["250", "Até R$ 250"], ["500", "Até R$ 500"], ["1000", "Até R$ 1.000"]];
  const ok = montar(tok, cabecalhoPagina({
    kicker: "Busca semântica · Vector Search", titulo: termo ? `Resultados para “${escHTML(termo)}”` : "O que você procura?",
    sub: "Busca por significado. Experimente “sala aconchegante para ler”, “tênis para correr na chuva” ou “presente para gamer”.",
  }) + `<div class="container">
    <div class="barra-filtros">
      <label class="campo-f">Departamento <select id="bf-dep"><option value="">Todos</option>${E.departamentos.map(d => `<option ${d.nome === dep ? "selected" : ""}>${escHTML(d.nome)}</option>`).join("")}</select></label>
      <label class="campo-f">Preço <select id="bf-preco">${precos.map(([v, t]) => `<option value="${v}" ${v === pmax ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <span class="contagem" id="bf-cont"></span></div>
    <div class="grade" id="bf-grade">${termo ? carregandoHTML() : `<p class="vazio">Digite o que procura no campo de busca do topo.</p>`}</div>
  </div>${rodapeHTML()}`);
  if (!ok || !termo) return;
  const qs = new URLSearchParams({ q: termo });
  if (dep) qs.set("departamento", dep);
  if (pmax) qs.set("preco_max", pmax);
  const r = await api("/api/busca?" + qs);
  if (tok !== E.tok) return;
  const lista = reg(r.produtos || []);
  $("#bf-grade").innerHTML = lista.length ? cards(lista) : `<p class="vazio">Nada encontrado para “${escHTML(termo)}”. Tente outras palavras.</p>`;
  $("#bf-cont").textContent = `${numPT(lista.length)} resultado(s)`;
  const mudar = () => {
    const qq = new URLSearchParams({ q: termo });
    if ($("#bf-dep").value) qq.set("departamento", $("#bf-dep").value);
    if ($("#bf-preco").value) qq.set("preco_max", $("#bf-preco").value);
    location.hash = "#/busca?" + qq;
  };
  $("#bf-dep").onchange = mudar; $("#bf-preco").onchange = mudar;
}

/* ───────────── meus pedidos ───────────── */
const STATUS_CLASSE = { "Entregue": "ok", "Em transporte": "info", "Cancelado": "erro", "Devolvido": "alerta" };
function pedidoHTML(p) {
  const data = new Date(p.data_pedido);
  const dataTxt = isNaN(data) ? String(p.data_pedido || "") : data.toLocaleDateString("pt-BR", { day: "2-digit", month: "long", year: "numeric" });
  return `<article class="pedido">
    <header><div><span class="mono muted">${escHTML(p.pedido_id)}</span><b>${escHTML(dataTxt)}</b></div>
      <span class="status ${STATUS_CLASSE[p.status] || ""}">${escHTML(p.status || "")}</span></header>
    <div class="pedido-itens">${(p.itens || []).map(i => `<div class="pi">${fotoMini(i)}<div><b>${escHTML(i.nome)}</b>
      <span>Qtd. ${i.quantidade} · ${reais(precoVigente(i))}</span></div></div>`).join("")}</div>
    ${p.previsao_entrega && p.status === "Em transporte" ? `<div class="pedido-entrega"><span>Previsão de entrega: <b>${escHTML(dataEntrega(p.previsao_entrega))}</b></span>${botaoAgenda(p.pedido_id)}</div>` : ""}
    ${(p.solicitacoes || []).map(sl => `<div class="pedido-sac"><div class="sac-linha"><b>${escHTML(sl.tipo || "")}</b> · protocolo
      <span class="mono">${escHTML(sl.protocolo)}</span> · ${escHTML(sl.status || "")} · ${escHTML(sl.prazo || "")}</div>
      <small>${escHTML(sl.motivo || "")}</small></div>`).join("")}
    <footer><span>Total do pedido</span><b>${reais(p.valor_total)}</b></footer></article>`;
}
async function paginaPedidos(_a, _q, tok) {
  if (!E.perfil || !E.perfil.cliente_id) {
    montar(tok, cabecalhoPagina({ kicker: "Minha conta", titulo: "Meus pedidos" }) + `<div class="container"><div class="vazio-grande">
      <b>Escolha um perfil</b><span>Para ver os pedidos, selecione quem está comprando.</span>
      <button class="btn btn-lava" data-trocar-perfil>Escolher perfil</button></div></div>`);
    return;
  }
  montar(tok, carregandoHTML());
  const d = await api("/api/meus-pedidos?cliente_id=" + encodeURIComponent(E.perfil.cliente_id));
  const peds = d.pedidos || [];
  reg(peds.flatMap(p => p.itens || []));
  montar(tok, cabecalhoPagina({ kicker: "Minha conta", titulo: "Meus pedidos", sub: `${numPT(peds.length)} pedido(s) de ${E.perfil.apelido}` })
    + `<div class="container pedidos-lista">${peds.length ? peds.map(pedidoHTML).join("")
      : `<div class="vazio-grande"><b>Nenhum pedido ainda</b><span>Quando você finalizar uma compra, ela aparece aqui.</span><a class="btn btn-lava" href="#/inicio">Ver ofertas</a></div>`}</div>${rodapeHTML()}`);
}

/* ───────────── Detetive de produtos ───────────── */
// etapas reais do backend (main.py /api/detetive → mcp_detetive.investigar)
const FASES_DET = ["Enviando a foto para o Volume…", "Lendo o produto com o modelo de visão (cor, material, tipo, estilo)…",
  "Buscando parecidos no catálogo (Vector Search) e ranqueando…"];
const compatHTML = p => {
  if (p.compatibilidade == null) return "";
  const v = Math.round(fracao(p.compatibilidade) * 100);
  return `<div class="compat"><div class="anel" style="--p:${v}"><b>${v}</b></div><div><span>compatibilidade</span>
    <ul>${(p.pistas || []).slice(0, 3).map(x => `<li>${escHTML(x)}</li>`).join("")}</ul></div></div>`;
};
function laudoHTML(r, url) {
  const l = r.laudo || {};
  const prods = r.produtos || [];
  reg(prods);
  const cores = (l.cores_hex || []).map(c => `<i style="background:${hexOK(c)}" title="${escHTML(c)}"></i>`).join("");
  return `<div class="laudo">
      <div class="laudo-topo"><img src="${url}" alt="Foto analisada">
        <div>
          <span class="kicker">Busca visual · ${escHTML(l.tipo || "Produto")}</span>
          <h2>${escHTML(l.descricao || l.tipo || "Produto não identificado")}</h2>
          <div class="paleta">${cores}</div>
          <div class="chips">${(l.atributos || []).map(a => `<span>${escHTML(a)}</span>`).join("")}</div>
          <dl class="laudo-dl">
            <div><dt>Cor</dt><dd>${escHTML(l.cor || "—")}</dd></div>
            <div><dt>Material</dt><dd>${escHTML(l.material || "—")}</dd></div>
            <div><dt>Estilo</dt><dd>${escHTML(l.estilo_nome || "—")}</dd></div>
            <div><dt>Produto reconhecido</dt><dd>${escHTML(l.produto_reconhecido || "—")}</dd></div>
          </dl>
        </div>
      </div>
      ${l.veredito ? `<blockquote class="veredito">${escHTML(l.veredito)}</blockquote>` : ""}
      ${l.consulta_busca ? `<p class="consulta">Consulta ao catálogo: <code>${escHTML(l.consulta_busca)}</code></p>` : ""}
    </div>
    <section class="det-item">
      <header><span class="kicker">Resultado</span><h3>Produtos parecidos na loja</h3>
        <span class="det-tags">${numPT(prods.length)} encontrado(s)</span></header>
      ${prods.length ? trilhoHTML(prods.map(p => `<div class="det-prod">${produtoHTML(p, { semAssoc: true })}${compatHTML(p)}</div>`).join(""))
        : `<p class="assoc-legenda">Nenhum produto parecido encontrado. Tente uma foto com o produto mais em destaque.</p>`}
    </section>`;
}
function paginaDetetive(_a, _q, tok) {
  const ok = montar(tok, `<div class="container pagina">
    <section class="det-hero">
      <div><span class="kicker">MCP · visão computacional · Vector Search</span><h1>Detetive de produtos</h1>
        <p>Busca visual: mande a foto de um produto. O Detetive identifica o que é (tipo, cor, material, estilo) e encontra na loja os produtos parecidos.</p></div>
      <div class="det-lupa" aria-hidden="true"><svg viewBox="0 0 200 200"><circle cx="84" cy="84" r="54" fill="rgba(255,255,255,.08)" stroke="#FF5F46" stroke-width="12"/><path d="M124 124 L170 170" stroke="#FF3621" stroke-width="20" stroke-linecap="round"/><path d="M54 72 q18 -22 46 -12" stroke="#fff" stroke-opacity=".55" stroke-width="6" fill="none" stroke-linecap="round"/></svg></div>
    </section>
    <div class="det-grid">
      <div class="det-entrada">
        <label class="drop" id="drop"><input type="file" accept="image/*" hidden id="det-arquivo">
          <span class="drop-icone">${ICO.upload}</span><b>Arraste a foto de um produto</b><span>ou clique para escolher · JPG, PNG ou WEBP</span></label>
        <p class="assoc-legenda det-dica">Funciona melhor com um produto em destaque: um tênis, uma poltrona, um headset, uma luminária…</p>
      </div>
      <div id="det-resultado" class="det-resultado"><div class="painel-vazio">Aguardando a primeira foto…</div></div>
    </div></div>${rodapeHTML()}`);
  if (!ok) return;
  const inp = $("#det-arquivo"), drop = $("#drop");
  inp.onchange = () => inp.files[0] && investigar(inp.files[0]);
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("sobre"); };
  drop.ondragleave = () => drop.classList.remove("sobre");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("sobre"); if (e.dataTransfer.files[0]) investigar(e.dataTransfer.files[0]); };
}
async function investigar(arquivo) {
  const res = $("#det-resultado");
  const url = URL.createObjectURL(arquivo);
  res.innerHTML = `<div class="scan"><div class="scan-img"><img src="${url}" alt=""><div class="scan-linha"></div></div>
    <div class="scan-fase" id="det-fase">${FASES_DET[0]}</div><div class="scan-barra"><i></i></div></div>`;
  const acomp = acompanhar(p => { const f = $("#det-fase"); if (f && FASES_DET[p]) f.textContent = FASES_DET[p]; });
  try {
    const fd = new FormData(); fd.append("imagem", arquivo); fd.append("quantidade", "8"); fd.append("tarefa", acomp.tarefa);
    const r = await apiForm("/api/detetive", fd);
    acomp.parar();
    res.innerHTML = laudoHTML(r, url);
    ligarTrilhos(res);
  } catch (e) { acomp.parar(); res.innerHTML = `<div class="painel painel-erro"><b>A busca visual falhou</b><span>${escHTML(e.message)}</span></div>`; }
}

/* ───────────── Estúdio (controle da loja) ───────────── */
const ESTUDIO_ABAS = [["painel", "Painel"], ["novo", "+ Novo produto (PDF)"], ["produtos", "Produtos"], ["previsao", "Previsão"], ["dados", "Dados"], ["modelo", "Modelo"], ["conversas", "Conversas"], ["ajuda", "Central de ajuda"], ["mcp", "MCP"]];
const aba = (tok, html) => { if (tok === E.tok) { const el = $("#aba"); if (el) el.innerHTML = html; } };
function paginaEstudio([sub = "painel"], _q, tok) {
  if (!E.admin) {
    montar(tok, cabecalhoPagina({ kicker: "Controle", titulo: "Estúdio" }) + `<div class="container"><div class="vazio-grande">
      <b>O Estúdio é do modo admin</b><span>Marque <b>Admin</b> no topo da página para ver e cadastrar dados de todos os clientes.</span></div></div>`);
    return;
  }
  // SAC por voz (Whisper): a aba só aparece no workspace corporativo com o endpoint do Whisper e a tabela atendimentos_voz
  const abas = E.sacVoz ? [...ESTUDIO_ABAS.slice(0, 4), ["voz", "SAC por voz"], ...ESTUDIO_ABAS.slice(4)] : ESTUDIO_ABAS;
  const ok = montar(tok, cabecalhoPagina({ kicker: "Controle", titulo: "Estúdio",
    sub: "Cadastre produtos a partir de fichas técnicas em PDF do fornecedor, mantenha a central de ajuda e acompanhe os índices de busca." })
    + `<div class="container"><nav class="abas">${abas.map(([k, n]) => `<a href="#/estudio/${k}" data-aba="${k}" class="${k === sub ? "ativo" : ""}">${n}</a>`).join("")}</nav><div id="aba"></div></div>${rodapeHTML()}`);
  if (!ok) return;
  if (E.sacVoz === undefined) {   // descobre uma vez se o SAC por voz está instalado e redesenha as abas
    E.sacVoz = false;
    api("/api/voz/disponivel").then(r => { if (r.disponivel) { E.sacVoz = true; if (tok === E.tok) paginaEstudio([sub], _q, tok); } }).catch(() => { });
  }
  const fn = { painel: abaPainel, novo: abaNovo, produtos: abaProdutos, previsao: abaPrevisao, dados: abaDados, modelo: abaModelo, conversas: abaConversas, voz: abaVoz, ajuda: abaAjuda, mcp: abaMcp }[sub] || abaPainel;
  fn(tok);
}
/* ── Dados (admin): perguntas ao Genie com tabela e gráfico + acesso a dados sensíveis por ABAC ── */
const SUGESTOES_DADOS = ["Quantos produtos temos por departamento? Mostre em gráfico",
  "Quais os 10 produtos mais comprados? Gráfico de barras", "Receita por mês nos últimos 6 meses, em gráfico de linha",
  "O que o cliente Gustavo Dias comprou?", "Qual o nome e o e-mail dos 5 clientes que mais gastaram?"];
async function abaDados(tok) {
  const sug = SUGESTOES_DADOS.map(q => `<button type="button" class="chip" data-q="${escHTML(q)}">${escHTML(q)}</button>`).join("");
  aba(tok, `<div class="dados-grade">
    <section class="painel dados-chat">
      <header class="dados-cab"><h3>Pergunte aos dados</h3>
        <span class="assoc-legenda">Em português → o <b>Genie</b> gera o SQL e roda no warehouse. Peça <i>"em gráfico"</i> (barras, linha ou pizza).</span></header>
      <div class="dados-msgs" id="dados-msgs">
        <div class="dados-vazio" id="dados-vazio"><b>Comece por uma destas perguntas</b><div class="dados-sug-ini">${sug}</div></div>
      </div>
      <div class="dados-sug-linha oculto" id="dados-sug">${sug}</div>
      <form id="dados-form" class="dados-form"><input id="dados-input" placeholder="Pergunte sobre vendas, produtos, clientes…" autocomplete="off">
        <button class="btn btn-lava">Perguntar</button></form>
    </section>
    <aside class="painel dados-acesso" id="dados-acesso">${carregandoHTML()}</aside></div>`);
  const f = $("#dados-form"), inp = $("#dados-input"), caixa = $("#dados-msgs");
  const rolar = () => { caixa.scrollTop = caixa.scrollHeight; };
  $$(".dados-chat [data-q]").forEach(b => b.onclick = () => { inp.value = b.dataset.q; f.requestSubmit(); });
  f.onsubmit = async ev => {
    ev.preventDefault(); const q = inp.value.trim(); if (!q) return;
    inp.value = ""; $("#dados-vazio")?.remove(); $("#dados-sug").classList.remove("oculto");
    const bt = f.querySelector("button"); bt.disabled = true; bt.innerHTML = `<span class="spin"></span>`;
    caixa.insertAdjacentHTML("beforeend", `<div class="dados-u">${escHTML(q)}</div>`);
    const resp = document.createElement("div"); resp.className = "dados-b";
    resp.innerHTML = `<div class="digitando"><span></span><span></span><span></span></div><small class="assoc-legenda">o Genie está montando o SQL…</small>`;
    caixa.appendChild(resp); rolar();
    try { resp.innerHTML = dadosRespostaHTML(await api("/api/admin/dados/perguntar", { json: { pergunta: q } }), q); ligarRespostaDados(resp); }
    catch (e) { resp.innerHTML = `<div class="painel painel-erro"><b>Não deu</b><span>${escHTML(e.message)}</span></div>`; }
    bt.disabled = false; bt.textContent = "Perguntar"; inp.focus(); rolar();
  };
  dadosAcesso();
}
async function dadosAcesso(acao) {
  const box = $("#dados-acesso"); if (!box) return;
  let d;
  try {
    if (acao === undefined) d = await api("/api/admin/dados/acesso");
    else {   // dispara o job (roda como o dono da tabela) e acompanha até terminar
      d = await api("/api/admin/dados/acesso", { json: { liberar: acao } });
      const ini = Date.now();
      while (d.run_id && !d.fim) {
        const b = $(acao ? "#abac-liberar" : "#abac-revogar");
        if (b) b.innerHTML = `<span class="spin"></span> ${acao ? "liberando" : "revogando"}… job ${escHTML(String(d.fase || "PENDING").toLowerCase())} · ${Math.round((Date.now() - ini) / 1000)} s`;
        await new Promise(r => setTimeout(r, 2000));
        d = await api(`/api/admin/dados/acesso/execucao?run_id=${encodeURIComponent(d.run_id)}&liberar=${acao}`);
        if (Date.now() - ini > 300000) throw new Error("o job passou de 5 min; confira em Jobs & Pipelines");
      }
      if (d.ok === false) throw new Error(d.erro || "o job falhou");
    }
  }
  catch (e) { toastErro(e); if (acao !== undefined) { await dadosAcesso(); return false; } box.innerHTML = `<b>Acesso indisponível</b><p class="assoc-legenda">${escHTML(e.message)}</p>`; return; }
  if (!d.disponivel) { box.innerHTML = `<h3>Dados sensíveis</h3><p class="assoc-legenda">${escHTML(d.motivo || "ABAC indisponível neste workspace.")}</p>`; return; }
  const m = d.mascarado;
  box.innerHTML = `<h3>Dados sensíveis (ABAC)</h3>
    <div class="abac-status ${m ? "on" : "off"}">${m ? "Mascarados" : "Liberados"}</div>
    <p class="assoc-legenda">Governed tag <code>${escHTML(d.tag)}</code> nas colunas abaixo → a policy <code>${escHTML(d.policy || "")}</code> mascara
      <b>tudo menos a penúltima letra</b>. Revogar = <b>pôr</b> a tag; liberar = <b>tirar</b> a tag (um job roda como o dono da tabela).</p>
    <ul class="abac-cols">${d.colunas.map(c => `<li><code>${escHTML(c.coluna)}</code> ${c.protegida ? "com a tag" : "sem a tag"}</li>`).join("")}</ul>
    <div class="botoes"><button class="btn ${m ? "btn-lava" : "btn-borda"}" id="abac-liberar" ${m ? "" : "disabled"}>Liberar acesso</button>
      <button class="btn ${m ? "btn-borda" : "btn-lava"}" id="abac-revogar" ${m ? "disabled" : ""}>Revogar acesso</button></div>
    ${(d.amostra || []).length ? `<h4>Como os dados aparecem agora</h4><table class="tabela-ml abac-amostra"><thead><tr><th>Cliente</th><th>Nome</th><th>E-mail</th></tr></thead>
      <tbody>${d.amostra.map(a => `<tr><td class="mono">${escHTML(a.cliente_id)}</td><td class="mono">${escHTML(a.nome)}</td><td class="mono">${escHTML(a.email)}</td></tr>`).join("")}</tbody></table>` : ""}
    ${d.sql ? `<details class="fc-sql" open><summary>SQL executado pelo ${escHTML(d.executado_por || "")}${d.ms ? ` · ${(d.ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} s` : ""}</summary><pre class="sql">${escHTML(d.sql.join(";\n") + ";")}</pre>
      ${d.job_link ? `<a href="${escHTML(d.job_link)}" target="_blank" rel="noopener">ver a execução do job ↗</a>` : ""}</details>` : ""}`;
  const bl = $("#abac-liberar"), br = $("#abac-revogar");
  const clicar = (b, v) => b && (b.onclick = async () => { b.disabled = true;
    b.innerHTML = `<span class="spin"></span> ${v ? "liberando" : "revogando"}… (job serverless, ~30 s)`;
    if (await dadosAcesso(v)) toast(`<div class="toast-txt"><b>${v ? "Acesso liberado" : "Acesso revogado"}</b><span>Pergunte de novo para ver o efeito.</span></div>`, 3000); });
  clicar(bl, true); clicar(br, false);
  return true;
}
const ehNumero = v => v !== null && v !== "" && !isNaN(Number(v));
function dadosRespostaHTML(r, q) {
  const cols = r.colunas || [], linhas = r.linhas || [];
  const selo = r.mascarado === true ? `<span class="abac-selo on">dados sensíveis mascarados</span>` : r.mascarado === false ? `<span class="abac-selo off">dados sensíveis liberados</span>` : "";
  const fmt = v => ehNumero(v) && String(v).length < 16 ? Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : String(v ?? "");
  const podeGrafico = cols.length >= 2 && linhas.length >= 2 && cols.some((c, i) => linhas.every(l => l[i] === null || ehNumero(l[i])));
  const tabela = cols.length ? `<div class="dados-tab-caixa"><table class="tabela-ml dados-tab"><thead><tr>${cols.map(c => `<th>${escHTML(c)}</th>`).join("")}</tr></thead>
    <tbody>${linhas.map(l => `<tr>${l.map(v => `<td class="${ehNumero(v) ? "num" : ""}">${escHTML(fmt(v))}</td>`).join("")}</tr>`).join("")
      || `<tr><td colspan="${cols.length}">Nenhuma linha.</td></tr>`}</tbody></table></div>` : "";
  const vistas = [podeGrafico && ["grafico", "Gráfico"], cols.length && ["tabela", `Tabela (${linhas.length})`], r.sql && ["sql", "SQL"]].filter(Boolean);
  const inicial = podeGrafico && r.pediu_grafico ? "grafico" : cols.length ? "tabela" : vistas[0] && vistas[0][0];
  const seg = ((r.ms || 0) / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  return `<div class="dados-meta">${selo}<span>Genie · ${seg} s</span></div>
    ${r.texto ? `<div class="dados-texto curto">${md(r.texto)}</div><button type="button" class="link dados-mais oculto">mostrar mais</button>` : ""}
    ${!cols.length && !r.texto ? `<p class="assoc-legenda">O Genie não trouxe resultado.</p>` : ""}
    ${vistas.length ? `<div class="dados-vistas">${vistas.map(([k, n]) => `<button type="button" data-vista="${k}" class="${k === inicial ? "sel" : ""}">${n}</button>`).join("")}</div>` : ""}
    ${podeGrafico ? `<div class="dados-vista ${inicial === "grafico" ? "" : "oculto"}" data-vista="grafico"><div class="dados-graf" data-cols="${escHTML(JSON.stringify(cols))}"
      data-linhas="${escHTML(JSON.stringify(linhas.slice(0, 30)))}" data-q="${escHTML(q)}"></div></div>` : ""}
    ${cols.length ? `<div class="dados-vista ${inicial === "tabela" ? "" : "oculto"}" data-vista="tabela">${tabela}</div>` : ""}
    ${r.sql ? `<div class="dados-vista ${inicial === "sql" ? "" : "oculto"}" data-vista="sql"><pre class="sql">${escHTML(r.sql)}</pre></div>` : ""}`;
}
function ligarRespostaDados(resp) {
  const g = resp.querySelector(".dados-graf");
  const desenhar = () => { if (g && !g.dataset.ok) { g.innerHTML = graficoDadosSVG(JSON.parse(g.dataset.cols), JSON.parse(g.dataset.linhas), g.dataset.q); g.dataset.ok = 1; } };
  if (g && !resp.querySelector('.dados-vista[data-vista="grafico"]').classList.contains("oculto")) desenhar();
  $$(".dados-vistas button", resp).forEach(b => b.onclick = () => {
    $$(".dados-vistas button", resp).forEach(x => x.classList.toggle("sel", x === b));
    $$(".dados-vista", resp).forEach(v => v.classList.toggle("oculto", v.dataset.vista !== b.dataset.vista));
    if (b.dataset.vista === "grafico") desenhar();
  });
  const t = resp.querySelector(".dados-texto"), mais = resp.querySelector(".dados-mais");
  if (t && mais && t.scrollHeight > t.clientHeight + 4) {
    mais.classList.remove("oculto");
    mais.onclick = () => { const curto = t.classList.toggle("curto"); mais.textContent = curto ? "mostrar mais" : "mostrar menos"; };
  }
}
// gráfico a partir do resultado: 1ª coluna de texto = rótulo, 1ª numérica (que não seja id/ano/mês) = valor;
// linha (datas ou "linha" na pergunta), pizza ("pizza"/"rosca") ou barras; passe o mouse para ver o valor
function graficoDadosSVG(cols, linhas, q) {
  const numerica = i => linhas.every(l => l[i] === null || ehNumero(l[i]));
  let iv = cols.findIndex((c, i) => numerica(i) && !/(^|_)(id|ano|mes|m[eê]s)$/i.test(c));
  if (iv < 0) iv = cols.findIndex((c, i) => numerica(i));
  let ir = cols.findIndex((c, i) => i !== iv && !numerica(i));
  if (ir < 0) ir = iv === 0 ? 1 : 0;
  const pts = linhas.map(l => ({ r: String(l[ir] ?? ""), v: Number(l[iv]) || 0 })).slice(0, 24);
  const datas = pts.every(p => /^\d{4}-\d{2}/.test(p.r));
  const tipo = /pizza|rosca/i.test(q) ? "pizza" : (datas || /linha/i.test(q)) ? "linha" : "barras";
  const fmt = v => v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  const rot = r => datas ? r.slice(0, 10).split("-").reverse().join("/").replace(/^01\//, "") : r;
  const titulo = `<p class="dados-graf-t">${escHTML(cols[iv])} por ${escHTML(cols[ir])}</p>`;
  if (tipo === "pizza") {
    const tot = pts.reduce((a, p) => a + Math.max(0, p.v), 0) || 1, cores = ["#FF3621", "#1B3139", "#2272B4", "#00A972", "#FFAB00", "#8A6FDF", "#98102A", "#5A6F77"];
    let ang = -Math.PI / 2;
    const fatias = pts.map((p, k) => {
      const a = (Math.max(0, p.v) / tot) * Math.PI * 2, x1 = 150 + 110 * Math.cos(ang), y1 = 130 + 110 * Math.sin(ang);
      ang += a; const x2 = 150 + 110 * Math.cos(ang), y2 = 130 + 110 * Math.sin(ang);
      return `<path d="M150,130 L${x1.toFixed(1)},${y1.toFixed(1)} A110,110 0 ${a > Math.PI ? 1 : 0} 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z" fill="${cores[k % cores.length]}"><title>${escHTML(rot(p.r))}: ${fmt(p.v)} (${(100 * p.v / tot).toFixed(1)}%)</title></path>`;
    });
    return `${titulo}<div class="dados-pizza"><svg viewBox="0 0 300 260"><g>${fatias.join("")}</g><circle cx="150" cy="130" r="55" fill="#fff"/></svg>
      <ul>${pts.map((p, k) => `<li><i style="background:${cores[k % cores.length]}"></i>${escHTML(rot(p.r))} <b>${(100 * p.v / tot).toFixed(1)}%</b></li>`).join("")}</ul></div>`;
  }
  const max = Math.max(...pts.map(p => p.v), 0) || 1;
  if (tipo === "linha") {
    const W = 720, H = 260, M = { l: 70, r: 16, t: 14, b: 34 };
    const X = i => M.l + (i / Math.max(1, pts.length - 1)) * (W - M.l - M.r), Y = v => M.t + (1 - v / (max * 1.08)) * (H - M.t - M.b);
    return `${titulo}<svg class="dados-svg" viewBox="0 0 ${W} ${H}">
      ${[0, .5, 1].map(t => `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(t * max)}" y2="${Y(t * max)}" class="grade"/><text x="${M.l - 6}" y="${Y(t * max) + 4}" text-anchor="end">${fmt(Math.round(t * max))}</text>`).join("")}
      <path d="${pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ")}" class="real"/>
      ${pts.map((p, i) => `<circle cx="${X(i)}" cy="${Y(p.v)}" r="4" class="dados-pt"><title>${escHTML(rot(p.r))}: ${fmt(p.v)}</title></circle>
        <text x="${X(i)}" y="${H - 10}" text-anchor="middle">${escHTML(rot(p.r).slice(0, 10))}</text>`).join("")}</svg>`;
  }
  return `${titulo}<div class="dados-barras">${pts.map(p => `<div class="barra" title="${escHTML(p.r)}: ${fmt(p.v)}"><span class="rot">${escHTML(p.r)}</span>
    <span class="dados-trilho"><span class="enche" style="width:${(100 * Math.max(0, p.v) / max).toFixed(1)}%"></span></span><b>${fmt(p.v)}</b></div>`).join("")}</div>`;
}
/* ── Modelo do Assistente (admin): roteador do Unity Gateway × modelo direto ── */
async function abaModelo(tok) {
  aba(tok, carregandoHTML());
  let mod;
  try { mod = await api("/api/admin/modelo"); } catch (e) { aba(tok, `<div class="painel painel-erro"><b>Modelo indisponível</b><span>${escHTML(e.message)}</span></div>`); return; }
  const atual = mod.opcoes.find(o => o.id === mod.atual) || { nome: mod.atual };
  aba(tok, `<section class="painel painel-modelo">
    <h3>Modelo do Assistente</h3>
    <p class="assoc-legenda">Escolha qual modelo responde no Assistente <b>agora</b> (vale para todos, até o App reiniciar).</p>
    <div class="modelo-atual">Em uso: <b>${escHTML(atual.nome)}</b><br><code>${escHTML(mod.atual)}</code></div>
    <div class="modelo-opcoes">${mod.opcoes.map(o => `<label class="modelo-op ${o.id === mod.atual ? "sel" : ""}">
      <input type="radio" name="modelo" value="${escHTML(o.id)}" ${o.id === mod.atual ? "checked" : ""}>
      <span><b>${escHTML(o.nome)}</b><code>${escHTML(o.id)}</code></span></label>`).join("")}</div>
    <div class="botoes"><button class="btn btn-lava" id="trocar-modelo">Usar este modelo</button></div>
    <table class="tabela-ml modelo-tab"><thead><tr><th></th><th>Roteador (<code>assistente_llm</code>)</th><th>Modelo direto</th></tr></thead><tbody>
      <tr><td>Balanço 50/50 (o selo do modelo alterna)</td><td>✓</td><td>—</td></tr>
      <tr><td>Fallback se o modelo falhar</td><td>✓</td><td>—</td></tr>
      <tr><td>Inference table (<code>assistente_llm_payload</code>)</td><td>✓</td><td>—</td></tr>
      <tr><td>Service policies do Unity Gateway (selo "Unity Gateway")</td><td>✓</td><td>—</td></tr>
      <tr><td>Guardrails do grafo do App (dados sensíveis, jailbreak, juiz)</td><td>✓</td><td>✓</td></tr>
    </tbody></table>
    <p class="assoc-legenda">Teste: troque o modelo e peça no Assistente <i>"Monte um setup gamer até R$ 3 mil"</i> (o selo do roteador mostra qual modelo respondeu) e <i>"A loja X vende mais barato?"</i> (com o roteador e a service policy, selo "Unity Gateway").</p>
  </section>`);
  $$("input[name=modelo]").forEach(r => r.onchange = () => $$(".modelo-op").forEach(l => l.classList.toggle("sel", l.contains(r) && r.checked)));
  $("#trocar-modelo").onclick = async () => {
    const id = ($("input[name=modelo]:checked") || {}).value; if (!id) return;
    try { const r = await api("/api/admin/modelo", { json: { id } });
          toast(`<div class="toast-txt"><b>Assistente agora usa</b><span>${escHTML(r.atual)}</span></div>`, 3500); abaModelo(tok); }
    catch (e) { toastErro(e); }
  };
}
/* ── Conversas (admin): todas as perguntas do Assistente, de todos os clientes ── */
const NOME_AGENTE = { vendas: "Vendas", pos_venda: "Pós-venda", analista: "Analista" };
async function abaConversas(tok) {
  aba(tok, carregandoHTML());
  let d;
  try { d = await api("/api/admin/conversas"); } catch (e) { aba(tok, `<div class="painel painel-erro"><b>Conversas indisponíveis</b><span>${escHTML(e.message)}</span></div>`); return; }
  if (!d.ativa) { aba(tok, `<div class="painel"><b>Sem Lakebase</b><p class="assoc-legenda">As conversas ficam na tabela <code>loja.conversas</code> do Lakebase; sem ele, nada é gravado.</p></div>`); return; }
  // uma linha por pergunta: junta cada pergunta () com a resposta () que veio logo depois, na mesma conversa
  const msgs = [...(d.mensagens || [])].sort((a, b) => String(a.criado_em).localeCompare(String(b.criado_em)));
  const turnos = [];
  msgs.forEach(m => {
    if (m.papel === "user") turnos.push({ ...m, pergunta: m.conteudo, resposta: "" });
    else { const t = [...turnos].reverse().find(x => x.conversa_id === m.conversa_id && !x.resposta);
           if (t) Object.assign(t, { resposta: m.conteudo, agente: m.agente || t.agente, modelo: m.modelo }); }
  });
  turnos.reverse();
  const quando = t => new Date(t).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const limpo = t => String(t || "").replace(/\*\*|__|`/g, "").replace(/\s+/g, " ").trim();
  const nBloq = turnos.filter(t => t.agente === "bloqueado").length;
  aba(tok, `<section class="painel conversas-admin">
    <h3>Todas as perguntas do Assistente · todos os clientes</h3>
    <p class="assoc-legenda">${numPT(turnos.length)} perguntas (as mais recentes primeiro), ${numPT(nBloq)} bloqueadas pelos guardrails (em vermelho; não entram na memória do cliente).
      Fonte: <code>loja.conversas</code> no Lakebase desta instalação (cada <code>INSTALAR</code> cria um Lakebase novo), também lida no Lakehouse pelo catálogo registrado.</p>
    <button class="btn btn-borda btn-sm" id="conv-atualizar">↻ Atualizar</button>
    <table class="tabela-ml conv-tab"><thead><tr><th>Quando</th><th>Cliente</th><th>Pergunta</th><th>Resposta</th><th>Agente</th><th>Modelo</th></tr></thead>
    <tbody>${turnos.map(t => `<tr class="${t.agente === "bloqueado" ? "bloq" : ""}">
      <td class="mono">${escHTML(quando(t.criado_em))}</td><td>${escHTML(t.cliente_nome || t.cliente_id || "")}</td>
      <td class="conv-perg">${escHTML(limpo(t.pergunta).slice(0, 220))}</td>
      <td class="conv-resp">${escHTML(limpo(t.resposta).slice(0, 220))}${limpo(t.resposta).length > 220 ? "…" : ""}</td>
      <td>${t.agente === "bloqueado" ? "Bloqueado" : escHTML(NOME_AGENTE[t.agente] || t.agente || "")}</td>
      <td class="mono">${escHTML(String(t.modelo || "").split(" (via")[0])}</td></tr>`).join("")
      || `<tr><td colspan="6">Nenhuma pergunta ainda.</td></tr>`}</tbody></table></section>`);
  const b = $("#conv-atualizar"); if (b) b.onclick = () => abaConversas(tok);
}
/* ── SAC por voz (Whisper no Model Serving + ai_classify / ai_analyze_sentiment / ai_extract) ── */
async function gravacaoParaWav(blob) {
  // o navegador grava em webm/opus (Chrome) ou mp4 (Safari): converte para WAV 16 kHz mono, que o Whisper lê sem ffmpeg
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const buf = await ctx.decodeAudioData(await blob.arrayBuffer()); ctx.close();
  const taxa = 16000, off = new OfflineAudioContext(1, Math.max(1, Math.ceil(buf.duration * taxa)), taxa);
  const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const dv = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const txt = (o, t) => [...t].forEach((c, k) => dv.setUint8(o + k, c.charCodeAt(0)));
  txt(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); txt(8, "WAVE"); txt(12, "fmt "); dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, taxa, true); dv.setUint32(28, taxa * 2, true);
  dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); txt(36, "data"); dv.setUint32(40, pcm.length * 2, true);
  for (let k = 0; k < pcm.length; k++) { const v = Math.max(-1, Math.min(1, pcm[k])); dv.setInt16(44 + k * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true); }
  return new Blob([dv], { type: "audio/wav" });
}
function vozResultado(r) {
  return `<h4>Resultado</h4><table class="tabela-ml voz-tab">${VOZ_CAB}<tbody>${vozLinhaHTML(r)}</tbody></table>`;
}
async function vozEnviar(arquivo, origem, destino) {
  destino.innerHTML = `<div class="painel"><span class="spin"></span> Transcrevendo com o Whisper e analisando…</div>`;
  const fd = new FormData(); fd.append("audio", arquivo); fd.append("origem", origem);
  if (E.perfil?.cliente_id) fd.append("cliente_id", E.perfil.cliente_id);
  try { destino.innerHTML = vozResultado(await apiForm("/api/voz", fd)); }
  catch (e) { destino.innerHTML = `<div class="painel painel-erro"><b>Falhou</b><span>${escHTML(e.message)}</span></div>`; }
}
async function abaVoz(tok) {
  aba(tok, carregandoHTML());
  let d, sols = { solicitacoes: [] };
  try { [d, sols] = await Promise.all([api("/api/voz/atendimentos"), api("/api/admin/solicitacoes").catch(() => sols)]); }
  catch (e) { aba(tok, `<div class="painel painel-erro"><b>SAC por voz indisponível</b><span>${escHTML(e.message)}</span></div>`); return; }
  const linhas = d.atendimentos || [];
  const podeGravar = !!(navigator.mediaDevices && window.MediaRecorder);
  aba(tok, `<section class="painel voz">
    <div class="voz-topo"><h3>SAC por voz com <b>Whisper</b></h3><button class="btn btn-borda btn-sm" id="voz-atualizar" title="Recarrega o histórico e as solicitações (inclusive as abertas pelo Assistente)">↻ Atualizar</button></div>
    <p class="assoc-legenda">Áudio → <b>Whisper</b> (endpoint de Model Serving) → <code>ai_classify</code>, <code>ai_analyze_sentiment</code> e <code>ai_extract</code> → tabela <code>atendimentos_voz</code> (também no Genie).</p>
    <div class="voz-blocos">
      <div class="voz-bloco"><h4>Gravar agora</h4>
        <p class="assoc-legenda">Fale como um cliente ligando para o SAC (ex.: <i>"o pedido P 0 0 1 1 6 5 5 está atrasado"</i>).</p>
        ${podeGravar ? `<button class="btn btn-lava" id="voz-gravar">● Gravar</button> <span class="mono" id="voz-tempo"></span>`
                     : `<p class="assoc-legenda">Este navegador não permite gravar áudio.</p>`}
        <div id="voz-gravado"></div></div>
      <div class="voz-bloco"><h4>Enviar um arquivo</h4>
        <form id="voz-form" class="fc-form"><label class="drop">Escolher áudio (.wav / .mp3)<input type="file" name="audio" accept="audio/*" hidden></label>
          <button class="btn btn-borda" type="submit">Transcrever e analisar</button></form></div>
    </div>
    <div id="voz-resultado"></div>
    <h4>Histórico (atendimentos_voz) · todos os clientes</h4>
    <p class="assoc-legenda">Inclui as 6 ligações gravadas antes e transcritas na instalação, e tudo o que for gravado ou enviado aqui.</p>
    <p class="assoc-legenda"><b>Cadastrar no SAC</b> abre a solicitação ligada ao <b>pedido</b> (confira o número: o Whisper pode errar dígitos); ela aparece em <i>Meus pedidos</i> do cliente.</p>
    <table class="tabela-ml voz-tab">${VOZ_CAB}
    <tbody>${linhas.map(vozLinhaHTML).join("") || `<tr><td colspan="7">Nenhum atendimento processado ainda.</td></tr>`}</tbody></table>
    <h4>Solicitações do SAC · todos os clientes</h4>
    <table class="tabela-ml"><thead><tr><th>Protocolo</th><th>Cliente</th><th>Pedido</th><th>Tipo</th><th>Status</th><th>Prazo</th><th>Motivo</th></tr></thead>
    <tbody>${(sols.solicitacoes || []).map(sl => `<tr><td class="mono">${escHTML(sl.protocolo)}</td><td>${escHTML(sl.cliente_nome || "")}</td>
      <td class="mono">${escHTML(sl.pedido_id || "")}</td><td>${escHTML(sl.tipo || "")}</td><td>${escHTML(sl.status || "")}</td>
      <td>${escHTML(sl.prazo || "")}</td><td>${escHTML(String(sl.motivo || "").slice(0, 90))}</td></tr>`).join("") || `<tr><td colspan="7">Nenhuma solicitação ainda.</td></tr>`}</tbody></table></section>`);
  const ba = $("#voz-atualizar"); if (ba) ba.onclick = () => abaVoz(tok);
  const sec = $(".voz");
  if (sec) {   // delegação: vale para o histórico e para os resultados que entram depois
    sec.addEventListener("click", e => { const b = e.target.closest("[data-voz-cadastrar]"); if (b) { e.preventDefault(); vozFormSAC(b); } });
    sec.addEventListener("submit", e => { const f = e.target.closest(".voz-sac-form"); if (f) { e.preventDefault(); vozEnviarSAC(f); } });
  }
  const f = $("#voz-form"); if (!f) return;
  f.audio.onchange = () => { f.querySelector(".drop").firstChild.textContent = f.audio.files[0]?.name || "Escolher áudio"; };
  f.onsubmit = ev => { ev.preventDefault(); if (f.audio.files[0]) vozEnviar(f.audio.files[0], "arquivo", $("#voz-resultado")); };
  const bg = $("#voz-gravar"); if (!bg) return;
  let rec = null, partes = [], t0 = 0, relogio = null;
  bg.onclick = async () => {
    if (rec && rec.state === "recording") { rec.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) { toastErro(new Error("Sem acesso ao microfone: permita o microfone para este site.")); return; }
    partes = []; rec = new MediaRecorder(stream);
    rec.ondataavailable = e => e.data.size && partes.push(e.data);
    rec.onstop = async () => {
      clearInterval(relogio); stream.getTracks().forEach(t => t.stop());
      bg.textContent = "● Gravar"; bg.classList.remove("gravando"); $("#voz-tempo").textContent = "";
      const destino = $("#voz-gravado");
      try {
        const wav = await gravacaoParaWav(new Blob(partes, { type: rec.mimeType || "audio/webm" }));
        destino.innerHTML = `<audio controls src="${URL.createObjectURL(wav)}"></audio>`;
        // o resultado (tabela larga) vai para a área de largura inteira, abaixo dos dois blocos
        await vozEnviar(new File([wav], "gravacao.wav", { type: "audio/wav" }), "microfone", $("#voz-resultado"));
      } catch (e) { destino.innerHTML = `<div class="painel painel-erro"><b>Não consegui converter o áudio</b><span>${escHTML(e.message)}</span></div>`; }
    };
    rec.start(); t0 = Date.now(); bg.textContent = "■ Parar"; bg.classList.add("gravando");
    relogio = setInterval(() => { const sgs = Math.round((Date.now() - t0) / 1000); $("#voz-tempo").textContent = `${sgs}s`; if (sgs >= 60) rec.stop(); }, 250);
  };
}
const TIPO_POR_CATEGORIA = { troca: "Troca", defeito: "Reclamação", garantia: "Garantia", atraso: "Reclamação", cancelamento: "Devolução" };
function vozLinhaHTML(a) {
  const nome = String(a.arquivo || "").split("/").pop();
  const sac = a.protocolo ? `<span class="status ok">${escHTML(a.protocolo)}</span>`
    : (a.categoria && a.categoria !== "elogio") ? `<button class="btn btn-sm btn-borda" data-voz-cadastrar data-arquivo="${escHTML(a.arquivo || "")}"
        data-pedido="${escHTML(a.pedido_id || "")}" data-tipo="${escHTML(TIPO_POR_CATEGORIA[a.categoria] || "Reclamação")}"
        data-motivo="${escHTML(a.motivo || a.transcricao || "")}">Cadastrar no SAC</button>` : "—";
  return `<tr><td>${a.audio_url ? `<audio controls preload="none" src="${escHTML(a.audio_url)}"></audio>` : ""}<small class="mono">${escHTML(nome)}</small>
    ${a.fonte_transcricao ? `<br><small class="muted">${escHTML(a.fonte_transcricao)}</small>` : ""}</td>
    <td>${escHTML(a.cliente_nome || "—")}</td>
    <td>${escHTML(a.transcricao || "")}</td><td><span class="status info">${escHTML(a.categoria || "")}</span></td>
    <td>${escHTML(a.sentimento || "")}</td><td class="mono">${escHTML(a.pedido_id || "")}</td><td class="voz-sac">${sac}</td></tr>`;
}
const VOZ_CAB = `<thead><tr><th>Áudio</th><th>Cliente</th><th>Transcrição</th><th>Categoria</th><th>Sentimento</th><th>Pedido</th><th>SAC</th></tr></thead>`;
function vozFormSAC(b) {
  // o Whisper pode errar o número: o pedido fica editável; o cliente é o DONO do pedido (modo admin)
  const tipos = ["Troca", "Devolução", "Garantia", "Reclamação"];
  b.closest("td").innerHTML = `<form class="voz-sac-form" data-arquivo="${escHTML(b.dataset.arquivo)}">
    <label>Pedido<input name="pedido_id" value="${escHTML(b.dataset.pedido)}" placeholder="P0011655" required></label>
    <label>Tipo<select name="tipo">${tipos.map(t => `<option ${t === b.dataset.tipo ? "selected" : ""}>${t}</option>`).join("")}</select></label>
    <label>Motivo<input name="motivo" value="${escHTML(b.dataset.motivo.slice(0, 200))}"></label>
    <button class="btn btn-sm btn-lava">Abrir solicitação</button></form>`;
}
async function vozEnviarSAC(f) {
  const bt = f.querySelector("button"); bt.disabled = true; bt.innerHTML = `<span class="spin"></span>`;
  try {
    const r = await api("/api/voz/solicitacao", { json: { arquivo: f.dataset.arquivo, pedido_id: f.pedido_id.value, tipo: f.tipo.value, motivo: f.motivo.value } });
    f.closest("td").innerHTML = `<span class="status ok">${escHTML(r.protocolo)}</span><br><small>${escHTML(r.tipo)} · ${escHTML(r.cliente_nome || r.cliente_id)} · ${escHTML(r.prazo)}</small>`;
  } catch (e) { bt.disabled = false; bt.textContent = "Abrir solicitação"; toastErro(e); }
}

/* ── Previsão de vendas sob demanda (ai_forecast) ── */
async function abaPrevisao(tok) {
  aba(tok, carregandoHTML());
  let op;
  try { op = await api("/api/previsao/opcoes"); } catch (e) { aba(tok, `<div class="painel painel-erro"><b>Previsão indisponível</b><span>${escHTML(e.message)}</span></div>`); return; }
  const opt = (v, n) => `<option value="${escHTML(v)}">${escHTML(n ?? v)}</option>`;
  aba(tok, `<section class="painel previsao">
    <h3>Previsão de vendas com <code>ai_forecast</code></h3>
    <p class="assoc-legenda">Escolha as vendas, o histórico e o horizonte: o App monta a série a partir de <code>pedidos</code> + <code>itens_pedido</code>
      e roda <code>ai_forecast</code> <b>na hora</b> no SQL warehouse.</p>
    <form id="fc-form" class="fc-form">
      <label>Vendas de<select name="filtro_tipo"><option value="total">Loja inteira</option><option value="departamento">Departamento</option><option value="tipo">Tipo de produto</option><option value="produto">Produto</option></select></label>
      <label id="fc-valor-l" class="oculto">Qual<select name="valor" id="fc-valor"></select></label>
      <label>Métrica<select name="metrica"><option value="receita">Receita (R$)</option><option value="quantidade">Unidades</option></select></label>
      <label>Granularidade<select name="granularidade"><option value="dia">Diária</option><option value="semana">Semanal</option></select></label>
      <label>Histórico<select name="historico_dias"><option value="90">90 dias</option><option value="180" selected>180 dias</option><option value="365">1 ano</option></select></label>
      <label>Horizonte<select name="horizonte"><option value="8">8 períodos</option><option value="14">14 períodos</option><option value="30" selected>30 períodos</option></select></label>
      <button class="btn btn-lava" type="submit">Prever com ai_forecast</button>
    </form>
    <div id="fc-res"></div></section>`);
  const f = $("#fc-form");
  const alfa = lista => lista.sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));   // menus em ordem alfabética
  const listas = { departamento: alfa((op.departamentos || []).map(d => [d, d])),
    tipo: alfa((op.tipos || []).map(t => typeof t === "string" ? [t, t] : [t.tipo, `${t.tipo} · ${t.departamento}`])),
    produto: alfa((op.produtos || []).map(p => [p.produto_id, p.nome])) };
  f.filtro_tipo.onchange = () => {
    const k = f.filtro_tipo.value, l = listas[k];
    $("#fc-valor-l").classList.toggle("oculto", !l);
    $("#fc-valor").innerHTML = (l || []).map(([v, n]) => opt(v, n)).join("");
  };
  f.onsubmit = async ev => {
    ev.preventDefault();
    const b = f.querySelector("button"); b.disabled = true; b.innerHTML = `<span class="spin"></span> Rodando ai_forecast…`;
    const corpo = Object.fromEntries(new FormData(f));
    ["historico_dias", "horizonte"].forEach(k => corpo[k] = Number(corpo[k]));
    if (corpo.filtro_tipo === "total") delete corpo.valor;
    try { $("#fc-res").innerHTML = previsaoHTML(await api("/api/previsao", { json: corpo }), corpo); ligarDicaPrevisao($("#fc-res")); }
    catch (e) { $("#fc-res").innerHTML = `<div class="painel painel-erro"><b>Falhou</b><span>${escHTML(e.message)}</span></div>`; }
    b.disabled = false; b.innerHTML = "Prever com ai_forecast";
  };
}
// passa o mouse no gráfico da previsão: linha-guia, ponto e a caixinha com data, valor e intervalo
function ligarDicaPrevisao(raiz) {
  const svg = raiz.querySelector(".fc-graf"); if (!svg) return;
  const pts = JSON.parse(svg.dataset.pontos || "[]"), W = +svg.dataset.w, rec = svg.dataset.receita === "1", sem = svg.dataset.semana === "1";
  const guia = svg.querySelector(".fc-guia"), ponto = svg.querySelector(".fc-ponto"), dica = raiz.querySelector(".fc-dica");
  const fmt = v => rec ? reais(v) : numPT(Math.round(v));
  const dataBR = d => { const dt = new Date(String(d).slice(0, 10) + "T12:00:00");
    return (sem ? "semana de " : dt.toLocaleDateString("pt-BR", { weekday: "short" }) + ", ") + dt.toLocaleDateString("pt-BR"); };
  svg.addEventListener("mousemove", e => {
    const caixa = svg.getBoundingClientRect(), x = (e.clientX - caixa.left) * (W / caixa.width);
    let k = 0; pts.forEach((p, i) => { if (Math.abs(p.x - x) < Math.abs(pts[k].x - x)) k = i; });
    const p = pts[k]; if (!p) return;
    guia.setAttribute("x1", p.x); guia.setAttribute("x2", p.x); ponto.setAttribute("cx", p.x); ponto.setAttribute("cy", p.y);
    ponto.classList.toggle("prev", !!p.p);
    [guia, ponto, dica].forEach(el => el.classList.remove("oculto"));
    dica.innerHTML = `<b>${escHTML(dataBR(p.d))}</b><span>${p.p ? "Previsto" : p.h ? "Hoje até agora (parcial)" : "Real"}: <b>${fmt(p.v)}</b></span>`
      + (p.p ? `<small>intervalo: ${fmt(p.lo)} a ${fmt(p.hi)}</small>` : "");
    const px = p.x * caixa.width / W, py = p.y * caixa.height / +svg.viewBox.baseVal.height;
    dica.style.left = Math.min(caixa.width - 190, Math.max(0, px + 12)) + "px"; dica.style.top = Math.max(0, py - 60) + "px";
  });
  svg.addEventListener("mouseleave", () => [guia, ponto, dica].forEach(el => el.classList.add("oculto")));
}
function previsaoHTML(r, par) {
  if (r.erro) return `<div class="painel painel-erro"><b>Não deu para prever</b><span>${escHTML(r.erro)}</span></div>`;
  const real = r.serie_real || [], prev = r.previsao || [];
  const parcial = real.length && real[real.length - 1].parcial;   // hoje: dia incompleto, ponto à parte (fora da linha e das somas)
  const completos = parcial ? real.slice(0, -1) : real;
  const ms = typeof r.ms === "object" ? (r.ms.serie || 0) + (r.ms.ai_forecast || 0) : (r.ms || 0);
  if (!real.length) return `<p class="assoc-legenda">Sem vendas no período escolhido.</p>`;
  const datas = [...real.map(x => x.data), ...prev.map(x => x.data)];
  const vals = [...real.map(x => +x.valor), ...prev.flatMap(x => [+x.valor, +(x.superior ?? x.valor), +(x.inferior ?? x.valor)])];
  const max = Math.max(...vals) * 1.08 || 1, min = Math.min(0, ...vals);
  const ehReceita0 = (par.metrica || "receita") === "receita";
  const rotuloY = t => ehReceita0 ? "R$ " + numPT(Math.round(t)) : numPT(Math.round(t));
  // margem esquerda do tamanho do maior rótulo do eixo (números grandes não ficam cortados)
  const W = 900, Hh = 300, M = { l: 16 + 7.2 * Math.max(...[0, .25, .5, .75, 1].map(t => rotuloY(min + t * (max - min)).length)), r: 16, t: 14, b: 30 };
  const X = i => M.l + (i / Math.max(1, datas.length - 1)) * (W - M.l - M.r);
  const Y = v => M.t + (1 - (v - min) / (max - min)) * (Hh - M.t - M.b);
  const ehReceita = (par.metrica || "receita") === "receita";
  const fmt = v => ehReceita ? reais(v) : numPT(Math.round(v));
  const lin = (pts) => pts.map(([i, v], k) => `${k ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const n0 = real.length;
  const banda = prev.length ? `M${prev.map((x, k) => `${X(n0 + k).toFixed(1)},${Y(+(x.superior ?? x.valor)).toFixed(1)}`).join(" L")} L${prev.map((x, k) => [n0 + k, x]).reverse().map(([i, x]) => `${X(i).toFixed(1)},${Y(+(x.inferior ?? x.valor)).toFixed(1)}`).join(" L")} Z` : "";
  const ticks = [0, .25, .5, .75, 1].map(t => min + t * (max - min));
  const nx = Math.min(8, datas.length), passo = Math.max(1, Math.floor(datas.length / nx));
  const somaPrev = prev.reduce((a, x) => a + (+x.valor || 0), 0), somaUlt = completos.slice(-prev.length).reduce((a, x) => a + (+x.valor || 0), 0);
  const varPct = somaUlt ? ((somaPrev / somaUlt - 1) * 100) : 0;
  const aviso = r.aviso ? `<div class="painel fc-aviso">${escHTML(r.aviso)}</div>` : "";
  return `${aviso}<div class="fc-kpis"><div><span>Previsto nos próximos ${prev.length} períodos</span><b>${fmt(somaPrev)}</b></div>
      <div><span>Mesmo nº de períodos anteriores</span><b>${fmt(somaUlt)}</b></div>
      <div><span>Variação</span><b class="${varPct >= 0 ? "pos" : "neg"}">${varPct >= 0 ? "+" : ""}${varPct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</b></div>
      <div><span>Tempo (série + ai_forecast)</span><b>${(ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s</b></div></div>
    <div class="fc-graf-caixa"><svg class="fc-graf" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Vendas reais e previstas"
      data-pontos="${escHTML(JSON.stringify(datas.map((d, i) => i < n0 ? { d, v: +real[i].valor, h: real[i].parcial ? 1 : 0, x: +X(i).toFixed(1), y: +Y(+real[i].valor).toFixed(1) }
        : { d, v: +prev[i - n0].valor, lo: +(prev[i - n0].inferior ?? prev[i - n0].valor), hi: +(prev[i - n0].superior ?? prev[i - n0].valor), p: 1,
            x: +X(i).toFixed(1), y: +Y(+prev[i - n0].valor).toFixed(1) })))}" data-w="${W}" data-receita="${ehReceita ? 1 : 0}"
      data-semana="${par.granularidade === "semana" ? 1 : 0}" data-yt="${M.t}" data-yb="${Hh - M.b}">
      ${ticks.map(t => `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(t)}" y2="${Y(t)}" class="grade"/><text x="${M.l - 6}" y="${Y(t) + 4}" text-anchor="end">${escHTML(rotuloY(t))}</text>`).join("")}
      ${datas.map((d, i) => i % passo === 0 ? `<text x="${X(i)}" y="${Hh - 8}" text-anchor="middle">${escHTML(String(d).slice(5, 10).split("-").reverse().join("/"))}</text>` : "").join("")}
      ${banda ? `<path d="${banda}" class="banda"/>` : ""}
      <path d="${lin(completos.map((x, i) => [i, +x.valor]))}" class="real"/>
      ${prev.length && completos.length ? `<path d="${lin([[completos.length - 1, +completos[completos.length - 1].valor], ...prev.map((x, k) => [n0 + k, +x.valor])])}" class="prev"/>` : ""}
      ${parcial ? `<circle cx="${X(n0 - 1)}" cy="${Y(+real[n0 - 1].valor)}" r="4.5" class="fc-parcial"/>` : ""}
      <line x1="${X(n0 - 1)}" x2="${X(n0 - 1)}" y1="${M.t}" y2="${Hh - M.b}" class="hoje"/><text x="${X(n0 - 1) + 4}" y="${M.t + 10}" class="hoje-t">hoje</text>
      <line class="fc-guia oculto" y1="${M.t}" y2="${Hh - M.b}"/><circle class="fc-ponto oculto" r="4"/>
    </svg><div class="fc-dica oculto"></div></div>
    <p class="fc-leg"><span class="l-real"></span>Real <span class="l-prev"></span>Previsto (ai_forecast) <span class="l-banda"></span>Intervalo de previsão${parcial ? ` <span class="l-parcial"></span>Hoje (parcial: só as compras feitas até agora)` : ""}</p>
    <details class="fc-sql"><summary>SQL executado</summary><pre class="sql">${escHTML(r.sql || "")}</pre></details>`;
}

function painelMLHTML(m) {
  if (!m || !m.disponivel) return `<section class="painel"><h3>Modelo de recomendação (ML)</h3><p class="assoc-legenda">${escHTML((m && m.mensagem) || "Modelo ainda não treinado.")}</p></section>`;
  const melhor = Math.max(...m.placar.map(p => p.hit_rate_10 || 0));
  const linhas = m.placar.map(p => {
    const top = (p.hit_rate_10 || 0) === melhor;
    return `<tr class="${top ? "vencedor" : ""}"><td>${escHTML(p.abordagem)}</td>
      <td><div class="barra-ml"><i style="width:${Math.round(100 * (p.hit_rate_10 || 0) / (melhor || 1))}%"></i><b>${(100 * (p.hit_rate_10 || 0)).toFixed(1)}%</b></div></td>
      <td>${(p.ndcg_10 || 0).toFixed(3)}</td><td>${(100 * (p.precision_10 || 0)).toFixed(2)}%</td></tr>`;
  }).join("");
  const imp = (m.importancias || []).slice(0, 8);
  const maxImp = Math.max(...imp.map(i => i.importancia || 0), 0.0001);
  const nClientes = (m.placar[0] || {}).n_clientes_teste;
  const auc = (m.placar.find(p => p.auc_modelo) || {}).auc_modelo;
  return `<section class="painel painel-ml"><h3>Modelo de recomendação (ML) · regras + SVD + Gradient Boosting</h3>
    <p class="assoc-legenda">Avaliação temporal: o último pedido de ${nClientes ? numPT(nClientes) : "cada"} clientes foi separado como teste. Acerto = o cliente comprou algo do top 10 recomendado.${auc ? ` AUC do ranking: <b>${Number(auc).toFixed(3)}</b>.` : ""}</p>
    <table class="tabela-ml"><thead><tr><th>Abordagem</th><th>Hit-rate@10</th><th>NDCG@10</th><th>Precision@10</th></tr></thead><tbody>${linhas}</tbody></table>
    <div class="duas" style="margin-top:18px"><div><h4>O que o modelo mais usa</h4>${imp.map(i => `<div class="imp-ml"><span>${escHTML(i.feature)}</span><div class="barra-ml fina"><i style="width:${Math.max(3, Math.round(100 * i.importancia / maxImp))}%"></i></div></div>`).join("")}</div>
      <div><h4>Rastreabilidade</h4><dl class="config">
        <div><dt>Modelo no Unity Catalog</dt><dd>${escHTML(m.modelo_uc || "—")}</dd></div>
        <div><dt>Experimento MLflow</dt><dd>${m.experimento_url ? `<a href="${escHTML(m.experimento_url)}" target="_blank" rel="noopener">${escHTML(m.experimento)}</a>` : "—"}</dd></div>
        <div><dt>Modelo servido (Model Serving)</dt><dd>${m.endpoint ? `<span class="pontinho ${m.endpoint.pronto ? "ok" : "alerta"}"></span> <a href="${escHTML(m.endpoint.url || "#")}" target="_blank" rel="noopener"><code>${escHTML(m.endpoint.nome)}</code></a> · ${escHTML(m.endpoint.estado || "—")}${m.endpoint.modelo ? ` · ${escHTML(m.endpoint.modelo)}` : ""}` : "— (o App lê a tabela recomendacoes_personalizadas)"}</dd></div>
        ${m.endpoint ? `<div><dt>Última recomendação veio de</dt><dd>${m.endpoint.ultima_origem === "endpoint" ? "endpoint (tempo real)" : m.endpoint.ultima_origem === "tabela" ? "tabela (reserva: endpoint frio ou indisponível)" : "—"}</dd></div>` : ""}
        <div><dt>Onde aparece</dt><dd>Fileira “Recomendado para você” e ferramenta MCP <code>recomendar_para_cliente</code></dd></div></dl></div></div>
  </section>`;
}

async function abaPainel(tok) {
  aba(tok, carregandoHTML());
  const [s, ml] = await Promise.all([api("/api/estudio/status"), api("/api/estudio/ml").catch(() => null)]);
  if (tok !== E.tok) return;
  const c = s.contagens || s.contadores || {};
  const kpi = (n, v) => `<div class="kpi"><small>${n}</small><b>${v == null ? "—" : numPT(v)}</b></div>`;
  const indices = s.indices || [], config = s.config || {};
  aba(tok, `<div class="kpis">${kpi("Produtos", c.produtos)}${kpi("Do Estúdio", c.produtos_estudio ?? c.produtos_do_estudio)}${kpi("Clientes", c.clientes)}
      ${kpi("Pedidos", c.pedidos)}${kpi("Regras de associação", c.regras ?? c.associacoes)}${kpi("Trechos de ajuda", c.chunks)}</div>
    <div class="duas">
      <section class="painel"><h3>Índices de busca (Vector Search)</h3>
        ${indices.length ? indices.map(i => `<div class="idx"><span class="pontinho ${i.pronto ? "ok" : "alerta"}"></span><code>${escHTML(String(i.nome || "").split(".").pop())}</code>
          <span>${i.linhas != null ? numPT(i.linhas) + " linhas" : ""}</span><small>${escHTML(i.mensagem || "")}</small></div>`).join("") : `<p class="assoc-legenda">Sem informações de índice.</p>`}
        <div class="botoes"><button class="btn btn-borda" data-acao="sync/produtos">Sincronizar catálogo</button><button class="btn btn-borda" data-acao="sync/ajuda">Sincronizar ajuda</button></div>
      </section>
      <section class="painel"><h3>Recomendações e cache</h3>
        <p class="assoc-legenda">Recalcula <code>quem_comprou_tambem_comprou</code>, incluindo as compras feitas no app, e recarrega o cache do catálogo.</p>
        <div class="botoes"><button class="btn btn-lava" data-acao="recalcular">Recalcular associações</button><button class="btn btn-borda" data-acao="recarregar">Recarregar cache</button></div>
      </section></div>
    ${painelMLHTML(ml)}
    <section class="painel"><h3>Configuração</h3><dl class="config">${Object.entries(config).map(([k, v]) => `<div><dt>${escHTML(k)}</dt><dd>${escHTML(v)}</dd></div>`).join("") || `<p class="assoc-legenda">—</p>`}</dl></section>`);
  $$("[data-acao]", $("#aba")).forEach(b => b.onclick = async () => {
    const txt = b.innerHTML; b.disabled = true; b.innerHTML = `<span class="spin"></span> processando…`;
    try { const r = await api("/api/estudio/" + b.dataset.acao, { method: "POST" }); toast(`<div class="toast-txt"><b>Concluído</b><span>${escHTML(JSON.stringify(r)).slice(0, 180)}</span></div>`); }
    catch (e) { toastErro(e); }
    b.disabled = false; b.innerHTML = txt;
  });
}

const ICONES_LISTA = ["top", "jaqueta", "vestido", "calca", "tenis", "bota", "sandalia", "bolsa", "mochila", "oculos", "relogio", "bone", "sofa", "poltrona", "mesa", "luminaria", "tapete", "almofada", "tecido", "vaso", "quadro", "prateleira", "planta", "panela", "cafeteira", "pratos", "eletro", "caneca", "tv", "fone", "caixasom", "celular", "notebook", "teclado", "mouse", "console", "led", "cadeira", "garrafa", "bike", "barraca", "halter", "frasco", "paleta", "secador"];
const CAMPOS_PRODUTO = [
  ["nome", "Nome do produto", "texto", "tudo"], ["marca_produto", "Marca própria", "texto"], ["departamento", "Departamento", "dep"], ["categoria", "Categoria", "texto"],
  ["tipo", "Tipo", "texto"], ["icone", "Desenho (ícone)", "icone"], ["estilo_id", "Estilo", "estilo"], ["cor", "Cor (nome)", "texto"], ["cor_hex", "Cor (hex)", "cor"],
  ["material", "Material", "texto"], ["tamanhos", "Tamanhos", "texto"], ["preco", "Preço (R$)", "num"], ["preco_promocional", "Preço promocional (R$)", "num"],
  ["parcelas_sem_juros", "Parcelas sem juros", "int"], ["estoque", "Estoque", "int"], ["avaliacao", "Avaliação (1 a 5)", "dec"], ["n_avaliacoes", "Nº de avaliações", "int"],
  ["lancamento", "Lançamento", "check"], ["descricao", "Descrição", "area", "tudo"], ["descricao_visual", "Descrição visual (alimenta a busca)", "area", "tudo"],
  ["especificacoes", "Especificações (chave: valor; …)", "area", "tudo"],
];
function campoHTML([k, rot, tipo, largura], v = {}) {
  const val = v[k] ?? "";
  const cl = largura ? "tudo" : "";
  switch (tipo) {
    case "dep": return `<label class="campo ${cl}"><span>${rot}</span><select name="${k}">${E.departamentos.map(d => `<option ${d.nome === val ? "selected" : ""}>${escHTML(d.nome)}</option>`).join("")}</select></label>`;
    case "icone": return `<label class="campo ${cl}"><span>${rot}</span><select name="${k}">${ICONES_LISTA.map(i => `<option ${i === val ? "selected" : ""}>${i}</option>`).join("")}</select></label>`;
    case "estilo": return `<label class="campo ${cl}"><span>${rot}</span><select name="${k}">${E.estilos.map(e => `<option value="${escHTML(e.estilo_id)}" ${e.estilo_id === val ? "selected" : ""}>${escHTML(e.nome)}</option>`).join("")}</select></label>`;
    case "area": return `<label class="campo ${cl}"><span>${rot}</span><textarea name="${k}" rows="3">${escHTML(val)}</textarea></label>`;
    case "check": return `<label class="campo check"><input type="checkbox" name="${k}" ${val ? "checked" : ""}><span>${rot}</span></label>`;
    case "cor": return `<label class="campo"><span>${rot}</span><input type="color" name="${k}" value="${hexOK(val)}"></label>`;
    case "num": return `<label class="campo"><span>${rot}</span><input name="${k}" type="number" step="0.01" min="0" value="${val == null ? "" : escHTML(val)}"></label>`;
    case "int": return `<label class="campo"><span>${rot}</span><input name="${k}" type="number" step="1" min="0" value="${val == null ? "" : escHTML(val)}"></label>`;
    case "dec": return `<label class="campo"><span>${rot}</span><input name="${k}" type="number" step="0.1" min="0" max="5" value="${val == null ? "" : escHTML(val)}"></label>`;
    default: return `<label class="campo ${cl}"><span>${rot}</span><input name="${k}" type="text" value="${escHTML(val)}"></label>`;
  }
}
const camposHTML = v => `<div class="campos">${CAMPOS_PRODUTO.map(c => campoHTML(c, v)).join("")}</div>`;
function lerCampos(form) {
  const d = {};
  CAMPOS_PRODUTO.forEach(([k, , tipo]) => {
    const el = form.querySelector(`[name=${k}]`); if (!el) return;
    if (tipo === "check") d[k] = el.checked;
    else if (tipo === "num" || tipo === "dec") d[k] = el.value === "" ? null : Number(el.value);
    else if (tipo === "int") d[k] = el.value === "" ? null : parseInt(el.value, 10);
    else d[k] = el.value;
  });
  return d;
}
async function abaNovo(tok) {
  let exemplos = []; try { exemplos = (await api("/api/estudio/fichas/exemplos")).exemplos || []; } catch { }
  aba(tok, `<div class="novo-grid"><div>
      <label class="drop" id="drop-ficha"><input type="file" accept="application/pdf" hidden id="ficha-arquivo">
        <span class="drop-icone">${ICO.doc}</span><b>Envie a ficha técnica do fornecedor (PDF)</b>
        <span>Texto, tabelas de especificações, dimensões e fotos do produto</span></label>
      ${exemplos.length ? `<p class="rotulo-sec">Ou use uma ficha de exemplo</p><div class="botoes-col">${exemplos.map(x => `<button class="btn btn-borda" data-ficha="${escHTML(x.caminho)}">${escHTML(String(x.nome).replace(/^ficha_/, "").replace(/\.pdf$/i, "").replace(/_/g, " "))}</button>`).join("")}</div>` : ""}
      <section class="painel passos-info"><h3>Como funciona</h3><ol>
        <li>O PDF vai para o Volume <code>midia/fichas/</code></li>
        <li><code>ai_parse_document</code> extrai texto, tabelas e imagens</li>
        <li>As figuras são recortadas e você escolhe a foto do produto</li>
        <li>O LLM preenche a ficha; você revisa</li>
        <li>Publicar grava na tabela <code>produtos</code> e sincroniza a busca</li></ol></section>
    </div><div id="ficha-res"><div class="painel-vazio">O rascunho do produto aparece aqui.</div></div></div>`);
  const inp = $("#ficha-arquivo"), drop = $("#drop-ficha");
  if (!inp) return;
  inp.onchange = () => inp.files[0] && processarFicha({ arquivo: inp.files[0] });
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("sobre"); };
  drop.ondragleave = () => drop.classList.remove("sobre");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("sobre"); if (e.dataTransfer.files[0]) processarFicha({ arquivo: e.dataTransfer.files[0] }); };
  $$("[data-ficha]").forEach(b => b.onclick = () => processarFicha({ exemplo: b.dataset.ficha }));
}
const PASSOS_FICHA = ["Enviando o PDF para o Volume…", "ai_parse_document: lendo texto, tabelas e imagens…", "Recortando as figuras…", "Estruturando a ficha com o LLM…"];
async function processarFicha({ arquivo, exemplo }) {
  const res = $("#ficha-res");
  res.innerHTML = `<div class="painel"><ol class="passos" id="passos">${PASSOS_FICHA.map((p, i) => `<li data-p="${i}"><span class="pontinho"></span>${p}</li>`).join("")}</ol></div>`;
  // cada bolinha acende quando o backend REALMENTE começa a etapa (main.py /api/estudio/fichas → estudio.processar_ficha)
  const marcar = i => $$("#passos li").forEach(li => { const k = +li.dataset.p; li.querySelector(".pontinho").className = "pontinho " + (k < i ? "ok" : k === i ? "alerta" : ""); });
  marcar(0);
  const acomp = acompanhar(marcar);
  try {
    const fd = new FormData(); if (arquivo) fd.append("arquivo", arquivo); if (exemplo) fd.append("exemplo", exemplo);
    fd.append("tarefa", acomp.tarefa);
    const r = await apiForm("/api/estudio/fichas", fd);
    acomp.parar(); renderRascunho(r);
  } catch (e) { acomp.parar(); res.innerHTML = `<div class="painel painel-erro"><b>Não foi possível processar a ficha</b><span>${escHTML(e.message)}</span></div>`; }
}
const sanitizarTabela = h => String(h).replace(/<(?!\/?(table|tr|th|td|thead|tbody|tfoot)\b)[^>]*>/gi, "");
function renderRascunho(r) {
  const res = $("#ficha-res"), f = r.ficha || {}, figs = r.figuras || [];
  let imagem = r.imagem_path || (figs[0] && figs[0].caminho) || null;
  const midia = c => `/api/midia?caminho=${encodeURIComponent(c)}`;
  res.innerHTML = `<div class="painel ficha-cab">
      <div><b>${escHTML(r.arquivo || r.chave)}</b><span class="muted">ai_parse_document · ${r.segundos_parse ?? "—"} s</span></div>
      <div class="chips">${Object.entries(r.elementos || {}).map(([k, v]) => `<span>${escHTML(k)}: ${escHTML(v)}</span>`).join("")}</div></div>
    ${figs.length ? `<div class="secao-mini"><h3>Imagens extraídas</h3><p class="muted">Clique na foto que representa o produto</p>
      <div class="figs">${figs.map(fg => `<figure data-fig="${escHTML(fg.caminho)}" class="${fg.caminho === imagem ? "sel" : ""} ${fg.retrato ? "retrato" : ""}">
        <img src="${midia(fg.caminho)}" alt=""><figcaption>p.${fg.pagina} · ${escHTML(String(fg.descricao || "").slice(0, 60))}</figcaption></figure>`).join("")}</div></div>` : ""}
    ${(r.tabelas_html || []).length ? `<details class="tabelas"><summary>Ver as ${r.tabelas_html.length} tabelas extraídas</summary><div class="tab-html">${r.tabelas_html.map(sanitizarTabela).join("")}</div></details>` : ""}
    <div class="ficha-edicao">
      <form id="ficha-form">${camposHTML(f)}</form>
      <aside class="ficha-prev"><span class="kicker">Pré-visualização</span><div id="ficha-card"></div>
        <button class="btn btn-lava btn-grande btn-cheio" id="publicar">Publicar no catálogo</button>
        <p class="assoc-legenda">Grava na tabela <code>produtos</code> e dispara o sync do índice de busca.</p></aside></div>`;
  const atualizar = () => {
    const d = { ...lerCampos($("#ficha-form")), produto_id: r.chave, origem: "estudio", imagem_path: null };
    $("#ficha-card").innerHTML = produtoHTML(d, { imgSrc: imagem ? midia(imagem) : null, semAdd: true, semAssoc: true });
  };
  $$("[data-fig]", res).forEach(fg => fg.onclick = () => {
    imagem = fg.dataset.fig; $$("[data-fig]", res).forEach(x => x.classList.toggle("sel", x === fg)); atualizar();
  });
  $("#ficha-form").oninput = atualizar;
  atualizar();
  $("#publicar").onclick = async () => {
    const b = $("#publicar"); b.disabled = true; b.innerHTML = `<span class="spin"></span> publicando…`;
    try {
      const p = await api(`/api/estudio/fichas/${encodeURIComponent(r.chave)}/publicar`, { json: { ficha: lerCampos($("#ficha-form")), imagem_path: imagem } });
      toast(`<div class="toast-txt"><b>${escHTML(p.nome)} publicado</b><span>Já está no catálogo; a busca semântica sincroniza em instantes.</span></div>`, 6000, "sucesso");
      location.hash = "#/produto/" + encodeURIComponent(p.produto_id);
    } catch (e) { toastErro(e); b.disabled = false; b.innerHTML = "Publicar no catálogo"; }
  };
}
async function abaProdutos(tok, q = "", origem = "") {
  aba(tok, `<div class="barra-filtros">
      <div class="busca-mini">${ICO.busca}<input id="ep-q" placeholder="Buscar por nome ou ID" value="${escHTML(q)}"></div>
      <label class="campo-f">Origem <select id="ep-o"><option value="">Todas</option><option value="estudio" ${origem === "estudio" ? "selected" : ""}>Do Estúdio</option><option value="seed" ${origem === "seed" ? "selected" : ""}>Base inicial</option></select></label>
    </div>
    <div class="tabela-wrap"><table class="tabela"><thead><tr><th></th><th>Produto</th><th>Departamento</th><th>Preço</th><th>Origem</th><th></th></tr></thead>
      <tbody id="ep-tb"><tr><td colspan="6">${carregandoHTML()}</td></tr></tbody></table></div>
    <div id="ep-editor"></div>`);
  if (tok !== E.tok) return;
  let lista = [];
  const carregar = async () => {
    const r = await api(`/api/estudio/produtos?q=${encodeURIComponent($("#ep-q").value)}&origem=${$("#ep-o").value}&limite=200`);
    lista = reg(Array.isArray(r) ? r : (r.produtos || []));
    const tb = $("#ep-tb"); if (!tb) return;
    tb.innerHTML = lista.map(p => `<tr><td><div class="mini-foto">${fotoHTML(p)}</div></td>
        <td><b>${escHTML(p.nome)}</b><div class="mono muted">${escHTML(p.produto_id)}</div></td>
        <td>${escHTML(p.departamento || "")}</td><td>${precoHTML(p)}</td>
        <td><span class="tag-origem ${escHTML(p.origem)}">${p.origem === "estudio" ? "ESTÚDIO" : "BASE"}</span></td>
        <td class="acoes-tab"><button class="btn btn-sm btn-borda" data-ed="${escHTML(p.produto_id)}">Editar</button>
          <label class="btn btn-sm btn-borda">Foto<input type="file" accept="image/*" hidden data-foto="${escHTML(p.produto_id)}"></label>
          <button class="btn btn-sm btn-perigo" data-rm="${escHTML(p.produto_id)}">Remover</button></td></tr>`).join("")
      || `<tr><td colspan="6" class="vazio">Nenhum produto encontrado.</td></tr>`;
  };
  let deb; $("#ep-q").oninput = () => { clearTimeout(deb); deb = setTimeout(carregar, 280); };
  $("#ep-o").onchange = carregar;
  $("#ep-tb").onclick = async e => {
    const ed = e.target.closest("[data-ed]"), rm = e.target.closest("[data-rm]");
    if (ed) return editarProduto(E.cache[ed.dataset.ed]);
    if (rm) {
      if (!confirm("Remover este produto do catálogo (DELETE na tabela Delta)?")) return;
      try { await api("/api/estudio/produtos/" + encodeURIComponent(rm.dataset.rm), { method: "DELETE" }); toast("Produto removido."); carregar(); }
      catch (err) { toastErro(err); }
    }
  };
  $("#ep-tb").onchange = async e => {
    const inp = e.target.closest("[data-foto]"); if (!inp || !inp.files[0]) return;
    const fd = new FormData(); fd.append("imagem", inp.files[0]);
    try { await apiForm(`/api/estudio/produtos/${encodeURIComponent(inp.dataset.foto)}/imagem`, fd); toast("Foto do produto atualizada."); carregar(); }
    catch (err) { toastErro(err); }
  };
  carregar();
}
function editarProduto(p) {
  if (!p) return;
  const ed = $("#ep-editor");
  ed.innerHTML = `<section class="painel editor"><div class="editor-cab"><h3>Editar · ${escHTML(p.nome)}</h3><span class="mono muted">${escHTML(p.produto_id)}</span></div>
    <div class="ficha-edicao"><form id="ep-form">${camposHTML(p)}</form>
    <aside class="ficha-prev"><div id="ep-card">${produtoHTML(p, { semAdd: true, semAssoc: true })}</div>
      <button class="btn btn-lava btn-grande btn-cheio" id="ep-salvar">Salvar alterações</button></aside></div></section>`;
  ed.scrollIntoView({ behavior: "smooth", block: "start" });
  $("#ep-form").oninput = () => { $("#ep-card").innerHTML = produtoHTML({ ...p, ...lerCampos($("#ep-form")) }, { semAdd: true, semAssoc: true }); };
  $("#ep-salvar").onclick = async () => {
    try {
      await api(`/api/estudio/produtos/${encodeURIComponent(p.produto_id)}`, { method: "PUT", json: lerCampos($("#ep-form")) });
      toast("Produto atualizado (UPDATE na tabela Delta + sync do índice)."); abaProdutos(E.tok);
    } catch (e) { toastErro(e); }
  };
}
async function abaAjuda(tok) {
  aba(tok, carregandoHTML());
  const linhas = d => (d.documentos || []).map(x => `<tr><td><b>${escHTML(x.documento || x.arquivo)}</b><div class="mono muted">${escHTML(x.arquivo || "")}</div></td>
      <td>${x.chunks ?? ""}</td><td>${x.tem_tabela ? "✓" : ""}</td><td><button class="btn btn-sm btn-perigo" data-rmdoc="${escHTML(x.arquivo)}">Remover</button></td></tr>`).join("")
    || `<tr><td colspan="4" class="vazio">Nenhum documento.</td></tr>`;
  const d = await api("/api/estudio/documentos");
  if (tok !== E.tok) return;
  aba(tok, `<div class="novo-grid"><div>
      <label class="drop" id="drop-doc"><input type="file" accept="application/pdf" hidden id="doc-arquivo">
        <span class="drop-icone">${ICO.doc}</span><b>Adicionar PDF à central de ajuda</b>
        <span>ai_parse_document, trechos por seção e índice de ajuda (RAG do assistente)</span></label>
      <div id="doc-res"></div></div>
    <section class="painel tab-pad"><table class="tabela"><thead><tr><th>Documento</th><th>Trechos</th><th>Tabelas</th><th></th></tr></thead>
      <tbody id="doc-tb">${linhas(d)}</tbody></table></section></div>`);
  const recarregarDocs = async () => { const x = await api("/api/estudio/documentos"); $("#doc-tb").innerHTML = linhas(x); };
  $("#doc-arquivo").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    const res = $("#doc-res"); res.innerHTML = `<div class="painel"><span class="spin"></span> ai_parse_document em andamento…</div>`;
    try {
      const fd = new FormData(); fd.append("arquivo", f);
      const r = await apiForm("/api/estudio/documentos", fd);
      const chunks = r.chunks || [];
      res.innerHTML = `<div class="painel"><b>${escHTML(r.arquivo || f.name)}</b> · ${r.segundos_parse ?? "—"} s · ${chunks.length} trechos
        <div class="chips">${Object.entries(r.elementos || {}).map(([k, v]) => `<span>${escHTML(k)}: ${escHTML(v)}</span>`).join("")}</div>
        ${chunks.slice(0, 4).map(c => `<div class="chunk"><b>${escHTML(c.secao || "")}</b>${c.tem_tabela ? " · tabela" : ""}<p>${escHTML(String(c.conteudo || "").split("\n").slice(1).join(" ").slice(0, 260))}</p></div>`).join("")}</div>`;
      recarregarDocs();
    } catch (err) { res.innerHTML = `<div class="painel painel-erro">${escHTML(err.message)}</div>`; }
  };
  $("#doc-tb").onclick = async e => {
    const b = e.target.closest("[data-rmdoc]"); if (!b) return;
    if (!confirm("Remover este documento da central de ajuda?")) return;
    try { await api("/api/estudio/documentos/" + encodeURIComponent(b.dataset.rmdoc), { method: "DELETE" }); recarregarDocs(); }
    catch (err) { toastErro(err); }
  };
}
async function abaMcp(tok) {
  aba(tok, carregandoHTML());
  const d = await api("/api/mcp/ferramentas");
  const url = location.origin + "/mcp";
  aba(tok, `<section class="painel mcp-cab"><div><span class="kicker">Model Context Protocol</span><h2>${escHTML(d.servidor || "Servidor MCP")}</h2>
      <p class="assoc-legenda">Servidor MCP (Streamable HTTP) embutido neste App. O assistente usa estas ferramentas; qualquer cliente MCP autorizado pode usar o endereço ao lado.</p></div>
      <div class="endereco"><span>Endereço</span><code>${escHTML(url)}</code><button class="btn btn-sm btn-borda" data-copiar="${escHTML(url)}">Copiar</button></div></section>
    <div class="mcp-grid">${(d.ferramentas || []).map(f => `<article class="painel mcp-tool"><b>${escHTML(f.nome)}</b><span class="muted">${escHTML(f.titulo || "")}</span>
      <p>${escHTML(f.descricao || "")}</p><div class="chips">${Object.keys((f.parametros || {}).properties || {}).map(p => `<span class="mono">${escHTML(p)}</span>`).join("")}</div></article>`).join("")}</div>
    <section class="painel dica"><b>Combine com outros MCPs no AI Playground</b>
      <p>No AI Playground, escolha um modelo com suporte a ferramentas, adicione este App como servidor MCP personalizado e combine com o <code>system.ai.google_calendar</code>, o MCP gerenciado do Unity Gateway. Também dá para combinar com um Genie com Gmail, Calendar e Drive.</p>
      <p class="exemplo">“Encontre um conjunto de sala escandinava para o meu apartamento e marque a entrega na minha agenda para sábado às 10h.”</p></section>`);
}

/* ───────────── assistente (chat) ───────────── */
const SUGESTOES_CHAT = ["Monte um setup gamer com até R$ 3 mil", "Quais produtos combinam com um quarto boho?", "Quem comprou um sofá também levou o quê?", "Qual é a política de troca?"];
const NOMES_FERRAMENTAS = { adicionar_a_sacola: "🛍️ Sacola", buscar_produtos: "Busca semântica", quem_comprou_tambem_comprou: "Quem comprou também comprou", compre_junto: "Compre junto",
  ficha_produto: "Ficha do produto", investigar_imagem: "Detetive de produtos", analisar_imagem: "Análise de imagem", consultar_dados: "Genie · dados", suporte: "Central de ajuda",
  pedidos_do_cliente: "Meus pedidos", agendar_entrega: "Google Calendar (MCP)", abrir_solicitacao: "Abrir solicitação (SAC)", recomendar_para_cliente: "Recomendação ML" };
const NOS_GRAFO = {
  guardrail_pii_entrada: ["🛡️", "Dados sensíveis"], guardrail_jailbreak: ["🛡️", "Regras de segurança"],
  guardrail_juiz: ["⚖️", "Juiz + supervisor"], bloqueio: ["⛔", "Bloqueio"],
  vendas: ["🛍️", "Agente de Vendas"], pos_venda: ["📦", "Agente de Pós-venda"], analista: ["📊", "Agente Analista"],
  guardrail_ferramentas: ["🛡️", "Permissões das ferramentas"], ferramentas: ["🔧", "Ferramentas (MCP)"], guardrail_saida: ["🛡️", "Revisão da resposta"] };
function trilhaHTML(passos) {
  const total = passos.reduce((a, p) => a + (p.ms || 0), 0);
  const nG = passos.filter(p => p.no.startsWith("guardrail")).length;
  const resumo = passos.some(p => p.status === "bloqueado" && (p.no === "bloqueio" || p.no.startsWith("guardrail_j"))) ? "bloqueado pelos guardrails"
    : passos.some(p => p.status !== "ok") ? "com correções dos guardrails" : "todos os guardrails ok";
  return `<details class="trilha"><summary>🕸️ Como cheguei nesta resposta <span>${passos.length} etapas · ${nG} guardrails · ${(total / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s · ${resumo}</span></summary>
    <ol>${passos.map(p => { const [ic, nome] = NOS_GRAFO[p.no] || ["•", p.no];
      return `<li class="${escHTML(p.status)}"><i>${ic}</i><div><b>${escHTML(nome)}</b><span>${escHTML(p.detalhe || "")}</span></div><em>${p.ms >= 1000 ? (p.ms / 1000).toFixed(1) + " s" : p.ms + " ms"}</em></li>`; }).join("")}</ol>
    <small>Grafo LangGraph · <a href="/assistente/grafo" target="_blank" rel="noopener">ver o diagrama</a></small></details>`;
}
function addMsg(papel, texto, extra = {}) {
  const box = $("#chat-msgs"), div = document.createElement("div");
  div.className = "msg " + papel;
  if (papel === "user") div.innerHTML = (extra.img ? `<img class="anexo" src="${extra.img}" alt="">` : "")
    + (texto ? `<p>${escHTML(texto)}</p>` : "");
  else {
    let h = md(texto);
    if (extra.laudo && (extra.laudo.cores_hex || []).length) h += `<div class="paleta">${extra.laudo.cores_hex.map(c => `<i style="background:${hexOK(c)}"></i>`).join("")}</div>`;
    if (extra.genie && extra.genie.sql) h += `<pre class="sql">${escHTML(extra.genie.sql)}</pre>`;
    if (extra.produtos && extra.produtos.length) h += `<div class="msg-prods">${reg(extra.produtos).slice(0, 4).map(p => miniProdutoHTML(p)).join("")}</div>`;
    if (extra.ferramentas && extra.ferramentas.length) h += `<div class="ferramentas">${[...new Set(extra.ferramentas)].map(f => `<span>${escHTML(NOMES_FERRAMENTAS[f] || "MCP · " + f)}</span>`).join("")}</div>`;
    if (extra.bloqueado) h = `<div class="agente-tag guardrail">🛡️ ${(extra.guardrail || []).some(g => g.categoria === "unity_gateway") ? "Unity Gateway · service policy" : "Guardrail"}</div>` + h;
    else if (extra.agente) h = `<div class="agente-tag">${escHTML(extra.agente.icone || "🤖")} ${escHTML(extra.agente.nome || "")}</div>` + h;
    if (extra.agenda) h += `<div class="chat-agenda">${agendaHTML(extra.agenda)}</div>`;
    if (extra.guardrail && extra.guardrail.length) h += `<div class="ferramentas guardrail">${extra.guardrail.map(g => `<span title="${escHTML(g.detalhe || "")}">🛡️ ${escHTML(rotuloGuardrail(g))}</span>`).join("")}</div>`;
    if (extra.memoria && extra.memoria.gravado) h += `<div class="ferramentas memoria"><span title="Pergunta e resposta gravadas na tabela loja.conversas do Lakebase">🧠 ${extra.memoria.mensagens ? `lembrei ${extra.memoria.mensagens} msg de conversas anteriores · ` : ""}salvo no Lakebase</span></div>`;
    if (extra.modelos && extra.modelos.length) h += `<div class="ferramentas modelos">${extra.modelos.map(m => `<span title="Modelo escolhido pelo roteador do Unity Gateway">🔀 ${escHTML(m)}</span>`).join("")}</div>`;
    if (extra.passos && extra.passos.length) h += trilhaHTML(extra.passos);
    else if (extra.trilha && extra.trilha.length) h += `<div class="trilha-grafo">🕸️ ${extra.trilha.map(escHTML).join(" → ")}</div>`;
    div.innerHTML = h;
  }
  box.appendChild(div); box.scrollTop = box.scrollHeight;
  return div;
}
/* 🧠 memória do chat: conversas gravadas no Lakebase (loja.conversas), por cliente */
const novoIdConversa = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
function avisoMemoria(html) {
  const div = document.createElement("div"); div.className = "memoria-aviso";
  div.innerHTML = `<span>🧠 ${html}</span><button type="button" data-esquecer title="Apagar a memória deste cliente no Lakebase">Esquecer</button>`;
  $("#chat-msgs").appendChild(div);
}
async function abrirChat() {
  const cli = E.perfil?.cliente_id, tok = (E.chatTok = (E.chatTok || 0) + 1);
  E.conversaId = novoIdConversa(); E.memoriaTotal = 0;
  if (!cli || !E.marca.memoria) { iniciarChat(); return; }
  const carregando = addMsg("bot", ""); carregando.innerHTML = `<div class="digitando"><span></span><span></span><span></span></div>`;
  const inp = $("#chat-input"); inp.disabled = true;               // não deixa enviar antes de a memória chegar
  let m = null;
  try { m = await api("/api/chat/memoria?cliente_id=" + encodeURIComponent(cli)); } catch { }
  carregando.remove(); inp.disabled = false;
  if (tok !== E.chatTok || cli !== E.perfil?.cliente_id) return;   // trocou de perfil ou clicou em Nova conversa enquanto carregava
  if (!m || !m.mensagens || !m.mensagens.length) { iniciarChat(); return; }
  E.memoriaTotal = m.total_mensagens || 0;
  E.conversaId = m.conversa_id;
  const quando = new Date(m.mensagens[m.mensagens.length - 1].em).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  avisoMemoria(`Retomei sua última conversa (${quando}). Memória no <b>Lakebase</b>: ${numPT(m.total_mensagens)} mensagens em ${numPT(m.total_conversas)} conversa(s).`);
  E.chat = m.mensagens.map(x => ({ role: x.role, content: x.content }));
  m.mensagens.forEach(x => addMsg(x.role === "user" ? "user" : "bot", x.content,
    x.role === "user" ? {} : { agente: G_AGENTES[x.agente] }));
}
const G_AGENTES = { vendas: { icone: "🛍️", nome: "Agente de Vendas" }, pos_venda: { icone: "📦", nome: "Agente de Pós-venda" }, analista: { icone: "📊", nome: "Agente Analista" } };
async function esquecerMemoria() {
  const cli = E.perfil?.cliente_id; if (!cli) return;
  if (!confirm("Apagar tudo o que o assistente lembra das suas conversas? (tabela loja.conversas no Lakebase)")) return;
  try { await api("/api/chat/memoria?cliente_id=" + encodeURIComponent(cli), { method: "DELETE" }); E.memoriaTotal = 0; novaConversa(); }
  catch (err) { toastErro(err); }
}
function iniciarChat() {
  addMsg("bot", `Olá${E.perfil?.apelido ? ", " + primeiroNome(E.perfil.apelido) : ""}! Sou o assistente da ${E.marca.marca || "loja"}. Posso **buscar produtos**, montar **kits**, dizer **quem comprou também comprou** e tirar dúvidas sobre **trocas e entregas**. Anexe a **foto de um produto** e eu procuro os parecidos na loja.`);
  $("#chat-sugestoes").innerHTML = SUGESTOES_CHAT.map(s => `<button>${escHTML(s)}</button>`).join("");
}
$("#fab-chat").onclick = () => {
  const c = $("#chat"); const abriu = c.classList.toggle("oculto") === false;
  $("#fab-chat").classList.toggle("ativo", abriu);
  if (abriu) { if (!E.chat.length && !$("#chat-msgs").children.length) abrirChat(); $("#chat-input").focus(); }
};
function novaConversa() {
  E.chatTok = (E.chatTok || 0) + 1; $("#chat-input").disabled = false;   // cancela uma restauração em andamento
  E.chat = []; E.anexo = null; E.conversaId = novoIdConversa();
  $("#chat-msgs").innerHTML = ""; $("#anexo-preview").classList.add("oculto"); $("#chat-input").value = "";
  if (E.memoriaTotal && E.perfil?.cliente_id) avisoMemoria("Conversa nova, mas eu lembro das anteriores (Lakebase). Pergunte: <i>o que eu te perguntei da última vez?</i>");
  iniciarChat();
}
$("#nova-conversa").onclick = () => { novaConversa(); $("#chat-input").focus(); };
$("#fechar-chat").onclick = () => { $("#chat").classList.add("oculto"); $("#fab-chat").classList.remove("ativo"); };
$("#chat-arquivo").onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  const prev = $("#anexo-preview"); prev.classList.remove("oculto"); prev.innerHTML = `<span class="spin"></span><span>Enviando a foto…</span>`;
  try {
    const fd = new FormData(); fd.append("imagem", f);
    const r = await apiForm("/api/upload-imagem", fd);
    E.anexo = { caminho: r.caminho, url: URL.createObjectURL(f) };
    prev.innerHTML = `<img src="${E.anexo.url}" alt=""><span>Foto anexada</span><button class="btn btn-sm btn-borda" id="tirar-anexo">Remover</button>`;
    $("#tirar-anexo").onclick = () => { E.anexo = null; prev.classList.add("oculto"); };
    if (!$("#chat-input").value) $("#chat-input").value = "Tem algo parecido com este produto?";
  } catch (err) { prev.innerHTML = `<span>Falha no envio: ${escHTML(err.message)}</span>`; E.anexo = null; }
  e.target.value = "";
};
// envia uma pergunta ao Assistente (o balão do cliente já pode existir: pergunta falada)
async function enviarAoAssistente(msg, { anexo = null } = {}) {
  E.chat.push({ role: "user", content: msg });
  const pensando = addMsg("bot", ""); pensando.innerHTML = `<div class="digitando"><span></span><span></span><span></span></div>`;
  try {
    if (!E.conversaId) E.conversaId = novoIdConversa();
    const corpo = { mensagens: E.chat, conversa_id: E.conversaId,
                    sacola: E.carrinho.map(i => `${i.quantidade}× ${i.nome}`) };   // o agente sabe o que está na sacola
    if (E.perfil?.cliente_id) corpo.cliente_id = E.perfil.cliente_id;
    if (anexo) corpo.imagem = anexo.caminho;
    const r = await api("/api/chat", { json: corpo });
    pensando.remove();
    addMsg("bot", r.resposta || "", r);
    E.chat.push({ role: "assistant", content: r.resposta || "" });
    // o agente colocou produtos na sacola (ferramenta adicionar_a_sacola): adiciona de verdade e avisa
    (r.sacola || []).forEach((p, k) => addCarrinho(p, { qtd: p.quantidade || 1, aviso: k === (r.sacola.length - 1) }));
    if (r.acao === "abrir_sacola") abrirGaveta();   // "quero finalizar a compra": mostra a sacola com o botão Finalizar pedido
    if (r.memoria && r.memoria.gravado) E.memoriaTotal = (E.memoriaTotal || 0) + 2;
  } catch (err) { pensando.remove(); addMsg("bot", "Não consegui responder agora: " + err.message); }
}
$("#chat-form").onsubmit = async e => {
  e.preventDefault();
  const inp = $("#chat-input"), texto = inp.value.trim();
  if (!texto && !E.anexo) return;
  const anexo = E.anexo; E.anexo = null; $("#anexo-preview").classList.add("oculto"); inp.value = "";
  $("#chat-sugestoes").innerHTML = "";
  const msg = texto || "Tem algo parecido com este produto?";
  addMsg("user", msg, { img: anexo && anexo.url });
  await enviarAoAssistente(msg, { anexo });
};
// 🎙️ pergunta falada: balão "gravando" com tempo → balão com o áudio + "transcrevendo" → texto do Whisper → Assistente
(() => {
  const bt = $("#chat-mic"); if (!bt) return;
  let rec = null, partes = [], relogio = null, bolha = null;
  const caixa = () => { const c = $("#chat-msgs"); c.scrollTop = c.scrollHeight; };
  bt.onclick = async () => {
    if (rec && rec.state === "recording") { rec.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { toastErro(new Error("Sem acesso ao microfone: permita o microfone para este site.")); return; }
    $("#chat-sugestoes").innerHTML = "";
    partes = []; rec = new MediaRecorder(stream);
    rec.ondataavailable = e => e.data.size && partes.push(e.data);
    bolha = addMsg("user", "");
    const t0 = Date.now();
    const tick = () => { const sgs = Math.round((Date.now() - t0) / 1000);
      bolha.innerHTML = `<p class="gravando-txt"><span class="ponto-rec"></span> Gravando… ${sgs}s<small>clique no 🎙️ de novo para parar (máx. 30 s)</small></p>`; };
    tick(); relogio = setInterval(tick, 500);
    rec.onstop = async () => {
      clearInterval(relogio); stream.getTracks().forEach(t => t.stop()); bt.classList.remove("gravando"); bt.disabled = true;
      try {
        const wav = await gravacaoParaWav(new Blob(partes, { type: rec.mimeType || "audio/webm" }));
        const url = URL.createObjectURL(wav);
        bolha.innerHTML = `<audio class="audio-msg" controls src="${url}"></audio>
          <small class="transcricao"><span class="spin"></span> transcrevendo com o Whisper…${E.marca.whisper_frio ? " (se o endpoint estava ocioso, pode levar alguns minutos para acordar)" : ""}</small>`;
        caixa();
        const fd = new FormData(); fd.append("audio", new File([wav], "pergunta.wav", { type: "audio/wav" }));
        const r = await apiForm("/api/voz/transcrever", fd);
        bolha.innerHTML = `<audio class="audio-msg" controls src="${url}"></audio><small class="transcricao">🎙️ transcrito pelo Whisper</small><p>${escHTML(r.texto)}</p>`;
        caixa(); bt.disabled = false;
        await enviarAoAssistente(r.texto);
      } catch (e) {
        bolha.querySelector(".transcricao") ? bolha.querySelector(".transcricao").innerHTML = `⚠️ não consegui transcrever: ${escHTML(e.message)}`
          : (bolha.innerHTML = `<p>⚠️ não consegui gravar: ${escHTML(e.message)}</p>`);
        bt.disabled = false;
      }
    };
    rec.start(); bt.classList.add("gravando");
    setTimeout(() => rec && rec.state === "recording" && rec.stop(), 30000);   // no máximo 30 s
  };
})();
$("#chat-sugestoes").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  $("#chat-input").value = b.textContent; $("#chat-form").requestSubmit();
};

/* ───────────── cabeçalho, gaveta, perfil: eventos globais ───────────── */
$("#form-busca").onsubmit = e => {
  e.preventDefault();
  const q = $("#campo-busca").value.trim();
  if (q) location.hash = "#/busca?q=" + encodeURIComponent(q);
};
function renderMenuDep() {
  $("#menu-dep").innerHTML = `<div class="dd-grade">${E.departamentos.map(d => `<a href="#/departamento/${encodeURIComponent(d.nome)}" data-fecha-dd>
    <b>${escHTML(d.nome)}</b><small>${numPT(d.n_produtos)} produtos</small></a>`).join("")}</div>`;
}
$("#btn-dep").onclick = e => { e.stopPropagation(); $("#dd-dep").classList.toggle("aberto"); };
$("#btn-sacola").onclick = () => abrirGaveta();
$("#fechar-gaveta").onclick = () => fecharGaveta();
$("#gaveta-fundo").onclick = () => fecharGaveta();
$("#btn-perfil").onclick = () => telaPerfis();
$("#fechar-perfis").onclick = fecharPerfis;
document.addEventListener("keydown", e => { if (e.key === "Escape" && E.perfil && $("#tela-perfis").classList.contains("aberta")) fecharPerfis(); });
$("#lista-perfis").onclick = e => { const b = e.target.closest(".perfil"); if (b) escolherPerfil(b.dataset.cliente || null); };
window.addEventListener("scroll", () => $("#topo").classList.toggle("solida", scrollY > 24), { passive: true });
window.addEventListener("hashchange", rotear);

document.addEventListener("click", async e => {
  const t = e.target;
  if (!t.closest("#dd-dep")) $("#dd-dep").classList.remove("aberto");
  const add = t.closest("[data-add]");
  if (add) {
    e.preventDefault(); e.stopPropagation();
    try { const p = E.cache[add.dataset.add] || await buscarProduto(add.dataset.add); addCarrinho(p); }
    catch (err) { toastErro(err); }
    return;
  }
  const q = t.closest("[data-qtd]");
  if (q) { alterarQtd(q.dataset.pid, Number(q.dataset.qtd)); return; }
  const rm = t.closest("[data-remover]");
  if (rm) { E.carrinho = E.carrinho.filter(i => i.produto_id !== rm.dataset.remover); salvarCarrinho(); return; }
  if (t.closest("[data-finalizar]")) { finalizarPedido(); return; }
  const ag = t.closest("[data-agendar]"); if (ag) { agendarEntrega(ag.dataset.agendar, ag); return; }
  if (t.closest("[data-abrir-sacola]")) { abrirGaveta(); return; }
  if (t.closest("[data-fechar-gaveta]")) { fecharGaveta(); return; }
  if (t.closest("[data-trocar-perfil]")) { telaPerfis(); return; }
  if (t.closest("[data-esquecer]")) { esquecerMemoria(); return; }

  const cp = t.closest("[data-copiar]");
  if (cp) { navigator.clipboard?.writeText(cp.dataset.copiar); cp.textContent = "Copiado"; return; }
  const fe = t.closest("[data-fechar]");
  if (fe) { fe.closest(".toast")?.remove(); return; }
  const card = t.closest("[data-pid]");
  if (card && !t.closest("button, a, input, select, label, textarea")) location.hash = "#/produto/" + encodeURIComponent(card.dataset.pid);
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { fecharGaveta(); $("#tela-perfis").classList.contains("aberta") && E.perfil && $("#tela-perfis").classList.remove("aberta"); }
  if (e.key === "Enter" && e.target.matches?.("[data-pid]")) location.hash = "#/produto/" + encodeURIComponent(e.target.dataset.pid);
});
$("#campo-busca").addEventListener("keydown", e => { if (e.key === "Escape") e.target.blur(); });

/* ───────────── boot ───────────── */
async function esperarCatalogo() {
  for (let i = 0; i < 150; i++) {
    let s = null;
    try { s = await api("/api/saude"); if (s.pronto) return true; } catch { }
    app.innerHTML = `<div class="splash"><span class="spin grande"></span><b>Preparando a loja…</b>
      <span>${escHTML(s && s.erro ? s.erro : "Carregando o catálogo e os índices de busca. Isso leva alguns instantes na primeira vez.")}</span></div>`;
    await new Promise(r => setTimeout(r, 2000));
  }
  return false;
}
function aplicarMarca() {
  const m = E.marca.marca || "Loja";
  $("#marca-nome").textContent = m;
  const mp = $("#marca-perfis"); if (mp) mp.textContent = m;   // tela "Quem está comprando?"
  document.title = m + (E.marca.slogan ? " · " + E.marca.slogan : "");
}
async function boot() {
  $("#logo-mark").innerHTML = LOGO_SVG;
  try { E.marca = { ...E.marca, ...(await api("/api/config")) }; } catch { }
  aplicarMarca();
  aplicarAdmin();
  $("#chat-mic").classList.toggle("oculto", !E.marca.whisper);
  try {
    await esperarCatalogo();
    const d = await api("/api/perfis");
    E.perfis = d.perfis || []; E.estilos = d.estilos || []; E.departamentos = d.departamentos || [];
    registrarEstilos(E.estilos);
    renderMenuDep();
    if (E.perfil) E.perfil = E.perfis.find(p => p.cliente_id === E.perfil.cliente_id) || E.perfil;
    atualizarContador();
    if (E.perfil) {
      atualizarPerfil();
      if (!location.hash || location.hash === "#" || location.hash === "#/") location.hash = "#/inicio"; else rotear();
    } else telaPerfis();
  } catch (e) {
    app.innerHTML = erroPagina(e);
  }
}
boot();
