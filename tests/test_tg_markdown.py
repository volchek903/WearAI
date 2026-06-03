from __future__ import annotations

import unittest

from app.utils.tg_markdown import render_markdown_to_html_chunks


class TelegramMarkdownTests(unittest.TestCase):
    def test_renders_basic_markdown_to_telegram_html(self) -> None:
        chunks = render_markdown_to_html_chunks(
            "**Жирный** текст и `код`, а еще _курсив_ и [ссылка](https://example.com)"
        )

        self.assertEqual(len(chunks), 1)
        self.assertIn("<b>Жирный</b>", chunks[0])
        self.assertIn("<code>код</code>", chunks[0])
        self.assertIn("<i>курсив</i>", chunks[0])
        self.assertIn('<a href="https://example.com">ссылка</a>', chunks[0])

    def test_renders_headings_rules_and_code_fences(self) -> None:
        chunks = render_markdown_to_html_chunks(
            "### Заголовок\n***\n```python\nprint('hi')\n```"
        )

        self.assertEqual(chunks[0], "<b>Заголовок</b>\n────────")
        self.assertEqual(chunks[1], "<pre><code>print(&#x27;hi&#x27;)</code></pre>")


if __name__ == "__main__":
    unittest.main()
