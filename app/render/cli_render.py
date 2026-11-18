"""Боевой прогон Этапа B: JSONL-выкладки -> VideoNewsRenderer.

Компоненты (LLM/TTS/Embedder/Vision) собираются через registry из YAML —
здесь нет ни одного имени модели. Запуск: python -m app.cli render
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from app.core.models import Brief, MediaRef, MediaType, Category
from app.core.registry import resolve, resolve_with_fallback


def brief_from_dict(d: dict) -> Brief:
    media = [MediaRef(MediaType(m["type"]), url=m["url"], local_path=m.get("local_path"))
             for m in d.get("media", [])]
    return Brief(event_id=d["event_id"], style=d.get("style", "standard"),
                 text=d["text"], links=d.get("links", []), media=media,
                 category=Category(d.get("category", "иное")),
                 confirmed_by=d.get("confirmed_by", 1),
                 model_used=d.get("model_used", ""))


def run_render(briefs_path: str, config_path: str, limit: int = 5) -> None:
    from app.pipeline.dag import Config
    from app.render.video_news import VideoNewsRenderer

    cfg = Config(config_path)
    tts = resolve_with_fallback("tts", cfg.get("ai", "tts"))
    llm = vision = embedder = None
    try:
        llm = resolve_with_fallback("llm", cfg.get("ai", "llm"))
    except Exception as e:  # noqa: BLE001
        print(f"[render] LLM недоступен ({e}); сценарий = текст выкладки")
    params = cfg.get("video_render", default={}) or {}

    src = Path(briefs_path)
    if not src.exists():
        print(f"[render] нет файла {briefs_path} — сначала выполните `run --once`")
        return
    lines = src.read_text(encoding="utf-8").strip().splitlines()[-limit:]
    renderer = VideoNewsRenderer(tts, params, llm=llm, embedder=embedder, vision=vision)
    for ln in lines:
        br = brief_from_dict(json.loads(ln))
        try:
            meta = renderer.render(br)
            print(f"[render] {br.event_id}: video={meta.get('video')} srt={meta['subtitles_srt']}")
        except Exception as e:  # noqa: BLE001
            print(f"[render] {br.event_id} ошибка: {e}")
