"""Beregner til Bredballe IF Padel-kontingenter.

Pure calculation skill for Bredballe IF Padel. It never writes to Conventus
or any external system; it only returns deterministic JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TIMEZONE = "Europe/Copenhagen"
ANNUAL_TOTAL_DKK = 1600

MONTH_VALUES_DKK: dict[str, int] = {
    "january": 25,
    "february": 25,
    "march": 75,
    "april": 125,
    "may": 250,
    "june": 250,
    "july": 250,
    "august": 250,
    "september": 150,
    "october": 100,
    "november": 50,
    "december": 50,
}

MONTHS = list(MONTH_VALUES_DKK)
MONTH_DA: dict[str, str] = {
    "january": "januar",
    "february": "februar",
    "march": "marts",
    "april": "april",
    "may": "maj",
    "june": "juni",
    "july": "juli",
    "august": "august",
    "september": "september",
    "october": "oktober",
    "november": "november",
    "december": "december",
}

PRODUCT_UNTIL_JUNE = "padel_until_june"
PRODUCT_REST_OF_YEAR = "padel_rest_of_year"
PRODUCT_NAMES_DA = {
    PRODUCT_UNTIL_JUNE: "Padel kontingent til og med 30. juni",
    PRODUCT_REST_OF_YEAR: "Padel kontingent resten af året",
}


def _money_da(amount: int) -> str:
    return f"{amount:,}".replace(",", ".")


def _parse_date(raw: Any | None) -> tuple[date | None, list[str]]:
    if raw in (None, ""):
        return datetime.now(ZoneInfo(TIMEZONE)).date(), []
    if not isinstance(raw, str):
        return None, ["Dato skal angives som tekst i ISO-formatet YYYY-MM-DD."]
    try:
        return date.fromisoformat(raw), []
    except ValueError:
        return None, [f"Kunne ikke læse datoen '{raw}'. Brug ISO-formatet YYYY-MM-DD."]


def _month_key(d: date) -> str:
    return MONTHS[d.month - 1]


def _included_months(start_month: str, end_month: str) -> list[dict[str, Any]]:
    start_idx = MONTHS.index(start_month)
    end_idx = MONTHS.index(end_month)
    return [
        {
            "month": month,
            "month_da": MONTH_DA[month],
            "value_dkk": MONTH_VALUES_DKK[month],
        }
        for month in MONTHS[start_idx : end_idx + 1]
    ]


def _product(key: str, current_date: date, start_month: str, end_month: str) -> dict[str, Any]:
    included = _included_months(start_month, end_month)
    end_day = 30 if end_month == "june" else 31
    end_month_number = MONTHS.index(end_month) + 1
    return {
        "key": key,
        "name_da": PRODUCT_NAMES_DA[key],
        "available": True,
        "active_should_be": True,
        "price_dkk": sum(m["value_dkk"] for m in included),
        "valid_until": date(current_date.year, end_month_number, end_day).isoformat(),
        "included_months": included,
    }


def _expected_products(current_date: date, current_month: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    if current_date.month <= 6:
        products.append(_product(PRODUCT_UNTIL_JUNE, current_date, current_month, "june"))
    products.append(_product(PRODUCT_REST_OF_YEAR, current_date, current_month, "december"))
    return products


def _validate_rules(current_date: date, products: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []

    if sum(MONTH_VALUES_DKK.values()) != ANNUAL_TOTAL_DKK:
        errors.append("Summen af månedsværdierne er ikke 1600 kr.")

    current_month = _month_key(current_date)
    if current_month not in MONTH_VALUES_DKK:
        errors.append("Aktuel måned kunne ikke identificeres.")

    product_map = {p["key"]: p for p in products}
    until_june = product_map.get(PRODUCT_UNTIL_JUNE)
    rest_of_year = product_map.get(PRODUCT_REST_OF_YEAR)

    if current_date.month <= 6 and until_june is None:
        errors.append("Kontingent til og med juni mangler i januar-juni.")
    if current_date.month >= 7 and until_june is not None:
        errors.append("Kontingent til og med juni må ikke være tilgængeligt efter 1. juli.")
    if rest_of_year is None:
        errors.append("Kontingent resten af året skal altid være tilgængeligt.")

    for product in products:
        price = product.get("price_dkk")
        if not isinstance(price, int):
            errors.append(f"Prisen for {product.get('key', 'ukendt produkt')} er ikke et helt antal kroner.")
            continue
        if price < 0:
            errors.append(f"Prisen for {product.get('key', 'ukendt produkt')} er negativ.")

    samples = [
        ("2026-12-01", PRODUCT_REST_OF_YEAR, 50, "December resten af året skal give 50 kr."),
        ("2026-07-01", PRODUCT_REST_OF_YEAR, 850, "Juli resten af året skal give 850 kr."),
        ("2026-05-01", PRODUCT_UNTIL_JUNE, 500, "Maj til og med juni skal give 500 kr."),
        ("2026-05-01", PRODUCT_REST_OF_YEAR, 1350, "Maj resten af året skal give 1350 kr."),
    ]
    for sample_date_raw, key, expected_price, error_text in samples:
        sample_date = date.fromisoformat(sample_date_raw)
        sample_month = _month_key(sample_date)
        sample_products = _expected_products(sample_date, sample_month)
        sample_product = next((p for p in sample_products if p["key"] == key), None)
        if sample_product is None or sample_product["price_dkk"] != expected_price:
            errors.append(error_text)

    return errors


def _normalise_existing_products(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if raw in (None, ""):
        return [], []
    if not isinstance(raw, list):
        return [], ["existing_products skal være en liste af produktobjekter."]

    products: list[dict[str, Any]] = []
    warnings: list[str] = []
    for idx, item in enumerate(raw):
        if isinstance(item, dict):
            products.append(item)
        else:
            warnings.append(f"Produkt nr. {idx + 1} blev ignoreret, fordi det ikke er et objekt.")
    return products, warnings


def _diff(existing_products: list[dict[str, Any]], expected_products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not existing_products:
        return []

    expected_by_key = {p["key"]: p for p in expected_products}
    expected_keys = set(expected_by_key)
    known_keys = {PRODUCT_UNTIL_JUNE, PRODUCT_REST_OF_YEAR}
    diffs: list[dict[str, Any]] = []

    key_counts = Counter(str(p.get("key", "")) for p in existing_products)
    seen_expected_keys: set[str] = set()

    for product in existing_products:
        key = str(product.get("key", "")).strip()
        current_price = product.get("current_price_dkk")
        current_active = bool(product.get("active", False))

        if key not in known_keys:
            diffs.append(
                {
                    "key": key or "(missing)",
                    "action": "unknown_product",
                    "current_price_dkk": current_price,
                    "current_active": current_active,
                    "reason_da": "Produktet kendes ikke af kontingentberegneren.",
                }
            )
            continue

        if key_counts[key] > 1:
            diffs.append(
                {
                    "key": key,
                    "action": "manual_review_required",
                    "reason_da": "Der findes flere produkter med samme nøgle; gennemgå dem manuelt.",
                }
            )
            seen_expected_keys.add(key)
            continue

        seen_expected_keys.add(key)
        expected = expected_by_key.get(key)

        if expected is None:
            action = "hide_or_deactivate" if current_active else "no_change"
            diff_item: dict[str, Any] = {
                "key": key,
                "action": action,
                "current_price_dkk": current_price,
                "expected_price_dkk": None,
                "current_active": current_active,
                "expected_active": False,
            }
            if action == "hide_or_deactivate":
                diff_item["reason_da"] = "Kontingent til og med 30. juni må ikke være aktivt efter 1. juli."
            return_item = diff_item
            diffs.append(return_item)
            continue

        expected_price = expected["price_dkk"]
        expected_active = expected["active_should_be"]
        base: dict[str, Any] = {
            "key": key,
            "current_price_dkk": current_price,
            "expected_price_dkk": expected_price,
            "current_active": current_active,
            "expected_active": expected_active,
        }

        if not isinstance(current_price, int):
            diffs.append(
                {
                    **base,
                    "action": "manual_review_required",
                    "reason_da": "Produktets nuværende pris mangler eller er ikke et helt antal kroner.",
                }
            )
        elif current_active != expected_active and expected_active:
            diffs.append(
                {
                    **base,
                    "action": "activate",
                    "reason_da": f"{expected['name_da']} skal være aktivt og koste {_money_da(expected_price)} kr.",
                }
            )
        elif current_active != expected_active:
            diffs.append(
                {
                    **base,
                    "action": "deactivate",
                    "reason_da": f"{expected['name_da']} skal ikke være aktivt.",
                }
            )
        elif current_price != expected_price:
            diffs.append(
                {
                    **base,
                    "action": "update_price",
                    "reason_da": f"{expected['name_da']} fra {expected['included_months'][0]['month_da']} skal koste {_money_da(expected_price)} kr.",
                }
            )
        else:
            diffs.append({**base, "action": "no_change"})

    missing_keys = expected_keys - seen_expected_keys
    for key in sorted(missing_keys):
        expected = expected_by_key[key]
        diffs.append(
            {
                "key": key,
                "action": "missing_product",
                "expected_price_dkk": expected["price_dkk"],
                "expected_active": expected["active_should_be"],
                "reason_da": f"{expected['name_da']} mangler.",
            }
        )

    return diffs


def _admin_summary(current_month: str, products: list[dict[str, Any]]) -> str:
    month_da = MONTH_DA[current_month].capitalize()
    product_map = {p["key"]: p for p in products}
    rest = product_map[PRODUCT_REST_OF_YEAR]["price_dkk"]
    until = product_map.get(PRODUCT_UNTIL_JUNE)

    if until is not None:
        return (
            f"{month_da}-kontingenterne er beregnet. "
            f"Kontingent til og med 30. juni skal være {_money_da(until['price_dkk'])} kr. "
            f"Kontingent resten af året skal være {_money_da(rest)} kr. "
            "Begge kontingenter må være aktive."
        )

    return (
        f"{month_da}-kontingentet er beregnet. "
        f"Kun kontingent resten af året må være aktivt, og prisen skal være {_money_da(rest)} kr. "
        "Kontingent til og med 30. juni skal skjules eller deaktiveres."
    )


def beregn_bif_padel_kontingent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Beregn Bredballe IF Padels kontingentprodukter ud fra valgfrit input."""
    payload = deepcopy(payload or {})
    warnings: list[str] = []

    current_date, date_errors = _parse_date(payload.get("date"))
    if date_errors or current_date is None:
        return {
            "success": False,
            "errors": date_errors,
            "warnings": [],
            "products": [],
        }

    current_month = _month_key(current_date)
    products = _expected_products(current_date, current_month)
    errors = _validate_rules(current_date, products)
    existing_products, existing_warnings = _normalise_existing_products(payload.get("existing_products"))
    warnings.extend(existing_warnings)

    if errors:
        return {
            "success": False,
            "errors": errors,
            "warnings": warnings,
            "products": [],
        }

    result: dict[str, Any] = {
        "success": True,
        "date": current_date.isoformat(),
        "timezone": TIMEZONE,
        "current_month": current_month,
        "current_month_da": MONTH_DA[current_month],
        "annual_total_dkk": ANNUAL_TOTAL_DKK,
        "products": products,
        "diff": _diff(existing_products, products),
        "warnings": warnings,
        "admin_summary_da": _admin_summary(current_month, products),
    }

    if bool(payload.get("include_debug", False)):
        result["debug"] = {
            "month_values_dkk": MONTH_VALUES_DKK,
            "month_values_sum_dkk": sum(MONTH_VALUES_DKK.values()),
            "existing_products_count": len(existing_products),
        }

    return result


def _read_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    if args.input_json:
        payload.update(json.loads(args.input_json))
    elif not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            payload.update(json.loads(stdin_data))

    if args.date:
        payload["date"] = args.date
    if args.include_debug:
        payload["include_debug"] = True
    if args.existing_products_json:
        payload["existing_products"] = json.loads(args.existing_products_json)

    return payload


def cmd_beregn(args: argparse.Namespace) -> int:
    try:
        payload = _read_payload(args)
    except json.JSONDecodeError as exc:
        result = {
            "success": False,
            "errors": [f"Kunne ikke læse JSON-input: {exc.msg}."],
            "warnings": [],
            "products": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result = beregn_bif_padel_kontingent(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


def main() -> None:
    argv = sys.argv[1:]
    known_actions = {"beregn", "-h", "--help"}
    if argv and argv[0] not in known_actions:
        argv = ["beregn", *argv]

    parser = argparse.ArgumentParser(
        prog="padel-kontingent-beregner",
        description="Beregn sæsonvægtede Bredballe IF Padel-kontingenter som JSON.",
    )
    sub = parser.add_subparsers(dest="action")

    p_beregn = sub.add_parser("beregn", help="Beregn kontingentprodukter")
    p_beregn.add_argument("--date", help="Dato i ISO-formatet YYYY-MM-DD")
    p_beregn.add_argument("--include-debug", action="store_true", help="Medtag fejlsøgningsfelter i JSON-output")
    p_beregn.add_argument("--input-json", help="JSON-input med date/include_debug/existing_products")
    p_beregn.add_argument("--existing-products-json", help="JSON-liste med eksisterende produkter")

    args = parser.parse_args(argv)
    if args.action is None:
        args = parser.parse_args(["beregn"])

    raise SystemExit(cmd_beregn(args))


if __name__ == "__main__":
    main()
