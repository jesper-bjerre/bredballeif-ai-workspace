from __future__ import annotations

import unittest

from agent import PRODUCT_REST_OF_YEAR, PRODUCT_UNTIL_JUNE, beregn_bif_padel_kontingent


class BifPadelKontingentBeregnerTests(unittest.TestCase):
    def product_by_key(self, result: dict, key: str) -> dict | None:
        return next((p for p in result["products"] if p["key"] == key), None)

    def test_expected_prices_for_all_12_months(self) -> None:
        cases = [
            ("2026-01-01", 750, 1600),
            ("2026-02-01", 725, 1575),
            ("2026-03-01", 700, 1550),
            ("2026-04-01", 625, 1475),
            ("2026-05-01", 500, 1350),
            ("2026-06-01", 250, 1100),
            ("2026-07-01", None, 850),
            ("2026-08-01", None, 600),
            ("2026-09-01", None, 350),
            ("2026-10-01", None, 200),
            ("2026-11-01", None, 100),
            ("2026-12-01", None, 50),
        ]

        for date_raw, until_june_price, rest_of_year_price in cases:
            with self.subTest(date=date_raw):
                result = beregn_bif_padel_kontingent({"date": date_raw})
                self.assertTrue(result["success"])

                until_june = self.product_by_key(result, PRODUCT_UNTIL_JUNE)
                rest_of_year = self.product_by_key(result, PRODUCT_REST_OF_YEAR)

                if until_june_price is None:
                    self.assertIsNone(until_june)
                else:
                    self.assertIsNotNone(until_june)
                    self.assertEqual(until_june["price_dkk"], until_june_price)

                self.assertIsNotNone(rest_of_year)
                self.assertEqual(rest_of_year["price_dkk"], rest_of_year_price)

    def test_mid_month_counts_as_full_month(self) -> None:
        first = beregn_bif_padel_kontingent({"date": "2026-05-01"})
        middle = beregn_bif_padel_kontingent({"date": "2026-05-15"})

        first_prices = {p["key"]: p["price_dkk"] for p in first["products"]}
        middle_prices = {p["key"]: p["price_dkk"] for p in middle["products"]}

        self.assertEqual(middle_prices, first_prices)

    def test_existing_products_no_change(self) -> None:
        result = beregn_bif_padel_kontingent(
            {
                "date": "2026-05-15",
                "existing_products": [
                    {"key": PRODUCT_UNTIL_JUNE, "current_price_dkk": 500, "active": True},
                    {"key": PRODUCT_REST_OF_YEAR, "current_price_dkk": 1350, "active": True},
                ],
            }
        )

        self.assertEqual([d["action"] for d in result["diff"]], ["no_change", "no_change"])

    def test_until_june_active_after_july_should_hide_or_deactivate(self) -> None:
        result = beregn_bif_padel_kontingent(
            {
                "date": "2026-07-01",
                "existing_products": [
                    {"key": PRODUCT_UNTIL_JUNE, "current_price_dkk": 250, "active": True},
                    {"key": PRODUCT_REST_OF_YEAR, "current_price_dkk": 850, "active": True},
                ],
            }
        )

        diff_by_key = {d["key"]: d for d in result["diff"]}
        self.assertEqual(diff_by_key[PRODUCT_UNTIL_JUNE]["action"], "hide_or_deactivate")

    def test_wrong_rest_of_year_price_requires_update(self) -> None:
        result = beregn_bif_padel_kontingent(
            {
                "date": "2026-09-01",
                "existing_products": [
                    {"key": PRODUCT_REST_OF_YEAR, "current_price_dkk": 400, "active": True},
                ],
            }
        )

        self.assertEqual(result["diff"][0]["action"], "update_price")
        self.assertEqual(result["diff"][0]["expected_price_dkk"], 350)


if __name__ == "__main__":
    unittest.main()
