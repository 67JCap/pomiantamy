"""Классификация и генерация выкладок. Зависит только от ILLM + файлы промптов."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.interfaces import ILLM
from app.core.models import Brief, Category, Event

CLASSIFY_SCHEMA = {
    "name": "classification",
    "schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": [c.value for c in Category]},
            "confidence": {"type": "number"},
            "geoloc": {"type": ["string", "null"]},
        },
        "required": ["category", "confidence"],
    },
}


def _load_prompt(name: str) -> str:
    return (Path("config/prompts") / name).read_text(encoding="utf-8")


class Classifier:
    def __init__(self, llm: ILLM, categories: list[str], min_confidence: float = 0.6):
        self.llm = llm
        self.categories = categories
        self.min_confidence = min_confidence

    def classify(self, event: Event) -> None:
        tpl = _load_prompt("classify.txt")
        prompt = tpl.format(
            categories=json.dumps(self.categories, ensure_ascii=False),
            title=event.best_item.title,
            text="\n\n".join(f"[{i.source_id}] {i.text[:900]}" for i in event.items[:5]),
        )
        raw = self.llm.complete(prompt, json_schema=CLASSIFY_SCHEMA, temperature=0.0)
        data = _extract_json(raw)
        try:
            cat = Category(data["category"])
        except (ValueError, KeyError):
            cat = Category.OTHER
        conf = float(data.get("confidence", 0))
        if conf >= self.min_confidence:
            event.category = cat
            event.confidence = conf
            event.geoloc = data.get("geoloc")
        else:
            event.category = Category.OTHER
            event.confidence = conf


class BriefGenerator:
    """Настраиваемая краткая выкладка уровня terse/standard/detailed."""

    def __init__(self, llm: ILLM, style: str = "standard",
                 max_sentences: dict | None = None, language: str = "ru"):
        self.llm = llm
        self.style = style
        self.max_sentences = max_sentences or {"terse": 2, "standard": 4, "detailed": 8}
        self.language = language

    def generate(self, event: Event) -> Brief:
        n_src = len({i.source_id for i in event.items})
        event.confirmed_by = n_src
        links = [i.url for i in event.items]
        media = [m for i in event.items for m in i.media]
        category = event.category or Category.OTHER

        # Если ни один источник не дал тело статьи, не просим LLM домысливать факты.
        full_items = [i for i in event.items
                      if i.content_status != "metadata_only" and len(i.text.strip()) >= 180]
        if not full_items:
            title = event.best_item.title
            text = (
                f"Недостаточно текста первоисточника для достоверной сводки. "
                f"Доступен только заголовок: «{title}». "
                f"Откройте оригинальную публикацию для проверки подробностей."
            )
            return Brief(
                event_id=event.event_id,
                style=self.style,
                text=text,
                links=links,
                media=media,
                category=category,
                confirmed_by=n_src,
                model_used="not-generated/insufficient-source-text",
            )

        tpl = _load_prompt("summarize_brief.txt")
        prompt = tpl.format(
            style=self.style,
            max_sentences=self.max_sentences.get(self.style, 4),
            language=self.language,
            category=category.value,
            confirmed_by=n_src,
            sources="\n".join(f"- {i.url}" for i in event.items),
            content="\n\n".join(
                f"[{i.source_id}] {i.title}\nСтатус текста: полный текст статьи.\n{i.text[:5000]}"
                for i in full_items[:6]
            ),
        )
        text = self.llm.complete(prompt, temperature=0.1).strip()
        return Brief(
            event_id=event.event_id,
            style=self.style,
            text=text,
            links=links,
            media=media,
            category=category,
            confirmed_by=n_src,
            model_used=self.llm.name,
        )


def _extract_json(raw: str) -> dict:
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        return {}
