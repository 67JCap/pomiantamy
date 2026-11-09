"""Чтение Telegram-каналов через Telethon — главный источник BY-новостей.

Секреты (TG_API_ID/TG_API_HASH) только из переменных окружения.
Медиа (фото/видео постов) скачиваются в data/media и попадают в MediaRef.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from app.core.interfaces import ISource
from app.core.models import MediaRef, MediaType, NewsItem
from app.core.registry import register


@register("source", "telegram")
class TelegramSource(ISource):
    async def fetch(self, since_ts: float) -> list[NewsItem]:
        from telethon import TelegramClient  # ленивый импорт

        api_id = int(os.environ[self.cfg.get("api_id_env", "TG_API_ID")])
        api_hash = os.environ[self.cfg.get("api_hash_env", "TG_API_HASH")]
        handle = self.cfg["handle"]
        sid = self.cfg["id"]

        items: list[NewsItem] = []
        dl_media = bool(self.cfg.get("media_download", True))
        async with TelegramClient(f"data/sessions/{sid}", api_id, api_hash) as client:
            entity = await client.get_entity(handle)
            async for msg in client.iter_messages(entity, min_id=int(since_ts) or 0,
                                                   limit=self.cfg.get("limit", 50)):
                if not msg.text and not msg.media:
                    continue
                media_refs = []
                if dl_media and msg.media:
                    media_refs = await self._harvest_media(client, msg, sid)
                link = f"https://t.me/{handle.lstrip('@')}/{msg.id}"
                items.append(NewsItem(
                    id=NewsItem.make_id(sid, link),
                    source_id=sid,
                    url=self.cfg.get("link_from_buttons", True) and _first_link(msg.text) or link,
                    title=(msg.text or "")[:120].split("\n")[0],
                    text=msg.text or "",
                    published_at=msg.date or datetime.now(timezone.utc),
                    language="ru",
                    media=media_refs,
                    source_weight=float(self.cfg.get("weight", 0.5)),
                    tags=list(self.cfg.get("tags", [])),
                ))
        return items

    @staticmethod
    async def _harvest_media(client, msg, sid: str) -> list[MediaRef]:
        from telethon.tl.types import (MessageMediaPhoto, MessageMediaDocument,
                                       DocumentAttributeVideo, DocumentAttributeFilename)
        out: list[MediaRef] = []
        os.makedirs("data/media", exist_ok=True)
        fname = f"data/media/{sid}_{msg.id}"
        if isinstance(msg.media, MessageMediaPhoto):
            path = await client.download_media(msg, fname + ".jpg")
            if path:
                out.append(MediaRef(MediaType.IMAGE, url=f"tg://{sid}/{msg.id}", local_path=path))
        elif isinstance(msg.media, MessageMediaDocument):
            is_video = any(isinstance(a, DocumentAttributeVideo) for a in msg.media.document.attributes) \
                or any(isinstance(a, DocumentAttributeFilename) and
                       a.file_name.lower().endswith((".mp4", ".mov"))
                       for a in msg.media.document.attributes)
            ext = ".mp4" if is_video else ".bin"
            path = await client.download_media(msg, fname + ext)
            if path:
                t = MediaType.VIDEO if is_video else MediaType.AUDIO
                out.append(MediaRef(t, url=f"tg://{sid}/{msg.id}", local_path=path))
        return out


def _first_link(text: str | None) -> str | None:
    if not text:
        return None
    import re
    m = re.search(r"https?://\S+", text)
    return m.group(0).rstrip(").,") if m else None
