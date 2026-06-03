from __future__ import annotations

import io
import unittest
import zipfile
from unittest.mock import patch

from app.repository.agent_settings import AgentToggleState
from app.services.wea_agent import (
    AgentModelConfig,
    SearchResult,
    _build_openrouter_body,
    _extract_web_page_text,
    build_user_question_prompt,
    build_agent_messages,
    extract_document_text,
    extract_openrouter_chat_content,
    extract_openrouter_finish_reason,
    extract_openrouter_stream_delta,
    generate_agent_reply_streaming,
    parse_duckduckgo_lite_results,
    parse_openrouter_sse_event,
    split_user_questions,
)


class WeaAgentHelpersTests(unittest.TestCase):
    def test_parse_duckduckgo_lite_results_extracts_title_url_and_snippet(self) -> None:
        sample_html = """
        <tr>
          <td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fopenrouter.ai%2Fqwen%2F" class='result-link'>Qwen API and Models - OpenRouter</a></td>
        </tr>
        <tr>
          <td class='result-snippet'>Access 75 Qwen models through OpenRouter.</td>
        </tr>
        """

        results = parse_duckduckgo_lite_results(sample_html, limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Qwen API and Models - OpenRouter")
        self.assertEqual(results[0].url, "https://openrouter.ai/qwen/")
        self.assertEqual(results[0].snippet, "Access 75 Qwen models through OpenRouter.")

    def test_parse_duckduckgo_html_results_extracts_title_url_and_snippet(self) -> None:
        sample_html = """
        <div class="result results_links results_links_deep web-result">
          <h2 class="result__title">
            <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftime.is%2FMinsk">Time in Minsk, Belarus now</a>
          </h2>
          <div class="result__extras">
            <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftime.is%2FMinsk">
              Exact time now, time zone, time difference, sunrise/sunset time and key facts for Minsk, Belarus.
            </a>
          </div>
        </div>
        """

        results = parse_duckduckgo_lite_results(sample_html, limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Time in Minsk, Belarus now")
        self.assertEqual(results[0].url, "https://time.is/Minsk")
        self.assertIn("Exact time now", results[0].snippet)

    def test_extract_openrouter_chat_content_supports_content_blocks(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Первая часть"},
                            {"type": "text", "text": "Вторая часть"},
                        ]
                    }
                }
            ]
        }

        text = extract_openrouter_chat_content(payload)

        self.assertEqual(text, "Первая часть\nВторая часть")

    def test_extract_openrouter_stream_delta_supports_string_and_blocks(self) -> None:
        payload_with_string = {
            "choices": [
                {
                    "delta": {
                        "content": "Первая часть",
                    }
                }
            ]
        }
        payload_with_blocks = {
            "choices": [
                {
                    "delta": {
                        "content": [
                            {"type": "text", "text": "Вторая"},
                            {"type": "text", "text": "часть"},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(extract_openrouter_stream_delta(payload_with_string), "Первая часть")
        self.assertEqual(extract_openrouter_stream_delta(payload_with_blocks), "Вторая\nчасть")

    def test_parse_openrouter_sse_event_ignores_comments_and_supports_done(self) -> None:
        raw_json_event = (
            ": OPENROUTER PROCESSING\n"
            "event: message\n"
            'data: {"choices":[{"delta":{"content":"Привет"}}]}\n'
        )

        parsed = parse_openrouter_sse_event(raw_json_event)
        done = parse_openrouter_sse_event("data: [DONE]")

        self.assertEqual(parsed, {"choices": [{"delta": {"content": "Привет"}}]})
        self.assertEqual(done, "[DONE]")

    def test_extract_openrouter_finish_reason(self) -> None:
        payload = {
            "choices": [
                {
                    "finish_reason": "length",
                }
            ]
        }

        self.assertEqual(extract_openrouter_finish_reason(payload), "length")

    def test_extract_document_text_reads_docx(self) -> None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>Привет</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Мир</w:t></w:r></w:p>"
            "</w:body>"
            "</w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", xml)

        text = extract_document_text(
            buf.getvalue(),
            file_name="demo.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        self.assertEqual(text, "Привет\nМир")

    def test_extract_web_page_text_uses_title_meta_and_body(self) -> None:
        page_html = """
        <html>
          <head>
            <title>Текущее время в Минске</title>
            <meta name="description" content="Актуальное время в Минске, Беларусь.">
            <script>console.log('skip');</script>
          </head>
          <body>
            <main>
              <h1>Сейчас в Минске 14:35</h1>
              <p>Разница с UTC составляет +3 часа.</p>
            </main>
          </body>
        </html>
        """

        text = _extract_web_page_text(page_html, quick_mode=False)

        self.assertIn("Текущее время в Минске", text)
        self.assertIn("Актуальное время в Минске, Беларусь.", text)
        self.assertIn("Сейчас в Минске 14:35", text)
        self.assertNotIn("console.log", text)

    def test_split_user_questions_handles_multiple_questions_in_one_sentence(self) -> None:
        questions = split_user_questions("Сколько сейчас времени в Минске и какая там погода?")

        self.assertEqual(
            questions,
            [
                "Сколько сейчас времени в Минске",
                "какая там погода",
            ],
        )

    def test_build_user_question_prompt_enumerates_questions(self) -> None:
        prompt = build_user_question_prompt("Сколько сейчас времени в Минске и какая там погода?")

        self.assertIn("Вопросы пользователя:", prompt)
        self.assertIn("1. Сколько сейчас времени в Минске", prompt)
        self.assertIn("2. какая там погода", prompt)

    def test_build_agent_messages_respects_quick_mode_over_deep_analysis(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=True,
            quick_mode_enabled=True,
            document_session_key="session-1",
        )

        messages = build_agent_messages(
            "Сделай краткий разбор",
            settings=settings,
            history=[],
            documents=[],
            search_results=[],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("WeaRai Agent", messages[0]["content"])
        self.assertIn("быстром режиме", messages[1]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "Сделай краткий разбор"})

    def test_build_agent_messages_with_web_search_includes_page_content(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=True,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )

        messages = build_agent_messages(
            "Сколько сейчас времени в Минске?",
            settings=settings,
            history=[],
            documents=[],
            search_results=[
                SearchResult(
                    title="Текущее время в Минске",
                    url="https://example.com/minsk-time",
                    snippet="Проверьте точное время в Минске.",
                    page_content="Сейчас в Минске 14:35. Часовой пояс UTC+3.",
                )
            ],
        )

        self.assertIn("используй факты из найденных материалов", messages[1]["content"])
        self.assertIn("Материал страницы: Сейчас в Минске 14:35", messages[2]["content"])

    def test_build_agent_messages_with_multiple_questions_adds_instruction(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )

        messages = build_agent_messages(
            "Сколько сейчас времени в Минске и какая там погода?",
            settings=settings,
            history=[],
            documents=[],
            search_results=[],
        )

        self.assertIn("ответь на каждый по порядку", messages[1]["content"])
        self.assertIn("1. Сколько сейчас времени в Минске", messages[-1]["content"])
        self.assertIn("2. какая там погода", messages[-1]["content"])

    def test_openrouter_body_uses_max_completion_tokens(self) -> None:
        cfg = AgentModelConfig(
            api_key="test",
            base_url="https://openrouter.ai/api/v1",
            model_name="qwen/qwen3-235b-a22b",
        )
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )

        body = _build_openrouter_body(
            cfg,
            "Напиши длинный ответ",
            settings=settings,
            history=[],
            documents=[],
            search_results=[],
            stream=False,
        )

        self.assertEqual(body["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", body)


class WeaAgentStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_agent_reply_streaming_auto_continues_on_length(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        cfg = AgentModelConfig(
            api_key="test",
            base_url="https://openrouter.ai/api/v1",
            model_name="qwen/qwen3-235b-a22b",
        )
        streamed: list[str] = []
        calls: list[list[dict[str, str]]] = []

        async def fake_stream_once(*args, **kwargs):
            messages = kwargs["messages"]
            on_delta = kwargs["on_delta"]
            calls.append(messages)
            if len(calls) == 1:
                await on_delta("<div")
                return "<div", "length"
            await on_delta(" class='demo'></div>")
            return " class='demo'></div>", "stop"

        async def on_delta(delta: str) -> None:
            streamed.append(delta)

        with (
            patch("app.services.wea_agent.load_agent_model_config", return_value=cfg),
            patch("app.services.wea_agent._stream_openrouter_once", side_effect=fake_stream_once),
        ):
            reply = await generate_agent_reply_streaming(
                "Отправь код полностью",
                settings=settings,
                history=[],
                documents=[],
                search_results=[],
                on_delta=on_delta,
            )

        self.assertEqual(reply, "<div class='demo'></div>")
        self.assertEqual("".join(streamed), reply)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][-2]["role"], "assistant")
        self.assertIn("Продолжай ответ строго с места остановки", calls[1][-1]["content"])

    async def test_generate_agent_reply_streaming_auto_continues_on_interrupted_stream(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        cfg = AgentModelConfig(
            api_key="test",
            base_url="https://openrouter.ai/api/v1",
            model_name="qwen/qwen3-235b-a22b",
        )
        streamed: list[str] = []
        calls: list[list[dict[str, str]]] = []

        async def fake_stream_once(*args, **kwargs):
            messages = kwargs["messages"]
            on_delta = kwargs["on_delta"]
            calls.append(messages)
            if len(calls) == 1:
                await on_delta("Первый кусок. ")
                return "Первый кусок. ", "interrupted"
            await on_delta("Второй кусок.")
            return "Второй кусок.", "stop"

        async def on_delta(delta: str) -> None:
            streamed.append(delta)

        with (
            patch("app.services.wea_agent.load_agent_model_config", return_value=cfg),
            patch("app.services.wea_agent._stream_openrouter_once", side_effect=fake_stream_once),
        ):
            reply = await generate_agent_reply_streaming(
                "Ответь подробно",
                settings=settings,
                history=[],
                documents=[],
                search_results=[],
                on_delta=on_delta,
            )

        self.assertEqual(reply, "Первый кусок. Второй кусок.")
        self.assertEqual("".join(streamed), reply)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
