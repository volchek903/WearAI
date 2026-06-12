from __future__ import annotations

import unittest

from app.keyboards.admin import admin_model_pricing_kb
from app.repository.app_settings import DEFAULT_PROVIDER_COST_USD, MODEL_TITLES, ModelPricing


class AdminPricingKeyboardTests(unittest.TestCase):
    def test_model_pricing_callbacks_fit_telegram_limit(self) -> None:
        pricing = [
            ModelPricing(
                model_key=model_key,
                title=title,
                provider_cost_usd=DEFAULT_PROVIDER_COST_USD[model_key],
                user_price_credits=1,
            )
            for model_key, title in MODEL_TITLES.items()
        ]

        markup = admin_model_pricing_kb(pricing)
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]

        too_long = [
            data
            for data in callback_data
            if len(data.encode("utf-8")) > 64
        ]
        self.assertEqual(too_long, [])


if __name__ == "__main__":
    unittest.main()
