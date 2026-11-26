"""
Motor de desenho das ilustrações flat ORIGINAIS (procedurais) usadas nas fichas técnicas (gerar_fichas.py).

`Tela` desenha em 2x e reduz com LANCZOS para bordas suaves. `tenis_perfil` desenha um tênis de corrida de lado.
"""
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 1280, 800
S = 2  # supersampling


class Tela:
    """Canvas em coordenadas 1280x800 que desenha internamente em 2x."""

    def __init__(self, fundo=(0, 0, 0), largura=W, altura=H):
        self.w, self.h = largura, altura
        self.img = Image.new("RGB", (largura * S, altura * S), fundo)
        self.d = ImageDraw.Draw(self.img)

    # --- utilitários de coordenada
    @staticmethod
    def _pts(pts):
        return [(x * S, y * S) for x, y in pts]

    @staticmethod
    def _box(x0, y0, x1, y1):
        return [x0 * S, y0 * S, x1 * S, y1 * S]

    # --- primitivas
    def faixa(self, y0, y1, c0, c1):
        """Gradiente vertical entre y0 e y1 (cores RGB)."""
        n = max(1, (y1 - y0) * S - 1)
        for i, y in enumerate(range(y0 * S, y1 * S)):
            k = i / n
            cor = tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3))
            self.d.line([(0, y), (self.w * S, y)], fill=cor)

    def rect(self, x0, y0, x1, y1, cor, r=0, cont=None, lw=0):
        if r:
            self.d.rounded_rectangle(self._box(x0, y0, x1, y1), radius=r * S, fill=cor,
                                     outline=cont, width=int(lw * S))
        else:
            self.d.rectangle(self._box(x0, y0, x1, y1), fill=cor, outline=cont, width=int(lw * S))

    def elipse(self, x0, y0, x1, y1, cor, cont=None, lw=0):
        self.d.ellipse(self._box(x0, y0, x1, y1), fill=cor, outline=cont, width=int(lw * S))

    def poli(self, pts, cor, cont=None, lw=0):
        self.d.polygon(self._pts(pts), fill=cor)
        if cont:
            self.d.line(self._pts(pts + [pts[0]]), fill=cont, width=int(lw * S), joint="curve")

    def linha(self, pts, cor, lw=2):
        self.d.line(self._pts(pts), fill=cor, width=max(1, int(lw * S)), joint="curve")

    def arco(self, x0, y0, x1, y1, ini, fim, cor, lw):
        self.d.arc(self._box(x0, y0, x1, y1), ini, fim, fill=cor, width=max(1, int(lw * S)))

    def elipse_rot(self, cx, cy, rx, ry, ang, cor):
        """Elipse com eixo maior rx girado de `ang` graus (a partir do eixo x)."""
        a = math.radians(ang)
        pts = []
        for k in range(72):
            t = 2 * math.pi * k / 72
            x = cx + rx * math.cos(t) * math.cos(a) - ry * math.sin(t) * math.sin(a)
            y = cy + rx * math.cos(t) * math.sin(a) + ry * math.sin(t) * math.cos(a)
            pts.append((x, y))
        self.poli(pts, cor)

    def retangulo_rot(self, cx, cy, w, h, ang, cor):
        a = math.radians(ang)
        cos, sin = math.cos(a), math.sin(a)
        pts = []
        for dx, dy in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
            pts.append((cx + dx * cos - dy * sin, cy + dx * sin + dy * cos))
        self.poli(pts, cor)

    # --- luz e sombra (camadas desfocadas somadas à imagem)
    def _somar(self, camada, intensidade):
        """Soma uma camada (já desfocada) à imagem, com intensidade limitada a 255."""
        self.img.paste(ImageChops.add(self.img, camada.point(lambda v: min(255, int(v * intensidade)))))

    def sombra(self, cx, cy, rx, ry, alpha=0.35, raio=14):
        mascara = Image.new("L", self.img.size, 0)
        ImageDraw.Draw(mascara).ellipse(self._box(cx - rx, cy - ry, cx + rx, cy + ry), fill=int(255 * alpha))
        mascara = mascara.filter(ImageFilter.GaussianBlur(raio * S))
        self.img.paste((0, 0, 0), (0, 0), mascara)

    def halo(self, cx, cy, r, cor, intensidade=0.8, raio=None):
        camada = Image.new("RGB", self.img.size, (0, 0, 0))
        ImageDraw.Draw(camada).ellipse(self._box(cx - r, cy - r, cx + r, cy + r), fill=cor)
        camada = camada.filter(ImageFilter.GaussianBlur((raio or r * 0.6) * S))
        self._somar(camada, intensidade)

    def neon(self, pts, cor, lw=8, raio=18, intensidade=1.2):
        """Linha de neon: brilho desfocado + núcleo nítido."""
        camada = Image.new("RGB", self.img.size, (0, 0, 0))
        ImageDraw.Draw(camada).line(self._pts(pts), fill=cor, width=int(lw * S * 2), joint="curve")
        camada = camada.filter(ImageFilter.GaussianBlur(raio * S))
        self._somar(camada, intensidade)
        self.linha(pts, cor, lw)

    def salvar(self, caminho):
        self.img.resize((self.w, self.h), Image.LANCZOS).save(caminho, quality=90)

    def jpeg(self) -> bytes:
        import io
        buf = io.BytesIO()
        self.img.resize((self.w, self.h), Image.LANCZOS).convert("RGB").save(buf, "JPEG", quality=90)
        return buf.getvalue()


# ======================================================================
# 1) SALA ESCANDINAVA — sofá de linho cinza, almofadas, tapete, mesa, luminária, planta, quadro
# ======================================================================


def tenis_perfil(t, x, y, escala, cor, detalhe, sola, espelho=False):
    """Tênis de corrida visto de lado (de frente para a direita). (x, y) = canto inferior esquerdo."""
    def P(px, py):
        px = px * escala
        py = py * escala
        if espelho:
            px = 300 * escala - px
        return (x + px, y + py - 130 * escala)

    def poli(pts, cor_):
        t.poli([P(a, b) for a, b in pts], cor_)

    # entressola/sola
    poli([(4, 104), (300, 104), (300, 126), (12, 126), (0, 118)], sola)
    poli([(0, 100), (296, 100), (300, 106), (0, 110)], detalhe)
    # cabedal
    poli([(8, 104), (10, 66), (30, 36), (76, 28), (128, 18), (160, 26), (200, 46),
          (244, 64), (282, 84), (300, 102)], cor)
    # chanfro/colarinho e língua
    poli([(10, 66), (30, 36), (50, 44), (40, 70), (18, 90)], detalhe)
    poli([(118, 22), (144, 16), (146, 40), (122, 46)], (236, 240, 240))
    # tira de cabedal (swoosh)
    poli([(60, 88), (150, 70), (220, 84), (290, 96), (240, 92), (150, 82), (70, 100)], detalhe)
    # cadarço
    for k in range(4):
        a = (134 + k * 14, 40 + k * 4)
        b = (146 + k * 14, 36 + k * 4)
        t.linha([P(*a), P(*b)], (240, 240, 236), max(1, int(3 * escala)))
    # garras / detalhes da sola
    for k in range(7):
        xx = 30 + k * 36
        t.linha([P(xx, 112), P(xx + 14, 112)], (120, 124, 128), max(1, int(2 * escala)))


