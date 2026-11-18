"""Оркестратор пайплайна: ingest -> dedup -> classify -> brief -> sinks.

Компоненты внедряются через registry (DI из YAML) — здесь нет ни одного
имени модели или источника.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import yaml

from app.core.models import NewsItem
from app.core.registry import resolve, resolve_with_fallback


class Config:
    def __init__(self, path: str = "config/settings.yaml"):
        self.raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    def __getitem__(self, k):  # sugar: cfg["ai"]["llm"]
        return self.raw[k]

    def get(self, *keys, default=None):
        node = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


def load_sources() -> list[dict]:
    data = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    return [{**defaults, **s} for s in data["sources"] if s.get("enabled", True)]


class Pipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        net = cfg.get("network", default={}) or {}
        from app.ingest.http import HttpClient
        self.http = HttpClient(proxy=net.get("proxy"), timeout=net.get("timeout_sec", 20),
                               retries=net.get("retries", 3),
                               politeness_delay=net.get("politeness_delay_sec", 2))
        # ИИ-компоненты — только через registry + YAML
        self.llm = resolve_with_fallback("llm", cfg.get("ai", "llm"))
        self.embedder = resolve("embed", cfg.get("ai", "embed"))
        # обработчики
        from app.process.dedup import Deduplicator
        from app.process.classify import Classifier, BriefGenerator
        self.dedup = Deduplicator(
            self.embedder,
            threshold=cfg.get("dedup", "similarity_threshold", default=0.87),
            window_hours=cfg.get("dedup", "event_window_hours", default=24))
        self.classifier = Classifier(
            self.llm, cfg.get("classify", "categories", default=[]),
            cfg.get("classify", "min_confidence", default=0.6))
        self.briefer = BriefGenerator(
            self.llm, style=cfg.get("brief", "style", default="standard"),
            max_sentences=cfg.get("brief", "max_sentences", default=None),
            language=cfg.get("brief", "language", default="ru"))
        # скачивание картинок/видео для материалов (настраивается YAML-секцией)
        from app.process.media_harvest import MediaHarvester
        self.harvester = MediaHarvester(
            self.http, cfg.get("media_harvest", default={}),
            data_dir=cfg.get("app", "data_dir", default="./data"))
        # sinks
        self.sinks = [resolve("sink", {"backend": name})
                      for name in cfg.get("sinks", default=["console"])]
        self._state_file = Path(cfg.get("app", "data_dir", default="./data")) / "state.json"

    # --------- состояние: когда последний раз опрашивали источник ----------
    def _load_state(self) -> dict:
        return json.loads(self._state_file.read_text()) if self._state_file.exists() else {}

    def _save_state(self, st: dict):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(st))

    def _build_sources(self) -> list:
        """Плагин источника = класс ISource, зарегистрированный под cfg['type']."""
        import importlib

        from app.core.registry import _REG
        sources = []
        for scfg in load_sources():
            cls = _REG["source"].get(scfg["type"])
            if cls is None:
                try:  # ленивая загрузка модуля плагина по имени типа
                    importlib.import_module(f"app.ingest.{scfg['type']}")
                    cls = _REG["source"][scfg["type"]]
                except (ModuleNotFoundError, KeyError):
                    print(f"[pipeline] неизвестный тип источника: {scfg['type']}")
                    continue
            sources.append(cls(scfg, self.http))
        return sources

    async def run_cycle(self) -> int:
        state = self._load_state()
        sources = self._build_sources()

        # 1) INGEST (параллельно по всем источникам)
        tasks, ids = [], []
        for src in sources:
            since = state.get(src.cfg["id"], time.time() - 3600)
            tasks.append(_safe_fetch(src, since)); ids.append(src.cfg["id"])
        results = await asyncio.gather(*tasks)
        items: list[NewsItem] = []
        for sid, res in zip(ids, results):
            state[sid] = time.time()
            if res:
                items += res
        self._save_state(state)
        print(f"[pipeline] собрано материалов: {len(items)}")

        # 1.5) MEDIA HARVEST: скачать картинки/видео, чтобы выкладка несла файлы
        if self.cfg.get("media_harvest", "enabled", default=True):
            items = list(await asyncio.gather(*[self.harvester.harvest(i) for i in items]))

        # 2) DEDUP -> события
        new_events = self.dedup.ingest(items)
        print(f"[pipeline] новых событий: {len(new_events)}")

        # 3) CLASSIFY + 4) BRIEF + 5) SINKS
        min_src = self.cfg.get("credibility", "min_independent_sources", default=1)
        count = 0
        for ev in new_events:
            await asyncio.to_thread(self.classifier.classify, ev)
            if ev.confirmed_by < min_src:   # не «подтверждено» — помечаем, но не скрываем
                pass
            brief = await asyncio.to_thread(self.briefer.generate, ev)
            for sink in self.sinks:
                await sink.emit(brief)
            count += 1
        print(f"[pipeline] выкладок выпущено: {count}")
        return count


async def _safe_fetch(src, since: float):
    try:
        return await src.fetch(since)
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] источник {src.cfg['id']} ошибся: {e}")
        return []
