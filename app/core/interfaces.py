"""Единые интерфейсы всех подключаемых компонентов.

Бизнес-логика (process/, pipeline/) зависит ТОЛЬКО от этого файла.
Любая реализация (Ollama, OpenAI, Piper, XTTS...) обязана реализовать ABC ниже —
и тогда она меняется одной строкой в config/settings.yaml без правок кода.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from .models import MediaRef, NewsItem


# ------------------------- ИИ-слой -------------------------

class ILLM(ABC):
    """Текстовая LLM: классификация, генерация выкладок и сценариев."""

    @abstractmethod
    def complete(self, prompt: str, *, json_schema: Optional[dict] = None,
                 temperature: float = 0.1, max_tokens: int = 1024) -> str:
        ...

    @property
    @abstractmethod
    def name(self) -> str:  # для метаданных model_used
        ...


class IEmbedder(ABC):
    """Эмбеддинги для дедупликации/кластеризации."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class IASR(ABC):
    """Распознавание речи (видео/аудио из источников)."""

    @abstractmethod
    def transcribe(self, media: MediaRef, *, word_timestamps: bool = False) -> dict[str, Any]:
        """-> {"text": str, "words": [{"w": str, "start": float, "end": float}, ...]}"""


class ITTS(ABC):
    """Голос диктора (Этап B)."""

    @abstractmethod
    def synthesize(self, text: str, out_path: str) -> dict[str, Any]:
        """-> {"path": out_path, "duration": float, "words": [...] | None}"""


class IVision(ABC):
    """Подпись изображений — для видеоряда, альтов и поиска релевантных картинок."""

    @abstractmethod
    def caption(self, image: MediaRef, question: str = "Что изображено?") -> str: ...


# ------------------------- Слой источников -------------------------

class ISource(ABC):
    """Плагин источника. Реестр типов -> классы см. registry.py."""

    def __init__(self, cfg: dict, http: Any):
        self.cfg = cfg
        self.http = http

    @abstractmethod
    async def fetch(self, since_ts: float) -> list[NewsItem]:
        """Вернуть новые материалы, опубликованные позже since_ts."""


# ------------------------- Слой выдачи -------------------------

class ISink(ABC):
    """Куда публикуем результат: консоль, файл, БД, Telegram-канал."""

    @abstractmethod
    async def emit(self, brief: Any) -> None: ...
