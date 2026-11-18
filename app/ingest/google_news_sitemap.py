"""Google News Sitemap источник с загрузкой полного текста статей."""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.core.interfaces import ISource
from app.core.models import NewsItem
from app.core.registry import register
from app.ingest.article import ArticleContent, extract_article


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    title: str
    published_at: datetime
    language: str


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_news_sitemap(xml_content: bytes | str, since_ts: float = 0) -> list[SitemapEntry]:
    """Чистый парсер Google News Sitemap; удобен для тестов без сети."""
    root = ET.fromstring(xml_content)
    entries: list[SitemapEntry] = []

    for node in root.findall(f".//{_tag(SITEMAP_NS, 'url')}"):
        loc = (node.findtext(_tag(SITEMAP_NS, "loc")) or "").strip()
        news = node.find(_tag(NEWS_NS, "news"))
        if not loc or news is None:
            continue

        title = (news.findtext(_tag(NEWS_NS, "title")) or "").strip()
        date_value = (
            news.findtext(_tag(NEWS_NS, "publication_date")) or ""
        ).strip()
        publication = news.find(_tag(NEWS_NS, "publication"))
        language = (
            publication.findtext(_tag(NEWS_NS, "language"))
            if publication is not None else None
        ) or "und"
        published_at = _parse_datetime(date_value)

        if not title or published_at is None or published_at.timestamp() <= since_ts:
            continue

        entries.append(SitemapEntry(
            url=loc,
            title=title,
            published_at=published_at,
            language=language.strip(),
        ))

    return sorted(entries, key=lambda item: item.published_at, reverse=True)


def _same_site(article_url: str, sitemap_url: str) -> bool:
    article_host = (urlparse(article_url).hostname or "").lower()
    sitemap_host = (urlparse(sitemap_url).hostname or "").lower()
    root_host = sitemap_host.removeprefix("by.")
    return bool(
        article_host
        and root_host
        and (article_host == root_host or article_host.endswith("." + root_host))
    )


@register("source", "google_news_sitemap")
class GoogleNewsSitemapSource(ISource):
    async def fetch(self, since_ts: float) -> list[NewsItem]:
        source_id = self.cfg["id"]
        sitemap_url = self.cfg["url"]
        response = await self.http.get(
            sitemap_url,
            headers={"Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Google News Sitemap вернул HTTP {response.status_code}: {sitemap_url}"
            )

        entries = parse_news_sitemap(response.content, since_ts)
        limit = max(1, int(self.cfg.get("limit", 30)))
        entries = entries[:limit]
        semaphore = asyncio.Semaphore(max(1, int(self.cfg.get("max_concurrency", 3))))
        min_chars = int(self.cfg.get("min_article_chars", 220))

        async def load_one(entry: SitemapEntry) -> NewsItem:
            content = ArticleContent(
                title=entry.title, text="", description="", status="metadata_only"
            )
            async with semaphore:
                if not _same_site(entry.url, sitemap_url):
                    print(
                        f"[{source_id}] пропущена внешняя ссылка из sitemap: {entry.url}"
                    )
                else:
                    try:
                        page = await self.http.get(
                            entry.url,
                            headers={"Accept": "text/html,application/xhtml+xml"},
                        )
                        if page.status_code == 200:
                            content = extract_article(page.text, min_chars=min_chars)
                        else:
                            print(
                                f"[{source_id}] статья вернула HTTP "
                                f"{page.status_code}: {entry.url}"
                            )
                    except Exception as exc:  # одна статья не должна ломать весь источник
                        print(f"[{source_id}] не удалось загрузить статью {entry.url}: {exc}")

            title = content.title or entry.title
            return NewsItem(
                id=NewsItem.make_id(source_id, entry.url),
                source_id=source_id,
                url=entry.url,
                title=title,
                text=content.text,
                published_at=entry.published_at,
                language=entry.language,
                source_weight=float(self.cfg.get("weight", 0.8)),
                tags=list(self.cfg.get("tags", [])),
                content_status=content.status,
            )

        return await asyncio.gather(*(load_one(entry) for entry in entries))
