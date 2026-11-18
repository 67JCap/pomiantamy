import unittest
from datetime import datetime, timezone

from app.ingest.google_news_sitemap import parse_news_sitemap


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://belsat.eu/123/story</loc>
    <news:news>
      <news:publication>
        <news:name>Белсат</news:name>
        <news:language>be</news:language>
      </news:publication>
      <news:publication_date>2026-11-18T20:44:00+01:00</news:publication_date>
      <news:title>Загаловак навіны</news:title>
    </news:news>
  </url>
</urlset>'''


class GoogleNewsSitemapTests(unittest.TestCase):
    def test_parses_news_item_and_timezone(self):
        result = parse_news_sitemap(XML, since_ts=0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].url, "https://belsat.eu/123/story")
        self.assertEqual(result[0].title, "Загаловак навіны")
        self.assertEqual(result[0].language, "be")
        self.assertEqual(result[0].published_at.tzinfo, timezone.utc)

    def test_skips_items_older_than_cursor(self):
        cutoff = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(parse_news_sitemap(XML, since_ts=cutoff), [])


if __name__ == "__main__":
    unittest.main()
