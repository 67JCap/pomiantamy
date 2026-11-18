"""JSONL sink — машиночитаемый лог всех выкладок (для БД/аналитики/Этапа B)."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from app.core.interfaces import ISink
from app.core.registry import register


@register("sink", "jsonl")
class JsonlSink(ISink):
    def __init__(self, path: str = "data/briefs.jsonl", **_):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def emit(self, brief) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dataclasses.asdict(brief), ensure_ascii=False, default=str) + "\n")
