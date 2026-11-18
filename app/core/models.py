"""Доменные модели данных. Не зависят ни от одной ИИ-модели."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Category(str, Enum):
    ACCIDENTS = "аварии"
    POLITICAL_STATEMENTS = "политические заявления"
    REPRESSIONS = "политические репрессии"
    OPPOSITION_RESPONSES = "ответы оппозиции"
    OTHER = "иное"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


@dataclass
class MediaRef:
    type: MediaType
    url: str
    local_path: Optional[str] = None
    caption: Optional[str] = None
    transcript: Optional[str] = None
    sha256: Optional[str] = None


@dataclass
class NewsItem:
    """Единица входящего сообщения; content_status отражает полноту текста."""
    id: str
    source_id: str
    url: str
    title: str
    text: str
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    language: str = "ru"
    media: list[MediaRef] = field(default_factory=list)
    source_weight: float = 0.5
    tags: list[str] = field(default_factory=list)
    content_status: str = "full"  # full | metadata_only

    @staticmethod
    def make_id(source_id: str, url: str) -> str:
        import hashlib
        return hashlib.sha256(f"{source_id}|{url}".encode()).hexdigest()[:16]


@dataclass
class Event:
    """Событие = кластер дублей NewsItem из одного или нескольких источников."""
    event_id: str
    items: list[NewsItem]
    category: Optional[Category] = None
    confidence: float = 0.0
    confirmed_by: int = 0
    geoloc: Optional[str] = None

    @property
    def best_item(self) -> NewsItem:
        return max(self.items, key=lambda i: i.source_weight)


@dataclass
class Brief:
    """Настраиваемая краткая выкладка — финальный продукт Этапа A."""
    event_id: str
    style: str
    text: str
    links: list[str]
    media: list[MediaRef]
    category: Category
    confirmed_by: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    model_used: str = ""
