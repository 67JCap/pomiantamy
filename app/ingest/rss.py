"""RSS/Atom источник — реализация ISource. Работает для любого URL из sources.yaml."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import feedparser

from app.core.interfaces import ISource
from app.core.models import NewsItem
from app.core.registry import register


@register("source", "rss")
class RssSource(ISource):
    async def fetch(self, since_ts: float) -> list[NewsItem]:
        sid = self.cfg["id"]
        resp = await self.http.get(self.cfg["url"])
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(io.BytesIO(resp.content))
        items = []
        for e in feed.entries:
            ts = self._entry_ts(e)
            if ts.timestamp() <= since_ts:
                continue  # уже видели в прошлых циклах
            link = e.get("link", "")
            media = []
            if e.get("media_thumbnail"):
                from app.core.models import MediaRef, MediaType
                media += [MediaRef(MediaType.IMAGE, t["url"]) for t in e["media_thumbnail"]]
            enc = e.get("enclosure")
            if enc and "image" in enc.get("type", ""):
                from app.core.models import MediaRef, MediaType
                media.append(MediaRef(MediaType.IMAGE, enc["href"]))
            items.append(NewsItem(
                id=NewsItem.make_id(sid, link),
                source_id=sid,
                url=link,
                title=e.get("title", "").strip(),
                text=self._clean_html(e.get("summary", "")),
                published_at=datetime.fromtimestamp(ts, tz=timezone.utc),
                source_weight=float(self.cfg.get("weight", 0.5)),
                tags=list(self.cfg.get("tags", [])),
                media=media,
            ))
        return items

    @staticmethod
    def _entry_ts(entry) -> datetime:
        p = entry.get("published_parsed") or entry.get("updated_parsed")
        if not p:
            return datetime.now(timezone.utc)
        return datetime(*p[:6], tzinfo=timezone.utc)

    @staticmethod
    def _clean_html(html: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()
