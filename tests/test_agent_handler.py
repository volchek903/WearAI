from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.handlers.agent import (
    _build_agent_request_badge_text,
    _build_agent_pricing_note,
    _describe_next_agent_request,
    _effective_agent_settings,
)
from app.repository.app_settings import AgentRequestPricing, build_agent_price_breakdown
from app.repository.generations import CHARGE_SOURCE_DAILY_FREE, ChargeResult
from app.repository.agent_settings import AgentToggleState


class AgentHandlerTests(unittest.TestCase):
    @staticmethod
    def _pricing() -> AgentRequestPricing:
        return AgentRequestPricing(
            base=5,
            memory=2,
            documents=2,
            web_search=1,
            deep_analysis=1,
            quick_mode=1,
        )

    def test_daily_free_request_disables_expensive_modes(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=True,
            documents_enabled=True,
            memory_enabled=True,
            deep_analysis_enabled=True,
            quick_mode_enabled=True,
            document_session_key="session-1",
        )

        effective = _effective_agent_settings(settings, is_daily_free=True)

        self.assertFalse(effective.web_search_enabled)
        self.assertFalse(effective.documents_enabled)
        self.assertFalse(effective.memory_enabled)
        self.assertFalse(effective.deep_analysis_enabled)
        self.assertFalse(effective.quick_mode_enabled)
        self.assertEqual(effective.document_session_key, "session-1")

    def test_paid_request_keeps_original_modes(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=True,
            documents_enabled=True,
            memory_enabled=True,
            deep_analysis_enabled=True,
            quick_mode_enabled=True,
            document_session_key="session-1",
        )

        effective = _effective_agent_settings(settings, is_daily_free=False)

        self.assertEqual(effective, settings)

    def test_pricing_note_mentions_free_and_paid_modes(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        user = SimpleNamespace(
            credit_balance=25,
            free_credit_balance=0,
            free_agent_requests_used_today=0,
            free_agent_requests_day=None,
        )

        note = _build_agent_pricing_note(
            settings=settings,
            pricing=self._pricing(),
            free_limit=1,
            user=user,
        )

        self.assertIn("Простых бесплатных запросов осталось сегодня", note)
        self.assertIn("затем <b>5</b> кредитов", note)
        self.assertIn("В бесплатном режиме все доп. режимы отключаются", note)

    def test_pricing_note_mentions_complex_mode_when_enabled(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=True,
            documents_enabled=True,
            memory_enabled=True,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        user = SimpleNamespace(
            credit_balance=25,
            free_credit_balance=0,
            free_agent_requests_used_today=0,
            free_agent_requests_day=None,
        )

        note = _build_agent_pricing_note(
            settings=settings,
            pricing=self._pricing(),
            free_limit=1,
            user=user,
        )

        self.assertIn("Следующий запрос будет <b>расширенным платным</b>", note)

    def test_next_request_description_for_free_simple_mode(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=False,
            memory_enabled=False,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        user = SimpleNamespace(
            credit_balance=0,
            free_credit_balance=0,
            free_agent_requests_used_today=0,
            free_agent_requests_day=None,
        )

        description = _describe_next_agent_request(
            settings=settings,
            pricing=self._pricing(),
            free_limit=1,
            user=user,
        )

        self.assertIn("бесплатным базовым", description)

    def test_next_request_description_for_complex_mode_without_balance(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=False,
            documents_enabled=True,
            memory_enabled=True,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        user = SimpleNamespace(
            credit_balance=0,
            free_credit_balance=0,
            free_agent_requests_used_today=0,
            free_agent_requests_day=None,
        )

        description = _describe_next_agent_request(
            settings=settings,
            pricing=self._pricing(),
            free_limit=1,
            user=user,
        )

        self.assertIn("бесплатным упрощённым", description)

    def test_free_badge_marks_request_as_simplified_when_features_are_dropped(self) -> None:
        requested = AgentToggleState(
            web_search_enabled=True,
            documents_enabled=True,
            memory_enabled=True,
            deep_analysis_enabled=True,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        effective = _effective_agent_settings(requested, is_daily_free=True)
        charge = ChargeResult(
            kind="agent",
            source=CHARGE_SOURCE_DAILY_FREE,
            amount=0,
            model_key="agent",
        )

        text = _build_agent_request_badge_text(
            charge=charge,
            requested_settings=requested,
            effective_settings=effective,
            requested_breakdown=build_agent_price_breakdown(
                self._pricing(),
                memory_enabled=True,
                documents_enabled=True,
                web_search_enabled=True,
                deep_analysis_enabled=True,
                quick_mode_enabled=False,
            ),
        )

        self.assertIn("Бесплатный упрощённый запрос", text)
        self.assertIn("память диалога", text)
        self.assertIn("документы", text)

    def test_paid_badge_mentions_price_and_active_features(self) -> None:
        settings = AgentToggleState(
            web_search_enabled=True,
            documents_enabled=True,
            memory_enabled=True,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
            document_session_key="session-1",
        )
        charge = ChargeResult(
            kind="agent",
            source="paid",
            amount=10,
            model_key="agent",
        )

        text = _build_agent_request_badge_text(
            charge=charge,
            requested_settings=settings,
            effective_settings=settings,
            requested_breakdown=build_agent_price_breakdown(
                self._pricing(),
                memory_enabled=True,
                documents_enabled=True,
                web_search_enabled=True,
                deep_analysis_enabled=False,
                quick_mode_enabled=False,
            ),
        )

        self.assertIn("Платный расширенный запрос", text)
        self.assertIn("10", text)
        self.assertIn("база 5 + память диалога 2 + документы 2 + веб-поиск 1", text)


if __name__ == "__main__":
    unittest.main()
