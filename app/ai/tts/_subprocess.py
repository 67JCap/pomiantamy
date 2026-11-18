"""Общий помощник: запуск внешних CLI (piper, ffmpeg) без python-зависимостей."""
from __future__ import annotations

import shutil
import subprocess


def run_cli(cmd: list[str], *, timeout: int = 300) -> str:
    """Выполнить команду; вернуть stdout. При ошибке — понятное исключение."""
    if not shutil.which(cmd[0]):
        raise RuntimeError(f"CLI '{cmd[0]}' не найден в PATH. Установите его или смените backend в config/settings.yaml")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} завершился с кодом {p.returncode}: {p.stderr[-500:]}")
    return p.stdout


def which(name: str) -> bool:
    return shutil.which(name) is not None
