"""
🎙️ Whisper (speech-to-text) como modelo MLflow pyfunc, servido no Model Serving (etapa setup/02b_whisper).

Entrada:  DataFrame com a coluna `audio` = conteúdo do arquivo (MP3, WAV, FLAC ou OGG) em base64.
Saída:    lista de dicionários {"texto": "...", "duracao_seg": 12.3}.

O áudio é decodificado com `soundfile` (libsndfile, sem ffmpeg) e reamostrado para 16 kHz mono; o pipeline
`automatic-speech-recognition` do transformers roda o Whisper em GPU quando houver (senão CPU), em português.
"""
import base64
import io

import mlflow
import numpy as np


class Whisper(mlflow.pyfunc.PythonModel):
    IDIOMA = "portuguese"

    def load_context(self, context):
        import torch
        from transformers import pipeline
        gpu = torch.cuda.is_available()
        self.pipe = pipeline("automatic-speech-recognition", model=context.artifacts["modelo"],
                             device=0 if gpu else -1, dtype=torch.float16 if gpu else torch.float32)

    @staticmethod
    def _pcm16k(dados: bytes) -> tuple[np.ndarray, float]:
        import soundfile as sf
        audio, taxa = sf.read(io.BytesIO(dados), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)                                   # mono
        duracao = len(audio) / float(taxa)
        if taxa != 16000:                                            # reamostragem linear (suficiente para fala)
            n = int(round(duracao * 16000))
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")
        return audio, duracao

    def predict(self, context, model_input, params=None):
        saida = []
        for b64 in list(model_input["audio"]):
            audio, duracao = self._pcm16k(base64.b64decode(b64))
            # acima de 30 s o Whisper usa o modo de áudio longo (precisa de timestamps)
            r = self.pipe({"raw": audio, "sampling_rate": 16000}, return_timestamps=duracao > 30,
                          generate_kwargs={"language": self.IDIOMA, "task": "transcribe"})
            saida.append({"texto": (r.get("text") or "").strip(), "duracao_seg": round(duracao, 1)})
        return saida


mlflow.models.set_model(Whisper())
