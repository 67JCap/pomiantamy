"""Извлечение основного текста новостной статьи без тяжёлых зависимостей.

Используется стандартный HTMLParser. Если тело статьи извлечь не удалось,
возвращаем только метаданные со статусом metadata_only: такой материал нельзя
передавать LLM для генерации фактической сводки.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser


_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

_SKIP_TAGS = {
    "nav", "footer", "aside", "script", "style", "noscript", "svg",
    "form", "button", "iframe", "template", "select", "option",
}
_NOISE_RE = re.compile(
    r"(?:^|[\s_-])(?:navigation|navbar|menu|breadcrumb|breadcrumbs|"
    r"share|sharing|social|related|comments?|cookie|advert(?:isement)?|"
    r"sidebar|pagination|subscribe|newsletter|promo|toolbar|"
    r"site-header|site-footer|article-tags|author-box)(?:$|[\s_-])",
    re.IGNORECASE,
)
_SEMANTIC_RE = re.compile(
    r"(?:article|post|entry|story|news)[\w_-]*(?:body|content|text)|"
    r"(?:body|content|text)[\w_-]*(?:article|post|entry|story|news)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ArticleContent:
    title: str
    text: str
    description: str
    status: str  # "full" или "metadata_only"


def _plain_text(value: str) -> str:
    value = unescape(_TAG_RE.sub(" ", value or ""))
    return _SPACE_RE.sub(" ", value).strip()


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, object]] = []
        self.meta: dict[str, str] = {}
        self.paragraphs: list[tuple[str, bool]] = []
        self.headings: list[str] = []
        self._paragraph: list[str] | None = None
        self._paragraph_semantic = False
        self._heading: list[str] | None = None
        self._jsonld_active = False
        self._jsonld_parts: list[str] = []
        self.jsonld_bodies: list[str] = []
        self.jsonld_titles: list[str] = []
        self.jsonld_descriptions: list[str] = []

    def _is_skipped(self) -> bool:
        return any(bool(frame["skip"]) for frame in self.stack)

    def _is_semantic(self) -> bool:
        return any(bool(frame["semantic"]) for frame in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            value = attr.get("content", "").strip()
            if key and value:
                self.meta[key] = value

        classes = f'{attr.get("id", "")} {attr.get("class", "")}'.lower()
        parent_skip = self._is_skipped()
        parent_semantic = self._is_semantic()
        own_noise = bool(_NOISE_RE.search(classes))
        skip = parent_skip or tag in _SKIP_TAGS or own_noise
        semantic = (
            parent_semantic
            or tag in {"article", "main"}
            or bool(_SEMANTIC_RE.search(classes))
        )
        self.stack.append({"tag": tag, "skip": skip, "semantic": semantic})

        if tag == "script" and "application/ld+json" in attr.get("type", "").lower():
            self._jsonld_active = True
            self._jsonld_parts = []

        if tag == "p" and not skip:
            if self._paragraph is not None:
                self._finish_paragraph()
            self._paragraph = []
            self._paragraph_semantic = semantic

        if tag == "h1" and not skip:
            if self._heading is not None:
                self._finish_heading()
            self._heading = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._jsonld_active:
            self._jsonld_parts.append(data)
            return
        if self._is_skipped():
            return
        if self._paragraph is not None:
            self._paragraph.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._paragraph is not None:
            self._finish_paragraph()
        if tag == "h1" and self._heading is not None:
            self._finish_heading()
        if tag == "script" and self._jsonld_active:
            self._consume_jsonld("".join(self._jsonld_parts))
            self._jsonld_active = False
            self._jsonld_parts = []

        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def close(self) -> None:
        super().close()
        if self._paragraph is not None:
            self._finish_paragraph()
        if self._heading is not None:
            self._finish_heading()
        if self._jsonld_active:
            self._consume_jsonld("".join(self._jsonld_parts))
            self._jsonld_active = False

    def _finish_paragraph(self) -> None:
        text = _SPACE_RE.sub(" ", "".join(self._paragraph or [])).strip()
        if len(text) >= 35:
            self.paragraphs.append((text, self._paragraph_semantic))
        self._paragraph = None
        self._paragraph_semantic = False

    def _finish_heading(self) -> None:
        text = _SPACE_RE.sub(" ", "".join(self._heading or [])).strip()
        if text:
            self.headings.append(text)
        self._heading = None

    def _consume_jsonld(self, raw: str) -> None:
        try:
            payload = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError):
            return

        def walk(node: object) -> None:
            if isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, dict):
                body = node.get("articleBody")
                headline = node.get("headline")
                description = node.get("description")
                if isinstance(body, str) and body.strip():
                    self.jsonld_bodies.append(_plain_text(body))
                if isinstance(headline, str) and headline.strip():
                    self.jsonld_titles.append(_plain_text(headline))
                if isinstance(description, str) and description.strip():
                    self.jsonld_descriptions.append(_plain_text(description))
                for key in ("@graph", "mainEntity", "mainEntityOfPage"):
                    if key in node:
                        walk(node[key])

        walk(payload)


def extract_article(html: str, min_chars: int = 220) -> ArticleContent:
    """Извлечь заголовок и тело статьи; не выдавать description за полный текст."""
    parser = _ArticleHTMLParser()
    parser.feed(html or "")
    parser.close()

    title = (
        (parser.headings[0] if parser.headings else "")
        or parser.jsonld_titles[0] if parser.jsonld_titles else ""
    )
    title = title or parser.meta.get("og:title", "") or parser.meta.get("twitter:title", "")
    title = _plain_text(title)

    semantic_paragraphs = [text for text, semantic in parser.paragraphs if semantic]
    all_paragraphs = [text for text, _ in parser.paragraphs]
    selected = semantic_paragraphs or all_paragraphs
    body = "\n\n".join(selected)

    jsonld_body = max(parser.jsonld_bodies, key=len, default="")
    if len(jsonld_body) > len(body):
        body = jsonld_body

    # Не считаем заголовок/description полноценным телом публикации.
    if len(body) >= max(100, int(min_chars)):
        return ArticleContent(
            title=title,
            text=body,
            description=parser.meta.get("og:description")
            or parser.meta.get("description")
            or max(parser.jsonld_descriptions, key=len, default=""),
            status="full",
        )

    description = (
        parser.meta.get("og:description")
        or parser.meta.get("description")
        or max(parser.jsonld_descriptions, key=len, default="")
    )
    return ArticleContent(
        title=title,
        text=_plain_text(description),
        description=_plain_text(description),
        status="metadata_only",
    )
