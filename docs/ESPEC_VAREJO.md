# Especificação — BrickStore (varejo) · contrato entre dados, backend e frontend

> Documento de trabalho: todos os módulos seguem ESTE contrato. Idioma: **português do Brasil** em tudo
> (código comentado, textos de UI, markdown dos notebooks). Tudo roda na **Databricks**
> (serverless, 1 warehouse 2X-Small, 1 endpoint de Vector Search, até 3 Apps, sem internet de saída).

## Marca (parametrizável)
- Nome padrão: **BrickStore** — loja de departamentos fictícia. NUNCA escrever o nome fixo no código do App:
  - backend lê `NB_MARCA` (env) → exposto em `GET /api/config` → `{"marca": "BrickStore", "slogan": "..."}`
  - notebooks usam a variável `MARCA` do `_config` (widget `marca`)
  - scripts em `ferramentas/` usam a constante `MARCA = os.environ.get("NB_MARCA", "BrickStore")`
- Domínio de e-mail fictício: derivado da marca → `brickstore.com.br` (minúsculas, sem espaços).
- Visual: identidade Databricks (navy `#0B2026`/`#1B3139`, Lava `#FF3621`/`#FF5F46`, Oat `#F9F7F4`, DM Sans / DM Mono).
- Catálogo UC padrão: `brickstore`, schema `varejo`. App: `brickstore`. Genie: `"<MARCA> · Genie de Dados"`.

## Estilos (substituem os "mundos visuais") — tabela `estilos`
`estilo_id, nome, descricao, paleta, materiais, ocasiao, cores (3 hex separados por vírgula), ordem`

| estilo_id | nome | paleta / materiais / vibe |
|---|---|---|
| escandinavo | Minimalista escandinavo | branco, cinza claro, madeira clara · linho, carvalho · aconchegante e funcional |
| industrial | Industrial urbano | preto, grafite, cobre · metal, couro, concreto · urbano e robusto |
| boho | Boho terroso | terracota, bege, mostarda · palha, macramê, algodão cru · leve e artesanal |
| classico | Clássico elegante | azul-marinho, dourado, off-white · veludo, mármore, seda · sofisticado |
| streetwear | Streetwear urbano | preto, branco, verde-neon · moletom, nylon · jovem e despojado |
| esportivo | Esportivo performance | azul-elétrico, preto, verde-lima · tecido tech, mesh · ativo |
| verao | Verão tropical | turquesa, coral, branco · linho, palha · solar e leve |
| inverno | Inverno aconchegante | vinho, marrom, creme · lã, tricô, flanela · quentinho |
| gamer | Tech gamer neon | preto, roxo, ciano (RGB) · plástico, alumínio · futurista |
| rustico | Rústico campo | verde-musgo, madeira escura, xadrez · madeira de demolição, juta · outdoor |
| retro | Retrô anos 70/80 | mostarda, laranja, verde-água · veludo cotelê, vinil · nostálgico |
| festa | Festa e noite | preto, prata, champanhe · cetim, paetê · glamour |
| natural | Natural & bem-estar | verde-sálvia, branco, bambu · bambu, cerâmica, algodão orgânico · calmo |

## Departamentos → tipos de produto (campo `tipo`; `icone` = chave do desenho SVG no frontend)
- **Moda**: Camiseta(top), Camisa(top), Moletom(top), Jaqueta(jaqueta), Vestido(vestido), Calça jeans(calca), Bermuda(calca),
  Tênis casual(tenis), Bota(bota), Sandália(sandalia), Bolsa(bolsa), Mochila(mochila), Óculos de sol(oculos), Relógio(relogio), Boné(bone)
- **Casa & Decoração**: Sofá(sofa), Poltrona(poltrona), Mesa de centro(mesa), Luminária(luminaria), Tapete(tapete), Almofada(almofada),
  Cortina(tecido), Jogo de cama(tecido), Manta(tecido), Vaso decorativo(vaso), Quadro(quadro), Prateleira(prateleira), Planta artificial(planta)
- **Cozinha**: Jogo de panelas(panela), Cafeteira(cafeteira), Jogo de pratos(pratos), Liquidificador(eletro), Air fryer(eletro), Caneca(caneca)
- **Eletrônicos**: Smart TV(tv), Monitor(tv), Fone de ouvido(fone), Headset gamer(fone), Caixa de som(caixasom), Smartphone(celular),
  Notebook(notebook), Teclado mecânico(teclado), Mouse gamer(mouse), Console(console), Smartwatch(relogio), Fita LED(led), Cadeira gamer(cadeira)
- **Esporte & Lazer**: Tênis de corrida(tenis), Legging(calca), Garrafa térmica(garrafa), Bicicleta(bike), Tapete de yoga(tapete),
  Barraca(barraca), Mochila de trilha(mochila), Halteres(halter)
- **Beleza**: Perfume(frasco), Hidratante(frasco), Kit skincare(frasco), Paleta de maquiagem(paleta), Secador de cabelo(secador)

Ícones SVG necessários no frontend (chaves): top, jaqueta, vestido, calca, tenis, bota, sandalia, bolsa, mochila, oculos, relogio, bone,
sofa, poltrona, mesa, luminaria, tapete, almofada, tecido, vaso, quadro, prateleira, planta, panela, cafeteira, pratos, eletro, caneca,
tv, fone, caixasom, celular, notebook, teclado, mouse, console, led, cadeira, garrafa, bike, barraca, halter, frasco, paleta, secador.

## Tabelas Delta em `<catalog>.<schema>`
- `estilos` (acima)
- `produtos` (PK `produto_id`, CDF ligado): `produto_id` ("SKU" + 6 dígitos), `nome`, `marca_produto` (marcas próprias fictícias,
  ex.: Nórdica Home, Urbano Co., Terra & Fio, Voltz, Pulse Sports, Maré Brasil, Lã & Lenha, Neon Lab, Raiz Rústica, Vintage 80,
  Noite de Gala, Sálvia), `departamento`, `categoria` (= departamento › subgrupo, livre), `tipo`, `icone`, `estilo_id`, `cor` (nome),
  `cor_hex`, `material`, `descricao` (2–3 frases), `descricao_visual` ("Estilo: … Cores: … Material: … Ocasião/ambiente: …"),
  `especificacoes` (texto "chave: valor; …"), `tamanhos` (ex. "P, M, G, GG" | "38–44" | null), `preco` (double), `preco_promocional`
  (double|null), `parcelas_sem_juros` (int), `avaliacao` (1–5, 1 casa), `n_avaliacoes`, `estoque` (int), `lancamento` (bool),
  `popularidade` (double latente), `vendedor` (marketplace: "Loja Oficial <marca>" ou lojista parceiro), `vendedor_reputacao` (0–5), `frete_gratis` (bool, preço ≥ R$ 99), `imagem_path` (null; Volume quando houver foto), `origem` ('seed'|'estudio'), `data_cadastro` (date),
  `texto_busca` (nome + tipo + departamento + descricao + descricao_visual — fonte do Vector Search). ~3.000 produtos.
- `clientes` (PK `cliente_id` "C" + 6 dígitos): nome, email (@<dominio fictício>), uf, cidade, faixa_etaria, genero, segmento
  (Bronze/Prata/Ouro/Diamante — programa de fidelidade), data_cadastro, canal_preferido. 20.000 clientes. Gostos LATENTES
  (1–2 estilos favoritos + departamentos preferidos) NÃO gravados.
- `pedidos` (PK `pedido_id`): cliente_id, data_pedido (timestamp), canal (Site, App, Loja física, Marketplace), loja (cidade quando
  física), forma_pagamento (Cartão, PIX, Boleto), parcelas, status (Entregue, Em transporte, Cancelado, Devolvido), valor_total, frete.
- `itens_pedido`: pedido_id, produto_id, quantidade, preco_unitario, desconto. **Cestas com associações fortes**: complementos
  (sofá→almofada/tapete/mesa de centro/luminária/manta; notebook→mouse/mochila/teclado; console→headset/cadeira gamer/fita LED;
  tênis de corrida→garrafa/legging; vestido→sandália/bolsa; jogo de cama→manta/almofada; cafeteira→caneca; etc.) + mesmo estilo.
  ~83 mil pedidos, ~190 mil itens (arquivos prontos em `dados/`).
- `eventos_navegacao`: evento_id, cliente_id, produto_id, data_hora, evento (visualizou, adicionou_carrinho, favoritou), dispositivo. ~250 mil.
- `perfis_demo` (6–7 clientes reais da base com gostos distintos): cliente_id, apelido ("Ana · Escandinavo"), nome, cor (hex),
  estilo_favorito, n_pedidos.
- `quem_comprou_tambem_comprou` (SQL em `app/backend/recomendacao_sql.py`, **cesta = pedido**): item_a, nome_a, item_b, nome_b,
  tipo_b, estilo_b, n_juntos, pedidos_a, pedidos_b, suporte, confianca, lift, rank (top 20 por item_a, lift > 1), mesmo_estilo (bool).
- `vw_vendas_produto`, `vw_cestas_mais_fortes` (views de apoio ao Genie).
- `documentos_parseados`, `central_ajuda_chunks` (PK chunk_id, CDF) — PDFs de ajuda via `ai_parse_document` (mesmo fluxo atual).
- `fichas_parseadas`: chave, arquivo, path, parsed VARIANT, produto_id, processado_em — fichas de fornecedor processadas pelo Estúdio.

## Volumes
- `documentos` (PDFs da central de ajuda), `midia` (subpastas: `imagens_busca/` fotos da busca visual, `fichas/<chave>/` PDFs + páginas +
  figuras recortadas, `produtos/<produto_id>.jpg` fotos publicadas, `fichas_exemplo/` fichas de exemplo).

## Índices de Vector Search
- `produtos_index` sobre `produtos.texto_busca` (PK produto_id); `ajuda_index` sobre `central_ajuda_chunks.conteudo`.

## API do App (JSON) — o frontend consome exatamente isto
- `GET /api/config` → `{marca, slogan, dominio}`
- `GET /api/saude` → `{pronto, erro, produtos}`
- `GET /api/perfis` → `{perfis:[{cliente_id, apelido, nome, cor, estilo_favorito, n_pedidos}], estilos:[{estilo_id,nome,descricao,paleta,materiais,ocasiao,cores,ordem}], departamentos:[{nome, n_produtos}]}`
- `GET /api/vitrine?cliente_id=` → `{perfil, destaques:[produto...] (3–5 para o banner rotativo), fileiras:[{id, titulo, subtitulo?, estilo?: 'associacao'|'ranking'|'oferta'|'destaque', base?: produto_id, itens:[produto...]}]}`
  - fileiras típicas: "Porque você comprou «X»" (associacao), "Mais vendidos" (ranking), "Ofertas do dia" (oferta), "Novidades do Estúdio" (destaque), "Seu estilo: <estilo>", uma por departamento.
- **produto (resumo)**: `{produto_id, nome, marca_produto, vendedor, vendedor_reputacao, frete_gratis, departamento, tipo, icone, estilo_id, cor, cor_hex, preco, preco_promocional, parcelas_sem_juros, avaliacao, n_avaliacoes, imagem_path, origem, lancamento}` (+ `confianca`, `lift`, `n_juntos` em associações)
- `GET /api/produto/{id}` → produto completo + `estilo` (obj) + `tambem_compraram:[produto+confianca+lift]` + `compre_junto:{itens:[produto...], total, total_com_desconto, desconto_pct}` + `mesmo_estilo:[produto...]`
- `GET /api/busca?q=&departamento=&preco_max=` → `{consulta, produtos:[produto+score]}`
- `GET /api/departamento/{nome}` → `{departamento, produtos:[...]}` ; `GET /api/estilo/{estilo_id}` → `{estilo, produtos:[...]}`
- `POST /api/pedido` `{cliente_id, itens:[{produto_id, quantidade}]}` → `{pedido_id, valor_total, sugestoes:[produto...]}` (INSERT em pedidos/itens_pedido)
- `GET /api/meus-pedidos?cliente_id=` → `{pedidos:[{pedido_id, data_pedido, status, valor_total, itens:[produto+quantidade]}]}`
- `GET /api/imagem/{produto_id}` → JPEG do Volume (quando `imagem_path`); `GET /api/midia?caminho=/Volumes/...` → JPEG
- `POST /api/detetive` (multipart `imagem`, `quantidade`) → busca visual: `{caminho, laudo, produtos:[produto+compatibilidade+pistas[]]}`
  - laudo: `{tipo, descricao, cor, cores_hex[], material, estilo_provavel, estilo_nome, atributos[], produto_reconhecido, veredito, consulta_busca}`
- `POST /api/upload-imagem` (multipart `imagem`) → `{caminho}` ; `POST /api/chat` `{mensagens:[{role,content}], imagem?, cliente_id?}` → `{resposta, ferramentas[], produtos[], laudo?, genie?}`
- `GET /api/mcp/ferramentas` → `{servidor, endpoint, ferramentas:[{nome,titulo,descricao,parametros}]}`
- Estúdio: `GET /api/estudio/status`, `GET /api/estudio/produtos?q=&origem=&limite=`, `PUT/DELETE /api/estudio/produtos/{id}`,
  `POST /api/estudio/produtos/{id}/imagem` (multipart), `GET /api/estudio/fichas/exemplos` → `{exemplos:[{nome,caminho}]}`,
  `POST /api/estudio/fichas` (multipart `arquivo` OU form `exemplo`) → `{chave, arquivo, caminho, segundos_parse, elementos{}, tabelas_html[], figuras[{caminho,pagina,largura,altura,retrato,descricao}], imagem_path, ficha{campos de produto}, texto_extraido}`,
  `POST /api/estudio/fichas/{chave}/publicar` `{ficha, imagem_path}` → produto, `GET/POST /api/estudio/documentos`, `DELETE /api/estudio/documentos/{arquivo}`,
  `POST /api/estudio/sync/{produtos|ajuda}`, `POST /api/estudio/recalcular`, `POST /api/estudio/recarregar`.

## MCP "Detetive de Produtos" (`brickstore-detetive-de-produtos`)
Ferramentas: `investigar_imagem(imagem, quantidade)`, `analisar_imagem(imagem)`, `buscar_produtos(consulta, departamento?, preco_max?, quantidade)`,
`quem_comprou_tambem_comprou(produto, quantidade)`, `compre_junto(produto)`, `ficha_produto(produto)`.

## Ativos estáticos
- `documentos/*.pdf` — central de ajuda do varejo (trocas e devoluções, entrega e frete, pagamento e parcelamento, garantia e assistência,
  programa de fidelidade, retirada em loja, privacidade do Detetive de Produtos, termos de uso) — com TABELAS.
- `fichas/*.pdf` — 3 fichas técnicas de fornecedor (com FOTO do produto renderizada + tabelas de especificações, dimensões/grade de
  tamanhos, preços e condições). Ex.: Sofá retrátil 3 lugares (Nórdica Home), Tênis de corrida (Pulse Sports), Headset gamer (Neon Lab).
