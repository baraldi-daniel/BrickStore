"""
Gera os áudios de SAC (ligações de clientes) usados pela etapa setup/05a_sac_voz (Whisper).

Usa o `say` do macOS (vozes pt-BR) + ffmpeg. Os áudios já vêm prontos no repositório (audios_sac/);
rode só se quiser regravar:  python ferramentas/gerar_audios_sac.py
O roteiro de cada ligação fica em audios_sac/roteiros.json (texto falado + cliente da ligação).
"""
import json
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "audios_sac"


def falado(texto: str) -> str:
    """Soletra o número do pedido (P0011655 → 'P, 0 0 1 1 6 5 5') para a voz ler dígito a dígito."""
    import re
    return re.sub(r"\bP(\d{7})\b", lambda m: "P, " + " ".join(m.group(1)), texto)


LIGACOES = [
    {"arquivo": "sac_01_troca_tamanho.mp3", "voz": "Reed", "cliente_id": "C003968", "pedido_id": "P0016465",
     "texto": "Oi, boa tarde. Aqui é o Gustavo. Comprei a camisa social de viscose azul-marinho no pedido P0016465, "
              "mas ela ficou apertada nos ombros. Queria trocar por um tamanho G, se possível."},
    {"arquivo": "sac_02_atraso_entrega.mp3", "voz": "Luciana", "cliente_id": "C002789", "pedido_id": "P0011655",
     "texto": "Olá, meu nome é Aline. Fiz o pedido P0011655 no dia dezesseis, uma bolsa baguete prata, e até agora "
              "não chegou. O rastreio está parado há dias. Qual é o novo prazo de entrega?"},
    {"arquivo": "sac_03_defeito.mp3", "voz": "Flo", "cliente_id": "C001466", "pedido_id": "P0006114",
     "texto": "Oi, aqui é a Vanessa. A air fryer digital roxa do pedido P0006114 parou de esquentar depois de duas semanas. "
              "Liga o painel, mas não aquece. Estou bem chateada, preciso de uma solução."},
    {"arquivo": "sac_04_elogio.mp3", "voz": "Sandy", "cliente_id": "C007915", "pedido_id": "P0032878",
     "texto": "Olá, sou a Renata. Só liguei para elogiar. A camisa de linho coral do pedido P0032878 chegou antes do prazo, "
              "muito bem embalada, e o tecido é lindo. Parabéns pelo atendimento!"},
    {"arquivo": "sac_05_garantia.mp3", "voz": "Eddy", "cliente_id": "C006500", "pedido_id": "P0026975",
     "texto": "Bom dia, aqui é o Pedro. O zíper principal da mochila de trilha de quarenta litros, do pedido P0026975, "
              "quebrou na primeira trilha. Ela ainda está na garantia? Como faço para acionar?"},
    {"arquivo": "sac_06_cancelamento.mp3", "voz": "Rocko", "cliente_id": "C009207", "pedido_id": "P0038239",
     "texto": "Oi, é o Vinícius. Comprei por engano o quadro decorativo de MDF branco no pedido P0038239. "
              "Quero cancelar essa compra e receber o estorno no cartão."},
]


def main():
    SAIDA.mkdir(exist_ok=True)
    for l in LIGACOES:
        aiff = SAIDA / "_tmp.aiff"
        subprocess.run(["say", "-v", l["voz"], "-r", "175", "-o", str(aiff), falado(l["texto"])], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ac", "1", "-ar", "44100", "-b:a", "96k",
                        str(SAIDA / l["arquivo"])], check=True)
        aiff.unlink()
        print("✓", l["arquivo"])
    (SAIDA / "roteiros.json").write_text(json.dumps(LIGACOES, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
