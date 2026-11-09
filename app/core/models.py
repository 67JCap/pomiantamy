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
    url: str                      # исходная ссылка (всегда сохраняем для выдачи пользователю)
    local_path: Optional[str] = None   # путь после скачивания (media_harvest)
    caption: Optional[str] = None      # из vision-модели (IVision.caption)
    transcript: Optional[str] = None   # из ASR-модели (IASR.transcribe)
    sha256: Optional[str] = None


@dataclass
class NewsItem:
    """Единица входящего сообщения от источника (ещё не событие)."""
    id: str
    source_id: str
    url: str                                  # ссылка на первоисточник — обязательна
    title: str
    text: str
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    language: str = "ru"
    media: list[MediaRef] = field(default_factory=list)
    source_weight: float = 0.5
    tags: list[str] = field(default_factory=list)

    @staticmethod
    def make_id(source_id: str, url: str) -> str:
        import hashlib
        return hashlib.sha256(f"{source_id}|{url}".encode()).hexdigest()[:16]


@dataclass
class Event:
    """Событие = кластер дублов NewsItem из одного или нескольких источников."""
    event_id: str
    items: list[NewsItem]
    category: Optional[Category] = None
    confidence: float = 0.0
    confirmed_by: int = 0                     # число независимых источников
    geoloc: Optional[str] = None

    @property
    def best_item(self) -> NewsItem:
        return max(self.items, key=lambda i: i.source_weight)


@dataclass
class Brief:
    """Настраиваемая краткая выкладка — финальный продукт Этапа A."""
    event_id: str
    style: str                                # terse | standard | detailed
    text: str
    links: list[str]                          # ссылки на все источники события
    media: list[MediaRef]                     # картинки/видео, связанные с новостью
    category: Category
    confirmed_by: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    model_used: str = ""                      # метаданные: какая модель сгенерировала
