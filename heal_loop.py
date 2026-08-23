"""
heal_loop.py

Orchestrates the self-healing cycle:

    run -> validate -> (if unhealthy) diagnose -> heal -> re-run -> validate

Capped at MAX_HEAL_ATTEMPTS so a genuinely broken/unreachable page fails
loudly (non-zero exit code, red CI check) instead of retrying forever.

Requires:
  - Bright Data CLI installed and authenticated (`brightdata login`)
  - ANTHROPIC_API_KEY set in the environment
  - collector_id.txt containing an existing collector ID
    (create one first with `brightdata scraper create <url> "<description>"`)
"""

import json
import shutil
import subprocess
import sys

from validator import validate_batch
from diagnose import diagnose_break

# On Windows, npm installs global CLIs as .cmd wrapper scripts, which
# subprocess.run() won't find unless shell=True or the exact path
# (with extension) is used. shutil.which() resolves this correctly
# cross-platform (Windows, Mac, Linux) by finding the actual executable
# on PATH, extension and all.
BRIGHTDATA_CMD = shutil.which("brightdata")
if BRIGHTDATA_CMD is None:
    print(
        "Could not find 'brightdata' on PATH. Make sure the Bright Data CLI "
        "is installed (npm install -g @brightdata/cli) and that you're "
        "running this from a terminal where 'brightdata --help' works.",
        file=sys.stderr,
    )
    sys.exit(1)

MAX_HEAL_ATTEMPTS = 3
TARGET_URL = "https://self-healing-scraper-red.vercel.app/baseline.html"
COLLECTOR_ID_FILE = "collector_id.txt"
LAST_GOOD_HTML_FILE = "last_good_html.txt"

SCHEMA_DESCRIPTION = {
    "product_name": "str",
    "price": {"value": "number", "currency": "str", "symbol": "str"},
    "availability": "str (one of: In Stock, Out of Stock, Unknown)",
}


def run_collector(collector_id: str) -> list:
    """Run an existing collector against TARGET_URL and return parsed records."""
    result = subprocess.run(
        [BRIGHTDATA_CMD, "scraper", "run", collector_id, TARGET_URL, "-o", "run_output.json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"CLI run failed: {result.stderr}", file=sys.stderr)
        return []

    try:
        with open("run_output.json") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Could not read run_output.json: {e}", file=sys.stderr)
        return []

    return data if isinstance(data, list) else [data]


def create_collector(description: str) -> str:
    """Create a new (healed) collector with an updated extraction description."""
    result = subprocess.run(
        [BRIGHTDATA_CMD, "scraper", "create", TARGET_URL, description, "-o", "create.json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create collector: {result.stderr}")

    with open("create.json") as f:
        data = json.load(f)
    return data["collector_id"]


def fetch_html_snippet(url: str) -> str:
    """Fetch raw HTML of the target page for diagnosis context."""
    result = subprocess.run(
        [BRIGHTDATA_CMD, "scrape", url, "--format", "html"],
        capture_output=True,
        text=True,
    )
    return result.stdout[:5000]


def load_last_good_html() -> str:
    try:
        with open(LAST_GOOD_HTML_FILE) as f:
            return f.read()
    except FileNotFoundError:
        return None


def save_last_good_html(html: str) -> None:
    with open(LAST_GOOD_HTML_FILE, "w") as f:
        f.write(html)


def main():
    try:
        with open(COLLECTOR_ID_FILE) as f:
            collector_id = f.read().strip()
    except FileNotFoundError:
        print(
            f"No {COLLECTOR_ID_FILE} found. Create a collector first:\n"
            f'  brightdata scraper create {TARGET_URL} "extract product name, price, and availability" -o create.json\n'
            f"  jq -r '.collector_id' create.json > {COLLECTOR_ID_FILE}",
            file=sys.stderr,
        )
        sys.exit(1)

    attempt = 0
    healthy = False
    report = {}

    while attempt < MAX_HEAL_ATTEMPTS and not healthy:
        print(f"--- Attempt {attempt + 1}: running collector {collector_id} ---")
        records = run_collector(collector_id)
        healthy, report = validate_batch(records)

        if healthy:
            print(f"Healthy run. {report}")
            html_now = fetch_html_snippet(TARGET_URL)
            save_last_good_html(html_now)
            break

        print(f"Validation failed: {report}")
        html_snippet = fetch_html_snippet(TARGET_URL)
        last_good = load_last_good_html()

        print("Diagnosing break with Claude...")
        diagnosis = diagnose_break(
            schema=SCHEMA_DESCRIPTION,
            validation_report=report,
            page_html_snippet=html_snippet,
            last_good_html_snippet=last_good,
        )
        print(f"Diagnosis: {diagnosis['diagnosis']} (confidence: {diagnosis['confidence']})")
        if diagnosis["confidence"] == "low":
            print("WARNING: low-confidence diagnosis, healing anyway but flagging for review")

        print("Healing: creating new collector with updated description...")
        collector_id = create_collector(diagnosis["new_extraction_description"])
        with open(COLLECTOR_ID_FILE, "w") as f:
            f.write(collector_id)

        attempt += 1

    if not healthy:
        print(f"Scraper still unhealthy after {MAX_HEAL_ATTEMPTS} heal attempts. Report: {report}")
        sys.exit(1)
    else:
        print(f"Scraper healed and verified in {attempt} attempt(s).")
        sys.exit(0)


if __name__ == "__main__":
    main()