"""
Gera uma ficha técnica NOVA (produto que não existe no catálogo) para testar o cadastro por PDF no Estúdio:
Poltrona Giratória Concha em veludo verde-musgo, estilo retrô (fornecedor fictício "Ateliê Ventura").

Uso: python ferramentas/gerar_ficha_nova.py   →   fichas/ficha_poltrona_giratoria_ventura.pdf
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerar_fichas import estudio, ficha  # noqa: E402

VELUDO, VELUDO_CL, VELUDO_ES = (74, 96, 62), (98, 122, 82), (52, 70, 44)
LATAO = (196, 160, 82)


def foto_poltrona():
    t = estudio()
    t.sombra(500, 838, 230, 22, 0.42, 20)
    t.rect(470, 690, 530, 830, LATAO, r=12)                     # coluna giratória
    t.elipse(330, 812, 670, 858, LATAO)                         # base redonda
    t.elipse(350, 808, 650, 838, (214, 182, 104))
    t.elipse(250, 300, 750, 560, VELUDO_ES)                     # concha (encosto)
    t.elipse(275, 320, 725, 560, VELUDO)
    for x in range(330, 700, 62):                               # gomos do capitonê
        t.rect(x, 340, x + 8, 540, VELUDO_ES, r=4)
    t.rect(250, 470, 330, 690, VELUDO_ES, r=40)                 # braços
    t.rect(670, 470, 750, 690, VELUDO_ES, r=40)
    t.rect(280, 560, 720, 700, VELUDO_CL, r=48)                 # assento
    t.rect(300, 575, 700, 600, (120, 146, 104), r=12)           # brilho do veludo
    return t.img.resize((1000, 1000))


def detalhe_veludo():
    t = estudio(600, VELUDO, VELUDO_ES)
    for i in range(0, 600, 46):
        t.rect(i, 0, i + 20, 600, VELUDO_CL, r=8)
    return t.img.resize((600, 600))


def detalhe_base():
    t = estudio(600)
    t.sombra(300, 470, 210, 26, 0.4, 16)
    t.elipse(80, 380, 520, 500, LATAO)
    t.elipse(110, 380, 490, 460, (222, 190, 112))
    t.rect(270, 140, 330, 420, LATAO, r=14)
    return t.img.resize((600, 600))


if __name__ == "__main__":
    ficha("ficha_poltrona_giratoria_ventura.pdf", dict(
        fornecedor="Ateliê Ventura", marca="Vintage 80", produto="Poltrona giratória Concha veludo verde-musgo",
        subtitulo="Poltrona giratória 360° em veludo cotelê verde-musgo com base de latão escovado · estilo retrô anos 70/80",
        departamento="Casa & Decoração", tipo="Poltrona", codigo="AV-PGC-VM07",
        foto=foto_poltrona(),
        detalhes=[(detalhe_veludo(), "Detalhe 1: veludo cotelê com capitonê vertical"),
                  (detalhe_base(), "Detalhe 2: base giratória de latão escovado")],
        especificacoes=[["Estrutura", "Madeira de eucalipto de reflorestamento e espuma injetada"],
                        ["Revestimento", "Veludo cotelê verde-musgo, toque macio, lavável a seco"],
                        ["Base", "Giratória 360°, aço com acabamento em latão escovado"],
                        ["Espuma", "D33 no assento e D26 no encosto"],
                        ["Capacidade", "Até 120 kg"], ["Montagem", "Não requer (entregue montada)"],
                        ["Garantia", "Legal de 90 dias + 2 anos do fabricante na estrutura"]],
        titulo_dimensoes="Dimensões e peso",
        dimensoes=dict(linhas=[["Medida", "Valor"], ["Largura", "82 cm"], ["Profundidade", "78 cm"], ["Altura", "84 cm"],
                               ["Altura do assento", "45 cm"], ["Peso", "21 kg"], ["Embalagem", "0,7 m³ (1 volume)"]],
                       larguras=[5.5 * 28.3465, 11.5 * 28.3465]),
        precos=[["Preço sugerido", "R$ 2.190,00"], ["Preço promocional", "R$ 1.849,00"],
                ["Parcelas sem juros", "até 10x de R$ 184,90"], ["Prazo de entrega", "10 a 15 dias úteis"],
                ["Frete", "Grátis para capitais do Sul e Sudeste"]],
        descricao=("Poltrona giratória em formato de concha, revestida em veludo cotelê verde-musgo com capitonê vertical "
                   "e base de latão escovado. Gira 360° e traz o charme dos anos 70 para a sala de estar, o canto de leitura "
                   "ou o quarto, com conforto de espuma D33."),
        estilo=[["Estilo", "Retrô anos 70/80"], ["Cores", "Verde-musgo com detalhes em latão (dourado)"],
                ["Materiais", "Veludo cotelê, latão escovado, madeira de reflorestamento"],
                ["Ocasião / ambiente", "Sala de estar vintage, canto de leitura, quarto"]],
    ))
