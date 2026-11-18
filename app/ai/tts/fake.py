"""FakeTTS — заглушка ITTS для offline-тестов Этапа B.

Генерирует реальный WAV через ffmpeg (или чистый PCM), чтобы весь
render-путь (субтитры -> mp4) проверялся без установки TTS-моделей.
Демонстрирует: пайплайн не различает fake и боевой бэкенды — только интерфейс.
"""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path
from typing import Any

from app.core.interfaces import ITTS
from app.core.registry import register


@register("tts", "fake")
class FakeTTS(ITTS):
    def __init__(self, wps: float = 2.6, **_):  # ~слов в секунду «речи»
        self.wps = wps

    def synthesize(self, text: str, out_path: str) -> dict[str, Any]:
        words = [w for w in text.split() if w.strip()]
        duration = max(len(words) / self.wps, 1.0)
        sr = 16000
        out = Path(out_path).with_suffix(".wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        n = int(sr * duration)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            frames = bytearray()
            for i in range(n):
                t = i / sr
                seg = min(int(t * len(words) / duration), len(words) - 1) if words else 0
                freq = 150 + (seg % 7) * 30          # «интонация» меняет тон по словам
                amp = 0.35 * (0.4 + 0.6 * abs(math.sin(2 * math.pi * 2.3 * t)))  # ритм слогов
                val = int(32767 * amp * math.sin(2 * math.pi * freq * t))
                frames += val.to_bytes(2, "little", signed=True)
            w.writeframes(bytes(frames))
        # псевдо word-тайминги — как если бы TTS вернул точные метки
        per = duration / max(len(words), 1)
        timed = [{"w": wd, "start": round(i * per, 2), "end": round((i + 1) * per, 2)}
                 for i, wd in enumerate(words)]
        return {"path": str(out), "duration": round(duration, 2), "words": timed}
