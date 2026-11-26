"""
Gera os DADOS SINTÉTICOS da BrickStore e grava em dados/*.parquet + dados/manifesto.json.

Os arquivos já vêm prontos no repositório; o notebook setup/01_dados só os carrega no Unity Catalog.
Rode este script apenas se quiser mudar a geração (estilos, produtos, clientes, pedidos, cestas, eventos):

    uv run --python 3.11 --with "pandas<3" --with "numpy<2.3" --with pyarrow python ferramentas/gerar_dados.py

A geração é determinística (sementes fixas 7 e 11 e data de referência fixa): mesmo código → mesmos dados.
Marcas, produtos e clientes são 100% fictícios.
"""
import json
from pathlib import Path

MARCA = "BrickStore"
DOMINIO = "brickstore.com.br"          # domínio fictício dos e-mails dos clientes
RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados"

import os
import re
import unicodedata
import numpy as np
import pandas as pd
from datetime import date, timedelta

# Referência fixa do lab (datas relativas a ela) e semente → mesmos dados em toda instalação
hoje = date(2026, 11, 20)
RN = np.random.default_rng(7)     # clientes, pedidos, cestas e eventos
RNP = np.random.default_rng(11)   # produtos


def limpar_nulos(pdf):
    """Colunas de texto: NaN/None viram None."""
    pdf = pdf.copy()
    for c in pdf.columns:
        if pdf[c].dtype == object:
            pdf[c] = pdf[c].astype(object).where(pdf[c].notna(), None)
    return pdf


def sem_acento(txt):
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")


TABELAS = {}      # tabela → DataFrame pandas
MANIFESTO = {"tabelas": {}, "pks": [], "fks": []}


def gravar(pdf, tabela, comentario, duplos=(), inteiros=(), nulos_texto=(), cdf=False):
    """Em vez de gravar no Delta, guarda o pandas e os metadados que o setup/01_dados usa ao carregar."""
    TABELAS[tabela] = limpar_nulos(pdf.drop(columns=list(nulos_texto), errors="ignore"))
    MANIFESTO["tabelas"][tabela] = {"comentario": comentario, "duplos": list(duplos), "inteiros": list(inteiros),
                                    "nulos_texto": list(nulos_texto), "cdf": bool(cdf)}


def chave_pk(tabela, coluna, nome_pk):
    MANIFESTO["pks"].append({"tabela": tabela, "coluna": coluna, "nome": nome_pk})


def chave_fk(tabela, coluna, ref_tabela, ref_coluna, nome_fk):
    MANIFESTO["fks"].append({"tabela": tabela, "coluna": coluna, "ref_tabela": ref_tabela,
                             "ref_coluna": ref_coluna, "nome": nome_fk})


# ## 1) Estilos (decoração e moda)


ESTILOS = [
    dict(id="escandinavo", nome="Minimalista escandinavo", paleta="branco, cinza claro, madeira clara",
         materiais="linho, carvalho", vibe="aconchegante e funcional", ocasiao="sala, quarto e home office",
         cores=["Branco", "Cinza claro", "Madeira clara", "Bege"],
         frase="Formas simples e acabamento claro, para ambientes funcionais e aconchegantes."),
    dict(id="industrial", nome="Industrial urbano", paleta="preto, grafite, cobre",
         materiais="metal, couro, concreto", vibe="urbana e robusta", ocasiao="loft, escritório e rua",
         cores=["Preto", "Grafite", "Cobre"],
         frase="Acabamento robusto e cara de loft, com metal aparente e visual urbano."),
    dict(id="boho", nome="Boho terroso", paleta="terracota, bege, mostarda",
         materiais="palha, macramê, algodão cru", vibe="leve e artesanal", ocasiao="varanda, quarto e dia a dia",
         cores=["Terracota", "Bege", "Mostarda", "Off-white"],
         frase="Textura artesanal e tons terrosos, para um clima leve e acolhedor."),
    dict(id="classico", nome="Clássico elegante", paleta="azul-marinho, dourado, off-white",
         materiais="veludo, mármore, seda", vibe="sofisticado", ocasiao="sala de jantar, eventos e sala de estar",
         cores=["Azul-marinho", "Dourado", "Off-white", "Vinho"],
         frase="Linhas elegantes e detalhes refinados, para ambientes sofisticados."),
    dict(id="streetwear", nome="Streetwear urbano", paleta="preto, branco, verde-neon",
         materiais="moletom, nylon", vibe="jovem e despojada", ocasiao="rua, skate e dia a dia",
         cores=["Preto", "Branco", "Verde-neon"],
         frase="Modelagem despojada e cara de rua, para compor looks jovens."),
    dict(id="esportivo", nome="Esportivo performance", paleta="azul-elétrico, preto, verde-lima",
         materiais="tecido tech, mesh", vibe="ativa e moderna", ocasiao="academia, corrida e treino ao ar livre",
         cores=["Azul-elétrico", "Preto", "Verde-lima"],
         frase="Tecnologia pensada para o movimento, com visual ativo e moderno."),
    dict(id="verao", nome="Verão tropical", paleta="turquesa, coral, branco",
         materiais="linho, palha", vibe="solar e leve", ocasiao="praia, piscina e férias",
         cores=["Turquesa", "Coral", "Branco"],
         frase="Tons solares e tecidos leves, perfeitos para dias quentes."),
    dict(id="inverno", nome="Inverno aconchegante", paleta="vinho, marrom, creme",
         materiais="lã, tricô, flanela", vibe="quentinha", ocasiao="noites frias, serra e sofá",
         cores=["Vinho", "Marrom", "Creme"],
         frase="Toque quentinho e acolhedor, para as noites mais frias."),
    dict(id="gamer", nome="Tech gamer neon", paleta="preto, roxo, ciano (RGB)",
         materiais="plástico, alumínio", vibe="futurista", ocasiao="setup de jogos e escritório gamer",
         cores=["Preto", "Roxo", "Ciano"],
         frase="Visual futurista com iluminação e detalhes em estilo gamer."),
    dict(id="rustico", nome="Rústico campo", paleta="verde-musgo, madeira escura, vermelho",
         materiais="madeira de demolição, juta", vibe="outdoor e acolhedora", ocasiao="sítio, chalé e varanda de campo",
         cores=["Verde-musgo", "Madeira escura", "Vermelho"],
         frase="Materiais naturais e cara de campo, para um clima de chalé e varanda."),
    dict(id="retro", nome="Retrô anos 70/80", paleta="mostarda, laranja, verde-água",
         materiais="veludo cotelê, vinil", vibe="nostálgica", ocasiao="sala vintage e festas temáticas",
         cores=["Mostarda", "Laranja", "Verde-água"],
         frase="Estética dos anos 70 e 80 com cores vibrantes e toque nostálgico."),
    dict(id="festa", nome="Festa e noite", paleta="preto, prata, champanhe",
         materiais="cetim, paetê", vibe="glamourosa", ocasiao="festas, casamentos e noites especiais",
         cores=["Preto", "Prata", "Champanhe"],
         frase="Brilho e sofisticação para noites especiais e celebrações."),
    dict(id="natural", nome="Natural e bem-estar", paleta="verde-sálvia, branco, bambu",
         materiais="bambu, cerâmica, algodão orgânico", vibe="calma e leve", ocasiao="spa em casa, meditação e cozinha",
         cores=["Verde-sálvia", "Branco", "Bambu"],
         frase="Materiais orgânicos e tons suaves, para um ambiente calmo e de bem-estar."),
]
CORES = {"Branco": "#FFFFFF", "Cinza claro": "#D9D9D9", "Madeira clara": "#D9B98C", "Bege": "#E8D9BF",
         "Preto": "#141414", "Grafite": "#3A3D42", "Cobre": "#B87333", "Terracota": "#C2643F",
         "Mostarda": "#D9A21B", "Off-white": "#F5F0E6", "Azul-marinho": "#1F2A44", "Dourado": "#C9A227",
         "Vinho": "#6D1F2F", "Verde-neon": "#39FF14", "Azul-elétrico": "#0057FF", "Verde-lima": "#C6F432",
         "Turquesa": "#1FB5B0", "Coral": "#FF7F6E", "Marrom": "#6B4226", "Creme": "#F3E9D2", "Roxo": "#9D4EDD",
         "Ciano": "#00F0FF", "Verde-musgo": "#4B5D3A", "Madeira escura": "#4A2F1B", "Vermelho": "#B23A2E",
         "Laranja": "#E8702A", "Verde-água": "#5FC9B4", "Prata": "#C0C0C0", "Champanhe": "#F7E7CE",
         "Verde-sálvia": "#9CAF88", "Bambu": "#C8A96A"}
ESTILO_BY = {e["id"]: e for e in ESTILOS}
ESTILO_IDS = [e["id"] for e in ESTILOS]

pdf_estilos = pd.DataFrame([{
    "estilo_id": e["id"], "nome": e["nome"],
    "descricao": f"{e['vibe'][0].upper() + e['vibe'][1:]}. {e['frase']}",
    "paleta": e["paleta"], "materiais": e["materiais"], "ocasiao": e["ocasiao"],
    "cores": ",".join(CORES[c] for c in e["cores"][:3]), "ordem": i + 1}
    for i, e in enumerate(ESTILOS)])
gravar(pdf_estilos, "estilos", "Estilos de decoracao e moda da BrickStore (paleta, materiais, ocasiao e cores).")
chave_pk("estilos", "estilo_id", "pk_estilos")
print(f"✅ estilos: {len(pdf_estilos)}")


# ## 2) Produtos (60 tipos, 6 departamentos)


def tp(tipo, dep, sub, icone, bases, atribs, mats, preco, tam, estilos, usos, specs, nome_mat=True):
    return dict(tipo=tipo, dep=dep, sub=sub, icone=icone, bases=bases, atribs=atribs, mats=mats,
                preco=preco, tam=tam, estilos=estilos, usos=usos, specs=specs, nome_mat=nome_mat)


MODA, CASA, COZ, ELET, ESP, BELEZA = "Moda", "Casa & Decoração", "Cozinha", "Eletrônicos", "Esporte & Lazer", "Beleza"
TIPOS = [
    # ---------------- Moda ----------------
    tp("Camiseta", MODA, "Camisetas", "top", ["Camiseta", "Camiseta Básica", "Camiseta Oversized"], [""],
       ["Algodão", "Algodão orgânico", "Malha"], (39, 129), "P, M, G, GG",
       ["streetwear", "esportivo", "verao", "natural", "escandinavo", "boho", "retro"],
       ["para o dia a dia", "para looks casuais", "para viagens"],
       [("Composição", ["100% algodão", "95% algodão e 5% elastano", "100% algodão orgânico"]),
        ("Gramatura", ["160 g/m²", "180 g/m²", "200 g/m²"]),
        ("Lavagem", ["lavar à mão ou máquina fria", "lavar na máquina a 30°C"])]),
    tp("Camisa", MODA, "Camisas", "top", ["Camisa Social", "Camisa de Linho", "Camisa Slim"], [""],
       ["Linho", "Algodão", "Viscose"], (99, 279), "P, M, G, GG",
       ["classico", "escandinavo", "verao", "festa", "retro"],
       ["para o trabalho", "para jantares", "para ocasiões especiais"],
       [("Composição", ["100% algodão", "55% linho e 45% viscose", "100% viscose"]),
        ("Manga", ["longa", "curta"]), ("Passadoria", ["fácil de passar"])]),
    tp("Moletom", MODA, "Moletons", "top", ["Moletom Canguru", "Moletom Básico", "Moletom Oversized"], [""],
       ["Moletom de algodão", "Flanela", "Moletom felpado"], (119, 249), "P, M, G, GG",
       ["streetwear", "inverno", "gamer", "rustico", "esportivo", "industrial"],
       ["para dias frios", "para o fim de semana", "para treinos leves"],
       [("Composição", ["80% algodão e 20% poliéster", "100% algodão"]),
        ("Gramatura", ["320 g/m²", "400 g/m²"]), ("Capuz", ["sim, com cordão", "sim, forrado"])]),
    tp("Jaqueta", MODA, "Jaquetas", "jaqueta", ["Jaqueta Jeans", "Jaqueta Corta-Vento", "Jaqueta Couro Sintético", "Jaqueta Bomber"],
       [""], ["Jeans", "Nylon", "Couro sintético", "Algodão"], (179, 499), "P, M, G, GG",
       ["streetwear", "industrial", "esportivo", "inverno", "retro", "rustico", "classico"],
       ["para dias frios", "para pedalar na cidade", "para looks urbanos"],
       [("Composição", ["100% algodão", "100% nylon", "poliéster e elastano"]),
        ("Forro", ["sem forro", "forro de malha"]), ("Impermeável", ["resistente à garoa", "não"])]),
    tp("Vestido", MODA, "Vestidos", "vestido", ["Vestido Midi", "Vestido Floral", "Vestido Longo", "Vestido Curto"],
       [""], ["Linho", "Viscose", "Crepe", "Algodão"], (129, 399), "P, M, G, GG",
       ["verao", "boho", "classico", "festa", "retro", "natural", "escandinavo"],
       ["para o verão", "para festas", "para um brunch"],
       [("Composição", ["100% viscose", "100% linho", "95% algodão e 5% elastano"]),
        ("Comprimento", ["midi", "longo", "curto"]), ("Forro", ["sim", "não"])]),
    tp("Calça jeans", MODA, "Calças", "calca", ["Calça Jeans Reta", "Calça Jeans Skinny", "Calça Jeans Wide Leg"], [""],
       ["Jeans", "Denim"], (149, 329), "36–46",
       ["streetwear", "industrial", "retro", "escandinavo", "classico", "rustico"],
       ["para o dia a dia", "para o trabalho", "para o fim de semana"],
       [("Composição", ["98% algodão e 2% elastano", "100% algodão"]),
        ("Cintura", ["alta", "média"]), ("Lavagem", ["escura", "clara", "estonada"])]),
    tp("Bermuda", MODA, "Bermudas", "calca", ["Bermuda Sarja", "Bermuda Moletom", "Bermuda Linho"], [""],
       ["Sarja", "Linho", "Moletom"], (79, 189), "P, M, G, GG",
       ["verao", "esportivo", "streetwear", "natural", "boho"],
       ["para a praia", "para o calor", "para o fim de semana"],
       [("Composição", ["100% algodão", "100% linho", "80% algodão e 20% poliéster"]),
        ("Bolsos", ["2 laterais e 1 traseiro", "com cordão"])]),
    tp("Tênis casual", MODA, "Calçados", "tenis", ["Tênis Casual Couro", "Tênis Canvas", "Tênis Plataforma"], [""],
       ["Couro", "Lona", "Couro vegano"], (149, 399), "35–44",
       ["streetwear", "escandinavo", "industrial", "natural", "retro", "classico", "verao"],
       ["para o dia a dia", "para caminhar na cidade", "para looks casuais"],
       [("Solado", ["borracha", "EVA"]), ("Fechamento", ["cadarço", "elástico"]),
        ("Peso", ["320 g por par", "280 g por par"])]),
    tp("Bota", MODA, "Calçados", "bota", ["Bota Coturno", "Bota Cano Curto", "Bota Chelsea"], [""],
       ["Couro", "Camurça", "Couro sintético"], (219, 499), "35–44",
       ["industrial", "rustico", "inverno", "classico", "streetwear", "boho"],
       ["para dias frios", "para o trabalho", "para trilhas urbanas"],
       [("Cano", ["curto", "médio"]), ("Salto", ["baixo de 3 cm", "plano"]), ("Forro", ["de lã", "de malha"])]),
    tp("Sandália", MODA, "Calçados", "sandalia", ["Sandália Rasteira", "Sandália de Tiras", "Sandália Anabela"], [""],
       ["Couro", "Palha", "Borracha"], (49, 189), "35–44",
       ["verao", "boho", "natural", "classico", "retro"],
       ["para a praia", "para o verão", "para passeios"],
       [("Solado", ["borracha antiderrapante", "EVA leve"]), ("Fechamento", ["tiras ajustáveis", "fivela"])]),
    tp("Bolsa", MODA, "Bolsas", "bolsa", ["Bolsa Transversal", "Bolsa Tote", "Bolsa Baguette"], [""],
       ["Couro", "Palha", "Couro vegano", "Lona"], (129, 499), None,
       ["classico", "boho", "verao", "festa", "industrial", "streetwear", "natural", "retro"],
       ["para o trabalho", "para o passeio", "para festas"],
       [("Dimensões", ["25 x 18 x 8 cm", "30 x 22 x 10 cm"]), ("Alça", ["regulável", "corrente"]),
        ("Fechamento", ["zíper", "imã"])]),
    tp("Mochila", MODA, "Mochilas", "mochila", ["Mochila Urbana", "Mochila para Notebook", "Mochila de Couro"], [""],
       ["Couro", "Nylon", "Lona"], (119, 359), None,
       ["streetwear", "industrial", "escandinavo", "esportivo", "gamer"],
       ["para a faculdade", "para o trabalho", "para levar o notebook"],
       [("Capacidade", ["18 L", "22 L", "28 L"]), ("Compartimento", ["para notebook de até 15,6 pol", "para tablet"]),
        ("Impermeável", ["resistente à chuva", "não"])]),
    tp("Óculos de sol", MODA, "Acessórios", "oculos", ["Óculos de Sol Aviador", "Óculos de Sol Redondo", "Óculos de Sol Quadrado"],
       [""], ["Acetato", "Metal", "TR90"], (89, 349), None,
       ["verao", "classico", "retro", "streetwear", "festa", "esportivo"],
       ["para a praia", "para dirigir", "para o dia a dia"],
       [("Proteção", ["UV400", "UV400 com polarização"]), ("Lente", ["cinza", "marrom", "espelhada"]),
        ("Estojo", ["incluso", "não incluso"])]),
    tp("Relógio", MODA, "Acessórios", "relogio", ["Relógio Analógico", "Relógio Minimalista", "Relógio Cronógrafo"], [""],
       ["Aço inoxidável", "Couro", "Aço"], (129, 599), None,
       ["classico", "escandinavo", "industrial", "festa", "streetwear", "esportivo"],
       ["para o trabalho", "para ocasiões especiais", "para o dia a dia"],
       [("Diâmetro", ["36 mm", "40 mm", "42 mm"]), ("Movimento", ["quartzo", "automático"]),
        ("Resistência à água", ["3 ATM", "5 ATM"])]),
    tp("Boné", MODA, "Acessórios", "bone", ["Boné Aba Curva", "Boné Trucker", "Boné Aba Reta"], [""],
       ["Algodão", "Sarja", "Nylon"], (49, 139), None,
       ["streetwear", "esportivo", "rustico", "retro", "verao"],
       ["para o sol", "para o dia a dia", "para jogos e passeios"],
       [("Ajuste", ["strapback", "snapback", "fechado"]), ("Proteção", ["UV", "sem proteção UV"])]),
    # ---------------- Casa & Decoração ----------------
    tp("Sofá", CASA, "Sofás e poltronas", "sofa", ["Sofá Retrátil", "Sofá Cama", "Sofá Modular", "Sofá Reclinável"],
       ["2 Lugares", "3 Lugares", "4 Lugares"], ["Linho", "Veludo", "Couro", "Suede"], (1190, 4590), None,
       ["escandinavo", "industrial", "boho", "classico", "retro", "rustico", "verao", "festa"],
       ["para a sala de estar", "para assistir filmes", "para receber visitas"],
       [("Dimensões", ["200 x 85 x 80 cm", "220 x 90 x 85 cm", "240 x 95 x 88 cm"]),
        ("Estrutura", ["madeira maciça", "MDF e pinus", "metal reforçado"]),
        ("Assento", ["espuma D28", "molas ensacadas", "retrátil"]),
        ("Garantia", ["12 meses", "24 meses"])]),
    tp("Poltrona", CASA, "Sofás e poltronas", "poltrona", ["Poltrona Decorativa", "Poltrona de Leitura", "Poltrona Balanço", "Poltrona Lounge"],
       [""], ["Veludo", "Linho", "Couro", "Palha"], (699, 2490), None,
       ["escandinavo", "classico", "boho", "retro", "rustico", "industrial", "festa"],
       ["para o canto de leitura", "para o escritório de casa", "para a varanda"],
       [("Dimensões", ["70 x 78 x 90 cm", "80 x 85 x 95 cm"]), ("Estrutura", ["madeira de demolição", "aço carbono", "madeira maciça"]),
        ("Carga máxima", ["120 kg", "150 kg"])]),
    tp("Mesa de centro", CASA, "Mesas", "mesa", ["Mesa de Centro Redonda", "Mesa de Centro Retangular", "Mesa de Centro Madeira"],
       [""], ["Madeira maciça", "Carvalho", "Mármore", "MDF"], (359, 1890), None,
       ["escandinavo", "industrial", "classico", "boho", "rustico", "retro", "natural"],
       ["para a sala de estar", "para o centro da sala"],
       [("Dimensões", ["90 x 45 cm", "100 x 40 cm", "80 x 50 cm"]), ("Tampo", ["vidro temperado", "madeira maciça", "mármore sintético"]),
        ("Pés", ["madeira", "metálicos"])]),
    tp("Luminária", CASA, "Iluminação", "luminaria", ["Luminária de Mesa", "Luminária de Piso", "Luminária Pendente", "Abajur"],
       [""], ["Metal", "Cerâmica", "Linho", "Bambu", "Vidro"], (119, 699), None,
       ["escandinavo", "industrial", "boho", "classico", "retro", "natural", "festa"],
       ["para leitura", "para criar um clima aconchegante", "para a sala"],
       [("Potência", ["E27 até 60 W", "LED 9 W", "LED 12 W"]), ("Altura", ["45 cm", "120 cm", "150 cm"]),
        ("Acabamento", ["fosco", "dourado", "preto"]), ("Voltagem", ["bivolt"])]),
    tp("Tapete", CASA, "Tapetes", "tapete", ["Tapete Trançado", "Tapete Shaggy", "Tapete Redondo", "Tapete Kilim"],
       [""], ["Algodão", "Juta", "Lã", "Poliéster"], (149, 899), None,
       ["escandinavo", "boho", "rustico", "retro", "classico", "natural", "inverno"],
       ["para a sala", "para o quarto", "para a entrada"],
       [("Dimensões", ["150 x 200 cm", "200 x 250 cm", "Ø 120 cm"]), ("Pelo", ["baixo", "alto (shaggy)"]),
        ("Lavável", ["sim, à mão", "sim, na máquina"])]),
    tp("Almofada", CASA, "Têxteis decorativos", "almofada", ["Almofada Decorativa", "Almofada de Linho", "Capa de Almofada Bordada"],
       [""], ["Linho", "Algodão", "Veludo", "Lã"], (39, 139), None,
       ["escandinavo", "boho", "classico", "retro", "inverno", "natural", "verao", "festa", "rustico"],
       ["para o sofá", "para a cama", "para a poltrona"],
       [("Dimensões", ["45 x 45 cm", "50 x 30 cm"]), ("Enchimento", ["fibra siliconada", "pena sintética"]),
        ("Capa", ["lavável", "removível com zíper"])]),
    tp("Cortina", CASA, "Têxteis decorativos", "tecido", ["Cortina Blackout", "Cortina de Linho", "Cortina Voile"],
       [""], ["Linho", "Voile", "Blackout", "Algodão"], (99, 449), None,
       ["escandinavo", "boho", "natural", "classico", "verao", "rustico", "retro"],
       ["para a sala", "para o quarto", "para deixar a luz suave"],
       [("Dimensões", ["2,00 x 2,50 m", "3,00 x 2,60 m"]), ("Fixação", ["ilhós metálicos", "varão com passa-fio"]),
        ("Proteção UV", ["sim", "parcial"])]),
    tp("Jogo de cama", CASA, "Roupas de cama", "tecido", ["Jogo de Cama Casal", "Jogo de Cama Queen", "Jogo de Cama Solteiro"],
       [""], ["Percal", "Algodão egípcio", "Linho", "Microfibra"], (179, 549), None,
       ["escandinavo", "boho", "natural", "classico", "verao", "inverno", "retro"],
       ["para o quarto", "para um quarto aconchegante"],
       [("Fio", ["200 fios", "300 fios", "400 fios"]), ("Composição", ["100% algodão", "50% linho e 50% algodão", "microfibra"]),
        ("Inclui", ["lençol, fronha e edredom", "lençol com elástico e 2 fronhas"])]),
    tp("Manta", CASA, "Têxteis decorativos", "tecido", ["Manta de Tricô", "Manta de Lã", "Manta Macia", "Manta Xadrez"],
       [""], ["Lã", "Acrílico", "Algodão", "Flanela"], (89, 299), None,
       ["inverno", "escandinavo", "boho", "rustico", "retro", "natural", "classico"],
       ["para o sofá nas noites frias", "para a cama", "para o piquenique"],
       [("Dimensões", ["1,30 x 1,50 m", "1,80 x 2,20 m"]), ("Composição", ["90% acrílico e 10% lã", "100% algodão"]),
        ("Lavagem", ["máquina fria"])]),
    tp("Vaso decorativo", CASA, "Decoração", "vaso", ["Vaso Decorativo", "Vaso de Cerâmica", "Vaso Canelado"],
       [""], ["Cerâmica", "Vidro", "Concreto", "Terracota"], (49, 259), None,
       ["escandinavo", "boho", "industrial", "natural", "retro", "classico"],
       ["para a sala", "para a estante", "para a mesa de jantar"],
       [("Altura", ["20 cm", "35 cm", "45 cm"]), ("Acabamento", ["esmaltado", "fosco", "texturizado"]),
        ("Capacidade", ["1 L", "2 L"])]),
    tp("Quadro", CASA, "Decoração", "quadro", ["Quadro Decorativo", "Quadro Minimalista", "Kit 3 Quadros", "Quadro em Tela"],
       [""], ["Madeira", "Tela canvas", "MDF", "Metal"], (79, 389), None,
       ["escandinavo", "industrial", "classico", "retro", "boho", "festa", "natural", "streetwear"],
       ["para a parede da sala", "para o quarto", "para o escritório"],
       [("Dimensões", ["40 x 60 cm", "60 x 90 cm", "30 x 40 cm"]), ("Moldura", ["madeira natural", "preta", "dourada"]),
        ("Fixação", ["ganchos inclusos"])]),
    tp("Prateleira", CASA, "Organização", "prateleira", ["Prateleira Flutuante", "Estante Modular", "Prateleira de Parede"],
       [""], ["Madeira", "MDF", "Metal", "Carvalho"], (89, 599), None,
       ["escandinavo", "industrial", "rustico", "boho", "natural", "retro"],
       ["para a sala", "para o escritório", "para a cozinha"],
       [("Dimensões", ["60 x 20 cm", "90 x 25 cm", "120 x 30 cm"]), ("Capacidade", ["até 10 kg por prateleira", "até 15 kg"]),
        ("Fixação", ["buchas e parafusos inclusos"])]),
    tp("Planta artificial", CASA, "Decoração", "planta", ["Planta Artificial Costela", "Samambaia Artificial", "Figueira Artificial", "Suculenta Artificial"],
       [""], ["Poliéster", "Plástico", "Látex"], (59, 299), None,
       ["escandinavo", "natural", "boho", "industrial", "verao", "classico"],
       ["para cantos sem luz natural", "para o escritório", "para a varanda"],
       [("Altura", ["60 cm", "90 cm", "120 cm"]), ("Vaso incluso", ["sim, cerâmica", "não"]),
        ("Manutenção", ["não precisa de rega"])]),
    # ---------------- Cozinha ----------------
    tp("Jogo de panelas", COZ, "Panelas e utensílios", "panela", ["Jogo de Panelas Antiaderente", "Jogo de Panelas Inox", "Jogo de Panelas Cerâmica"],
       [""], ["Alumínio", "Aço inox", "Cerâmica"], (229, 899), None,
       ["industrial", "escandinavo", "natural", "classico", "rustico", "retro"],
       ["para o dia a dia", "para receber em casa", "para cozinhar em família"],
       [("Peças", ["5 peças", "7 peças", "10 peças"]), ("Revestimento", ["antiaderente de cerâmica", "antiaderente PTFE", "inox 3 camadas"]),
        ("Compatível", ["indução, gás e elétrico", "gás e elétrico"])]),
    tp("Cafeteira", COZ, "Cafés e bebidas", "cafeteira", ["Cafeteira Elétrica", "Cafeteira Italiana", "Cafeteira de Filtro", "Cafeteira Espresso"],
       [""], ["Aço inox", "Alumínio", "Plástico", "Vidro"], (79, 999), None,
       ["escandinavo", "industrial", "retro", "inverno", "natural", "classico", "festa"],
       ["para o café da manhã", "para o escritório", "para receber visitas"],
       [("Capacidade", ["500 ml", "1,2 L", "15 xícaras"]), ("Potência", ["800 W", "1450 W"]),
        ("Desligamento automático", ["sim"]), ("Voltagem", ["bivolt"])]),
    tp("Jogo de pratos", COZ, "Mesa posta", "pratos", ["Jogo de Pratos de Porcelana", "Jogo de Pratos Cerâmica", "Aparelho de Jantar 12 Peças"],
       [""], ["Porcelana", "Cerâmica", "Grés", "Vidro"], (119, 459), None,
       ["escandinavo", "classico", "boho", "natural", "retro", "festa", "rustico"],
       ["para o jantar em família", "para jantares formais", "para o café"],
       [("Peças", ["4 pratos rasos e 4 fundos", "12 peças", "18 peças"]), ("Material", ["porcelana", "grés"]),
        ("Lavável", ["lava-louças e micro-ondas"])]),
    tp("Liquidificador", COZ, "Eletroportáteis", "eletro", ["Liquidificador Potente", "Liquidificador Inox", "Liquidificador Compacto"],
       [""], ["Aço inox", "Plástico", "Vidro"], (179, 549), None,
       ["industrial", "escandinavo", "natural", "retro", "esportivo", "streetwear"],
       ["para vitaminas", "para molhos", "para o café da manhã"],
       [("Potência", ["600 W", "1000 W", "1200 W"]), ("Velocidades", ["3 velocidades e pulsar", "5 velocidades"]),
        ("Capacidade", ["1,5 L", "2 L"])]),
    tp("Air fryer", COZ, "Eletroportáteis", "eletro", ["Air Fryer 4 Litros", "Air Fryer Digital", "Air Fryer Compacta"],
       [""], ["Aço inox", "Plástico", "Vidro"], (279, 899), None,
       ["industrial", "escandinavo", "streetwear", "gamer", "natural", "retro"],
       ["para fritar com pouco óleo", "para receitas rápidas", "para a família"],
       [("Capacidade", ["4 L", "5,5 L", "3 L"]), ("Potência", ["1500 W", "1700 W"]),
        ("Programas", ["8 programas", "12 programas", "funções manuais"])]),
    tp("Caneca", COZ, "Cafés e bebidas", "caneca", ["Caneca de Cerâmica", "Caneca Esmaltada", "Caneca Térmica", "Caneca com Tampa"],
       [""], ["Cerâmica", "Porcelana", "Aço inox", "Vidro"], (29, 119), None,
       ["escandinavo", "boho", "natural", "retro", "streetwear", "gamer", "inverno", "verao", "classico"],
       ["para o café da manhã", "para o escritório", "para o chá da tarde"],
       [("Capacidade", ["300 ml", "350 ml", "500 ml"]), ("Micro-ondas", ["sim", "não"]), ("Lavagem", ["lava-louças"])]),
    # ---------------- Eletrônicos ----------------
    tp("Smart TV", ELET, "TVs e monitores", "tv", ["Smart TV LED 43 pol", "Smart TV 4K 55 pol", "Smart TV QLED 65 pol", "Smart TV 50 pol"],
       [""], ["Plástico e metal"], (1499, 5999), None,
       ["gamer", "industrial", "escandinavo", "festa", "streetwear", "classico"],
       ["para a sala", "para assistir filmes e jogos", "para o quarto"],
       [("Resolução", ["4K UHD", "Full HD", "8K"]), ("Taxa de atualização", ["60 Hz", "120 Hz"]),
        ("Conectividade", ["HDMI x3, USB x2, Wi-Fi e Bluetooth"]), ("Sistema", ["Android TV", "sistema com apps de streaming"])],
       nome_mat=False),
    tp("Monitor", ELET, "TVs e monitores", "tv", ["Monitor Gamer 27 pol", "Monitor 24 pol Full HD", "Monitor Ultrawide 34 pol", "Monitor 4K 32 pol"],
       [""], ["Plástico e metal"], (649, 2499), None,
       ["gamer", "industrial", "escandinavo", "streetwear", "classico", "natural"],
       ["para o home office", "para jogos competitivos", "para edição de fotos"],
       [("Painel", ["IPS", "VA", "OLED"]), ("Taxa de atualização", ["75 Hz", "144 Hz", "165 Hz"]),
        ("Resolução", ["Full HD", "QHD", "4K"])],
       nome_mat=False),
    tp("Fone de ouvido", ELET, "Áudio", "fone", ["Fone de Ouvido Bluetooth", "Fone de Ouvido com Fio", "Fone Intra-auricular", "Fone True Wireless"],
       [""], ["Plástico", "Alumínio", "Borracha"], (79, 899), None,
       ["streetwear", "esportivo", "gamer", "industrial", "verao", "natural", "festa"],
       ["para ouvir música no treino", "para ligações", "para viagens"],
       [("Conexão", ["Bluetooth 5.3", "com fio P2", "USB-C"]), ("Autonomia", ["6 h", "30 h com estojo", "8 h"]),
        ("Cancelamento de ruído", ["sim", "não"]), ("Resistência", ["IPX4"])],
       nome_mat=False),
    tp("Headset gamer", ELET, "Áudio", "fone", ["Headset Gamer Surround", "Headset Gamer RGB", "Headset Gamer sem Fio"],
       [""], ["Plástico e espuma", "Couro sintético", "Alumínio"], (149, 799), None,
       ["gamer", "streetwear", "esportivo", "industrial"],
       ["para jogos online", "para lives e chamadas", "para maratonas de jogos"],
       [("Driver", ["50 mm", "40 mm"]), ("Conexão", ["USB e P2", "sem fio 2.4 GHz"]),
        ("Microfone", ["removível com cancelamento de ruído"]), ("Iluminação", ["RGB"])],
       nome_mat=False),
    tp("Caixa de som", ELET, "Áudio", "caixasom", ["Caixa de Som Bluetooth", "Caixa de Som Portátil Resistente à Água", "Soundbar 2.1", "Caixa de Som com Graves"],
       [""], ["Tecido e plástico", "Alumínio", "Madeira"], (99, 1299), None,
       ["gamer", "esportivo", "verao", "retro", "natural", "escandinavo", "industrial", "festa"],
       ["para a praia", "para a festa no quintal", "para a sala"],
       [("Potência", ["20 W RMS", "40 W RMS", "60 W RMS"]), ("Bateria", ["12 h", "18 h"]),
        ("Conexão", ["Bluetooth 5.0 e AUX"]), ("Resistência", ["IP67", "IPX5"])],
       nome_mat=False),
    tp("Smartphone", ELET, "Celulares e wearables", "celular", ["Smartphone 128 GB", "Smartphone 256 GB", "Smartphone 512 GB"],
       [""], ["Alumínio", "Vidro e alumínio", "Policarbonato"], (899, 4999), None,
       ["gamer", "streetwear", "industrial", "esportivo", "classico", "verao", "escandinavo"],
       ["para fotos e vídeos", "para o trabalho", "para jogos e redes sociais"],
       [("Tela", ["6,1 pol OLED", "6,7 pol AMOLED", "6,5 pol LCD"]), ("Memória", ["8 GB RAM", "12 GB RAM"]),
        ("Câmera", ["50 MP", "108 MP"]), ("Bateria", ["5000 mAh", "4500 mAh"])],
       nome_mat=False),
    tp("Notebook", ELET, "Computadores", "notebook", ["Notebook Ultrafino 14 pol", "Notebook 15,6 pol", "Notebook Creator", "Notebook Gamer 16 pol"],
       [""], ["Alumínio", "Plástico", "Magnésio"], (2199, 7999), None,
       ["industrial", "escandinavo", "streetwear", "gamer", "classico", "festa", "esportivo"],
       ["para o trabalho remoto", "para estudar", "para jogos e edição"],
       [("Processador", ["Intel Core i5", "AMD Ryzen 7", "Intel Core i7"]), ("Memória", ["8 GB", "16 GB", "32 GB"]),
        ("SSD", ["256 GB", "512 GB", "1 TB"]), ("Tela", ["Full HD IPS", "2.5K 120 Hz"])],
       nome_mat=False),
    tp("Teclado mecânico", ELET, "Periféricos", "teclado", ["Teclado Mecânico Gamer", "Teclado Mecânico 60%", "Teclado Mecânico Compacto", "Teclado Mecânico RGB"],
       [""], ["Alumínio", "Plástico ABS", "Policarbonato"], (199, 699), None,
       ["gamer", "industrial", "streetwear", "retro", "escandinavo", "classico"],
       ["para programar", "para jogos competitivos", "para escrever"],
       [("Switch", ["vermelho linear", "marrom tátil", "azul clicky"]), ("Layout", ["ABNT2", "ANSI", "60%"]),
        ("Conexão", ["USB-C", "sem fio Bluetooth"]), ("Iluminação", ["RGB", "monocromática"])],
       nome_mat=False),
    tp("Mouse gamer", ELET, "Periféricos", "mouse", ["Mouse Gamer Sem Fio", "Mouse Gamer RGB", "Mouse Ergonômico", "Mouse Gamer Leve"],
       [""], ["Plástico", "Borracha"], (79, 399), None,
       ["gamer", "industrial", "streetwear", "escandinavo", "esportivo"],
       ["para jogos competitivos", "para o trabalho no computador", "para edição de imagens"],
       [("DPI", ["16000 DPI", "8000 DPI", "3200 DPI"]), ("Peso", ["58 g", "72 g", "95 g"]),
        ("Botões", ["6 botões", "8 botões"]), ("Conexão", ["USB 2.4 GHz", "Bluetooth e USB"])],
       nome_mat=False),
    tp("Console", ELET, "Games", "console", ["Console de Videogame 1 TB", "Console 512 GB", "Console Digital Edition"],
       [""], ["Plástico", "Alumínio"], (2499, 4999), None,
       ["gamer", "streetwear", "industrial", "festa", "esportivo"],
       ["para jogar com amigos", "para jogos em 4K", "para a sala"],
       [("Armazenamento", ["1 TB", "825 GB", "512 GB"]), ("Resolução", ["até 4K", "até 8K"]),
        ("Controle incluso", ["1 controle sem fio"]), ("Garantia", ["12 meses"])],
       nome_mat=False),
    tp("Smartwatch", ELET, "Celulares e wearables", "relogio", ["Smartwatch Esportivo", "Smartwatch com Monitor Cardíaco", "Smartwatch Tela AMOLED", "Smartwatch Premium"],
       [""], ["Alumínio", "Silicone", "Aço inox"], (249, 1499), None,
       ["esportivo", "gamer", "streetwear", "classico", "escandinavo", "verao", "industrial"],
       ["para treinos", "para o dia a dia", "para viagens"],
       [("Tela", ["1,4 pol AMOLED", "1,9 pol"]), ("Bateria", ["7 dias", "14 dias"]),
        ("Sensores", ["frequência cardíaca, oxigênio e GPS"]), ("Resistência", ["5 ATM"])],
       nome_mat=False),
    tp("Fita LED", ELET, "Iluminação", "led", ["Fita LED RGB 5 m", "Fita LED Smart 10 m", "Fita LED Branca Quente 5 m"],
       [""], ["Silicone", "PVC", "Alumínio"], (39, 249), None,
       ["gamer", "festa", "retro", "streetwear", "inverno", "industrial"],
       ["atrás da TV", "para o setup gamer", "para a festa"],
       [("Comprimento", ["5 m", "10 m"]), ("Controle", ["controle remoto e app", "app com música"]),
        ("Potência", ["12 W", "24 W"])],
       nome_mat=False),
    tp("Cadeira gamer", ELET, "Cadeiras", "cadeira", ["Cadeira Gamer Reclinável", "Cadeira Gamer Ergonômica", "Cadeira Gamer Couro Sintético", "Cadeira Escritório Ergonômica"],
       [""], ["Couro sintético", "Tecido respirável", "Nylon"], (599, 1899), None,
       ["gamer", "industrial", "streetwear", "escandinavo", "classico"],
       ["para jogar por horas", "para o home office", "para o setup gamer"],
       [("Carga máxima", ["120 kg", "150 kg"]), ("Inclinação", ["até 180 graus", "até 135 graus"]),
        ("Apoio lombar", ["sim, ajustável"]), ("Garantia", ["24 meses"])],
       nome_mat=False),
    # ---------------- Esporte & Lazer ----------------
    tp("Tênis de corrida", ESP, "Corrida", "tenis", ["Tênis de Corrida Amortecido", "Tênis de Corrida Leve", "Tênis de Corrida Trail", "Tênis de Corrida Performance"],
       [""], ["Mesh", "Tecido tech", "Borracha"], (249, 899), "35–44",
       ["esportivo", "streetwear", "verao", "gamer", "industrial"],
       ["para corridas de rua", "para treinos intervalados", "para caminhadas"],
       [("Drop", ["8 mm", "10 mm", "4 mm"]), ("Peso", ["240 g", "270 g", "300 g"]),
        ("Solado", ["EVA com placa de carbono", "borracha de alta aderência"]), ("Uso", ["asfalto", "trilha leve"])]),
    tp("Legging", ESP, "Treino", "calca", ["Legging Cintura Alta", "Legging de Compressão", "Legging Estampada"],
       [""], ["Poliamida", "Tecido tech", "Suplex"], (89, 249), "P, M, G, GG",
       ["esportivo", "streetwear", "verao", "natural", "gamer", "retro"],
       ["para a academia", "para yoga", "para correr"],
       [("Composição", ["80% poliamida e 20% elastano", "88% poliéster e 12% elastano"]),
        ("Cintura", ["alta com bolso", "média"]), ("Secagem", ["rápida"])]),
    tp("Garrafa térmica", ESP, "Hidratação", "garrafa", ["Garrafa Térmica 500 ml", "Garrafa Térmica 1 L", "Garrafa Térmica Esportiva"],
       [""], ["Aço inox", "Tritan", "Alumínio"], (59, 219), None,
       ["esportivo", "natural", "verao", "industrial", "boho", "gamer", "retro", "streetwear"],
       ["para o treino", "para a praia", "para o escritório"],
       [("Capacidade", ["500 ml", "750 ml", "1 L"]), ("Isolamento", ["até 12 h quente e 24 h frio"]),
        ("Tampa", ["bico com trava", "rosca antivazamento"])]),
    tp("Bicicleta", ESP, "Ciclismo", "bike", ["Bicicleta Aro 29", "Bicicleta Urbana Aro 26", "Bicicleta Speed 21 marchas", "Bicicleta Dobrável Aro 20"],
       [""], ["Alumínio", "Aço carbono"], (1199, 4999), None,
       ["esportivo", "industrial", "retro", "verao", "streetwear", "natural"],
       ["para pedalar na cidade", "para trilhas leves", "para o fim de semana"],
       [("Quadro", ["alumínio 6061", "aço carbono"]), ("Marchas", ["7 marchas", "21 marchas", "1 marcha"]),
        ("Freios", ["a disco mecânico", "V-brake"]), ("Peso", ["12 kg", "14,5 kg"])]),
    tp("Barraca", ESP, "Camping", "barraca", ["Barraca de Camping 2 Pessoas", "Barraca Iglu 4 Pessoas", "Barraca Túnel 6 Pessoas", "Barraca Impermeável 3 Pessoas"],
       [""], ["Poliéster", "Nylon ripstop", "Alumínio"], (249, 1299), None,
       ["rustico", "natural", "verao", "esportivo", "industrial"],
       ["para acampar na serra", "para a praia", "para festivais"],
       [("Capacidade", ["2 pessoas", "4 pessoas", "6 pessoas"]), ("Coluna de água", ["3000 mm", "2000 mm"]),
        ("Peso", ["2,1 kg", "3,8 kg"]), ("Montagem", ["sem ferramentas, em 5 min"])]),
    tp("Mochila de trilha", ESP, "Camping", "mochila", ["Mochila de Trilha 40 L", "Mochila de Trilha 60 L", "Mochila de Trilha Cargueira 70 L"],
       [""], ["Nylon", "Poliéster ripstop"], (279, 899), None,
       ["rustico", "esportivo", "natural", "verao", "industrial", "streetwear"],
       ["para trilhas de vários dias", "para bate-volta", "para acampamentos"],
       [("Capacidade", ["40 L", "60 L", "70 L"]), ("Peso", ["1,2 kg", "1,8 kg"]),
        ("Suporte", ["alças acolchoadas e cinto de quadril"]), ("Impermeável", ["capa de chuva inclusa"])]),
    tp("Halteres", ESP, "Musculação", "halter", ["Par de Halteres Emborrachados", "Haltere Ajustável 20 kg", "Par de Halteres de Neoprene", "Kit Halteres 10 kg"],
       [""], ["Borracha", "Ferro fundido", "Neoprene"], (79, 899), None,
       ["esportivo", "industrial", "gamer", "streetwear", "rustico", "natural"],
       ["para treinar em casa", "para a academia", "para o home office"],
       [("Peso", ["2 x 2 kg", "2 x 5 kg", "até 20 kg"]), ("Revestimento", ["emborrachado antiderrapante", "neoprene"]),
        ("Vendido como", ["par", "kit com suporte"])]),
    tp("Tapete de yoga", ESP, "Yoga e pilates", "tapete", ["Tapete de Yoga Antiderrapante", "Tapete de Yoga Grosso 10 mm", "Tapete de Pilates Ecológico"],
       [""], ["TPE", "Borracha natural", "Cortiça"], (79, 299), None,
       ["natural", "verao", "esportivo", "boho", "streetwear", "classico"],
       ["para yoga", "para pilates", "para alongamento em casa"],
       [("Espessura", ["6 mm", "10 mm"]), ("Dimensões", ["183 x 61 cm"]), ("Antiderrapante", ["sim, dos dois lados"])]),
    # ---------------- Beleza ----------------
    tp("Perfume", BELEZA, "Perfumaria", "frasco", ["Perfume Eau de Parfum", "Perfume Eau de Toilette", "Perfume Floral", "Colônia Cítrica"],
       ["100 ml", "75 ml", "50 ml"], ["Notas amadeiradas", "Notas cítricas", "Notas florais"], (149, 699), None,
       ["classico", "festa", "verao", "natural", "streetwear", "retro", "gamer", "inverno"],
       ["para o dia a dia", "para noites especiais", "para o trabalho"],
       [("Volume", ["50 ml", "75 ml", "100 ml"]), ("Fixação", ["até 8 h"]), ("Concentração", ["15% a 20% de essência"])],
       nome_mat=False),
    tp("Hidratante", BELEZA, "Cuidados com a pele", "frasco", ["Hidratante Facial Ácido Hialurônico", "Hidratante Corporal Karité", "Hidratante Facial com FPS 30", "Loção Hidratante Camomila"],
       [""], ["Creme", "Gel", "Loção"], (39, 169), None,
       ["natural", "verao", "classico", "escandinavo", "boho", "streetwear"],
       ["para a rotina diária", "para pele seca", "para depois do banho"],
       [("Volume", ["100 ml", "200 ml", "400 ml"]), ("Tipo de pele", ["todos os tipos", "pele seca", "pele oleosa"]),
        ("Principais ativos", ["ácido hialurônico e vitamina E", "karité e manteiga de cacau"]), ("Dermatologicamente testado", ["sim"])],
       nome_mat=False),
    tp("Kit skincare", BELEZA, "Cuidados com a pele", "frasco", ["Kit Skincare Completo", "Kit Skincare Rotina Noturna", "Kit Skincare Glow", "Kit Skincare Iniciantes"],
       [""], ["Vidro", "Plástico reciclado", "Bambu"], (179, 499), None,
       ["natural", "verao", "classico", "boho", "festa", "escandinavo", "streetwear"],
       ["para presentear", "para a rotina de cuidados", "para viagens"],
       [("Itens", ["3 produtos", "4 produtos", "5 produtos"]), ("Conteúdo", ["limpador, tônico e hidratante", "sérum, creme e máscara"]),
        ("Vegano", ["sim", "não"]), ("Validade", ["24 meses"])],
       nome_mat=False),
    tp("Paleta de maquiagem", BELEZA, "Maquiagem", "paleta", ["Paleta de Sombras 12 Cores", "Paleta Contorno e Iluminador", "Paleta Nude 18 Tons", "Paleta Multiuso Neon"],
       [""], ["Pigmento", "Plástico"], (69, 299), None,
       ["festa", "retro", "gamer", "streetwear", "classico", "boho", "verao"],
       ["para uma maquiagem do dia", "para festas", "para ensaios e fotos"],
       [("Cores", ["12 cores", "18 tons", "9 cores"]), ("Acabamento", ["fosco e cintilante", "matte e metálico"]),
        ("Fixação", ["longa duração"]), ("Vegana", ["sim"])],
       nome_mat=False),
    tp("Secador de cabelo", BELEZA, "Cabelos", "secador", ["Secador de Cabelo Íons", "Secador Profissional 2200 W", "Secador Compacto de Viagem", "Secador com Difusor"],
       [""], ["Plástico e metal", "Cerâmica"], (119, 499), None,
       ["classico", "streetwear", "natural", "verao", "industrial", "festa", "gamer"],
       ["para o dia a dia", "para salão em casa", "para viagens"],
       [("Potência", ["1800 W", "2200 W"]), ("Temperaturas", ["3 temperaturas e 2 velocidades", "6 temperaturas"]),
        ("Tecnologia", ["íons negativos e cerâmica"]), ("Voltagem", ["bivolt"])],
       nome_mat=False),
]
assert len(TIPOS) == 60, len(TIPOS)

# Complementos típicos (quem leva X costuma levar Y) — base das cestas e da associação "quem comprou também comprou"
COMPL = {
    "Sofá": ["Almofada", "Tapete", "Mesa de centro", "Luminária", "Manta"],
    "Poltrona": ["Almofada", "Luminária", "Tapete"],
    "Mesa de centro": ["Tapete", "Luminária", "Vaso decorativo"],
    "Luminária": ["Quadro", "Vaso decorativo"],
    "Tapete": ["Almofada", "Manta"],
    "Almofada": ["Manta", "Tapete"],
    "Cortina": ["Almofada", "Planta artificial"],
    "Jogo de cama": ["Manta", "Almofada", "Cortina"],
    "Manta": ["Almofada", "Jogo de cama"],
    "Vaso decorativo": ["Planta artificial"],
    "Quadro": ["Luminária", "Prateleira"],
    "Prateleira": ["Vaso decorativo", "Quadro", "Planta artificial"],
    "Planta artificial": ["Vaso decorativo"],
    "Jogo de panelas": ["Cafeteira", "Jogo de pratos"],
    "Cafeteira": ["Caneca", "Jogo de pratos"],
    "Jogo de pratos": ["Caneca", "Jogo de panelas"],
    "Liquidificador": ["Jogo de pratos", "Jogo de panelas"],
    "Air fryer": ["Jogo de pratos", "Jogo de panelas"],
    "Caneca": ["Cafeteira", "Jogo de pratos"],
    "Smart TV": ["Caixa de som", "Fita LED"],
    "Monitor": ["Teclado mecânico", "Mouse gamer", "Cadeira gamer"],
    "Fone de ouvido": ["Smartphone", "Smartwatch"],
    "Headset gamer": ["Console", "Mouse gamer"],
    "Caixa de som": ["Smart TV", "Fita LED"],
    "Smartphone": ["Fone de ouvido", "Smartwatch"],
    "Notebook": ["Mouse gamer", "Mochila", "Teclado mecânico"],
    "Teclado mecânico": ["Mouse gamer", "Headset gamer"],
    "Mouse gamer": ["Teclado mecânico"],
    "Console": ["Headset gamer", "Cadeira gamer", "Fita LED"],
    "Smartwatch": ["Fone de ouvido", "Smartphone"],
    "Fita LED": ["Smart TV", "Console"],
    "Cadeira gamer": ["Headset gamer", "Monitor"],
    "Tênis de corrida": ["Garrafa térmica", "Legging"],
    "Legging": ["Tênis de corrida", "Garrafa térmica"],
    "Garrafa térmica": ["Mochila de trilha", "Tênis de corrida"],
    "Bicicleta": ["Garrafa térmica", "Legging"],
    "Tapete de yoga": ["Legging", "Garrafa térmica"],
    "Barraca": ["Mochila de trilha", "Garrafa térmica"],
    "Mochila de trilha": ["Barraca", "Garrafa térmica"],
    "Halteres": ["Tapete de yoga", "Garrafa térmica", "Legging"],
    "Camiseta": ["Bermuda", "Boné", "Tênis casual"],
    "Camisa": ["Calça jeans", "Relógio"],
    "Moletom": ["Calça jeans", "Tênis casual", "Boné"],
    "Jaqueta": ["Camiseta", "Calça jeans", "Bota"],
    "Vestido": ["Sandália", "Bolsa", "Óculos de sol"],
    "Calça jeans": ["Camisa", "Tênis casual", "Camiseta"],
    "Bermuda": ["Camiseta", "Boné", "Sandália"],
    "Tênis casual": ["Calça jeans", "Camiseta"],
    "Bota": ["Jaqueta", "Calça jeans"],
    "Sandália": ["Vestido", "Bermuda"],
    "Bolsa": ["Vestido", "Óculos de sol"],
    "Mochila": ["Notebook", "Garrafa térmica"],
    "Óculos de sol": ["Vestido", "Relógio", "Bolsa"],
    "Relógio": ["Camisa", "Óculos de sol"],
    "Boné": ["Camiseta", "Moletom"],
    "Perfume": ["Kit skincare", "Hidratante"],
    "Hidratante": ["Kit skincare", "Perfume"],
    "Kit skincare": ["Hidratante", "Perfume"],
    "Paleta de maquiagem": ["Kit skincare", "Secador de cabelo"],
    "Secador de cabelo": ["Paleta de maquiagem"],
}
assert all(t["tipo"] in COMPL for t in TIPOS)

MARCAS = {
    MODA: ["Urbano Co.", "Terra & Fio", "Maré Brasil", "Noite de Gala", "Vintage 80", "Lã & Lenha"],
    CASA: ["Nórdica Home", "Raiz Rústica", "Lã & Lenha", "Vintage 80", "Terra & Fio"],
    COZ: ["Casa Forte", "Aço & Brasa", "Sálvia"],
    ELET: ["Voltz", "Neon Lab", "Ondaflux"],
    ESP: ["Pulse Sports", "Trilha Norte", "Maré Brasil"],
    BELEZA: ["Sálvia", "Aurora Beauty", "Noite de Gala"],
}
# ── Coerência do catálogo ───────────────────────────────────────────────────────────────
# Cores PERMITIDAS por grupo de ícone (a cor sai da paleta do estilo ∩ permitidas; se vazio, das permitidas)
ELETRONICO = ["Preto", "Branco", "Grafite", "Prata", "Cinza claro", "Azul-marinho"]
GRUPO_CORES = {
    **{i: ELETRONICO for i in ("tv", "notebook", "celular", "mouse", "teclado", "fone", "caixasom", "console",
                               "eletro", "cafeteira", "secador", "cadeira")},
    "led": ["Roxo", "Ciano", "Branco"],
    "relogio": ["Preto", "Prata", "Dourado", "Marrom", "Azul-marinho", "Branco", "Grafite", "Verde-musgo", "Vinho"],
    **{i: ["Madeira clara", "Madeira escura", "Bambu", "Preto", "Branco", "Grafite", "Cobre", "Off-white"]
       for i in ("mesa", "prateleira", "quadro")},
    **{i: ["Bege", "Cinza claro", "Off-white", "Branco", "Terracota", "Mostarda", "Vinho", "Azul-marinho", "Verde-musgo",
           "Verde-sálvia", "Marrom", "Creme", "Champanhe", "Coral", "Turquesa", "Laranja", "Verde-água", "Preto", "Grafite", "Roxo"]
       for i in ("sofa", "poltrona", "almofada", "tecido", "tapete")},
    "luminaria": ["Preto", "Branco", "Dourado", "Cobre", "Madeira clara", "Grafite", "Off-white", "Bambu", "Prata"],
    "vaso": ["Branco", "Off-white", "Terracota", "Bege", "Preto", "Verde-sálvia", "Azul-marinho", "Mostarda", "Verde-água", "Dourado"],
    "planta": ["Verde-musgo", "Verde-sálvia"],
    "panela": ["Preto", "Grafite", "Vermelho", "Cobre", "Prata", "Off-white", "Verde-sálvia", "Mostarda", "Terracota", "Azul-marinho"],
    **{i: ["Branco", "Off-white", "Creme", "Bege", "Terracota", "Preto", "Verde-sálvia", "Azul-marinho", "Mostarda", "Verde-água", "Cinza claro"]
       for i in ("pratos", "caneca")},
    "garrafa": ["Preto", "Branco", "Prata", "Azul-marinho", "Verde-musgo", "Coral", "Turquesa", "Azul-elétrico", "Verde-lima", "Grafite"],
    "halter": ["Preto", "Grafite", "Cinza claro"],
    "bike": ["Preto", "Branco", "Vermelho", "Azul-marinho", "Grafite", "Verde-musgo", "Prata"],
    "barraca": ["Verde-musgo", "Laranja", "Azul-marinho", "Grafite", "Vermelho", "Bege"],
    # embalagens de beleza: tons de cosmético (nada de neon)
    **{i: ["Branco", "Off-white", "Champanhe", "Dourado", "Preto", "Verde-sálvia", "Bege", "Vinho", "Coral", "Creme", "Azul-marinho"]
       for i in ("frasco", "paleta")},
}
# Moda/beleza: qualquer cor da paleta, menos madeira/bambu/cobre; metálicos só no estilo festa
BLOQ_MODA = {"Madeira clara", "Madeira escura", "Bambu", "Cobre"}


def cor_para(t, est):
    permitidas = GRUPO_CORES.get(t["icone"])
    paleta = est["cores"]
    if permitidas:
        cands = [c for c in paleta if c in permitidas] or permitidas
        if est["id"] == "gamer" and t["icone"] in GRUPO_CORES and permitidas is ELETRONICO:
            cands = cands + ["Roxo", "Ciano"]   # setup gamer pode ter acabamento colorido
    else:
        cands = [c for c in paleta if c not in BLOQ_MODA and (c not in ("Dourado", "Prata") or est["id"] == "festa")]
        cands = cands or ["Preto", "Branco", "Bege"]
    return cands[RNP.integers(len(cands))]


# Marca × estilo (estilos-assinatura); se nenhuma marca do departamento casa com o estilo, sorteia no departamento
ESTILOS_MARCA = {"Nórdica Home": {"escandinavo", "natural", "classico"}, "Raiz Rústica": {"rustico", "boho"},
                 "Lã & Lenha": {"inverno", "rustico"}, "Vintage 80": {"retro", "classico"}, "Terra & Fio": {"boho", "natural", "verao"},
                 "Urbano Co.": {"streetwear", "industrial"}, "Maré Brasil": {"verao", "esportivo"}, "Noite de Gala": {"festa", "classico"},
                 "Voltz": {"escandinavo", "industrial", "classico", "natural"}, "Neon Lab": {"gamer", "streetwear"},
                 "Ondaflux": {"escandinavo", "natural", "retro", "verao"}, "Pulse Sports": {"esportivo", "streetwear"},
                 "Trilha Norte": {"rustico", "esportivo", "inverno"}, "Casa Forte": {"classico", "escandinavo", "industrial"},
                 "Aço & Brasa": {"industrial", "rustico"}, "Sálvia": {"natural", "boho", "escandinavo"},
                 "Aurora Beauty": {"classico", "festa", "verao", "retro"}}


def marca_para(t, est):
    do_dep = MARCAS[t["dep"]]
    cands = [m for m in do_dep if est["id"] in ESTILOS_MARCA.get(m, set())] or do_dep
    return cands[RNP.integers(len(cands))]


N_POR_TIPO = 50
N_PRODUTOS = N_POR_TIPO * len(TIPOS)   # 3.000

linhas = []
for t in TIPOS:
    for _ in range(N_POR_TIPO):
        est = ESTILO_BY[t["estilos"][RNP.integers(len(t["estilos"]))]]
        cor = cor_para(t, est)
        cor2 = cor_para(t, est)
        mat = t["mats"][RNP.integers(len(t["mats"]))]
        base = t["bases"][RNP.integers(len(t["bases"]))]
        # se o nome-base já diz o material (ex.: "Vaso de Cerâmica", "Mesa de Centro Madeira"), o material é esse
        no_nome = [m for m in t["mats"] if m.split()[0].lower() in base.lower()]
        if no_nome:
            mat = no_nome[0]
        atrib = t["atribs"][RNP.integers(len(t["atribs"]))]
        marca = marca_para(t, est)
        uso = t["usos"][RNP.integers(len(t["usos"]))]
        cor_nome = cor
        if cor.startswith("Madeira") and "madeira" in f"{base} {mat}".lower():   # evita "Madeira maciça Madeira clara"
            cor_nome = {"Madeira clara": "Natural", "Madeira escura": "Tabaco"}[cor]
        partes = [base, atrib] + ([mat] if t["nome_mat"] and mat.split()[0].lower() not in base.lower() else []) + [cor_nome]
        nome_sem = " ".join(p for p in partes if p)
        nome = f"{nome_sem} — {marca}"

        lo, hi = t["preco"]
        preco = max(float(lo), round(float(np.exp(RNP.uniform(np.log(lo), np.log(hi))))) - 0.10)
        promo = np.nan
        if RNP.random() < 0.22:
            cand = round(preco * RNP.uniform(0.70, 0.90)) - 0.10
            if 0 < cand < preco:
                promo = float(cand)
        if preco < 150:
            parc = 3
        elif preco < 600:
            parc = int(RNP.choice([3, 6, 10]))
        else:
            parc = int(RNP.choice([6, 10, 12]))
        pop = float(RNP.lognormal(0.0, 0.9))
        lanc = bool(RNP.random() < 0.08)
        data_cad = hoje - timedelta(days=int(RNP.integers(0, 50)) if lanc else int(RNP.integers(60, 2400)))
        specs = "; ".join(f"{k}: {v[RNP.integers(len(v))]}" for k, v in t["specs"])
        descricao = (f"{nome_sem} na cor {cor.lower()}, pensado {uso}. {est['frase']} "
                     f"Disponível para retirada na loja {MARCA} ou entrega em todo o Brasil.")
        descricao_visual = (f"Estilo: {est['nome']}. Cores: {cor} e {cor2}. Material: {mat}. "
                            f"Ocasião/ambiente: {uso}, ideal para {est['ocasiao']}. Atmosfera: {est['vibe']}.")
        linhas.append(dict(
            nome=nome, marca_produto=marca, departamento=t["dep"], categoria=f"{t['dep']} › {t['sub']}",
            tipo=t["tipo"], icone=t["icone"], estilo_id=est["id"], cor=cor, cor_hex=CORES[cor],
            material=mat, descricao=descricao, descricao_visual=descricao_visual, especificacoes=specs,
            tamanhos=t["tam"], preco=preco, preco_promocional=promo, parcelas_sem_juros=parc,
            avaliacao=0.0, n_avaliacoes=0, estoque=0, lancamento=lanc, popularidade=pop,
            imagem_path=None, origem="seed", data_cadastro=data_cad,
            texto_busca=(f"{nome}. Tipo: {t['tipo']}. Departamento: {t['dep']}. {descricao} {descricao_visual}")))

pdf_produtos = pd.DataFrame(linhas)
pdf_produtos.insert(0, "produto_id", [f"SKU{i + 1:06d}" for i in range(len(pdf_produtos))])
# popularidade: normaliza (média 1) e deriva avaliações, estoque e ruptura
pdf_produtos["popularidade"] = (pdf_produtos["popularidade"] / pdf_produtos["popularidade"].mean()).round(3)
n = len(pdf_produtos)
pdf_produtos["avaliacao"] = np.clip(np.round(3.7 + 0.8 * np.log(pdf_produtos["popularidade"]) + RNP.normal(0, 0.3, n), 1), 2.5, 5.0)
pdf_produtos["n_avaliacoes"] = (pdf_produtos["popularidade"] * RNP.integers(5, 60, n)).astype(int)
pdf_produtos["estoque"] = np.where(RNP.random(n) < 0.06, 0, RNP.integers(3, 320, n)).astype(int)
pdf_produtos["origem"] = "seed"
# Público do produto (realismo das cestas): itens tipicamente femininos; o resto é unissex
FEMININO = {"Vestido", "Sandália", "Bolsa", "Paleta de maquiagem"}
pdf_produtos["publico"] = np.where(pdf_produtos["tipo"].isin(FEMININO), "Feminino", "Unissex")
# Marketplace: cada produto tem um VENDEDOR (loja oficial da marca ou lojista parceiro) e frete grátis acima de R$ 99
PARCEIROS = {MODA: ["Moda Brasil Outlet", "Closet da Vila", "Estilo & Cia"],
             CASA: ["Casa & Cia", "Lar Doce Lar Store", "Decora Já"],
             COZ: ["Cozinha Gourmet", "Utilidades do Lar", "Casa & Cia"],
             ELET: ["Tech Point", "Mega Eletro Shop", "Ponto do Gamer"],
             ESP: ["Esporte Total", "Mundo Fitness", "Aventura Outdoor"],
             BELEZA: ["Bela Pele Cosméticos", "Perfumaria Aroma", "Beauty Hub"]}
oficial = RNP.random(n) < 0.55
pdf_produtos["vendedor"] = np.where(oficial, "Loja Oficial " + pdf_produtos["marca_produto"],
                                    [PARCEIROS[d][RNP.integers(len(PARCEIROS[d]))] for d in pdf_produtos["departamento"]])
pdf_produtos["vendedor_reputacao"] = np.where(oficial, np.round(RNP.uniform(4.6, 5.0, n), 1),
                                              np.round(RNP.uniform(3.8, 4.9, n), 1))
pdf_produtos["frete_gratis"] = (pdf_produtos["preco_promocional"].fillna(pdf_produtos["preco"]) >= 99)
pdf_produtos["texto_busca"] = pdf_produtos["texto_busca"] + " Vendido por " + pdf_produtos["vendedor"] + "."
print(f"{len(pdf_produtos):,} produtos | {pdf_produtos['departamento'].nunique()} departamentos | "
      f"{pdf_produtos['tipo'].nunique()} tipos | {(pdf_produtos['estoque'] == 0).sum()} sem estoque")


gravar(pdf_produtos, "produtos", "Catálogo de produtos da BrickStore (fictício). texto_busca alimenta o Vector Search.",
       duplos=["preco", "preco_promocional", "avaliacao", "popularidade", "vendedor_reputacao"], inteiros=["parcelas_sem_juros", "n_avaliacoes", "estoque"],
       nulos_texto=["imagem_path"], cdf=True)
chave_pk("produtos", "produto_id", "pk_produtos")
print("✓ produtos")


# ## 3) Clientes (com gostos latentes: estilos e departamentos preferidos)


N_CLIENTES = 20000
PRIMEIRO = ["Ana", "Carlos", "Mariana", "Rafael", "Juliana", "Bruno", "Patrícia", "Fernando", "Camila", "Thiago",
            "Larissa", "Gustavo", "Renata", "Marcelo", "Aline", "Diego", "Vanessa", "Rodrigo", "Débora", "Leonardo",
            "Priscila", "André", "Fernanda", "Vinícius", "Tatiane", "Eduardo", "Sabrina", "Felipe", "Natália",
            "Beatriz", "Henrique", "Isabela", "Lucas", "Gabriela", "Pedro", "Amanda", "Guilherme", "Lívia", "Duda",
            "Helena", "Caio", "Bia", "Leo", "Rafa"]
ULTIMO = ["Souza", "Lima", "Costa", "Santos", "Rocha", "Dias", "Martins", "Melo", "Nunes", "Pinto", "Freitas",
          "Lopes", "Ramos", "Monteiro", "Cruz", "Pires", "Azevedo", "Cunha", "Moraes", "Reis", "Campos", "Barros"]
CIDADES = [("SP", "São Paulo"), ("SP", "São Paulo"), ("SP", "Campinas"), ("RJ", "Rio de Janeiro"), ("RJ", "Niterói"),
           ("MG", "Belo Horizonte"), ("MG", "Uberlândia"), ("PR", "Curitiba"), ("PR", "Londrina"),
           ("SC", "Florianópolis"), ("SC", "Joinville"), ("RS", "Porto Alegre"), ("RS", "Caxias do Sul"),
           ("BA", "Salvador"), ("PE", "Recife"), ("DF", "Brasília"), ("CE", "Fortaleza"), ("GO", "Goiânia"),
           ("PA", "Belém"), ("AM", "Manaus"), ("ES", "Vitória")]
DEPTS = [MODA, CASA, COZ, ELET, ESP, BELEZA]
FAIXAS = ["18-24", "25-34", "35-44", "45-54", "55+"]
CANAIS_PREF = ["Site", "App", "Loja física", "Marketplace"]

eng = RN.beta(2, 2.5, N_CLIENTES)                     # engajamento latente
cid = RN.integers(len(CIDADES), size=N_CLIENTES)
clientes = []
for k in range(N_CLIENTES):
    pn, un = PRIMEIRO[RN.integers(len(PRIMEIRO))], ULTIMO[RN.integers(len(ULTIMO))]
    uf, cidade = CIDADES[cid[k]]
    email = sem_acento(f"{pn}.{un}{k + 1}@{DOMINIO}".lower().replace(" ", ""))
    estilos_fav = [ESTILO_IDS[RN.integers(len(ESTILO_IDS))]]
    if RN.random() < 0.5:
        outro = ESTILO_IDS[RN.integers(len(ESTILO_IDS))]
        if outro not in estilos_fav:
            estilos_fav.append(outro)
    deptos = [DEPTS[RN.integers(len(DEPTS))]]
    if RN.random() < 0.4 and DEPTS[0] != deptos[0]:
        deptos.append(DEPTS[RN.integers(len(DEPTS))] if RN.random() < 0.5 else deptos[0])
    deptos = list(dict.fromkeys(deptos))
    clientes.append(dict(cliente_id=f"C{k + 1:06d}", nome=f"{pn} {un}", email=email, uf=uf, cidade=cidade,
                         faixa_etaria=FAIXAS[RN.integers(len(FAIXAS))],
                         genero=str(RN.choice(["Feminino", "Masculino", "Não informado"], p=[0.52, 0.44, 0.04])),
                         segmento="Bronze",
                         data_cadastro=hoje - timedelta(days=int(RN.integers(30, 2400))),
                         canal_preferido=str(RN.choice(CANAIS_PREF, p=[0.3, 0.4, 0.2, 0.1])),
                         _eng=float(eng[k]), _estilos=estilos_fav, _deptos=deptos))
pdf_clientes = pd.DataFrame(clientes)
print(f"{len(pdf_clientes):,} clientes")


# ## 4) Pedidos e cestas (cesta = pedido)
# Cada cliente escolhe um **estilo** e um **departamento** preferidos. Cada pedido começa com um produto
# desse gosto e, com boa probabilidade, traz um **complemento** do mesmo estilo (o "parceiro" preferido
# daquele produto). É isso que produz as associações fortes entre itens.


prod_tipo = pdf_produtos["tipo"].to_numpy()
prod_pub = pdf_produtos["publico"].to_numpy()
prod_est = pdf_produtos["estilo_id"].to_numpy()
prod_dep = pdf_produtos["departamento"].to_numpy()
prod_pop = pdf_produtos["popularidade"].to_numpy()
prod_preco = pdf_produtos["preco"].to_numpy()
prod_promo = pdf_produtos["preco_promocional"].to_numpy()
prod_unit = np.where(np.isnan(prod_promo), prod_preco, prod_promo)   # preço praticado na venda
prod_id = pdf_produtos["produto_id"].to_numpy()
ALL_POS = np.arange(len(pdf_produtos))


def _pool(chave, posicoes):
    posicoes = np.asarray(posicoes, dtype=int)
    if len(posicoes):
        w = prod_pop[posicoes]
        POOL[chave] = (posicoes, np.cumsum(w) / w.sum())


POOL = {}
for e in ESTILO_IDS:
    _pool(("e", e), ALL_POS[prod_est == e])
    for d in DEPTS:
        _pool(("ed", e, d), ALL_POS[(prod_est == e) & (prod_dep == d)])
for t in pdf_produtos["tipo"].unique():
    _pool(("t", t), ALL_POS[prod_tipo == t])
    for e in ESTILO_IDS:
        _pool(("te", t, e), ALL_POS[(prod_tipo == t) & (prod_est == e)])
_pool(("todos",), ALL_POS)


def pick(chave):
    pos, cdf = POOL[chave]
    k = min(int(np.searchsorted(cdf, RN.random(), side="right")), len(pos) - 1)
    return int(pos[k])


def permitido(pos, cli) -> bool:
    """Respeita o público do produto: item feminino para cliente homem (e vice-versa) só como presente (~5%)."""
    pub, gen = prod_pub[pos], cli.get("genero")
    if pub == "Unissex" or gen == "Não informado":
        return True
    return pub == gen or RN.random() < 0.05


def pick_cli(chave, cli):
    j = pick(chave)
    for _ in range(8):
        if permitido(j, cli):
            return j
        j = pick(chave)
    return j


# "Parceiros" preferidos: cada produto tem 2 complementos fixos por tipo complementar, do mesmo estilo
PAR = {}
for i in range(len(pdf_produtos)):
    PAR[i] = {}
    for c in COMPL.get(prod_tipo[i], []):
        cands = ALL_POS[(prod_tipo == c) & (prod_est == prod_est[i])]
        if len(cands) < 2:
            cands = ALL_POS[prod_tipo == c]
        PAR[i][c] = [int(x) for x in RNP.choice(cands, size=2, replace=False)]


def montar_cesta(cli):
    est = cli["_estilos"][RN.integers(len(cli["_estilos"]))] if RN.random() < 0.85 else ESTILO_IDS[RN.integers(len(ESTILO_IDS))]
    dep = cli["_deptos"][RN.integers(len(cli["_deptos"]))] if RN.random() < 0.7 else DEPTS[RN.integers(len(DEPTS))]
    seed = pick_cli(("ed", est, dep), cli) if ("ed", est, dep) in POOL else pick_cli(("e", est), cli)
    cesta = [seed]
    comps = COMPL.get(prod_tipo[seed], [])
    if comps:
        u = RN.random()
        n_comp = 2 if u < 0.25 else (1 if u < 0.75 else 0)
        for k in RN.permutation(len(comps))[:n_comp]:
            c = comps[k]
            if RN.random() < 0.6:
                j = PAR[seed][c][RN.integers(2)]
            elif ("te", c, est) in POOL:
                j = pick_cli(("te", c, est), cli)
            else:
                j = pick_cli(("t", c), cli)
            if j not in cesta and permitido(j, cli):
                cesta.append(j)
    for _ in range(RN.poisson(0.35)):
        j = pick_cli(("ed", est, dep), cli) if (("ed", est, dep) in POOL and RN.random() < 0.5) else pick_cli(("e", est), cli)
        if j not in cesta:
            cesta.append(j)
    return cesta


N_PEDIDOS_POR_CLIENTE = RN.poisson(0.6 + 8 * pdf_clientes["_eng"].to_numpy())
pedidos, itens = [], []
ped_seq = 0
for k, cli in enumerate(clientes):
    for _ in range(int(N_PEDIDOS_POR_CLIENTE[k])):
        ped_seq += 1
        pid = f"P{ped_seq:07d}"
        dias_jan = int(RN.integers(0, max(1, (hoje - cli["data_cadastro"]).days)))
        data_p = pd.Timestamp(cli["data_cadastro"]) + pd.Timedelta(days=dias_jan, minutes=int(RN.integers(0, 1440)))
        if data_p.date() > hoje:
            data_p = pd.Timestamp(hoje) + pd.Timedelta(minutes=int(RN.integers(0, 1440)))
        canal = str(RN.choice(["Site", "App", "Loja física", "Marketplace"], p=[0.35, 0.35, 0.2, 0.1]))
        loja = cli["cidade"] if canal == "Loja física" else None
        cesta = montar_cesta(cli)
        subtotal = 0.0
        for pos in cesta:
            qtd = 1 if RN.random() < 0.88 else 2
            unit = float(prod_unit[pos])
            desc = round((float(prod_preco[pos]) - unit) * qtd, 2)
            itens.append((pid, prod_id[pos], qtd, unit, desc))
            subtotal += unit * qtd
        frete = 0.0 if (canal == "Loja física" or subtotal >= 199) else float(RN.choice([19.9, 24.9, 29.9, 39.9]))
        valor = round(subtotal + frete, 2)
        forma = str(RN.choice(["Cartão", "PIX", "Boleto"], p=[0.6, 0.3, 0.1]))
        if forma == "Cartão":
            parc = int(RN.choice([1, 3, 6, 10, 12], p=[0.3, 0.3, 0.2, 0.12, 0.08])) if valor >= 200 else int(RN.choice([1, 2, 3]))
        else:
            parc = 1
        recente = (hoje - data_p.date()).days <= 7
        if recente and RN.random() < 0.7:
            status = "Em transporte"
        elif RN.random() < 0.04:
            status = "Cancelado"
        elif RN.random() < 0.03:
            status = "Devolvido"
        else:
            status = "Entregue"
        pedidos.append((pid, cli["cliente_id"], data_p, canal, loja, forma, parc, status, valor, frete))

pdf_pedidos = pd.DataFrame(pedidos, columns=["pedido_id", "cliente_id", "data_pedido", "canal", "loja", "forma_pagamento",
                                             "parcelas", "status", "valor_total", "frete"])
pdf_itens = pd.DataFrame(itens, columns=["pedido_id", "produto_id", "quantidade", "preco_unitario", "desconto"])

# segmento de fidelidade pelo gasto (não cancelado): top 5% Diamante, 15% Ouro, 30% Prata, resto Bronze
gasto = pdf_pedidos[pdf_pedidos["status"] != "Cancelado"].groupby("cliente_id")["valor_total"].sum()
pdf_clientes["_gasto"] = pdf_clientes["cliente_id"].map(gasto).fillna(0.0)
pct = pdf_clientes["_gasto"].rank(pct=True, method="first")
pdf_clientes["segmento"] = np.select([pct > 0.95, pct > 0.80, pct > 0.50], ["Diamante", "Ouro", "Prata"], "Bronze")
pdf_pedidos_n = pdf_pedidos.groupby("cliente_id").size()
print(f"{len(pdf_pedidos):,} pedidos | {len(pdf_itens):,} itens | cesta média {len(pdf_itens) / len(pdf_pedidos):.2f} itens")


gravar(pdf_clientes[["cliente_id", "nome", "email", "uf", "cidade", "faixa_etaria", "genero", "segmento",
                     "data_cadastro", "canal_preferido"]],
       "clientes", "Clientes da BrickStore (fictícios). Programa de fidelidade: segmento Bronze, Prata, Ouro ou Diamante.")
gravar(pdf_pedidos, "pedidos", "Pedidos da BrickStore (fictícios). Cada pedido é uma cesta para as regras de quem comprou também comprou.",
       duplos=["valor_total", "frete"], inteiros=["parcelas"])
gravar(pdf_itens, "itens_pedido", "Itens dos pedidos da BrickStore (fictícios). Cestas com complementos de estilo.",
       duplos=["preco_unitario", "desconto"], inteiros=["quantidade"])
print("✓ clientes, pedidos, itens_pedido")


# ## 5) Eventos de navegação (visualizou, carrinho, favoritou)


EVENTOS = []
ev_seq = 0
n_ev = RN.poisson(3 + 22 * pdf_clientes["_eng"].to_numpy())
for k, cli in enumerate(clientes):
    for _ in range(int(n_ev[k])):
        ev_seq += 1
        est = cli["_estilos"][RN.integers(len(cli["_estilos"]))]
        dep = cli["_deptos"][RN.integers(len(cli["_deptos"]))]
        if RN.random() < 0.75:
            pos = pick(("ed", est, dep)) if ("ed", est, dep) in POOL else pick(("e", est))
        else:
            pos = pick(("todos",))
        u = RN.random()
        evento = "visualizou" if u < 0.82 else ("adicionou_carrinho" if u < 0.94 else "favoritou")
        quando = pd.Timestamp(hoje) - pd.Timedelta(minutes=int(RN.integers(0, 365 * 24 * 60)))
        EVENTOS.append((f"E{ev_seq:08d}", cli["cliente_id"], prod_id[pos], quando, evento,
                        str(RN.choice(["Celular", "Desktop", "Tablet"], p=[0.55, 0.35, 0.10]))))
pdf_eventos = pd.DataFrame(EVENTOS, columns=["evento_id", "cliente_id", "produto_id", "data_hora", "evento", "dispositivo"])
print(f"{len(pdf_eventos):,} eventos de navegação")


gravar(pdf_eventos, "eventos_navegacao", "Eventos de navegacao na loja online da BrickStore (visualizou, adicionou_carrinho, favoritou).")
print("✓ eventos_navegacao")


# ## 6) Perfis de demonstração ("Quem vai comprar?")
# Clientes reais da base, com muitos pedidos e gostos de estilo bem diferentes, para que cada perfil
# mostre uma vitrine personalizada no App.


PERFIS_DEMO = [("escandinavo", "Escandinavo", "#D9B98C"), ("gamer", "Gamer", "#00F0FF"),
               ("boho", "Boho", "#C2643F"), ("esportivo", "Esportivo", "#0057FF"),
               ("classico", "Clássico", "#C9A227"), ("streetwear", "Street", "#39FF14"),
               ("verao", "Verão", "#1FB5B0")]
perfis = []
for est, apelido, cor in PERFIS_DEMO:
    cands = pdf_clientes[pdf_clientes["_estilos"].apply(lambda e: e[0] == est)]
    if cands.empty:
        cands = pdf_clientes
    cands = cands.assign(n_pedidos=cands["cliente_id"].map(pdf_pedidos_n).fillna(0).astype(int))
    melhor = cands.sort_values(["n_pedidos", "cliente_id"], ascending=[False, True]).iloc[0]
    primeiro = melhor["nome"].split()[0]
    perfis.append(dict(cliente_id=melhor["cliente_id"], apelido=f"{primeiro} · {apelido}", nome=melhor["nome"],
                       cor=cor, estilo_favorito=est, n_pedidos=int(melhor["n_pedidos"])))
pdf_perfis = pd.DataFrame(perfis)
gravar(pdf_perfis, "perfis_demo", "Perfis de demonstracao da tela de entrada do App (clientes reais da base).",
       inteiros=["n_pedidos"])
print(pdf_perfis[["apelido", "estilo_favorito", "n_pedidos"]].to_string(index=False))


# ## 7) Tabelas auxiliares e chaves (informativas)
# Chaves ajudam o Genie a entender os relacionamentos.


# clientes e pedidos/itens/eventos: os dados já foram gravados; aqui só registramos as chaves
chave_pk("clientes", "cliente_id", "pk_clientes")
chave_pk("pedidos", "pedido_id", "pk_pedidos")
chave_pk("perfis_demo", "cliente_id", "pk_perfis_demo")
chave_pk("eventos_navegacao", "evento_id", "pk_eventos")
chave_fk("pedidos", "cliente_id", "clientes", "cliente_id", "fk_ped_cliente")
chave_fk("itens_pedido", "pedido_id", "pedidos", "pedido_id", "fk_item_pedido")
chave_fk("itens_pedido", "produto_id", "produtos", "produto_id", "fk_item_produto")
chave_fk("eventos_navegacao", "cliente_id", "clientes", "cliente_id", "fk_evt_cliente")
chave_fk("eventos_navegacao", "produto_id", "produtos", "produto_id", "fk_evt_produto")
chave_fk("produtos", "estilo_id", "estilos", "estilo_id", "fk_prod_estilo")
chave_fk("perfis_demo", "cliente_id", "clientes", "cliente_id", "fk_perfil_cliente")



# ───────────────────────────── grava os arquivos ─────────────────────────────
if __name__ == "__main__":
    SAIDA.mkdir(exist_ok=True)
    total = 0
    for nome, pdf in TABELAS.items():
        destino = SAIDA / f"{nome}.parquet"
        pdf.to_parquet(destino, index=False, compression="zstd")
        MANIFESTO["tabelas"][nome]["linhas"] = int(len(pdf))
        total += destino.stat().st_size
        print(f"  {nome:<20} {len(pdf):>9,} linhas  {destino.stat().st_size / 1e6:6.2f} MB")
    MANIFESTO["marca"], MANIFESTO["dominio"], MANIFESTO["referencia"] = MARCA, DOMINIO, str(hoje)
    (SAIDA / "manifesto.json").write_text(json.dumps(MANIFESTO, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {len(TABELAS)} tabelas em {SAIDA} ({total / 1e6:.1f} MB)")
