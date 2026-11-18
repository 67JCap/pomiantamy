import unittest
from datetime import datetime, timezone

from app.core.models import Category, Event, NewsItem
from app.process.classify import BriefGenerator


class NoCallLLM:
    name = "must-not-run"

    def complete(self, *args, **kwargs):
        raise AssertionError("LLM must not generate a brief from metadata only")


class BriefSafetyTests(unittest.TestCase):
    def test_metadata_only_item_does_not_call_llm(self):
        item = NewsItem(
            id="1",
            source_id="belsat",
            url="https://belsat.eu/article",
            title="Загаловак навіны",
            text="Кароткае апісанне са старонкі.",
            published_at=datetime.now(timezone.utc),
            content_status="metadata_only",
        )
        event = Event(event_id="event-1", items=[item], category=Category.REPRESSIONS)

        brief = BriefGenerator(NoCallLLM()).generate(event)

        self.assertIn("сводка не создавалась", brief.text)
        self.assertIn(item.title, brief.text)
        self.assertEqual(brief.model_used, "not-generated/insufficient-source-text")


if __name__ == "__main__":
    unittest.main()
