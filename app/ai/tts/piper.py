"""Piper TTS — быстрый локальный диктор на CPU (0% VRAM). Backend по умолчанию.

Не требует GPU и python-пакетов: достаточно бинарника `piper` + модели .onnx.
Смена голоса = одна строка `voice:` в settings.yaml. Реализует ITTS.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from app.core.interfaces import ITTS
from app.core.registry import register

from ._subprocess import run_cli


@register("tts", "piper")
class PiperTTS(ITTS):
    def __init__(self, voice: str = "ru_RU-midia-medium",
                 output_dir: str = "./data/audio", model_dir: str = "./models/piper",
                 binary: str = "piper", **_):
        self.voice = voice
        self.output_dir = Path(output_dir)
        self.model_dir = Path(model_dir)
        self.binary = binary
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, text: str, out_path: str) -> dict[str, Any]:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        wav = out.with_suffix(".wav")
        # piper читает текст со stdin, пишет wav
        subprocess_run = [self.binary, "--model",
                          str(self.model_dir / f"{self.voice}.onnx"),
                          "--output_file", str(wav)]
        import subprocess
        p = subprocess.run(subprocess_run, input=text, text=True,
                           capture_output=True, timeout=300)
        if p.returncode != 0 or not wav.exists():
            raise RuntimeError(f"piper недоступен ({p.stderr[-200:]}). "
                               "Установите piper-tts или смените ai.tts.backend (xtts/edge_tts).")
        with wave.open(str(wav), "rb") as w:
            duration = w.getnframes() / w.getframerate()
        return {"path": str(wav), "duration": round(duration, 2), "words": None}
