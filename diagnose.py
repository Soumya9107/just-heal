"""
diagnose.py

When the scraper's output fails validation, this module sends the failure
context (schema, validation report, current page HTML, and optionally the
last known-good HTML) to Claude and asks for:
  1. A diagnosis of what likely changed on the page
  2. A new plain-English extraction description suitable for handing to
     Bright Data's Scraper Studio (`brightdata scraper create`)

Requires ANTHROPIC_API_KEY to be set in the environment.
"""

import json
import os
import requests
from dotenv import load_dotenv
load_dotenv()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"


def diagnose_break(
    schema: dict,
    validation_report: dict,
    page_html_snippet: str,
    last_good_html_snippet: str = None,
) -> dict:
    """Ask Claude to diagnose a scraper break and propose a fix.

    Returns a dict with keys: diagnosis, confidence, new_extraction_description
    """
    diff_context = ""
    if last_good_html_snippet:
        diff_context = f"""
LAST KNOWN-GOOD HTML SNIPPET (when scraper worked):
{last_good_html_snippet[:3000]}
"""

    prompt = f"""You are debugging a web scraper that just failed validation.

EXPECTED OUTPUT SCHEMA:
{json.dumps(schema, indent=2, default=str)}

VALIDATION FAILURES:
{json.dumps(validation_report, indent=2)}

CURRENT PAGE HTML SNIPPET (what the scraper sees now):
{page_html_snippet[:3000]}
{diff_context}

Your task:
1. Diagnose what likely changed on the page (e.g. class renamed, element
   restructured, new wrapper div, price moved to a different tag).
2. Write a new, precise, plain-English extraction description for each
   schema field that Bright Data's Scraper Studio can use to re-create the
   collector. Be specific about where the data now lives in the HTML.

Respond ONLY in JSON, no markdown fences, in this exact shape:
{{
  "diagnosis": "short explanation of what changed",
  "confidence": "high|medium|low",
  "new_extraction_description": "a single natural-language paragraph describing what to extract and where, suitable for brightdata scraper create"
}}
"""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    response = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": MODEL,
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    if response.status_code != 200:
        print(f"Anthropic API error {response.status_code}: {response.text}")

    response.raise_for_status()
    data = response.json()
    text = data["content"][0]["text"]
    clean = text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


if __name__ == "__main__":
    # Manual smoke test - requires ANTHROPIC_API_KEY set
    sample_report = {
        "total_records": 1,
        "failed_records": 1,
        "fail_rate": 1.0,
        "sample_failures": [
            {
                "index": 0,
                "record": {"name": "", "price": None, "availability": "Ships within 24h"},
                "problems": [
                    "'name' is missing or empty",
                    "'price' is missing or empty",
                    "'availability' value 'Ships within 24h' not in allowed set ['in_stock', 'out_of_stock', 'unknown']",
                ],
            }
        ],
    }
    sample_html = """
    <div class="pdp-card-v2">
      <div class="title-wrap"><span data-testid="name">Wireless Mouse</span></div>
      <div class="pricing"><b>USD 24.99</b></div>
      <p class="fulfillment">Ships within 24h</p>
    </div>
    """
    result = diagnose_break(
        schema={"name": "str", "price": "number", "availability": "str"},
        validation_report=sample_report,
        page_html_snippet=sample_html,
    )
    print(json.dumps(result, indent=2))
