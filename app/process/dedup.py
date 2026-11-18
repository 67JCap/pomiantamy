"""Дедупликация и кластеризация событий. Зависит только от IEmbedder."""
from __future__ import annotations

import uuid
from typing import Iterable

from app.core.interfaces import IEmbedder
from app.core.models import Event, NewsItem


def cosine(a: list[float], b: list[float]) -> float:
    # эмбеддинги нормализованы -> косинус = скалярное произведение
    return sum(x * y for x, y in zip(a, b))


class Deduplicator:
    """Жадный кластерizer: новый item приклеивается к ближайшему событию,
    если сходство >= порога из конфига; иначе создаёт новое событие."""

    def __init__(self, embedder: IEmbedder, threshold: float = 0.87,
                 window_hours: int = 24, capacity: int = 5000):
        self.embedder = embedder
        self.threshold = threshold
        self.window_s = window_hours * 3600
        self.capacity = capacity
        self._events: list[tuple[Event, list[float]]] = []  # (событие, центральный вектор)

    def ingest(self, items: Iterable[NewsItem]) -> list[Event]:
        new_events: list[Event] = []
        items = list(items)
        if not items:
            return new_events
        vectors = self.embedder.embed([f"{i.title}. {i.text[:500]}" for i in items])
        for item, vec in zip(items, vectors):
            best, best_sim = None, 0.0
            for ev, evec in self._events:
                age = abs((ev.items[0].published_at - item.published_at).total_seconds())
                if age > self.window_s:
                    continue
                sim = cosine(vec, evec)
                if sim > best_sim:
                    best, best_sim = ev, sim
            if best is not None and best_sim >= self.threshold:
                best.items.append(item)
                n = len(best.items)  # бегущее среднее центра кластера
                evec = best.__dict__.setdefault("_vec", [])  # храним вектор на объекте
                best_vec = [ (evec[j]*(n-1)+vec[j])/n for j in range(len(vec)) ] if evec else vec
                self._events = [(e, v) for e, v in self._events if e is not best]
                self._events.append((best, best_vec))
            else:
                ev = Event(event_id=uuid.uuid4().hex[:12], items=[item])
                setattr(ev, "_vec", vec)
                self._events.append((ev, vec))
                new_events.append(ev)
        self._trim()
        return new_events

    def all_events(self) -> list[Event]:
        return [e for e, _ in self._events]

    def _trim(self):
        if len(self._events) > self.capacity:
            self._events.sort(key=lambda ev_: max(i.published_at for i in ev_[0].items), reverse=True)
            self._events = self._events[: self.capacity]
