/* ═══════════════════════════════════════════════════════════════════
   Arte de produto (SVG procedural em fundo de estúdio),
   cards de produto e helpers de formatação. JavaScript puro, sem build.
   Chaves de `icone` (docs/ESPEC_VAREJO.md) → desenhos abaixo.
   Determinístico: o mesmo produto_id sempre gera o mesmo desenho.
   ═══════════════════════════════════════════════════════════════════ */

const escHTML = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reais = v => (v == null || v === "") ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const numPT = v => Number(v || 0).toLocaleString("pt-BR");

/* fração 0–1 (aceita também percentual 0–100 vindo do backend) */
const fracao = v => v == null ? 0 : (Number(v) > 1 ? Number(v) / 100 : Number(v));
const pctTxt = v => Math.round(fracao(v) * 100) + "%";

/* ───────────── cores ───────────── */
const HEX_RE = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i;
function hexOK(h, fallback = "#7a8792") {
  if (!h) return fallback;
  const s = String(h).trim();
  if (!HEX_RE.test(s)) return fallback;
  let v = s.replace("#", "");
  if (v.length === 3) v = v.split("").map(c => c + c).join("");
  return "#" + v.toLowerCase();
}
function mix(a, b, t) {
  const A = hexOK(a), B = hexOK(b);
  const pa = [1, 3, 5].map(i => parseInt(A.substr(i, 2), 16)), pb = [1, 3, 5].map(i => parseInt(B.substr(i, 2), 16));
  return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("");
}
function hashStr(s) { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }

/* cores dos estilos (vindas de GET /api/perfis → estilos[].cores) */
const ESTILOS_CORES = {};
const ESTILOS_NOME = {};
function registrarEstilos(lista) {
  (lista || []).forEach(e => {
    const cs = String(e.cores || "").split(",").map(s => s.trim()).filter(s => HEX_RE.test(s)).map(s => hexOK(s));
    if (cs.length) ESTILOS_CORES[e.estilo_id] = cs;
    ESTILOS_NOME[e.estilo_id] = e.nome;
  });
}
const PALETA_PADRAO = ["#f3f1ed", "#dfe5e8", "#1b3139"];
function coresEstilo(id) {
  const c = ESTILOS_CORES[id] || PALETA_PADRAO;
  return [c[0], c[1] || c[0], c[2] || c[1] || c[0]];
}
const nomeEstilo = id => ESTILOS_NOME[id] || id || "";

/* ───────────── preço ───────────── */
const temPromo = p => p.preco_promocional != null && Number(p.preco_promocional) > 0 && Number(p.preco_promocional) < Number(p.preco);
const precoVigente = p => temPromo(p) ? Number(p.preco_promocional) : Number(p.preco || 0);
const descontoPct = p => temPromo(p) ? Math.round((1 - Number(p.preco_promocional) / Number(p.preco)) * 100) : 0;

function precoHTML(p, grande = false) {
  if (temPromo(p)) return `<div class="preco ${grande ? "grande" : ""}"><s>${reais(p.preco)}</s><b class="promo">${reais(precoVigente(p))}</b></div>`;
  return `<div class="preco ${grande ? "grande" : ""}"><b>${reais(p.preco)}</b></div>`;
}
function parcelaHTML(p) {
  const n = Number(p.parcelas_sem_juros || 0);
  if (n < 2) return "";
  return `<div class="parcela">${n}x de <b>${reais(precoVigente(p) / n)}</b> sem juros</div>`;
}
function estrelasHTML(av, n) {
  if (av == null) return "";
  const pc = Math.max(0, Math.min(5, Number(av))) / 5 * 100;
  return `<span class="estrelas" title="${Number(av).toFixed(1)} de 5"><span class="cheias" style="width:${pc}%">★★★★★</span><span class="vazias">★★★★★</span></span>`
    + (n != null ? `<span class="n-aval">${numPT(n)}</span>` : "");
}

/* ───────────── arte SVG ───────────── */
const G = (t, x) => `url(#${t}${x.u})`;
const SHD = (x, rx = 62, cy = 180, ry = 9) => `<ellipse cx="100" cy="${cy}" rx="${rx}" ry="${ry}" fill="${G("s", x)}"/>`;

function defsArte({ u, c, hi, sh, dk, c0, c1 }) {
  return `<defs>
    <radialGradient id="bg${u}" cx=".5" cy=".36" r=".82"><stop offset="0" stop-color="${mix(c0, "#ffffff", .6)}"/><stop offset=".68" stop-color="${c0}"/><stop offset="1" stop-color="${c1}"/></radialGradient>
    <linearGradient id="b${u}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${hi}"/><stop offset=".55" stop-color="${c}"/><stop offset="1" stop-color="${dk}"/></linearGradient>
    <linearGradient id="v${u}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${dk}"/><stop offset=".36" stop-color="${hi}"/><stop offset=".62" stop-color="${c}"/><stop offset="1" stop-color="${dk}"/></linearGradient>
    <linearGradient id="m${u}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#8d979f"/><stop offset=".35" stop-color="#f5f8fa"/><stop offset=".65" stop-color="#9aa4ac"/><stop offset="1" stop-color="#e3e8eb"/></linearGradient>
    <linearGradient id="k${u}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4b525a"/><stop offset="1" stop-color="#13161a"/></linearGradient>
    <linearGradient id="w${u}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#e2e0dc"/></linearGradient>
    <radialGradient id="s${u}"><stop offset="0" stop-color="#000" stop-opacity=".45"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
  </defs>`;
}

const DESENHOS = {
  top: x => `${SHD(x, 70)}
    <path d="M76 36 Q100 58 124 36 L164 50 L188 98 L162 112 L152 100 L152 172 Q152 178 146 178 L54 178 Q48 178 48 172 L48 100 L38 112 L12 98 L36 50 Z" fill="${G("b", x)}"/>
    <path d="M76 36 Q100 58 124 36" fill="none" stroke="${x.dk}" stroke-width="5" stroke-linecap="round"/>
    <path d="M48 166 H152" stroke="${x.dk}" stroke-width="2" opacity=".25"/>
    <path d="M66 70 Q62 114 64 156" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".2"/>`,

  jaqueta: x => `${SHD(x, 72)}
    <path d="M70 34 L40 46 L14 130 L44 142 L54 104 L54 176 L146 176 L146 104 L156 142 L186 130 L160 46 L130 34 Q100 52 70 34 Z" fill="${G("b", x)}"/>
    <path d="M70 34 L98 108 M130 34 L102 108" stroke="${x.dk}" stroke-width="3" fill="none"/>
    <path d="M100 56 V176" stroke="#e9edf0" stroke-width="2.5" stroke-dasharray="3 3"/>
    <path d="M24 132 L44 140 M176 132 L156 140" stroke="${x.dk}" stroke-width="7" stroke-linecap="round"/>
    <path d="M60 128 L86 124 M114 124 L140 128" stroke="${x.dk}" stroke-width="3" stroke-linecap="round"/>
    <path d="M62 62 Q58 110 60 150" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".2"/>`,

  vestido: x => `${SHD(x, 56)}
    <path d="M80 28 L120 28 L124 62 Q126 70 138 74 L162 176 L38 176 L62 74 Q74 70 76 62 Z" fill="${G("b", x)}"/>
    <path d="M80 28 Q100 50 120 28" fill="none" stroke="${x.dk}" stroke-width="4"/>
    <path d="M60 104 Q100 114 140 104" fill="none" stroke="${x.dk}" stroke-width="4" stroke-linecap="round"/>
    <path d="M40 168 Q100 182 160 168" fill="none" stroke="${x.dk}" stroke-width="2" opacity=".35"/>
    <path d="M78 36 Q74 72 84 104" stroke="#fff" stroke-width="6" fill="none" opacity=".2" stroke-linecap="round"/>`,

  calca: x => `${SHD(x, 70)}
    <path d="M46 26 L154 26 L162 176 L110 176 L100 104 L90 176 L38 176 Z" fill="${G("b", x)}"/>
    <rect x="44" y="20" width="112" height="16" rx="4" fill="${x.dk}"/>
    <path d="M100 104 V176" stroke="${x.dk}" stroke-width="2.5"/>
    <path d="M70 44 L66 168 M130 44 L134 168" stroke="#fff" stroke-width="2" stroke-dasharray="4 4" opacity=".4"/>
    <path d="M56 62 Q68 74 74 92" fill="none" stroke="${x.dk}" stroke-width="2" opacity=".35"/>`,

  tenis: x => `${SHD(x, 80, 166, 8)}
    <path d="M18 146 Q16 132 32 132 L176 130 Q188 131 188 144 L188 150 Q188 162 174 162 L30 162 Q18 162 18 150 Z" fill="#f5f4f0"/>
    <path d="M22 151 H184" stroke="${x.dk}" stroke-width="2" opacity=".22"/>
    <path d="M26 130 L26 92 Q26 80 42 83 L70 90 Q88 94 96 70 Q104 50 126 52 Q144 56 150 84 L176 114 Q190 124 186 132 Z" fill="${G("b", x)}"/>
    <path d="M34 120 Q104 98 180 124" fill="none" stroke="#fff" stroke-width="4" opacity=".9" stroke-linecap="round"/>
    <path d="M98 74 L110 84 M110 62 L122 72 M120 56 L131 66" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
    <path d="M26 96 Q40 88 66 92" fill="none" stroke="${x.dk}" stroke-width="3" opacity=".35"/>`,

  bota: x => `${SHD(x, 74, 180, 7)}
    <path d="M56 22 L122 22 L122 110 L168 122 Q186 128 186 146 L186 162 Q186 172 174 172 L54 172 Z" fill="${G("b", x)}"/>
    <rect x="50" y="158" width="140" height="16" rx="5" fill="${x.dk}"/>
    <path d="M52 26 H126" stroke="${x.dk}" stroke-width="8" stroke-linecap="round" opacity=".8"/>
    <path d="M64 52 L112 60 M64 68 L112 76 M64 84 L112 92" stroke="#fff" stroke-width="2.5" opacity=".45" stroke-linecap="round"/>
    <path d="M70 44 Q80 40 90 46" fill="none" stroke="#fff" stroke-width="6" opacity=".15" stroke-linecap="round"/>`,

  sandalia: x => `${SHD(x, 74, 160, 7)}
    <path d="M30 150 Q24 134 46 134 L156 130 Q178 128 178 142 Q178 154 160 156 L44 158 Q32 160 30 150 Z" fill="${x.sh}"/>
    <path d="M50 134 Q76 86 104 132" fill="none" stroke="${G("b", x)}" stroke-width="11" stroke-linecap="round"/>
    <path d="M94 134 Q124 92 154 130" fill="none" stroke="${G("b", x)}" stroke-width="11" stroke-linecap="round"/>
    <path d="M40 146 Q100 122 170 142" fill="none" stroke="${x.hi}" stroke-width="5" stroke-linecap="round" opacity=".7"/>
    <circle cx="60" cy="138" r="6" fill="${G("m", x)}"/><circle cx="150" cy="136" r="6" fill="${G("m", x)}"/>`,

  bolsa: x => `${SHD(x, 72)}
    <path d="M70 84 Q68 36 100 36 Q132 36 130 84" fill="none" stroke="${x.dk}" stroke-width="8" stroke-linecap="round"/>
    <rect x="36" y="76" width="128" height="100" rx="16" fill="${G("b", x)}"/>
    <path d="M36 100 Q100 124 164 100 L164 124 Q100 148 36 124 Z" fill="${x.sh}"/>
    <rect x="44" y="90" width="112" height="82" rx="10" fill="none" stroke="#fff" stroke-width="2" opacity=".12"/>
    <circle cx="100" cy="120" r="7" fill="${G("m", x)}" stroke="${x.dk}" stroke-width="1.5"/>`,

  mochila: x => `${SHD(x, 62)}
    <path d="M84 28 Q100 8 116 28" fill="none" stroke="${x.dk}" stroke-width="6" stroke-linecap="round"/>
    <rect x="50" y="24" width="100" height="150" rx="38" fill="${G("b", x)}"/>
    <rect x="64" y="100" width="72" height="54" rx="16" fill="${x.sh}"/>
    <path d="M64 112 Q100 104 136 112" fill="none" stroke="${x.dk}" stroke-width="3"/>
    <rect x="84" y="40" width="32" height="12" rx="3" fill="#fff" opacity=".85"/>
    <path d="M52 84 V150" stroke="${x.dk}" stroke-width="6" opacity=".3"/>`,

  oculos: x => `${SHD(x, 74, 160, 8)}
    <path d="M24 84 Q24 68 44 68 L84 68 Q98 68 98 86 L98 112 Q98 136 70 136 Q40 136 30 118 Q24 106 24 84 Z" fill="${G("b", x)}" stroke="#16191e" stroke-width="6"/>
    <path d="M176 84 Q176 68 156 68 L116 68 Q102 68 102 86 L102 112 Q102 136 130 136 Q160 136 170 118 Q176 106 176 84 Z" fill="${G("b", x)}" stroke="#16191e" stroke-width="6"/>
    <path d="M98 84 Q100 74 102 84" fill="none" stroke="#16191e" stroke-width="5"/>
    <path d="M24 84 L8 80 M176 84 L192 80" stroke="#16191e" stroke-width="6" stroke-linecap="round"/>
    <path d="M40 84 Q48 76 64 76" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".6"/>
    <path d="M116 84 Q124 76 140 76" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".6"/>`,

  relogio: x => `${SHD(x, 50, 184, 6)}
    <rect x="78" y="4" width="44" height="50" rx="6" fill="${G("b", x)}"/>
    <rect x="78" y="146" width="44" height="50" rx="6" fill="${G("b", x)}"/>
    <circle cx="100" cy="100" r="56" fill="${G("m", x)}" stroke="#6e7880" stroke-width="2"/>
    <circle cx="100" cy="100" r="48" fill="${mix(x.c, "#ffffff", .8)}"/>
    ${[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(i => `<line x1="100" y1="${i % 3 ? 58 : 56}" x2="100" y2="${i % 3 ? 64 : 66}" stroke="#16191e" stroke-width="${i % 3 ? 2 : 3.5}" transform="rotate(${i * 30} 100 100)"/>`).join("")}
    <line x1="100" y1="100" x2="100" y2="72" stroke="#16191e" stroke-width="4.5" stroke-linecap="round"/>
    <line x1="100" y1="100" x2="128" y2="88" stroke="#16191e" stroke-width="3" stroke-linecap="round"/>
    <line x1="100" y1="100" x2="84" y2="122" stroke="#ff3621" stroke-width="1.6" stroke-linecap="round"/>
    <circle cx="100" cy="100" r="4" fill="#16191e"/>
    <rect x="155" y="92" width="9" height="16" rx="2" fill="${G("m", x)}"/>`,

  smartwatch: x => `${SHD(x, 50, 184, 6)}
    <path d="M74 52 L86 22 L114 22 L126 52 Z" fill="${G("k", x)}"/>
    <path d="M74 148 L86 178 L114 178 L126 148 Z" fill="${G("k", x)}"/>
    <rect x="56" y="48" width="88" height="104" rx="26" fill="${G("m", x)}"/>
    <rect x="66" y="58" width="68" height="84" rx="18" fill="#0f1417"/>
    <circle cx="100" cy="100" r="22" fill="none" stroke="${x.c}" stroke-width="7"/>
    <circle cx="100" cy="100" r="8" fill="${x.hi}"/>
    <rect x="80" y="130" width="40" height="4" rx="2" fill="#fff" opacity=".3"/>`,

  bone: x => `${SHD(x, 62, 176, 7)}
    <path d="M36 118 Q34 42 100 40 Q166 42 164 118 Z" fill="${G("b", x)}"/>
    <path d="M26 116 Q100 146 174 116 Q172 132 100 140 Q28 132 26 116 Z" fill="${x.sh}"/>
    <path d="M100 40 V116" stroke="${x.dk}" stroke-width="2" opacity=".45"/>
    <path d="M70 46 Q66 80 70 116 M130 46 Q134 80 130 116" stroke="${x.dk}" stroke-width="2" fill="none" opacity=".3"/>
    <circle cx="100" cy="40" r="5" fill="${x.dk}"/>
    <rect x="84" y="78" width="32" height="18" rx="3" fill="#fff" opacity=".9"/>
    <path d="M92 87 H108" stroke="${x.c}" stroke-width="4" stroke-linecap="round"/>`,

  sofa: x => `${SHD(x, 92, 178, 8)}
    <rect x="32" y="158" width="10" height="16" rx="3" fill="${x.dk}"/><rect x="158" y="158" width="10" height="16" rx="3" fill="${x.dk}"/>
    <rect x="38" y="58" width="124" height="66" rx="22" fill="${G("b", x)}"/>
    <rect x="20" y="84" width="30" height="78" rx="14" fill="${x.sh}"/>
    <rect x="150" y="84" width="30" height="78" rx="14" fill="${x.sh}"/>
    <rect x="46" y="108" width="108" height="46" rx="8" fill="${x.hi}"/>
    <rect x="48" y="104" width="50" height="46" rx="12" fill="${G("b", x)}" opacity=".92"/>
    <rect x="102" y="104" width="50" height="46" rx="12" fill="${G("b", x)}" opacity=".92"/>
    <path d="M60 74 Q64 66 76 68" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".25"/>`,

  poltrona: x => `${SHD(x, 70, 178, 7)}
    <path d="M50 66 Q100 34 150 66 L158 128 L42 128 Z" fill="${G("b", x)}"/>
    <rect x="28" y="94" width="34" height="62" rx="17" fill="${x.sh}"/>
    <rect x="138" y="94" width="34" height="62" rx="17" fill="${x.sh}"/>
    <rect x="50" y="112" width="100" height="36" rx="14" fill="${x.hi}"/>
    <path d="M100 112 V146" stroke="${x.dk}" stroke-width="2" opacity=".2"/>
    <rect x="44" y="154" width="9" height="14" rx="4" fill="${x.dk}"/><rect x="147" y="154" width="9" height="14" rx="4" fill="${x.dk}"/>
    <path d="M62 80 Q72 60 96 54" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".25"/>`,

  mesa: x => `${SHD(x, 50, 170, 8)}
    <ellipse cx="100" cy="168" rx="40" ry="9" fill="${x.dk}"/>
    <path d="M90 112 H110 L114 166 H86 Z" fill="${G("v", x)}"/>
    <ellipse cx="100" cy="106" rx="70" ry="22" fill="${x.sh}"/>
    <ellipse cx="100" cy="100" rx="70" ry="22" fill="${G("b", x)}"/>
    <path d="M52 96 Q78 82 118 80" fill="none" stroke="#fff" stroke-width="4" opacity=".22" stroke-linecap="round"/>`,

  luminaria: x => `${SHD(x, 40, 178, 6)}
    <ellipse cx="100" cy="176" rx="34" ry="7" fill="${G("k", x)}"/>
    <rect x="97" y="108" width="6" height="68" fill="${G("m", x)}"/>
    <circle cx="100" cy="112" r="80" fill="#fff6d0" opacity=".08"/>
    <path d="M72 44 H128 L156 106 H44 Z" fill="${G("b", x)}"/>
    <ellipse cx="100" cy="44" rx="28" ry="5" fill="${x.dk}"/>
    <ellipse cx="100" cy="106" rx="56" ry="10" fill="#fff3b0"/>
    <ellipse cx="100" cy="106" rx="56" ry="10" fill="none" stroke="${x.dk}" stroke-width="2" opacity=".3"/>
    <path d="M60 70 Q66 60 78 56" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".3"/>`,

  tapete: x => `${SHD(x, 88, 162, 7)}
    <path d="M22 74 L178 56 L186 140 L14 156 Z" fill="${G("b", x)}"/>
    <path d="M34 84 L166 70 L172 130 L28 144 Z" fill="none" stroke="#fff" stroke-width="3" opacity=".55"/>
    <path d="M100 88 L132 102 L100 118 L68 102 Z" fill="${x.sh}"/>
    <path d="M100 96 L118 102 L100 110 L82 102 Z" fill="${x.hi}" opacity=".7"/>
    <path d="M22 74 L14 156" stroke="${x.dk}" stroke-width="3" opacity=".3"/>`,

  almofada: x => `${SHD(x, 66, 166, 7)}
    <path d="M44 64 Q100 42 156 64 Q166 104 152 142 Q100 162 48 142 Q34 104 44 64 Z" fill="${G("b", x)}"/>
    <path d="M56 74 Q100 58 144 74 Q154 104 142 130 Q100 146 58 130 Q46 104 56 74 Z" fill="none" stroke="#fff" stroke-width="2" stroke-dasharray="4 4" opacity=".4"/>
    <ellipse cx="82" cy="84" rx="22" ry="8" fill="#fff" opacity=".25" transform="rotate(-12 82 84)"/>`,

  tecido: x => `${SHD(x, 70, 176, 8)}
    <path d="M30 120 Q100 104 170 120 L170 150 Q100 166 30 150 Z" fill="${x.sh}"/>
    <path d="M34 92 Q100 76 166 92 L166 124 Q100 140 34 124 Z" fill="${x.hi}"/>
    <path d="M30 60 Q100 44 170 60 L170 96 Q100 112 30 96 Z" fill="${G("b", x)}"/>
    <path d="M70 52 Q74 78 70 104 M120 50 Q124 76 120 102" stroke="${x.dk}" stroke-width="2" fill="none" opacity=".35"/>`,

  cortina: x => `${SHD(x, 78, 176, 7)}
    <rect x="14" y="18" width="172" height="8" rx="4" fill="${G("m", x)}"/>
    <circle cx="34" cy="22" r="4" fill="${G("m", x)}"/><circle cx="166" cy="22" r="4" fill="${G("m", x)}"/>
    <path d="M24 28 H94 V166 Q82 180 70 166 Q58 154 46 166 Q36 178 24 166 Z" fill="${G("v", x)}"/>
    <path d="M106 28 H176 V166 Q164 180 152 166 Q140 154 130 166 Q118 178 106 166 Z" fill="${G("v", x)}"/>
    <path d="M48 40 Q44 100 50 160 M70 40 Q66 100 72 158 M130 40 Q126 100 132 158 M152 40 Q148 100 154 160" stroke="${x.dk}" stroke-width="2" fill="none" opacity=".28"/>`,

  vaso: x => `${SHD(x, 50, 176, 7)}
    <path d="M84 26 L116 26 L118 44 Q152 68 152 116 Q152 170 100 172 Q48 170 48 116 Q48 68 82 44 Z" fill="${G("b", x)}"/>
    <ellipse cx="100" cy="26" rx="17" ry="5" fill="${x.sh}"/>
    <ellipse cx="100" cy="26" rx="13" ry="3" fill="#2b1d17" opacity=".8"/>
    <path d="M66 84 Q64 120 72 150" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".3"/>`,

  quadro: x => `${SHD(x, 70, 172, 6)}
    <rect x="26" y="34" width="148" height="122" rx="4" fill="${G("b", x)}"/>
    <rect x="38" y="46" width="124" height="98" fill="${mix(x.c0 || x.hi, "#ffffff", .25)}"/>
    <rect x="38" y="46" width="124" height="98" fill="${x.hi}" opacity=".5"/>
    <circle cx="132" cy="72" r="14" fill="#fff" opacity=".85"/>
    <path d="M38 124 Q80 92 110 116 T162 110 L162 144 L38 144 Z" fill="${x.sh}"/>
    <path d="M38 134 Q70 116 100 130 T162 128 L162 144 L38 144 Z" fill="${x.dk}"/>`,

  prateleira: x => `${SHD(x, 74, 178, 3)}
    <rect x="34" y="60" width="28" height="50" rx="3" fill="${x.c}"/>
    <rect x="34" y="60" width="28" height="6" rx="2" fill="${x.hi}"/>
    <rect x="66" y="72" width="22" height="38" rx="3" fill="${x.sh}"/>
    <rect x="92" y="54" width="26" height="56" rx="3" fill="${x.hi}"/>
    <path d="M132 110 V92 Q132 84 142 80 Q152 84 152 92 V110 Z" fill="#fff" opacity=".95"/>
    <rect x="16" y="110" width="168" height="14" rx="3" fill="${G("b", x)}"/>
    <rect x="20" y="124" width="160" height="4" rx="2" fill="#000" opacity=".12"/>
    <path d="M28 126 L50 126 L28 150 Z M172 126 L150 126 L172 150 Z" fill="${x.dk}"/>`,

  planta: x => {
    const angs = [-72, -44, -18, 8, 34, 60, -90, 90];
    const folhas = angs.map((a, i) => { const len = i % 2 ? 30 : 38; return `<ellipse cx="100" cy="${116 - len}" rx="11" ry="${len}" transform="rotate(${a} 100 116)" fill="${i % 3 === 0 ? x.hi : G("b", x)}"/>`; }).join("");
    return `${SHD(x, 46, 178, 7)}${folhas}
      <path d="M62 122 H138 L130 172 Q100 180 70 172 Z" fill="#b8643d"/>
      <rect x="58" y="114" width="84" height="14" rx="5" fill="#d27a4e"/>
      <path d="M72 140 Q100 146 128 140" fill="none" stroke="#fff" stroke-width="2" opacity=".2"/>`;
  },

  panela: x => `${SHD(x, 70, 178, 7)}
    <rect x="152" y="108" width="38" height="13" rx="6" fill="${x.dk}"/>
    <path d="M40 90 L46 158 Q48 170 62 170 L138 170 Q152 170 154 158 L160 90 Z" fill="${G("b", x)}"/>
    <path d="M42 120 H158" stroke="#fff" stroke-width="2" opacity=".2"/>
    <ellipse cx="100" cy="90" rx="60" ry="10" fill="${G("m", x)}"/>
    <path d="M44 86 Q100 16 156 86 Z" fill="${G("b", x)}"/>
    <ellipse cx="100" cy="86" rx="58" ry="8" fill="${x.dk}"/>
    <ellipse cx="100" cy="30" rx="11" ry="6" fill="${x.dk}"/>
    <rect x="96" y="30" width="8" height="10" fill="${x.dk}"/>
    <path d="M60 110 Q64 136 70 150" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".18"/>`,

  cafeteira: x => `${SHD(x, 74, 180, 7)}
    <rect x="40" y="160" width="112" height="12" rx="6" fill="${x.dk}"/>
    <rect x="50" y="20" width="92" height="100" rx="14" fill="${G("b", x)}"/>
    <rect x="44" y="12" width="104" height="12" rx="6" fill="${x.dk}"/>
    <rect x="62" y="32" width="68" height="28" rx="6" fill="#0d1a1f" opacity=".85"/>
    <path d="M68 38 H106" stroke="#fff" stroke-width="3" opacity=".25" stroke-linecap="round"/>
    <rect x="62" y="118" width="60" height="10" rx="3" fill="${x.dk}"/>
    <rect x="88" y="108" width="8" height="12" fill="${x.dk}"/>
    <rect x="120" y="106" width="44" height="60" rx="10" fill="#dce9ee" opacity=".8" stroke="#9fb3ba" stroke-width="2"/>
    <rect x="124" y="136" width="36" height="28" rx="6" fill="#4a2b1c"/>
    <rect x="122" y="98" width="40" height="8" rx="3" fill="${x.dk}"/>
    <path d="M164 118 Q178 118 178 140 Q178 160 164 160" fill="none" stroke="#9fb3ba" stroke-width="5"/>
    <circle cx="128" cy="62" r="3.5" fill="#ff5f46"/>
    <rect x="76" y="82" width="10" height="5" rx="2" fill="#fff" opacity=".35"/><rect x="92" y="82" width="10" height="5" rx="2" fill="#fff" opacity=".35"/>`,

  pratos: x => {
    const prato = (y, fill, rim) => `<ellipse cx="100" cy="${y + 8}" rx="66" ry="22" fill="${x.dk}" opacity=".45"/>
      <ellipse cx="100" cy="${y}" rx="66" ry="22" fill="${fill}"/>
      <ellipse cx="100" cy="${y}" rx="40" ry="12" fill="none" stroke="${rim}" stroke-width="2.5" opacity=".7"/>`;
    return `${SHD(x, 72, 184, 6)}${prato(150, "#f7f6f3", "#c7c3bd")}${prato(128, "#eef0f1", "#b9c0c5")}${prato(106, G("b", x), x.dk)}`;
  },

  eletro: x => `${SHD(x, 56, 180, 7)}
    <rect x="52" y="152" width="96" height="26" rx="10" fill="${G("k", x)}"/>
    <circle cx="74" cy="165" r="4.5" fill="${x.c}"/><circle cx="90" cy="165" r="4.5" fill="#e9ecee" opacity=".7"/>
    <path d="M60 58 H140 L148 146 H52 Z" fill="#dfeef3" opacity=".5" stroke="#9fb3ba" stroke-width="2"/>
    <path d="M64 100 H136 L144 144 H56 Z" fill="${x.c}" opacity=".85"/>
    <rect x="56" y="36" width="88" height="22" rx="7" fill="${G("k", x)}"/>
    <path d="M74 130 H126 M80 124 L120 124" stroke="${G("m", x)}" stroke-width="4" stroke-linecap="round"/>
    <path d="M70 66 Q68 80 72 96" fill="none" stroke="#fff" stroke-width="4" opacity=".5" stroke-linecap="round"/>`,

  airfryer: x => `${SHD(x, 72, 180, 7)}
    <rect x="36" y="34" width="128" height="130" rx="24" fill="${G("b", x)}"/>
    <rect x="58" y="54" width="84" height="56" rx="12" fill="#1a2226"/>
    <rect x="66" y="66" width="68" height="34" rx="8" fill="#c98b52"/>
    <path d="M72 72 H128" stroke="#f0c38f" stroke-width="3" opacity=".6" stroke-linecap="round"/>
    <rect x="70" y="122" width="60" height="12" rx="4" fill="${x.dk}"/>
    <circle cx="80" cy="128" r="2" fill="#ff5f46"/><circle cx="90" cy="128" r="2" fill="#fff" opacity=".7"/>
    <circle cx="146" cy="146" r="10" fill="${G("m", x)}"/>
    <path d="M52 150 H84 M52 158 H84" stroke="${x.dk}" stroke-width="2" opacity=".4"/>`,

  caneca: x => `${SHD(x, 62, 178, 7)}
    <path d="M140 72 Q178 72 178 106 Q178 140 140 140" fill="none" stroke="${x.c}" stroke-width="14"/>
    <path d="M140 72 Q178 72 178 106 Q178 140 140 140" fill="none" stroke="${x.dk}" stroke-width="2" opacity=".3" transform="translate(4 0)"/>
    <rect x="38" y="46" width="104" height="120" rx="12" fill="${G("v", x)}"/>
    <rect x="38" y="128" width="104" height="8" fill="#fff" opacity=".35"/>
    <ellipse cx="90" cy="46" rx="52" ry="12" fill="#f4f1ec"/>
    <ellipse cx="90" cy="47" rx="44" ry="8" fill="#3b2a22"/>
    <path d="M56 80 Q56 118 62 150" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".25"/>`,

  tv: x => `${SHD(x, 88, 178, 7)}
    <rect x="10" y="26" width="180" height="122" rx="8" fill="${G("k", x)}"/>
    <rect x="20" y="36" width="160" height="102" rx="4" fill="${G("b", x)}"/>
    <rect x="20" y="36" width="160" height="102" rx="4" fill="#0b1417" opacity=".35"/>
    <path d="M30 40 L86 40 L40 134 L22 134 Z" fill="#fff" opacity=".1"/>
    <path d="M120 40 L150 40 L110 134 L96 134 Z" fill="#fff" opacity=".06"/>
    <rect x="88" y="148" width="24" height="16" fill="${G("k", x)}"/>
    <rect x="58" y="160" width="84" height="8" rx="4" fill="${G("k", x)}"/>`,

  fone: x => `${SHD(x, 72, 182, 6)}
    <path d="M36 118 Q34 30 100 30 Q166 30 164 118" fill="none" stroke="${x.c}" stroke-width="12"/>
    <path d="M40 112 Q40 40 100 36" fill="none" stroke="#fff" stroke-width="3" opacity=".2"/>
    <rect x="20" y="98" width="38" height="62" rx="16" fill="${G("b", x)}"/>
    <rect x="144" y="98" width="38" height="62" rx="16" fill="${G("b", x)}"/>
    <rect x="28" y="110" width="22" height="40" rx="10" fill="${G("k", x)}"/>
    <rect x="150" y="110" width="22" height="40" rx="10" fill="${G("k", x)}"/>`,

  headset: x => `${SHD(x, 72, 182, 6)}
    <path d="M36 112 Q34 26 100 26 Q166 26 164 112" fill="none" stroke="${x.c}" stroke-width="12"/>
    <rect x="20" y="96" width="38" height="62" rx="16" fill="${G("b", x)}"/>
    <rect x="144" y="96" width="38" height="62" rx="16" fill="${G("b", x)}"/>
    <rect x="28" y="108" width="22" height="40" rx="10" fill="${G("k", x)}"/>
    <rect x="150" y="108" width="22" height="40" rx="10" fill="${G("k", x)}"/>
    <path d="M26 150 Q26 178 66 176" fill="none" stroke="#16191e" stroke-width="4" stroke-linecap="round"/>
    <rect x="62" y="170" width="16" height="11" rx="5" fill="#16191e"/>`,

  caixasom: x => `${SHD(x, 66, 180, 7)}
    <rect x="44" y="18" width="112" height="164" rx="18" fill="${G("b", x)}"/>
    <circle cx="100" cy="56" r="14" fill="${G("k", x)}"/>
    <circle cx="100" cy="56" r="6" fill="${G("m", x)}"/>
    <circle cx="100" cy="126" r="46" fill="${G("k", x)}"/>
    <circle cx="100" cy="126" r="40" fill="none" stroke="#6b737a" stroke-width="2"/>
    <circle cx="100" cy="126" r="30" fill="#1d2328"/>
    <circle cx="100" cy="126" r="12" fill="${G("m", x)}"/>
    <path d="M60 36 Q70 30 80 34" fill="none" stroke="#fff" stroke-width="4" opacity=".25" stroke-linecap="round"/>`,

  celular: x => `${SHD(x, 50, 186, 5)}
    <rect x="56" y="14" width="88" height="172" rx="22" fill="${G("b", x)}"/>
    <rect x="64" y="26" width="72" height="148" rx="10" fill="#0e1418"/>
    <rect x="90" y="30" width="20" height="6" rx="3" fill="#000"/>
    ${[0, 1, 2].map(r => [0, 1, 2].map(c => `<rect x="${76 + c * 19}" y="${52 + r * 22}" width="13" height="13" rx="3.5" fill="${[x.c, x.hi, x.sh, "#ffffff", x.hi, x.c, x.sh, x.c, "#ffffff"][r * 3 + c]}" opacity=".9"/>`).join("")).join("")}
    <path d="M70 40 L92 150" stroke="#fff" stroke-width="10" opacity=".05"/>`,

  notebook: x => `${SHD(x, 98, 170, 7)}
    <rect x="40" y="24" width="120" height="100" rx="8" fill="${G("b", x)}"/>
    <rect x="48" y="32" width="104" height="84" rx="3" fill="${G("k", x)}"/>
    <circle cx="100" cy="74" r="9" fill="${x.hi}" opacity=".7"/>
    <path d="M56 42 L92 42" stroke="#fff" stroke-width="3" opacity=".12"/>
    <path d="M18 124 H182 L190 146 Q191 154 182 154 H18 Q9 154 10 146 Z" fill="${G("m", x)}"/>
    <rect x="50" y="130" width="100" height="12" rx="3" fill="${x.dk}" opacity=".3"/>
    <rect x="92" y="126" width="16" height="4" rx="2" fill="${x.dk}"/>`,

  teclado: x => {
    let teclas = "";
    for (let r = 0; r < 4; r++) for (let c = 0; c < 12; c++) {
      const destaque = (r + c) % 5 === 0;
      teclas += `<rect x="${24 + c * 13.4}" y="${80 + r * 17}" width="11" height="12" rx="2.5" fill="${destaque ? x.c : "#e9ecee"}" opacity="${destaque ? 1 : .8}"/>`;
    }
    return `${SHD(x, 92, 168, 6)}
      <path d="M14 74 Q14 66 22 66 H178 Q186 66 186 74 V150 Q186 158 178 158 H22 Q14 158 14 150 Z" fill="${G("k", x)}"/>
      ${teclas}
      <rect x="20" y="152" width="160" height="3" rx="1.5" fill="${x.c}"/>`;
  },

  mouse: x => `${SHD(x, 44, 182, 5)}
    <path d="M100 20 Q150 20 152 98 L152 136 Q152 180 100 180 Q48 180 48 136 L48 98 Q50 20 100 20 Z" fill="${G("b", x)}"/>
    <path d="M100 22 V96" stroke="${x.dk}" stroke-width="2"/>
    <path d="M48 98 Q100 110 152 98" fill="none" stroke="${x.dk}" stroke-width="2"/>
    <rect x="94" y="50" width="12" height="24" rx="6" fill="${G("k", x)}"/>
    <path d="M56 152 Q100 172 144 152" fill="none" stroke="${x.hi}" stroke-width="3" opacity=".9"/>
    <path d="M70 40 Q60 60 58 90" fill="none" stroke="#fff" stroke-width="6" opacity=".18" stroke-linecap="round"/>`,

  console: x => `${SHD(x, 88, 178, 7)}
    <rect x="18" y="62" width="164" height="96" rx="26" fill="${G("b", x)}"/>
    <rect x="28" y="70" width="144" height="22" rx="11" fill="#fff" opacity=".16"/>
    <rect x="44" y="104" width="112" height="6" rx="3" fill="${G("k", x)}"/>
    <rect x="152" y="120" width="18" height="6" rx="3" fill="#4bc8e8"/>
    <circle cx="40" cy="134" r="6" fill="${G("k", x)}"/>
    <path d="M58 138 H142" stroke="${x.dk}" stroke-width="3" stroke-dasharray="2 6" opacity=".5"/>`,

  led: x => `${SHD(x, 70, 180, 6)}
    <path d="M52 152 Q96 56 124 96 T186 70" fill="none" stroke="${x.c}" stroke-width="13" stroke-linecap="round"/>
    <path d="M52 152 Q96 56 124 96 T186 70" fill="none" stroke="${x.hi}" stroke-width="3" opacity=".6"/>
    <path d="M52 152 Q96 56 124 96 T186 70" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-dasharray="0.1 13" opacity=".95"/>
    <circle cx="34" cy="150" r="24" fill="${G("k", x)}"/>
    <circle cx="34" cy="150" r="13" fill="${x.c}"/>
    <circle cx="34" cy="150" r="5" fill="#15181d"/>`,

  cadeira: x => `${SHD(x, 66, 180, 7)}
    <rect x="94" y="142" width="12" height="26" rx="4" fill="${G("k", x)}"/>
    <ellipse cx="100" cy="174" rx="50" ry="8" fill="${G("k", x)}"/>
    <circle cx="54" cy="180" r="4" fill="#0b0d10"/><circle cx="146" cy="180" r="4" fill="#0b0d10"/>
    <path d="M60 26 Q100 12 140 26 L150 120 L50 120 Z" fill="${G("b", x)}"/>
    <rect x="76" y="14" width="48" height="20" rx="9" fill="${G("k", x)}"/>
    <rect x="40" y="112" width="120" height="36" rx="16" fill="${G("b", x)}"/>
    <rect x="28" y="96" width="18" height="48" rx="8" fill="${G("k", x)}"/>
    <rect x="154" y="96" width="18" height="48" rx="8" fill="${G("k", x)}"/>
    <path d="M100 32 V112" stroke="${x.hi}" stroke-width="3" opacity=".5"/>`,

  garrafa: x => `${SHD(x, 50, 182, 6)}
    <rect x="80" y="8" width="40" height="12" rx="4" fill="${G("m", x)}"/>
    <rect x="72" y="16" width="56" height="26" rx="6" fill="${G("k", x)}"/>
    <rect x="64" y="38" width="72" height="138" rx="26" fill="${G("b", x)}"/>
    <rect x="64" y="100" width="72" height="12" fill="#fff" opacity=".85"/>
    <rect x="72" y="168" width="56" height="10" rx="3" fill="${G("k", x)}"/>
    <rect x="78" y="58" width="8" height="96" rx="4" fill="#fff" opacity=".3"/>`,

  bike: x => `${SHD(x, 88, 178, 6)}
    <circle cx="50" cy="134" r="30" fill="none" stroke="#16191e" stroke-width="8"/>
    <circle cx="150" cy="134" r="30" fill="none" stroke="#16191e" stroke-width="8"/>
    <circle cx="50" cy="134" r="22" fill="none" stroke="#fff" stroke-width="1.5" opacity=".4"/>
    <circle cx="150" cy="134" r="22" fill="none" stroke="#fff" stroke-width="1.5" opacity=".4"/>
    <path d="M50 134 L100 134 L84 74 L50 134 M100 134 L136 74 L84 74 M136 74 L150 134 M136 74 L146 56 L156 56" fill="none" stroke="${x.c}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M70 68 L92 68" stroke="#16191e" stroke-width="6" stroke-linecap="round"/>
    <circle cx="100" cy="134" r="6" fill="#16191e"/>`,

  barraca: x => `${SHD(x, 92, 170, 7)}
    <rect x="14" y="162" width="172" height="6" rx="3" fill="${x.sh}"/>
    <path d="M22 164 L100 34 L178 164 Z" fill="${G("b", x)}"/>
    <path d="M100 34 L178 164 L120 164 Z" fill="${x.dk}" opacity=".35"/>
    <path d="M100 74 L72 164 L128 164 Z" fill="#1a1f24"/>
    <path d="M22 164 L100 34" stroke="#fff" stroke-width="3" opacity=".25"/>
    <path d="M100 34 V20" stroke="#16191e" stroke-width="3"/>`,

  halter: x => `${SHD(x, 82, 178, 6)}
    <rect x="50" y="94" width="100" height="12" rx="6" fill="${G("m", x)}"/>
    <rect x="50" y="70" width="20" height="60" rx="5" fill="${G("k", x)}"/>
    <rect x="130" y="70" width="20" height="60" rx="5" fill="${G("k", x)}"/>
    <rect x="24" y="52" width="28" height="96" rx="8" fill="${G("b", x)}"/>
    <rect x="148" y="52" width="28" height="96" rx="8" fill="${G("b", x)}"/>
    <rect x="28" y="60" width="5" height="82" rx="2" fill="#fff" opacity=".35"/>
    <rect x="167" y="60" width="5" height="82" rx="2" fill="#fff" opacity=".35"/>`,

  frasco: x => `${SHD(x, 56, 180, 7)}
    <rect x="86" y="62" width="28" height="18" fill="${G("m", x)}"/>
    <rect x="52" y="78" width="96" height="100" rx="16" fill="${G("b", x)}" opacity=".92"/>
    <rect x="58" y="100" width="84" height="74" rx="12" fill="${x.sh}" opacity=".35"/>
    <rect x="76" y="24" width="48" height="44" rx="8" fill="${G("k", x)}"/>
    <rect x="76" y="24" width="48" height="8" rx="4" fill="#fff" opacity=".12"/>
    <rect x="70" y="116" width="60" height="34" rx="3" fill="#fff" opacity=".95"/>
    <rect x="78" y="126" width="40" height="4" rx="2" fill="${x.dk}" opacity=".5"/>
    <rect x="78" y="136" width="28" height="4" rx="2" fill="${x.dk}" opacity=".35"/>
    <path d="M64 92 Q62 110 64 150" fill="none" stroke="#fff" stroke-width="6" opacity=".3" stroke-linecap="round"/>`,

  pote: x => `${SHD(x, 74, 176, 6)}
    <rect x="30" y="80" width="140" height="34" rx="12" fill="${G("b", x)}"/>
    <rect x="34" y="112" width="132" height="56" rx="16" fill="${G("w", x)}"/>
    <rect x="34" y="122" width="132" height="10" fill="${x.c}" opacity=".9"/>
    <rect x="58" y="140" width="84" height="16" rx="3" fill="${x.dk}" opacity=".25"/>
    <path d="M44 124 Q42 146 46 160" fill="none" stroke="#fff" stroke-width="6" opacity=".7" stroke-linecap="round"/>`,

  paleta: x => {
    const cores = [x.c, x.hi, x.sh, mix(x.c, "#ffb3a0", .5), mix(x.c, "#000000", .5), "#e8d3b0"];
    const pos = [[66, 92], [100, 92], [134, 92], [66, 126], [100, 126], [134, 126]];
    return `${SHD(x, 86, 176, 7)}
      <rect x="22" y="40" width="156" height="120" rx="18" fill="${G("b", x)}"/>
      <rect x="30" y="48" width="140" height="104" rx="12" fill="#1d2429"/>
      ${pos.map(([cx, cy], i) => `<circle cx="${cx}" cy="${cy}" r="17" fill="${cores[i]}"/><circle cx="${cx - 5}" cy="${cy - 5}" r="5" fill="#fff" opacity=".35"/>`).join("")}
      <path d="M140 172 L184 128" stroke="#16191e" stroke-width="6" stroke-linecap="round"/>
      <ellipse cx="186" cy="124" rx="7" ry="12" transform="rotate(45 186 124)" fill="${x.sh}"/>`;
  },

  secador: x => `${SHD(x, 56, 182, 6)}
    <g transform="rotate(-8 100 100)">
      <rect x="30" y="44" width="112" height="60" rx="28" fill="${G("b", x)}"/>
      <rect x="14" y="56" width="36" height="36" rx="10" fill="${G("k", x)}"/>
      <rect x="18" y="62" width="8" height="24" rx="3" fill="#fff" opacity=".2"/>
      <path d="M66 58 V92 M84 58 V92 M102 58 V92" stroke="${x.dk}" stroke-width="2" opacity=".3"/>
      <rect x="98" y="96" width="36" height="84" rx="16" fill="${G("k", x)}"/>
      <path d="M104 118 H128 M104 130 H128 M104 142 H128" stroke="#fff" stroke-width="2" opacity=".18"/>
    </g>`,

  caixa: x => `${SHD(x, 70, 176, 7)}
    <rect x="36" y="60" width="128" height="110" rx="6" fill="${G("b", x)}"/>
    <path d="M36 60 L164 60 L150 40 L50 40 Z" fill="${x.sh}"/>
    <rect x="92" y="40" width="16" height="130" fill="#fff" opacity=".45"/>`,
};

/* variações de desenho pelo nome (ex.: Smartwatch ≠ relógio clássico) */
function chaveDesenho(p) {
  const n = String(p.nome || "").toLowerCase(), i = p.icone;
  if (i === "relogio" && /smart/.test(n)) return "smartwatch";
  if (i === "eletro" && /fryer/.test(n)) return "airfryer";
  if (i === "fone" && /headset/.test(n)) return "headset";
  if (i === "frasco" && /hidrat|creme/.test(n)) return "pote";
  if (i === "tecido" && /cortina/.test(n)) return "cortina";
  return i;
}

/* arte completa (SVG 200×200): fundo de estúdio nas cores do estilo + produto com sombra de contato */
function arteProduto(p) {
  const chave = String(p.produto_id ?? p.chave ?? p.nome ?? "x");
  const u = "a" + hashStr(chave).toString(36);
  const [c0, c1, c2] = coresEstilo(p.estilo_id);
  const c = hexOK(p.cor_hex);
  const x = { u, c, hi: mix(c, "#ffffff", .38), sh: mix(c, "#000000", .2), dk: mix(c, "#000000", .42), c0, c1, c2 };
  const desenho = DESENHOS[chaveDesenho(p)] || DESENHOS.caixa;
  return `<svg class="arte-svg" viewBox="0 0 200 200" aria-hidden="true" focusable="false">${defsArte(x)}
    <rect width="200" height="200" fill="url(#bg${u})"/>
    <rect y="162" width="200" height="38" fill="${mix(c2, "#000000", .1)}" opacity=".12"/>
    ${desenho(x)}</svg>`;
}

/* foto (se houver imagem) sobreposta à arte; some sozinha se o arquivo não existir */
function fotoHTML(p, src, classe = "ft") {
  const url = src || (p.imagem_path ? `/api/imagem/${encodeURIComponent(p.produto_id)}` : (p.foto_url || ""));
  return `${arteProduto(p)}${url ? `<img class="${classe}" src="${escHTML(url)}" alt="" loading="lazy" onerror="this.remove()">` : ""}`;
}

/* card de produto (1:1 + preço + parcelamento + estrelas) */
function produtoHTML(p, opts = {}) {
  const id = escHTML(p.produto_id ?? "");
  const selos = [];
  const d = descontoPct(p);
  if (d) selos.push(`<span class="selo-p oferta">-${d}%</span>`);
  if (p.lancamento || opts.novo) selos.push(`<span class="selo-p novo">Novo</span>`);
  if (p.origem === "estudio") selos.push(`<span class="selo-p estudio">Estúdio</span>`);
  if (opts.selo) selos.push(`<span class="selo-p ${opts.seloCor || ""}">${escHTML(opts.selo)}</span>`);
  const assoc = (!opts.semAssoc && p.confianca != null && p.lift != null)
    ? `<span class="assoc-badge"><b>${pctTxt(p.confianca)}</b> também compraram<small>lift ${Number(p.lift).toFixed(1)}×</small></span>` : "";
  const add = opts.semAdd ? "" : `<button class="add-rapido" data-add="${id}" aria-label="Adicionar ${escHTML(p.nome)} à sacola" title="Adicionar à sacola">+</button>`;
  return `<article class="prod ${opts.classe || ""}" data-pid="${id}" tabindex="0" aria-label="${escHTML(p.nome)}">
    <div class="prod-foto">${fotoHTML(p, opts.imgSrc)}
      ${opts.rank ? `<span class="rank">${opts.rank}</span>` : ""}
      ${selos.length ? `<div class="selos">${selos.join("")}</div>` : ""}
      ${assoc}${add}</div>
    <div class="prod-info">
      <span class="prod-marca">${escHTML(p.marca_produto || p.departamento || "")}</span>
      <h3 class="prod-nome">${escHTML(p.nome)}</h3>
      ${p.avaliacao != null ? `<div class="prod-aval">${estrelasHTML(p.avaliacao, p.n_avaliacoes)}</div>` : ""}
      ${precoHTML(p)}${parcelaHTML(p)}
      ${p.frete_gratis === true ? `<span class="frete-gratis">Frete grátis</span>` : ""}
      ${p.motivo ? `<span class="motivo-ml" title="Sugestão do modelo de ML">✦ ${escHTML(p.motivo)}</span>` : ""}
    </div></article>`;
}

/* linha compacta (chat, sacola, sugestões de pedido) */
function miniProdutoHTML(p, opts = {}) {
  return `<div class="mini-prod" data-pid="${escHTML(p.produto_id)}">
    <div class="mini-foto">${fotoHTML(p, opts.imgSrc, "ft")}</div>
    <div class="mini-txt"><b>${escHTML(p.nome)}</b><span>${escHTML(p.departamento || "")}${temPromo(p) ? ` · <i>${reais(precoVigente(p))}</i>` : ` · ${reais(p.preco)}`}</span></div>
    <button class="btn btn-sm btn-escuro" data-add="${escHTML(p.produto_id)}">+ Sacola</button></div>`;
}
