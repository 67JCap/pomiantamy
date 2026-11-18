import unittest

from app.ingest.article import extract_article


class ArticleExtractionTests(unittest.TestCase):
    def test_extracts_article_body_and_ignores_navigation(self):
        html = """
        <html><head>
          <meta property="og:description" content="Краткое описание." />
        </head><body>
          <nav><p>Навигационный текст, который не должен попасть в статью.</p></nav>
          <main><article>
            <h1>Заголовок настоящей статьи</h1>
            <p>Первый абзац публикации содержит достаточно подробное описание события,
            обстоятельств и сведений, приведённых непосредственно в материале издания.</p>
            <p>Второй абзац продолжает изложение и содержит дополнительную информацию
            о хронологии, участниках события и сообщённых журналистами подробностях.</p>
          </article></main>
          <aside><p>Похожие материалы и рекламная информация не относятся к статье.</p></aside>
        </body></html>
        """
        result = extract_article(html, min_chars=150)
        self.assertEqual(result.status, "full")
        self.assertEqual(result.title, "Заголовок настоящей статьи")
        self.assertIn("Первый абзац публикации", result.text)
        self.assertNotIn("Навигационный текст", result.text)
        self.assertNotIn("Похожие материалы", result.text)

    def test_metadata_is_not_mislabeled_as_full_text(self):
        html = """
        <html><head>
          <meta property="og:title" content="Короткая новость" />
          <meta property="og:description" content="Только краткое описание публикации." />
        </head><body><nav>Меню</nav></body></html>
        """
        result = extract_article(html, min_chars=150)
        self.assertEqual(result.status, "metadata_only")
        self.assertEqual(result.title, "Короткая новость")
        self.assertEqual(result.text, "Только краткое описание публикации.")

    def test_uses_jsonld_article_body(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type":"NewsArticle","headline":"Заголовок JSON-LD",
         "articleBody":"Первый абзац JSON-LD содержит достаточно полный текст новости. "
         "Второй фрагмент добавляет детали и контекст публикации для читателя."}
        </script>
        </head><body></body></html>
        """
        result = extract_article(html, min_chars=80)
        self.assertEqual(result.status, "full")
        self.assertEqual(result.title, "Заголовок JSON-LD")
        self.assertIn("полный текст новости", result.text)


if __name__ == "__main__":
    unittest.main()
