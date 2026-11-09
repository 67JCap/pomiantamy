"""ffmpeg-сборщик видеоряда: картинки-слайды + озвучка диктора + субтитры.

Зависимость только от системного ffmpeg (проверяется в рантайме).
Вход — список локальных картинок и аудио; выход — mp4 для Telegram.
Все параметры (разрешение, длительность слайда, fps) передаёт VideoNewsRenderer
из config/settings.yaml — здесь нет ни одного «вечного» значения.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class FFmpegError(RuntimeError):
    pass


def check_ffmpeg() -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise FFmpegError("ffmpeg не найден в PATH — установите его (apt install ffmpeg)") from e


def probe_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", path], capture_output=True, text=True, timeout=30)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def black_frame(w: int, h: int) -> Path:
    """Заглушка, если медиа не собрано — чёрный фон вместо падения сборки."""
    p = Path("data/tmp/black.png")
    p.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:s={w}x{h}:d=1", "-frames:v", "1", str(p)],
                   capture_output=True, check=True, timeout=60)
    return p


def render_slideshow(images: list[str], audio_path: str, out_path: str,
                     *, width: int = 1280, height: int = 720, fps: int = 30,
                     subtitle_file: str | None = None,
                     per_image: float | None = None) -> dict[str, Any]:
    """Собрать mp4: смена картинок под дорожку диктора, опц. burned-in субтитры."""
    check_ffmpeg()
    images = [p for p in images if p and Path(p).exists()]
    if not images:
        images = [str(black_frame(width, height))]
    total = probe_duration(audio_path) or 20.0
    n = len(images)
    per = per_image or max(total / n, 2.0)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    for img in images:
        inputs += ["-loop", "1", "-t", f"{per:.2f}", "-i", img]
    inputs += ["-i", audio_path]  # индекс n — аудио диктора

    filters = []
    for i in range(n):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}[v{i}]")
    concat_in = "".join(f"[v{i}]" for i in range(n))
    filters.append(f"{concat_in}concat=n={n}:v=1:a=0[vcat]")
    vf = "[vcat]"
    if subtitle_file and Path(subtitle_file).exists():
        safe = subtitle_file.replace("\\", "/").replace(":", r"\:")
        filters.append(f"[vcat]subtitles='{safe}'[vout]")
        vf = "[vout]"

    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", ";".join(filters),
           "-map", vf, "-map", f"{n}:a",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-shortest", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if p.returncode != 0 or not out.exists():
        raise FFmpegError(f"ffmpeg error: {p.stderr[-800:]}")
    return {"path": str(out), "duration": probe_duration(str(out)),
            "images_used": n, "subtitles": bool(subtitle_file)}
