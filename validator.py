"""
validator.py

Defines what "healthy" scraper output looks like and checks scraped
records against that schema. This is deliberately stricter than "did we
get a 200 response" — it checks field presence, type, and plausibility,
since scrapers usually break silently (returning empty or malformed
fields) rather than throwing errors.
"""

from typing import Any, Dict, List, Tuple

# Edit this to match the fields your collector is expected to extract.
SCHEMA = {
    "name": {"type": str, "required": True, "min_len": 1},
    "price": {"type": (int, float), "required": True, "min_val": 0},
    "availability": {
        "type": str,
        "required": True,
        "allowed": ["in_stock", "out_of_stock", "unknown"],
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
    good = {"name": "Wireless Mouse", "price": 24.99, "availability": "in_stock"}
    bad = {"name": "", "price": "twenty", "availability": "maybe"}

    print(validate(good))
    print(validate(bad))
    print(validate_batch([good, bad]))
