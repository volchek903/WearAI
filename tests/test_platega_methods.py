from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.services.platega import enabled_platega_methods, resolve_platega_payment_method


class PlategaMethodConfigTests(unittest.TestCase):
    def test_defaults_to_sbp_only(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(enabled_platega_methods(), ("sbp",))
            self.assertEqual(resolve_platega_payment_method("sbp"), 2)
            self.assertIsNone(resolve_platega_payment_method("card"))

    def test_env_enables_known_methods_and_ignores_invalid_values(self) -> None:
        with patch.dict(
            os.environ,
            {"PLATEGA_ENABLED_METHODS": "sbp, card, unknown, crypto, card"},
        ):
            self.assertEqual(enabled_platega_methods(), ("sbp", "card", "crypto"))
            self.assertEqual(resolve_platega_payment_method("card"), 11)
            self.assertEqual(resolve_platega_payment_method("crypto"), 13)
            self.assertIsNone(resolve_platega_payment_method("unknown"))


if __name__ == "__main__":
    unittest.main()
