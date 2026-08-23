"""
validator.py

Defines what "healthy" scraper output looks like and checks scraped
records against that schema. This is deliberately stricter than "did we
get a 200 response" — it checks field presence, type, and plausibility,
since scrapers usually break silently (returning empty or malformed
fields) rather than throwing errors.

IMPORTANT: Bright Data's Scraper Studio regenerates the exact field
NAMES/SHAPE slightly differently each time a collector is (re)created from
a natural-language description - e.g. one generation might return
  {"price": {"value": 24.99, "currency": "USD"}}
and another might return
  {"price_value": 24.99, "price_currency": "USD"}
for the same underlying data. This validator checks for the *presence and
plausibility of the right information*, trying several known field-name
variants, rather than hard-coding one exact shape - so a re-healed
collector with a different (but still correct) field layout isn't
incorrectly flagged as broken.
"""

from typing import Any, Dict, List, Optional, Tuple

# Field name variants Bright Data has been observed to generate for the
# same logical field. Add to these lists if you see a new variant.
NAME_FIELDS = ["product_name", "name", "title"]
PRICE_VALUE_FIELDS = ["price_value", "value"]  # checked inside record AND inside record["price"]
AVAILABILITY_FIELDS = ["availability", "stock_status", "availability_status"]

ALLOWED_AVAILABILITY = {"in stock", "out of stock", "unknown"}


def _first_present(record: Dict[str, Any], field_names: List[str]) -> Optional[Any]:
    """Return the first non-empty value found among a list of candidate field names."""
    for name in field_names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def _extract_price_value(record: Dict[str, Any]) -> Optional[Any]:
    """Price may be a flat field (price_value) or nested (price: {value: ...})."""
    flat = _first_present(record, PRICE_VALUE_FIELDS)
    if flat is not None:
        return flat

    nested = record.get("price")
    if isinstance(nested, dict):
        return _first_present(nested, PRICE_VALUE_FIELDS)
    if isinstance(nested, (int, float)):
        return nested  # price itself is just a bare number

    return None


def validate(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a single scraped record. Returns (is_valid, list_of_problems)."""
    problems: List[str] = []

    # --- Name ---
    name = _first_present(record, NAME_FIELDS)
    if name is None:
        problems.append(f"no product name field found (checked {NAME_FIELDS})")
    elif not isinstance(name, str) or len(name) < 1:
        problems.append(f"product name is empty or wrong type: {name!r}")

    # --- Price ---
    price_value = _extract_price_value(record)
    if price_value is None:
        problems.append(f"no price value found (checked {PRICE_VALUE_FIELDS} flat and nested under 'price')")
    elif not isinstance(price_value, (int, float)):
        problems.append(f"price value has wrong type: expected number, got {type(price_value)} ({price_value!r})")
    elif price_value < 0:
        problems.append(f"price value is negative: {price_value}")

    # --- Availability ---
    availability = _first_present(record, AVAILABILITY_FIELDS)
    if availability is None:
        problems.append(f"no availability field found (checked {AVAILABILITY_FIELDS})")
    elif not isinstance(availability, str):
        problems.append(f"availability has wrong type: {type(availability)}")
    elif availability.strip().lower() not in ALLOWED_AVAILABILITY:
        # Not necessarily wrong - the site may phrase it differently
        # (e.g. "Ships within 24h") - flag it but don't hard-fail on
        # wording alone, since the field being present and non-empty is
        # the more important signal that extraction is working.
        problems.append(
            f"availability value '{availability}' doesn't match a known status "
            f"(expected roughly one of {sorted(ALLOWED_AVAILABILITY)}) - may just be "
            f"different wording, review before treating as a hard failure"
        )

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
    # Quick manual smoke test covering both field-shape variants we've
    # actually seen Bright Data generate for this same page.
    nested_shape = {
        "product_name": "Wireless Mouse",
        "price": {"value": 24.99, "currency": "USD", "symbol": "$"},
        "availability": "In Stock",
    }
    flat_shape = {
        "product_name": "Wireless Mouse",
        "price_value": 24.99,
        "price_currency": "USD",
        "availability": "In Stock",
    }
    genuinely_broken = {
        "product_name": "",
        "price": {"value": "twenty"},
        "availability": "maybe",
    }

    print("nested shape:", validate(nested_shape))
    print("flat shape:  ", validate(flat_shape))
    print("broken:      ", validate(genuinely_broken))
    print(validate_batch([nested_shape, flat_shape, genuinely_broken]))