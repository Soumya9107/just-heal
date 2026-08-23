"""
validator.py

Defines what "healthy" scraper output looks like and checks scraped
records against that schema. This is deliberately stricter than "did we
get a 200 response" — it checks field presence, type, and plausibility,
since scrapers usually break silently (returning empty or malformed
fields) rather than throwing errors.
"""

from typing import Any, Dict, List, Tuple

# This matches the ACTUAL output shape Bright Data's AI generated for our
# collector, e.g.:
#   {
#     "product_name": "Wireless Mouse",
#     "price": {"value": 24.99, "currency": "USD", "symbol": "$"},
#     "availability": "In Stock"
#   }
# Bright Data's schema generator names fields based on its own interpretation
# of your extraction description, so always check real output (like we did)
# before assuming field names — don't guess them in advance.
SCHEMA = {
    "product_name": {"type": str, "required": True, "min_len": 1},
    "price": {"type": dict, "required": True},  # nested object, checked specially below
    "availability": {
        "type": str,
        "required": True,
        "allowed": ["In Stock", "Out of Stock", "Unknown"],
    },
}


def validate(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a single scraped record against SCHEMA.

    Returns (is_valid, list_of_problems).
    """
    problems: List[str] = []

    for field, rules in SCHEMA.items():
        value = record.get(field)

        if rules.get("required") and (value is None or value == ""):
            problems.append(f"'{field}' is missing or empty")
            continue

        if value is None:
            continue

        if "type" in rules and not isinstance(value, rules["type"]):
            problems.append(
                f"'{field}' has wrong type: expected {rules['type']}, got {type(value)}"
            )

        if "min_len" in rules and isinstance(value, str) and len(value) < rules["min_len"]:
            problems.append(f"'{field}' is shorter than expected")

        if "min_val" in rules and isinstance(value, (int, float)) and value < rules["min_val"]:
            problems.append(f"'{field}' value {value} is below minimum {rules['min_val']}")

        if "allowed" in rules and value not in rules["allowed"]:
            problems.append(f"'{field}' value '{value}' not in allowed set {rules['allowed']}")

    # Special check: price is a nested object, validate its inner "value"
    price = record.get("price")
    if isinstance(price, dict):
        inner = price.get("value")
        if inner is None:
            problems.append("'price.value' is missing")
        elif not isinstance(inner, (int, float)):
            problems.append(f"'price.value' has wrong type: expected number, got {type(inner)}")
        elif inner < 0:
            problems.append(f"'price.value' is negative: {inner}")

    return (len(problems) == 0, problems)


def validate_batch(records: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
    """Validate a list of scraped records, return overall health + stats.

    Tolerates a small failure rate (<10%) as normal noise; anything worse
    is treated as a broken scraper that needs healing.
    """
    total = len(records)
    if total == 0:
        return False, {"error": "empty result set - likely total extraction failure"}

    failures = []
    for i, r in enumerate(records):
        ok, problems = validate(r)
        if not ok:
            failures.append({"index": i, "record": r, "problems": problems})

    fail_rate = len(failures) / total
    is_healthy = fail_rate < 0.1

    return is_healthy, {
        "total_records": total,
        "failed_records": len(failures),
        "fail_rate": round(fail_rate, 3),
        "sample_failures": failures[:5],
    }


if __name__ == "__main__":
    # Quick manual smoke test
    good = {
        "product_name": "Wireless Mouse",
        "price": {"value": 24.99, "currency": "USD", "symbol": "$"},
        "availability": "In Stock",
    }
    bad = {
        "product_name": "",
        "price": {"value": "twenty"},
        "availability": "maybe",
    }

    print(validate(good))
    print(validate(bad))
    print(validate_batch([good, bad]))