"""Edge-TTS — облачный бесплатный русский диктор (Microsoft neural voices).

Ставится одним пакетом (`pip install edge-tts`), ноль VRAM, качество выше Piper.
Как и все бэкенды ITTS — меняется строкой в YAML. words-тайминги не отдаёт
(субтитры тогда строятся оценочно по длине текста или через ASR-выравнивание).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from app.core.interfaces import ITTS
from app.core.registry import register


@register("tts", "edge_tts")
class EdgeTTSSynthesizer(ITTS):
    def __init__(self, voice: str = "ru-RU-DmitryNeural",
                 output_dir: str = "./data/audio", **_):
        self.voice = voice
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, text: str, out_path: str) -> dict[str, Any]:
        out = Path(out_path).with_suffix(".mp3")
        cmd = ["edge-tts", "--voice", self.voice, "--text", text,
               "--write-media", str(out)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=True)
        except FileNotFoundError as e:
            raise RuntimeError("edge-tts не установлен (pip install edge-tts)") from e
        except subprocess.CalledProcessError as e:
            # чистим пустые файлы, чтобы следующий бэкенд/fallback писал начисто
            Path(out).unlink(missing_ok=True)
            raise RuntimeError(f"edge-tts ошибка: {e.stderr[-200:]}") from e
        if not out.exists() or out.stat().st_size == 0:
            # Microsoft endpoint вернул пустоту (блокировка/ошибка голоса) —
            # удаляем мусор и падаем ПОНЯТНОЙ ошибкой, чтобы registry/fallback
            # мог подхватить другой TTS-бэкенд.
            out.unlink(missing_ok=True)
            raise RuntimeError(
                f"edge-tts: голос '{self.voice}' вернул пустой аудио (сервис недоступен "
                f"или блокирует регион). Смените voice или backend в config/settings.yaml")
        duration = self._probe_duration(str(out))
        return {"path": str(out), "duration": duration, "words": None}

    @staticmethod
    def _probe_duration(path: str) -> float:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", path], capture_output=True, text=True, timeout=30)
            return float(json.loads(r.stdout)["format"]["duration"])
        except Exception:  # noqa: BLE001
            return 0.0
