"""Sink Этапа B: публикация в Telegram-канал (фото-альбом, видео или текст).

Зависит только от Telethon (ISink-контракт) и конфига. Секреты — из env
(TG_API_ID/TG_API_HASH/TG_BOT_TOKEN), в коде их нет. Если telethon не
установлен или канал не задан — sink логично деградирует в dry-run,
не ломая пайплайн.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.core.interfaces import ISink
from app.core.registry import register
from app.core.models import MediaType


@register("sink", "telegram_channel")
class TelegramChannelSink(ISink):
    def __init__(self, channel_username: str | None = None,
                 api_id_env: str = "TG_API_ID", api_hash_env: str = "TG_API_HASH",
                 session_dir: str = "./data/tg", mode: str = "auto", **_):
        """mode: auto (текст+медиа; видео-ролик если уже отрендерен) | text | dry."""
        self.channel = channel_username
        self.api_id_env, self.api_hash_env = api_id_env, api_hash_env
        self.session_dir = Path(session_dir)
        self.mode = mode
        self._client = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        from telethon import TelegramClient  # импорт здесь => пакет опционален
        api_id, api_hash = os.getenv(self.api_id_env), os.getenv(self.api_hash_env)
        if not api_id or not api_hash:
            raise RuntimeError(f"env {self.api_id_env}/{self.api_hash_env} не заданы")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._client = TelegramClient(str(self.session_dir / "bot"), int(api_id), api_hash)
        await self._client.connect()
        return self._client

    async def emit(self, brief) -> None:
        text = (f"<b>[{brief.category.value}]</b> {brief.text}\n\n"
                + "\n".join(f'🔗 <a href="{l}">источник</a>' for l in brief.links[:6]))
        if self.mode == "dry" or not self.channel:
            print(f"[tg-dry] в канал {self.channel or 'N/A'}:\n{text[:200]}…")
            return
        client = await self._get_client()
        video = Path(f"data/videos/{brief.event_id}.mp4")
        try:
            if video.exists():
                await client.send_file(self.channel, str(video), caption=text[:900])
            else:
                imgs = [m.local_path for m in brief.media
                        if m.type == MediaType.IMAGE and m.local_path][:5]
                if imgs and self.mode == "auto":
                    await client.send_file(self.channel, imgs, caption=text[:900])
                else:
                    await client.send_message(self.channel, text, parse_mode="html")
        except Exception as e:  # noqa: BLE001 — публикация не должна ронять цикл
            print(f"[tg-sink] ошибка публикации {brief.event_id}: {e}")
