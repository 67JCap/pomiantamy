"""Видеоряд по релевантности: картинки события ранжируются под текст новости.

Релевантность считается через IEmbedder (текст↔изображение-подпись) — т.е.
полностью зависит от подключённых бэкендов из YAML, а не от хардкода.
Если IVision недоступен — берём порядок «как в источнике» (graceful degradation).
"""
from __future__ import annotations

from app.core.interfaces import IEmbedder, IVision
from app.core.models import MediaRef, MediaType


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def rank_media(media: list[MediaRef], query_text: str, *,
               embedder: IEmbedder | None = None,
               vision: IVision | None = None,
               limit: int = 8) -> list[MediaRef]:
    images = [m for m in media if m.type == MediaType.IMAGE]
    videos = [m for m in media if m.type == MediaType.VIDEO]
    if not embedder or not vision or not images:
        return (images + videos)[:limit]

    # подписываем картинки (кэш в m.caption, чтобы не переписывать при повторе)
    try:
        for m in images:
            if m.caption is None and m.local_path:
                m.caption = vision.caption(m)
    except Exception:  # noqa: BLE001 — vision-модель упала: работаем без ранжирования
        return (images + videos)[:limit]

    scored = [(m, _cos(*embedder.embed([query_text, m.caption or ""])))
              for m in images if m.caption]
    scored.sort(key=lambda t: t[1], reverse=True)
    ranked_images = [m for m, _ in scored]
    ranked_images += [m for m in images if m not in ranked_images]
    return (ranked_images + videos)[:limit]
