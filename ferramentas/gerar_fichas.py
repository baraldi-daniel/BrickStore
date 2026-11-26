"""
Gera as FICHAS TÉCNICAS DE FORNECEDOR em PDF, em ../fichas/.

Cada ficha tem o que uma ficha de fornecedor real costuma ter — e é justamente o que o
`ai_parse_document` extrai no Estúdio do App (cadastro de produto a partir de PDF):
  • IMAGENS: foto principal (1ª figura do PDF; o App recorta pela bounding box e usa como foto
    do produto) + 1 ou 2 fotos de detalhe, renderizadas com PIL sobre fundo neutro de estúdio;
  • TABELAS: especificações, dimensões/grade de tamanhos e preços e condições;
  • TEXTO: cabeçalho "FICHA TÉCNICA · <fornecedor>", descrição para o e-commerce e estilo/ambientação.

Fornecedores fictícios: Nórdica Home (sofá), Pulse Sports (tênis), Neon Lab (headset).

Uso (local, opcional — as fichas já vêm prontas no repositório):
    pip install pillow reportlab
    python ferramentas/gerar_fichas.py
"""
import io
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, str(Path(__file__).resolve().parent))  # importa desenho.py (mesmo diretório)
from desenho import Tela, tenis_perfil  # noqa: E402

MARCA = os.environ.get("NB_MARCA", "BrickStore")
SAIDA = Path(__file__).resolve().parent.parent / "fichas"
SAIDA.mkdir(exist_ok=True)

NAVY = colors.HexColor("#1B3139")
LAVA = colors.HexColor("#FF3621")
CINZA = colors.HexColor("#C9CCD6")
ZEBRA = colors.HexColor("#F4F5F9")


# ======================================================================
# Fotos (PIL) — fundo neutro de estúdio, sombra de contato, produto centralizado
# ======================================================================
def estudio(lado=1000, topo=(246, 245, 242), base=(224, 222, 218)):
    t = Tela(largura=lado, altura=lado)
    t.faixa(0, lado, topo, base)
    return t


def foto_sofa():
    t = estudio()
    t.sombra(500, 796, 380, 26, 0.42, 20)
    madeira = (164, 124, 84)
    for x in (188, 786):
        t.rect(x, 770, x + 24, 800, madeira, r=6)
    linho, linho_cl, costura = (196, 200, 202), (214, 218, 220), (168, 172, 174)
    t.rect(120, 480, 214, 790, linho, r=40)           # braço esq.
    t.rect(786, 480, 880, 790, linho, r=40)           # braço dir.
    t.rect(200, 380, 800, 600, linho, r=50)           # encosto
    t.rect(150, 560, 850, 780, linho, r=40)           # base
    t.rect(226, 400, 486, 580, linho_cl, r=30)        # almofadas do encosto
    t.rect(514, 400, 774, 580, linho_cl, r=30)
    t.rect(226, 600, 486, 740, (208, 212, 214), r=24)  # almofadas do assento
    t.rect(514, 600, 774, 740, (208, 212, 214), r=24)
    t.linha([(486, 410), (486, 570)], costura, 2)
    t.linha([(514, 410), (514, 570)], costura, 2)
    t.linha([(486, 610), (486, 730)], costura, 2)
    t.linha([(514, 610), (514, 730)], costura, 2)
    t.linha([(160, 600), (840, 600)], costura, 2)
    # mecanismo retrátil: alavanca discreta na lateral
    t.rect(858, 636, 872, 664, (120, 120, 124), r=4)
    return t.img


def foto_tenis():
    t = estudio()
    t.sombra(500, 782, 380, 20, 0.42, 16)
    tenis_perfil(t, 110, 760, 2.6, (34, 98, 240), (176, 246, 60), (238, 242, 240))
    return t.img


def foto_headset():
    t = estudio(topo=(78, 80, 94), base=(30, 30, 38))  # fundo escuro-médio para o headset destacar
    t.sombra(500, 830, 300, 20, 0.6, 18)
    detalhe = (170, 70, 255)
    t.arco(240, 130, 760, 650, 180, 360, (62, 60, 76), 46)     # arco da cabeceira
    t.arco(252, 142, 748, 638, 180, 360, detalhe, 4)
    for x in (190, 660):                                        # conchas
        t.rect(x, 420, x + 150, 660, (44, 42, 56), r=60)
        t.rect(x + 16, 440, x + 134, 640, (66, 64, 80), r=50)
        t.elipse(x + 34, 470, x + 116, 610, (40, 38, 52))
        t.elipse(x + 22, 452, x + 128, 628, (40, 38, 52), cont=(0, 230, 255), lw=4)
    # braço do microfone (saindo da concha esquerda) e microfone
    t.linha([(232, 640), (250, 760), (380, 818)], (62, 60, 76), 18)
    t.linha([(232, 640), (250, 760), (380, 818)], detalhe, 3)
    t.elipse(350, 796, 430, 836, (50, 48, 62), cont=(0, 230, 255), lw=3)
    return t.img


def detalhe_tecido():
    t = Tela(largura=600, altura=600)
    t.faixa(0, 600, (200, 204, 206), (192, 196, 198))
    for y in range(0, 600, 6):
        t.linha([(0, y), (600, y)], (184, 188, 190), 2)
    for x in range(0, 600, 6):
        t.linha([(x, 0), (x, 600)], (214, 218, 220), 2)
    t.linha([(0, 300), (600, 300)], (150, 154, 156), 3)
    for x in range(20, 600, 28):
        t.linha([(x, 300), (x + 12, 300)], (120, 124, 126), 4)
    return t.img


def detalhe_pe_madeira():
    t = Tela(largura=600, altura=600)
    t.faixa(0, 600, (236, 234, 230), (222, 220, 216))
    t.sombra(300, 540, 130, 22, 0.45, 14)
    t.poli([(250, 80), (350, 80), (330, 500), (270, 500)], (170, 126, 84))
    t.poli([(250, 80), (262, 80), (254, 500), (270, 500)], (196, 152, 110))
    for x in range(282, 340, 9):
        t.linha([(x, 110), (x - 4 + (x % 3), 480)], (150, 108, 70), 2)
    t.rect(246, 36, 354, 84, (120, 88, 56), r=8)
    return t.img


def detalhe_sola():
    t = Tela(largura=600, altura=600)
    t.faixa(0, 600, (236, 238, 238), (222, 226, 226))
    t.rect(60, 180, 540, 430, (238, 242, 240), r=60)
    t.rect(60, 370, 540, 430, (176, 246, 60), r=30)
    for x in range(90, 520, 46):
        t.poli([(x, 220), (x + 18, 300), (x + 36, 220), (x + 42, 220), (x + 18, 318), (x - 6, 220)], (70, 74, 78))
    for x in range(100, 520, 46):
        t.linha([(x, 340), (x + 30, 340)], (120, 124, 128), 3)
    return t.img


def detalhe_mesh():
    t = Tela(largura=600, altura=600)
    t.faixa(0, 600, (40, 110, 236), (30, 90, 210))
    for y in range(30, 600, 42):
        for x in range(30 + (y // 42 % 2) * 21, 600, 42):
            t.elipse(x - 9, y - 6, x + 9, y + 6, (14, 58, 170))
            t.elipse(x - 7, y - 5, x + 7, y + 3, (80, 150, 250))
    t.linha([(0, 520), (600, 520)], (238, 242, 240), 6)
    return t.img


def detalhe_microfone():
    t = Tela(largura=600, altura=600)
    t.faixa(0, 600, (34, 34, 42), (20, 20, 26))
    t.linha([(80, 540), (300, 340)], (30, 30, 40), 28)
    t.linha([(80, 540), (300, 340)], (170, 70, 255), 3)
    t.elipse(260, 260, 420, 420, (26, 26, 34), cont=(0, 230, 255), lw=5)
    for y in range(280, 400, 16):
        for x in range(280, 400, 16):
            if (x - 340) ** 2 + (y - 340) ** 2 < 56 ** 2:
                t.elipse(x - 3, y - 3, x + 3, y + 3, (60, 60, 70))
    return t.img


def detalhe_concha():
    t = Tela(largura=600, altura=600)
    t.faixa(0, 600, (30, 30, 38), (14, 14, 20))
    t.elipse(90, 90, 510, 510, (26, 24, 36))
    t.elipse(130, 130, 470, 470, (50, 48, 62))
    for y in range(160, 460, 22):
        for x in range(160, 460, 22):
            if (x - 300) ** 2 + (y - 300) ** 2 < 130 ** 2:
                t.elipse(x - 4, y - 4, x + 4, y + 4, (30, 28, 40))
    t.elipse(110, 110, 490, 490, (0, 0, 0), cont=(0, 230, 255), lw=8)
    t.elipse(140, 140, 460, 460, (0, 0, 0), cont=(170, 70, 255), lw=4)
    return t.img


def png_bytes(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    buf.seek(0)
    return buf


# ======================================================================
# PDF da ficha
# ======================================================================
ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontName="Helvetica-Bold", fontSize=22,
                    leading=26, spaceAfter=4)
SUB = ParagraphStyle("sub", parent=ss["BodyText"], fontSize=10.5, textColor=colors.HexColor("#4A5A60"), spaceAfter=8)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=LAVA, fontName="Helvetica-Bold", fontSize=13,
                    spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("p", parent=ss["BodyText"], fontSize=10.2, leading=14.5, spaceAfter=4)
CAP = ParagraphStyle("cap", parent=P, fontSize=8.5, textColor=colors.grey, spaceAfter=0)
CEL = ParagraphStyle("cel", parent=P, fontSize=9, leading=12, spaceAfter=0)
CEL_H = ParagraphStyle("celh", parent=CEL, fontName="Helvetica-Bold", textColor=colors.white)
BANDA = ParagraphStyle("banda", parent=CEL_H, fontSize=9, textColor=colors.white)


def tabela(linhas, larguras):
    dados = [[Paragraph(escape(str(c)), CEL_H if i == 0 else CEL) for c in linha] for i, linha in enumerate(linhas)]
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


def ficha(arquivo, d):
    """d: dict com fornecedor, produto, marca, departamento, tipo, codigo, subtitulo, fotos, etc."""
    story = []
    cabecalho = Table([[Paragraph(escape(f"FICHA TÉCNICA · {d['fornecedor'].upper()}"), BANDA)]],
                      colWidths=[17.0 * cm], hAlign="LEFT")
    cabecalho.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LINEBELOW", (0, 0), (-1, -1), 2, LAVA),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    story += [cabecalho, Spacer(1, 0.35 * cm), Paragraph(escape(d["produto"]), H1),
              Paragraph(escape(d["subtitulo"]), SUB)]

    # foto principal (PRIMEIRA figura do PDF)
    story.append(RLImage(png_bytes(d["foto"]), width=10.5 * cm, height=10.5 * cm))
    story.append(Paragraph("Foto principal (ilustração do produto, fundo de estúdio)", CAP))
    story.append(Spacer(1, 0.25 * cm))
    detalhes = []
    for img, legenda in d["detalhes"]:
        detalhes.append([RLImage(png_bytes(img), width=6.6 * cm, height=6.6 * cm),
                         Paragraph(escape(legenda), CAP)])
    if detalhes:
        linha = [[c[0] for c in detalhes], [c[1] for c in detalhes]]
        tb = Table(linha, colWidths=[7.0 * cm] * len(detalhes), hAlign="LEFT")
        tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [tb, Spacer(1, 0.2 * cm)]

    story += [Paragraph("Dados de cadastro", H2),
              tabela([["Campo", "Valor"], ["Fornecedor", d["fornecedor"]], ["Marca", d["marca"]],
                      ["Departamento", d["departamento"]], ["Tipo", d["tipo"]],
                      ["Código do fornecedor", d["codigo"]]], [5.5 * cm, 11.5 * cm]),
              Paragraph("Especificações", H2),
              tabela([["Característica", "Valor"]] + d["especificacoes"], [5.5 * cm, 11.5 * cm]),
              Paragraph(d["titulo_dimensoes"], H2),
              tabela(d["dimensoes"]["linhas"], d["dimensoes"]["larguras"]),
              Paragraph("Preços e condições", H2),
              tabela([["Condição", "Valor"]] + d["precos"], [5.5 * cm, 11.5 * cm]),
              Paragraph("Descrição para o e-commerce", H2),
              Paragraph(escape(d["descricao"]), P),
              Paragraph("Estilo e ambientação", H2),
              tabela([["Aspecto", "Descrição"]] + d["estilo"], [5.5 * cm, 11.5 * cm]),
              Spacer(1, 0.4 * cm),
              Paragraph(escape(f"Ficha fictícia gerada para demonstração do ai_parse_document no {MARCA}."), CAP)]
    SimpleDocTemplate(str(SAIDA / arquivo), pagesize=A4, title=f"Ficha técnica — {d['produto']}",
                      author=d["fornecedor"], leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=1.8 * cm, bottomMargin=1.8 * cm).build(story)
    print("✓", arquivo)


# ======================================================================
# Os três produtos
# ======================================================================
FICHAS = [
    dict(
        arquivo="ficha_sofa_retratil_nordica.pdf",
        fornecedor="Nórdica Home", marca="Nórdica Home", produto="Sofá retrátil 3 lugares Nórdica",
        subtitulo="Sofá retrátil de 3 lugares em linho cinza-névoa · estilo minimalista escandinavo",
        departamento="Casa & Decoração", tipo="Sofá", codigo="NH-SR3-CZ01",
        foto=foto_sofa(),
        detalhes=[(detalhe_tecido(), "Detalhe 1: textura do linho e costura decorativa do assento"),
                  (detalhe_pe_madeira(), "Detalhe 2: pé de madeira de faia natural")],
        especificacoes=[
            ["Estrutura", "Madeira de pinus maciço e MDF com acabamento sem verniz tóxico"],
            ["Assentos", "3 lugares, com almofadas removíveis"],
            ["Mecanismo", "Retrátil: encosto reclinável em 3 posições, com alavanca lateral"],
            ["Revestimento", "Linho sintético cinza-névoa, lavável a seco"],
            ["Espumas", "D28 nos assentos e D20 no encosto"],
            ["Pés", "Faia natural, 14 cm de altura"],
            ["Capacidade", "Até 300 kg distribuídos"],
            ["Montagem", "Parcial (pés, encosto e braços); manual incluso"],
            ["Garantia", "Legal de 90 dias + 1 ano do fabricante"],
        ],
        titulo_dimensoes="Dimensões e peso",
        dimensoes=dict(linhas=[["Medida", "Valor"], ["Largura total", "210 cm"], ["Profundidade total", "88 cm"],
                               ["Altura total", "82 cm"], ["Altura do assento", "44 cm"],
                               ["Profundidade do assento", "56 cm"], ["Peso líquido", "58 kg"],
                               ["Volume da embalagem", "1,6 m³ (2 volumes)"]],
                       larguras=[5.5 * cm, 11.5 * cm]),
        precos=[["Preço sugerido", "R$ 3.499,00"], ["Preço promocional", "R$ 2.899,00"],
                ["Parcelas sem juros", "até 10x de R$ 289,90"],
                ["Prazo de entrega", "15 a 20 dias úteis (caminhão, com agendamento de janela de 4 horas)"],
                ["Frete", "Calculado no carrinho; frete grátis para o Sudeste a partir de R$ 199,00 (exceto volumosos)"]],
        descricao=("Sofá retrátil de três lugares com estrutura de madeira e revestimento de linho cinza-névoa. "
                   "O encosto reclina em três posições pela alavanca lateral, sem perder a linha limpa do design "
                   "escandinavo. Ideal para sala de estar, sala de TV ou um canto de leitura que pede conforto."),
        estilo=[["Estilo", "Minimalista escandinavo"],
                ["Cores", "Cinza-névoa (principal) com pés em faia natural"],
                ["Materiais", "Linho sintético, madeira de faia, espuma D28"],
                ["Ocasião / ambiente", "Sala de estar, sala de TV, apartamento compacto"]],
    ),
    dict(
        arquivo="ficha_tenis_corrida_pulse.pdf",
        fornecedor="Pulse Sports", marca="Pulse Sports", produto="Tênis de corrida Pulse Aero",
        subtitulo="Tênis de corrida neutro com amortecimento responsivo · cabedal em mesh respirável",
        departamento="Esporte & Lazer", tipo="Tênis de corrida", codigo="PS-AERO-22",
        foto=foto_tenis(),
        detalhes=[(detalhe_sola(), "Detalhe 1: solado de borracha com tração em zigue-zague"),
                  (detalhe_mesh(), "Detalhe 2: cabedal em mesh tech, azul-elétrico")],
        especificacoes=[
            ["Cabedal", "Mesh tech respirável com reforço TPU nas laterais"],
            ["Entressola", "Espuma PulseFoam (amortecimento responsivo)"],
            ["Solado", "Borracha de alta aderência com tração em zigue-zague"],
            ["Pisada", "Neutra"],
            ["Indicação", "Corrida de rua, treino de intervalo e caminhada"],
            ["Fechamento", "Cadarço com reforço na língua"],
            ["Lavagem", "Pano úmido e sabão neutro; não usar secadora"],
            ["Garantia", "Legal de 90 dias + 6 meses do fabricante"],
        ],
        titulo_dimensoes="Grade de tamanhos e dimensões",
        dimensoes=dict(linhas=[["Tamanho BR", "Comprimento da palmilha", "Peso aproximado"],
                               ["36", "22,5 cm", "240 g"], ["37", "23,0 cm", "246 g"], ["38", "23,5 cm", "252 g"],
                               ["39", "24,0 cm", "256 g"], ["40", "24,5 cm", "260 g"], ["41", "25,0 cm", "266 g"],
                               ["42", "25,5 cm", "272 g"], ["43", "26,0 cm", "278 g"], ["44", "26,5 cm", "284 g"]],
                       larguras=[4.0 * cm, 6.5 * cm, 6.5 * cm]),
        precos=[["Preço sugerido", "R$ 599,90"], ["Preço promocional", "R$ 449,90"],
                ["Parcelas sem juros", "até 6x de R$ 74,98"],
                ["Prazo de entrega", "5 a 7 dias úteis"],
                ["Troca de tamanho", "Gratuita em até 30 dias, com o par na embalagem original"]],
        descricao=("Tênis de corrida neutro para quem treina na rua ou na esteira. A entressola PulseFoam "
                   "amortece cada passada sem tirar a estabilidade, e o cabedal em mesh deixa o pé fresco mesmo em "
                   "treinos longos. Drop de 10 mm e solado com tração para asfalto molhado."),
        estilo=[["Estilo", "Esportivo performance"],
                ["Cores", "Azul-elétrico (principal), preto e verde-lima"],
                ["Materiais", "Mesh tech, espuma PulseFoam, borracha de solado"],
                ["Ocasião / ambiente", "Corrida de rua, academia, uso no dia a dia"]],
    ),
    dict(
        arquivo="ficha_headset_neon_lab.pdf",
        fornecedor="Neon Lab", marca="Neon Lab", produto="Headset gamer Neon Lab X7",
        subtitulo="Headset gamer com som virtual 7.1, microfone removível e iluminação RGB",
        departamento="Eletrônicos", tipo="Headset gamer", codigo="NL-X7-RGB",
        foto=foto_headset(),
        detalhes=[(detalhe_microfone(), "Detalhe 1: microfone removível com cancelamento de ruído"),
                  (detalhe_concha(), "Detalhe 2: concha com almofada de espuma e anel RGB")],
        especificacoes=[
            ["Drivers", "50 mm, neodímio"],
            ["Resposta de frequência", "20 Hz a 20 kHz"],
            ["Som", "Virtual 7.1 via USB (software opcional)"],
            ["Microfone", "Removível, unidirecional, com cancelamento de ruído"],
            ["Conexões", "USB-A (som 7.1 e iluminação) e P2 de 3,5 mm (com adaptador incluso)"],
            ["Iluminação", "RGB com cores configuráveis (roxo e ciano de fábrica)"],
            ["Almofadas", "Espuma de memória e couro sintético"],
            ["Garantia", "Legal de 90 dias + 2 anos do fabricante"],
        ],
        titulo_dimensoes="Dimensões e conexões",
        dimensoes=dict(linhas=[["Medida", "Valor"], ["Peso (sem microfone)", "320 g"],
                               ["Comprimento do cabo", "2,0 m"], ["Comprimento do microfone", "18 cm"],
                               ["Diâmetro dos drivers", "50 mm"], ["Ajuste da cabeceira", "Ajustável, 9 posições"],
                               ["Compatibilidade", "PC, console e celular (P2; microfone depende do aparelho)"]],
                       larguras=[5.5 * cm, 11.5 * cm]),
        precos=[["Preço sugerido", "R$ 399,90"], ["Preço promocional", "R$ 329,90"],
                ["Parcelas sem juros", "até 6x de R$ 54,98"],
                ["Prazo de entrega", "3 a 5 dias úteis"],
                ["Garantia estendida (opcional)", "Até 3 anos, contratada no carrinho"]],
        descricao=("Headset gamer com drivers de 50 mm, som virtual 7.1 pelo USB e microfone removível que corta "
                   "o ruído do teclado. A iluminação RGB combina com o setup, e as almofadas de espuma de memória "
                   "aguentam sessões longas de jogo ou de chamadas no home office."),
        estilo=[["Estilo", "Tech gamer neon"],
                ["Cores", "Preto, com detalhes em roxo e ciano (RGB)"],
                ["Materiais", "Plástico ABS, alumínio na cabeceira, espuma de memória"],
                ["Ocasião / ambiente", "Jogos, streaming e home office gamer"]],
    ),
]

if __name__ == "__main__":
    for f in FICHAS:
        arquivo = f.pop("arquivo")
        ficha(arquivo, f)
