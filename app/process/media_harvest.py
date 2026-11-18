"""Сбор медиа (картинки/видео) для NewsItem перед выдачей пользователю.

Полностью настраивается из config/settings.yaml (секция media_harvest):
размеры, лимиты, домены-исключения — без правок кода. Скачивание идёт через
единый HttpClient (proxy/retry/politeness) — источник не знает про сеть.

Логика:
1) берём MediaRef у источника (RSS enclosure / Telegram-вложение уже заполнены);
2) если локального файла нет, а URL картинки — качаем в data/media/<item_id>/;
3) видео > max_video_mb не качаем целиком — оставляем ссылку (Telegram-посты
   с видео скачивает сам telethon-ридатель, см. telegram_reader).
Деградация: любая ошибка сети не роняет пайплайн, медиа просто остаётся ссылкой.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from app.core.models import MediaRef, MediaType, NewsItem
from app.ingest.http import HttpClient


def _ext_from_url(url: str, default: str) -> str:
    tail = Path(url.split("?")[0]).suffix.lower()
    return tail if tail in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else default


class MediaHarvester:
    def __init__(self, http: HttpClient, params: Optional[dict] = None,
                 data_dir: str = "./data"):
        p = params or {}
        self.http = http
        self.enabled = p.get("enabled", True)
        self.max_images = p.get("max_images_per_item", 4)
        self.max_image_mb = p.get("max_image_mb", 8)
        self.max_video_mb = p.get("max_video_mb", 60)
        self.skip_domains = [d.lower() for d in p.get("skip_domains", [])]
        self.media_root = Path(data_dir) / "media"

    def _allowed(self, url: str) -> bool:
        u = url.lower()
        return not any(d in u for d in self.skip_domains)

    async def harvest(self, item: NewsItem) -> NewsItem:
        """Скачивает отсутствующие локальные медиа; заполняет sha256."""
        if not self.enabled:
            return item
        imgs = 0
        for m in item.media:
            if m.local_path and Path(m.local_path).exists():
                continue
            if not self._allowed(m.url):
                continue
            if m.type == MediaType.IMAGE:
                if imgs >= self.max_images:
                    continue
                imgs += 1
                ok = await self._download(m, ".jpg", self.max_image_mb)
                if ok:
                    m.sha256 = _sha256(m.local_path)
            elif m.type == MediaType.VIDEO:
                # целое видео тянем только если источник явно разрешил (small clips)
                await self._download(m, ".mp4", self.max_video_mb)
        return item

    async def _download(self, m: MediaRef, default_ext: str, max_mb: float) -> bool:
        try:
            folder = self.media_root / hashlib.sha1(m.url.encode()).hexdigest()[:12]
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / ("file" + _ext_from_url(m.url, default_ext))
            if dest.exists() and dest.stat().st_size <= max_mb * 1e6:
                m.local_path = str(dest)
                return True
            if await self.http.download(m.url, str(dest)):
                if dest.stat().st_size <= max_mb * 1e6:
                    m.local_path = str(dest)
                    return True
                dest.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 — сеть никогда не роняет пайплайн
            pass
        return False


def _sha256(path: Optional[str]) -> Optional[str]:
    if not path or not Path(path).exists():
        return None
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()[:16]
