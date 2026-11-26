"""
Gera os PDFs da CENTRAL DE AJUDA do varejo em ../documentos/.

Esses PDFs são o insumo do `ai_parse_document` (setup/02_documentos_ai_parse.py): o Databricks lê o
PDF binário, extrai títulos, seções, parágrafos e TABELAS, e o chunking por seção alimenta o
Vector Search do suporte (RAG da central de ajuda).

Marca: lida de NB_MARCA (padrão "BrickStore"). Todo o conteúdo é fictício, mas coerente com o
varejo brasileiro (CDC: 7 dias de arrependimento para compras online, garantia legal etc.).

Uso (local, opcional — os PDFs já vêm prontos no repositório):
    pip install reportlab
    python ferramentas/gerar_documentos.py
"""
import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MARCA = os.environ.get("NB_MARCA", "BrickStore")
DOMINIO = MARCA.lower().replace(" ", "") + ".com.br"
SAIDA = Path(__file__).resolve().parent.parent / "documentos"
SAIDA.mkdir(exist_ok=True)

NAVY = colors.HexColor("#1B3139")
LAVA = colors.HexColor("#FF3621")
CINZA = colors.HexColor("#C9CCD6")
ZEBRA = colors.HexColor("#F4F5F9")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontName="Helvetica-Bold", fontSize=20, spaceAfter=8)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=LAVA, fontName="Helvetica-Bold", fontSize=13.5,
                    spaceBefore=12, spaceAfter=5)
P = ParagraphStyle("p", parent=ss["BodyText"], fontSize=10.5, leading=15, spaceAfter=4)
SMALL = ParagraphStyle("s", parent=P, fontSize=8.5, textColor=colors.grey)
CEL = ParagraphStyle("cel", parent=P, fontSize=9, leading=12, spaceAfter=0)
CEL_H = ParagraphStyle("celh", parent=CEL, fontName="Helvetica-Bold", textColor=colors.white)


def brl(valor):
    """Formata em reais no padrão brasileiro: 1234.5 -> 'R$ 1.234,50'."""
    s = f"{valor:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def parcela_price(principal, taxa_mensal, n):
    """Valor da parcela pelo sistema Price (juros compostos)."""
    if taxa_mensal == 0:
        return principal / n
    return principal * taxa_mensal / (1 - (1 + taxa_mensal) ** -n)


def tabela(linhas, larguras=None):
    """Primeira linha = cabeçalho navy; demais zebradas. Células viram Paragraph (quebra de linha)."""
    dados = []
    for i, linha in enumerate(linhas):
        estilo = CEL_H if i == 0 else CEL
        dados.append([Paragraph(str(c), estilo) for c in linha])
    t = Table(dados, colWidths=larguras, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, LAVA),
        ("GRID", (0, 0), (-1, -1), 0.4, CINZA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def doc(nome, titulo, blocos):
    """blocos: lista de ('h2', txt) | ('p', txt) | ('t', linhas, larguras|None)."""
    story = [Paragraph(f"CENTRAL DE AJUDA · {MARCA.upper()}", SMALL), Spacer(1, 0.2 * cm),
             Paragraph(titulo, H1),
             Paragraph(f"Documento fictício para fins de demonstração · versão 2026.11 · atendimento: {DOMINIO}", SMALL),
             Spacer(1, 0.5 * cm)]
    for bloco in blocos:
        tipo, conteudo = bloco[0], bloco[1]
        if tipo == "h2":
            story.append(Paragraph(conteudo, H2))
        elif tipo == "p":
            story.append(Paragraph(conteudo, P))
        elif tipo == "t":
            larguras = bloco[2] if len(bloco) > 2 else None
            story.append(tabela(conteudo, larguras))
            story.append(Spacer(1, 0.35 * cm))
    SimpleDocTemplate(str(SAIDA / nome), pagesize=A4, title=f"{titulo} — {MARCA}", author=MARCA,
                      leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm).build(story)
    print("✓", nome)


# ---------------------------------------------------------------- 01
doc("01_trocas_e_devolucoes.pdf", "Trocas e devoluções", [
    ("p", f"Na {MARCA} você pode trocar ou devolver produtos com tranquilidade. Este documento explica os prazos, "
          "quem paga o frete e como o reembolso é feito. Compras feitas pelo site, pelo app ou por telefone seguem "
          "o Código de Defesa do Consumidor; compras feitas nas lojas físicas seguem a mesma política, com o "
          "cupom fiscal."),
    ("h2", "Direito de arrependimento (7 dias)"),
    ("p", "Em compras online, fora da loja física, você pode desistir da compra em até <b>7 dias corridos</b> após "
          "o recebimento, sem precisar justificar. O produto deve voltar sem sinais de uso, na embalagem original e "
          "com todos os acessórios e etiquetas. Nós buscamos o produto na sua casa sem custo."),
    ("h2", "Prazos para troca e devolução"),
    ("t", [["Situação", "Prazo", "Quem paga o frete", "Como é resolvido"],
           ["Arrependimento (compra online)", "7 dias corridos após o recebimento", MARCA, "Reembolso integral"],
           ["Produto com defeito de fabricação", "30 dias (não duráveis: roupas, alimentos) ou 90 dias (duráveis: móveis, eletrônicos)",
            MARCA, "Troca, reparo ou reembolso"],
           ["Produto diferente do pedido", "30 dias após o recebimento", MARCA, "Troca imediata ou reembolso"],
           ["Tamanho ou cor diferente do desejado (loja física)", "30 dias com cupom fiscal", "Cliente", "Troca por outro tamanho ou cor"],
           ["Produto avariado na entrega", "Recusar na hora ou em até 48 horas", MARCA, "Reenvio ou reembolso"]],
     [5.0 * cm, 5.2 * cm, 2.8 * cm, 4.0 * cm]),
    ("h2", "Como solicitar a troca"),
    ("p", "Acesse <b>Minha conta &gt; Meus pedidos &gt; Trocar ou devolver</b>, escolha o item e o motivo e agende a "
          "coleta. Você também pode falar com o atendimento pelo chat do app ou pelo e-mail "
          f"atendimento@{DOMINIO}. A solicitação recebe um número de protocolo e uma resposta em até 2 dias úteis."),
    ("h2", "Itens que não podem ser trocados"),
    ("t", [["Item", "Motivo"],
           ["Produtos personalizados (gravação, bordado, medidas sob encomenda)", "Fabricados sob demanda"],
           ["Produtos de higiene e beleza com lacre violado", "Risco à saúde do consumidor"],
           ["Alimentos e bebidas", "Perecíveis"],
           ["Itens sem embalagem ou com sinais de uso", "Descaracterização do produto"]],
     [9.0 * cm, 8.0 * cm]),
    ("h2", "Reembolso"),
    ("p", "O reembolso é feito na mesma forma de pagamento: estorno no cartão em até 2 faturas, devolução ao PIX "
          "em até 5 dias úteis ou crédito no saldo da conta. Compras pagas com cupom ou vale-presente têm o valor "
          "devolvido na mesma modalidade."),
])

# ---------------------------------------------------------------- 02
FRETE = [  # região, prazo padrão, frete padrão, frete expresso, frete grátis a partir de
    ("Sudeste", "3 a 5 dias úteis", 14.90, 29.90, 199.00),
    ("Sul", "4 a 7 dias úteis", 19.90, 39.90, 249.00),
    ("Centro-Oeste", "5 a 8 dias úteis", 24.90, 49.90, 279.00),
    ("Nordeste", "6 a 10 dias úteis", 29.90, 59.90, 299.00),
    ("Norte", "8 a 14 dias úteis", 39.90, 79.90, 349.00),
]
doc("02_entrega_e_frete.pdf", "Entrega e frete", [
    ("p", f"A {MARCA} entrega em todo o Brasil. O prazo começa a contar no dia útil seguinte à aprovação do pagamento "
          "e à emissão da nota fiscal. Os valores abaixo são por pedido, para uma entrega em endereço residencial."),
    ("h2", "Prazo e valor do frete por região"),
    ("t", [["Região", "Prazo (padrão)", "Frete padrão", "Frete expresso", "Frete grátis a partir de"]] +
          [[r, p, brl(fp), brl(fe), brl(g)] for r, p, fp, fe, g in FRETE],
     [3.2 * cm, 3.8 * cm, 3.0 * cm, 3.2 * cm, 3.8 * cm]),
    ("p", "O <b>frete expresso</b> reduz o prazo em cerca de 2 dias úteis, quando disponível para o seu CEP. O frete "
          "grátis vale para o valor dos produtos, antes do frete, e não se aplica a móveis volumosos (sofás, "
          "estantes e camas), que têm cálculo próprio mostrado no carrinho."),
    ("h2", "Móveis e produtos volumosos"),
    ("p", "Sofás, camas, guarda-roupas e outros produtos volumosos são entregues em caminhão. Você recebe um e-mail com "
          "a janela de entrega de 4 horas, e o motorista pode levar o produto até o cômodo escolhido. A montagem é "
          "opcional e tem valor próprio."),
    ("t", [["Produto volumoso", "Entrega", "Montagem"],
           ["Sofás e poltronas", "Caminhão, até o andar", "Opcional (R$ 89,90)"],
           ["Camas e colchões", "Caminhão, até o andar", "Opcional (R$ 119,90)"],
           ["Estantes e guarda-roupas", "Caminhão, até o andar", "Opcional (R$ 149,90)"]],
     [6.0 * cm, 6.0 * cm, 5.0 * cm]),
    ("h2", "Acompanhamento"),
    ("p", "Assim que o pedido sai do centro de distribuição você recebe o código de rastreio por e-mail e pelo app. "
          "Em <b>Meus pedidos</b> o status muda entre Separação, Em transporte, Saiu para entrega e Entregue."),
    ("h2", "Não localizado ou endereço incorreto"),
    ("p", "Se a entrega não puder ser feita, tentamos uma segunda vez no dia útil seguinte. Após duas tentativas, o pedido "
          "retorna ao centro de distribuição e você pode reagendar em até 15 dias, pagando o novo frete."),
])

# ---------------------------------------------------------------- 03
PARCELAS_TAB = []
PRINCIPAL = 1000.0
for n in (1, 3, 6, 10, 12):
    juros = 0.0199 if n > 6 else 0.0
    total = parcela_price(PRINCIPAL, juros, n) * n
    PARCELAS_TAB.append([f"{n}x", "sem juros" if juros == 0 else "1,99% ao mês",
                         brl(total / n), brl(total),
                         "Parcela no cartão" if n > 1 else "Pagamento à vista no cartão"])
doc("03_pagamento_e_parcelamento.pdf", "Pagamento e parcelamento", [
    ("p", f"Na {MARCA} você paga com cartão de crédito (parcelado), PIX, boleto ou saldo da conta. O parcelamento "
          "aparece no carrinho antes da confirmação, com o valor de cada parcela e o total final."),
    ("h2", "Formas de pagamento"),
    ("t", [["Forma", "Parcelamento", "Desconto", "Observação"],
           ["Cartão de crédito (Visa, Mastercard, Elo, Amex)", "Até 12x", "—", "Aprovação em segundos"],
           ["PIX", "À vista", "5% no total do pedido", "Confirmação imediata"],
           ["Boleto bancário", "À vista", "3% no total do pedido", "Compensação em até 3 dias úteis"],
           ["Saldo da conta / vale-presente", "À vista", "—", "Não expira"]],
     [5.8 * cm, 3.0 * cm, 3.6 * cm, 4.6 * cm]),
    ("h2", "Parcelas e juros do cartão"),
    ("p", "Parcelamentos de 2x a 6x são <b>sem juros</b> para compras acima de R$ 150,00. De 7x a 12x incide juros "
          "de 1,99% ao mês. A tabela abaixo é um exemplo para uma compra de R$ 1.000,00, com cálculo pelo sistema Price."),
    ("t", [["Parcelas", "Juros", "Valor da parcela", "Total pago", "Observação"]] + PARCELAS_TAB,
     [2.4 * cm, 3.2 * cm, 3.4 * cm, 3.2 * cm, 4.8 * cm]),
    ("h2", "Falha na cobrança"),
    ("p", "Se o cartão for recusado, você pode tentar outro cartão ou escolher PIX sem perder o carrinho. O pedido só "
          "é separado depois que o pagamento é aprovado."),
    ("h2", "Cupons e promoções"),
    ("p", "Cupons têm validade e regras indicadas na própria oferta. Não é possível combinar dois cupons no mesmo "
          "pedido, e o desconto do PIX ou do boleto não se soma a cupons de primeira compra. Ofertas do dia valem "
          "enquanto houver estoque."),
    ("h2", "Nota fiscal"),
    ("p", f"A nota fiscal eletrônica é enviada por e-mail após a aprovação do pagamento e fica disponível em "
          "<b>Minha conta &gt; Pedidos &gt; Nota fiscal</b>."),
])

# ---------------------------------------------------------------- 04
doc("04_garantia_e_assistencia.pdf", "Garantia e assistência técnica", [
    ("p", "Todo produto vendido pela " + MARCA + " tem <b>garantia legal</b>, prevista no Código de Defesa do Consumidor, "
          "e, quando aplicável, a <b>garantia do fabricante</b>. A garantia cobre defeitos de fabricação, não cobre mau uso."),
    ("h2", "Prazos de garantia"),
    ("t", [["Categoria", "Garantia legal", "Garantia do fabricante", "Garantia estendida (opcional)"],
           ["Moda e acessórios (não duráveis)", "30 dias", "—", "Não disponível"],
           ["Casa e decoração (móveis, tapetes, luminárias)", "90 dias", "3 meses a 1 ano", "Até 2 anos"],
           ["Cozinha (panelas, eletroportáteis)", "90 dias", "1 ano", "Até 2 anos"],
           ["Eletrônicos (TVs, notebooks, fones, consoles)", "90 dias", "6 meses a 3 anos", "Até 3 anos"],
           ["Esporte e lazer (bicicletas, barracas)", "90 dias", "6 meses a 1 ano", "Até 2 anos"]],
     [5.8 * cm, 2.8 * cm, 3.6 * cm, 4.8 * cm]),
    ("p", "A garantia legal começa a contar na data de entrega. Para defeitos que aparecem depois do uso normal, o "
          "prazo legal é contado a partir do aparecimento do defeito."),
    ("h2", "Garantia estendida"),
    ("p", "É um plano opcional contratado no carrinho ou em até 30 dias após a compra. Cobre danos acidentais (queda, "
          "líquido derramado, oscilação de tensão) e amplia o prazo do fabricante. Não substitui a garantia legal."),
    ("h2", "Assistência técnica"),
    ("p", "Para acionar a garantia, acesse <b>Minha conta &gt; Pedidos &gt; Assistência</b>, informe o defeito e envie fotos "
          "ou vídeo. Em produtos eletrônicos, a análise inicial é feita em até 2 dias úteis. Quando há reparo, o "
          "produto é coletado sem custo e devolvido em até 30 dias."),
    ("t", [["Etapa", "Prazo", "Responsável"],
           ["Abertura do chamado", "Imediato", "Cliente"],
           ["Análise técnica inicial", "Até 2 dias úteis", MARCA],
           ["Coleta do produto (quando necessário)", "Até 3 dias úteis", MARCA],
           ["Reparo ou troca", "Até 30 dias", "Assistência autorizada"],
           ["Devolução ao cliente", "Até 5 dias úteis após o reparo", MARCA]],
     [7.0 * cm, 5.0 * cm, 5.0 * cm]),
    ("h2", "Quando a garantia não vale"),
    ("p", "Danos por queda ou líquido, uso fora da finalidade indicada no manual, instalação elétrica inadequada, "
          "violação do lacre e desgaste natural (cor, pilling em tecidos e riscos em superfícies) não são cobertos."),
])

# ---------------------------------------------------------------- 05
doc("05_programa_de_fidelidade.pdf", f"Programa de fidelidade {MARCA} Clube", [
    ("p", f"O <b>{MARCA} Clube</b> é gratuito e dá pontos a cada compra aprovada. Os pontos sobem o seu nível de "
          "fidelidade, que libera cashback, frete e benefícios exclusivos. O nível é reavaliado a cada 12 meses, com "
          "base nos pontos acumulados nesse período."),
    ("h2", "Como acumular pontos"),
    ("p", "Cada R$ 1,00 em compras aprovadas (excluindo frete e impostos) vale 1 ponto. Pontos de compras pagas "
          "com cartão são liberados 30 dias após a entrega; pontos de compras com PIX ou boleto, após a compensação."),
    ("h2", "Níveis e benefícios"),
    ("t", [["Nível", "Pontos no ano", "Cashback", "Frete", "Benefícios extras"],
           ["Bronze", "0 a 999", "1%", "Grátis acima de R$ 299", "Ofertas do Clube"],
           ["Prata", "1.000 a 4.999", "2%", "Grátis acima de R$ 199", "Cupom de aniversário de 10%"],
           ["Ouro", "5.000 a 14.999", "3%", "Grátis acima de R$ 99", "Acesso antecipado a lançamentos"],
           ["Diamante", "15.000 ou mais", "5%", "Grátis acima de R$ 49", "Consultoria de decoração e atendimento prioritário"]],
     [2.4 * cm, 3.0 * cm, 2.2 * cm, 4.0 * cm, 5.4 * cm]),
    ("h2", "Como usar o cashback"),
    ("p", "O cashback vira saldo na conta e pode ser usado em qualquer compra, sem valor mínimo, em até 12 meses após "
          "o crédito. Pontos não podem ser convertidos em dinheiro."),
    ("h2", "Quando o nível cai"),
    ("p", "Se, na reavaliação anual, os pontos ficarem abaixo do patamar do nível atual, o nível é reduzido para o "
          "anterior. Você recebe um aviso por e-mail 30 dias antes da mudança."),
    ("h2", "Pontos expirados e cancelamentos"),
    ("p", "Pontos expiram após 24 meses sem movimentação. Pedidos cancelados ou devolvidos têm os pontos estornados "
          "proporcionalmente, e o cashback correspondente é descontado do saldo."),
])

# ---------------------------------------------------------------- 06
LOJAS = [
    [f"{MARCA} Paulista", "Av. Brasil, 1500, térreo", "São Paulo / SP", "10h às 22h", "12h às 20h"],
    [f"{MARCA} Barra", "Av. das Américas, 4200, L2", "Rio de Janeiro / RJ", "10h às 22h", "12h às 20h"],
    [f"{MARCA} Savassi", "Rua Pernambuco, 800", "Belo Horizonte / MG", "10h às 21h", "Fechada"],
    [f"{MARCA} Batel", "Rua Padre Anchieta, 1200", "Curitiba / PR", "10h às 22h", "12h às 20h"],
    [f"{MARCA} Iguatemi", "Av. Tancredo Neves, 2000", "Salvador / BA", "10h às 22h", "13h às 19h"],
    [f"{MARCA} Moinhos", "Rua Padre Chagas, 300", "Porto Alegre / RS", "10h às 21h", "Fechada"],
]
doc("06_retirada_em_loja.pdf", "Retirada em loja e compre online, retire na loja", [
    ("p", "Escolha a opção <b>Retirar na loja</b> no carrinho e acompanhe o pedido. A retirada é gratuita, e a maior "
          "parte dos pedidos fica pronta em até 2 horas úteis (exceto produtos volumosos, que são separados em até 24 "
          "horas)."),
    ("h2", "Lojas com retirada"),
    ("t", [["Loja", "Endereço", "Cidade / UF", "Seg. a sáb.", "Domingo e feriados"]] + LOJAS,
     [3.4 * cm, 4.6 * cm, 3.4 * cm, 2.6 * cm, 3.0 * cm]),
    ("p", "Horários podem mudar em feriados e datas comemorativas. Consulte a loja antes da visita."),
    ("h2", "Como retirar"),
    ("p", "Leve um documento com foto e o número do pedido (ou o QR Code no app). Quem for retirar no lugar do "
          "titular precisa de autorização por escrito e do documento de quem comprou."),
    ("t", [["Situação", "Prazo para retirar", "O que acontece depois"],
           ["Pedido pronto para retirada", "7 dias corridos", "Após o prazo, o pedido volta ao estoque e o valor é estornado"],
           ["Produto volumoso", "5 dias corridos", "Pode ser convertido em entrega em domicílio, com frete a pagar"],
           ["Pedido pago com boleto ainda não compensado", "Após a compensação", "A retirada só é liberada depois da confirmação"]],
     [5.4 * cm, 4.0 * cm, 7.6 * cm]),
    ("h2", "Troca na loja física"),
    ("p", "Pedidos online podem ser trocados ou devolvidos em qualquer loja da " + MARCA + ", mesmo quando foram "
          "comprados em outra cidade, desde que o prazo de 30 dias seja respeitado e o produto esteja na embalagem original."),
])

# ---------------------------------------------------------------- 07
doc("07_detetive_de_produtos.pdf", "Detetive de Produtos: como funciona e privacidade", [
    ("p", "O <b>Detetive de Produtos</b> é a <b>busca visual</b> da " + MARCA + ". Você envia a foto de um produto "
          "(um tênis, uma poltrona, um fone, uma luminária que viu por aí) e a nossa IA identifica o que é o produto "
          "e encontra no catálogo os produtos parecidos."),
    ("h2", "Como a busca visual é feita"),
    ("p", "1) Um modelo de visão multimodal produz um <b>laudo</b> do produto em destaque na foto: tipo, cor, "
          "material, estilo provável e detalhes visíveis. 2) O laudo vira uma busca semântica no catálogo, sobre as "
          "descrições e as descrições visuais de cada produto. 3) Os resultados são ordenados por similaridade e "
          "compatibilidade, e cada um vem com as <b>pistas</b> que explicam a escolha."),
    ("t", [["Etapa", "O que acontece", "Resultado para você"],
           ["Reconhecimento", "A IA identifica o produto da foto", "Tipo do produto"],
           ["Laudo", "Cor, material, estilo e detalhes", "Descrição do produto"],
           ["Busca no catálogo", "Comparação com a descrição visual dos produtos", "Produtos parecidos, por similaridade"]],
     [4.0 * cm, 6.5 * cm, 6.5 * cm]),
    ("h2", "Retenção e privacidade das imagens"),
    ("t", [["Item", "Política"],
           ["Imagem enviada", "Armazenada em volume privado por até 30 dias e depois apagada"],
           ["Laudo da imagem", "Guardado sem identificação, apenas para melhorar as recomendações"],
           ["Pessoas na foto", "Rostos não são identificados nem reconhecidos. Não criamos perfis por imagem"],
           ["Dados de localização", "Metadados de GPS e data são removidos ao enviar a foto"],
           ["Compartilhamento", f"Nunca compartilhamos imagens com terceiros. Dúvidas: privacidade@{DOMINIO}"]],
     [4.5 * cm, 12.5 * cm]),
    ("h2", "Limites de uso"),
    ("p", "Formatos aceitos: JPG, PNG e WEBP, com até 10 MB. Fotos com conteúdo impróprio ou sem um produto "
          "identificável são recusadas com uma explicação. Em perfis infantis o recurso não está disponível."),
    ("h2", "Uso por outros aplicativos (servidor MCP)"),
    ("p", "O Detetive de Produtos também é exposto como um servidor <b>MCP (Model Context Protocol)</b>. Assim, "
          "assistentes de IA autorizados podem usar as mesmas ferramentas de busca visual, busca por texto e "
          "compre-junto. O acesso ao servidor MCP exige autenticação e é registrado para auditoria."),
])

# ---------------------------------------------------------------- 08
doc("08_termos_de_uso.pdf", "Termos de uso (resumo)", [
    ("p", "Este resumo acompanha os Termos de Uso completos, disponíveis no site e no app. Ao criar uma conta ou "
          "finalizar uma compra, você concorda com as condições abaixo."),
    ("h2", "Conta e idade mínima"),
    ("p", "Para comprar é preciso ter 18 anos ou mais, ou ser representado por um responsável legal. Você é "
          "responsável pela guarda da senha e pelas compras feitas na sua conta."),
    ("h2", "Preços, estoque e ofertas"),
    ("p", "Os preços e as condições de pagamento são os vigentes no momento da compra. Erros evidentes de preço podem "
          "ser corrigidos antes da confirmação do pedido, com aviso ao cliente. Ofertas têm prazo e estoque limitados."),
    ("h2", "Prazos de atendimento"),
    ("t", [["Canal", "Disponibilidade", "Tempo de resposta"],
           ["Chat no app e no site", "Todos os dias, das 8h às 22h", "Imediato (bot) ou até 1 hora úteis (atendente)"],
           ["E-mail", "Todos os dias", "Até 2 dias úteis"],
           ["Telefone SAC", "Seg. a sáb., das 8h às 20h", "Imediato"]],
     [4.8 * cm, 6.0 * cm, 6.2 * cm]),
    ("h2", "Propriedade intelectual"),
    ("p", "Marcas, fotos, textos e a identidade visual do site e do app pertencem à " + MARCA + " ou são usados com "
          "autorização. Marcas de terceiros (fabricantes) são citadas apenas para identificar os produtos."),
    ("h2", "Privacidade (LGPD)"),
    ("p", "Tratamos dados pessoais conforme a Lei Geral de Proteção de Dados. Você pode solicitar acesso, correção, "
          f"portabilidade ou exclusão dos seus dados em <b>Minha conta &gt; Privacidade</b>. O encarregado de dados "
          f"(DPO) atende pelo e-mail privacidade@{DOMINIO}."),
    ("h2", "Alterações destes termos"),
    ("p", "Podemos atualizar estes termos. Mudanças relevantes são comunicadas por e-mail e no app com 30 dias de "
          "antecedência, e a continuidade do uso após esse prazo indica a aceitação."),
])
