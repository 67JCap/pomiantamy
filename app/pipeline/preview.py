"""Offline-прогон пайплайна на фикстурах с FakeLLM/FakeEmbedder.

Доказывает главное требование проекта: компоненты взаимозаменяемы —
тестовые заглушки подставляются в те же интерфейсы без правок кода.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from app.core.interfaces import IEmbedder, ILLM
from app.core.models import Category, Event, MediaRef, MediaType, NewsItem


class FakeLLM(ILLM):
    """Имитирует поведение модели: JSON для classify, текст для brief."""
    @property
    def name(self) -> str:
        return "fake/llm-test"

    def complete(self, prompt: str, *, json_schema=None, temperature=0.1, max_tokens=1024) -> str:
        if json_schema:  # режим классификации
            low = prompt.lower()
            cat = Category.OTHER.value
            for kw, c in [("дтп", Category.ACCIDENTS), ("авари", Category.ACCIDENTS),
                          ("приговор", Category.REPRESSIONS), ("задержал", Category.REPRESSIONS),
                          ("заявил", Category.POLITICAL_STATEMENTS), ("оппозиц", Category.OPPOSITION_RESPONSES)]:
                if kw in low:
                    cat = c.value
                    break
            return json.dumps({"category": cat, "confidence": 0.9, "geoloc": "Минск"})
        # режим выкладки: берём блок "Материалы:" из промпта как «суммаризацию»
        marker = prompt.find("Материалы:")
        body = prompt[marker + len("Материалы:"):].strip() if marker != -1 else prompt
        first_line = next((l for l in body.splitlines() if l.startswith("[")), "")
        return (first_line[:300] + " … [FakeLLM: тестовая выкладка уровня стиля из промпта]")


class FakeEmbedder(IEmbedder):
    """Хэш-эмбеддинги n-грамм: похожие тексты -> близкие векторы (для теста дедупа)."""
    DIM = 64

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.DIM
            words = t.lower().split()
            for w in words:
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                v[h % self.DIM] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


async def run_preview(fixture_path: str) -> int:
    from app.process.classify import BriefGenerator, Classifier
    from app.process.dedup import Deduplicator
    from app.sinks.console import ConsoleSink
    from app.sinks.jsonl import JsonlSink

    raw = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    items = []
    for r in raw:
        items.append(NewsItem(
            id=NewsItem.make_id(r["source_id"], r["url"]),
            source_id=r["source_id"], url=r["url"], title=r["title"], text=r["text"],
            media=[MediaRef(MediaType.IMAGE, url=m) for m in r.get("media", [])],
            source_weight=r.get("weight", 0.7)))

    llm, emb = FakeLLM(), FakeEmbedder()
    dedup = Deduplicator(emb, threshold=0.5, window_hours=24)
    clf = Classifier(llm, [c.value for c in Category], min_confidence=0.5)
    briefer = BriefGenerator(llm, style="standard")
    sinks = [ConsoleSink(), JsonlSink(path="data/preview_briefs.jsonl")]

    events: list[Event] = dedup.ingest(items)
    print(f"[preview] {len(items)} материалов -> {len(events)} событий")
    briefs = []
    for ev in events:
        clf.classify(ev)
        brief = briefer.generate(ev)
        briefs.append(brief)
        for s in sinks:
            await s.emit(brief)

    if "--video" in sys.argv:
        # Этап B offline: FakeTTS (ITTS) + ffmpeg — полный путь до mp4 без моделей
        from app.ai.tts.fake import FakeTTS
        from app.render.video_news import VideoNewsRenderer
        renderer = VideoNewsRenderer(FakeTTS(), {"rewrite_script": False}, llm=None)
        for br in briefs[:1]:
            meta = renderer.render(br, images=[])
            print(f"[preview][B] видео: {meta.get('video')} "
                  f"(длительность {meta.get('duration')}, субтитры {meta['subtitles_srt']})")
    return len(events)
