"""
diagnose.py

When the scraper's output fails validation, this module sends the failure
context (schema, validation report, current page HTML, and optionally the
last known-good HTML) to Google's Gemini API and asks for:
  1. A diagnosis of what likely changed on the page
  2. A new plain-English extraction description suitable for handing to
     Bright Data's Scraper Studio (`brightdata scraper create`)

Requires GEMINI_API_KEY to be set in the environment (free tier available
at https://aistudio.google.com/apikey - no credit card required).
"""

import json
import os
import requests

from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def diagnose_break(
    schema: dict,
    validation_report: dict,
    page_html_snippet: str,
    last_good_html_snippet: str = None,
) -> dict:
    """Ask Gemini to diagnose a scraper break and propose a fix.

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

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    response = requests.post(
        f"{GEMINI_API_URL}?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            },
        },
    )
    if response.status_code != 200:
        # Print the actual error body before raising, since a bare
        # HTTPError hides the reason (bad key, quota, bad model name, etc.)
        print(f"Gemini API error {response.status_code}: {response.text}")
    response.raise_for_status()

    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]

    # Gemini sometimes wraps JSON in markdown fences or adds stray text
    # before/after it. Extract just the {...} block to be safe.
    clean = text.replace("```json", "").replace("```", "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1:
        clean = clean[start:end + 1]

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"Failed to parse Gemini's response as JSON: {e}")
        print(f"Raw response text was:\n{text}")
        raise


if __name__ == "__main__":
    # Manual smoke test - requires GEMINI_API_KEY set
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