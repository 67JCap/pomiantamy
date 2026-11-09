"""Консольный sink — для разработки и превью выкладок."""
from __future__ import annotations

from app.core.interfaces import ISink
from app.core.registry import register


@register("sink", "console")
class ConsoleSink(ISink):
    def __init__(self, **_):
        pass

    async def emit(self, brief) -> None:
        print("\n" + "=" * 70)
        print(f"[{brief.category.value}] событие {brief.event_id} "
              f"(источников: {brief.confirmed_by}, модель: {brief.model_used})")
        print(brief.text)
        print("Ссылки:")
        for l in brief.links:
            print("  •", l)
        if brief.media:
            print(f"Медиа: {len(brief.media)} шт.")
            for m in brief.media[:5]:
                print(f"  [{m.type.value}] {m.local_path or m.url}")
