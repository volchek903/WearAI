from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "utils" / "pricing.py"
_APP_SETTINGS_STUB = types.ModuleType("app.repository.app_settings")
_APP_SETTINGS_STUB.MODEL_PRICE_NANO_BANANA_KEY = "stub_model_key"


async def _stub_get_model_price_credits(*args, **kwargs):
    raise AssertionError("get_model_price_credits should not be called in this test")


_APP_SETTINGS_STUB.get_model_price_credits = _stub_get_model_price_credits
sys.modules.setdefault("app.repository.app_settings", _APP_SETTINGS_STUB)
_SPEC = importlib.util.spec_from_file_location("pricing_utils_test_module", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

format_credits = _MODULE.format_credits
single_generation_price_line = _MODULE.single_generation_price_line


class PricingUtilsTests(unittest.TestCase):
    def test_format_credits_uses_russian_plural_forms(self) -> None:
        self.assertEqual(format_credits(1), "1 кредит")
        self.assertEqual(format_credits(2), "2 кредита")
        self.assertEqual(format_credits(5), "5 кредитов")
        self.assertEqual(format_credits(21), "21 кредит")
        self.assertEqual(format_credits(24), "24 кредита")
        self.assertEqual(format_credits(11), "11 кредитов")

    def test_single_generation_price_line_is_html_ready(self) -> None:
        self.assertEqual(
            single_generation_price_line(24),
            "💳 Цена за 1 генерацию: <b>24 кредита</b>.",
        )


if __name__ == "__main__":
    unittest.main()
