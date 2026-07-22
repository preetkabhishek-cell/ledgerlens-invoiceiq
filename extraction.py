"""Gemini vision extraction with per-field self-reported confidence.

Design decision: we ask the model for structured JSON with a confidence score
per field (see prompts/extraction_prompt.txt) rather than using function
calling — the retry logic is simpler and the prompt is a plain text file the
whole team can read and version.

MOCK_EXTRACTION=1 (or a missing API key) returns a canned result so the app
and the test suite run without network access.
"""

import base64
import json
import mimetypes
import os
import time

import requests

GEMINI_MODEL = "gemini-2.0-flash"
API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "extraction_prompt.txt")

MOCK_RESULT = {
    "currency": "INR",
    "fields": {
        "vendor": {"value": "Sharma Traders", "confidence": 0.97},
        "invoice_number": {"value": "ST-2026-0142", "confidence": 0.93},
        "invoice_date": {"value": "2026-07-01", "confidence": 0.9},
        "subtotal": {"value": "12500", "confidence": 0.88},
        "tax": {"value": "2250", "confidence": 0.62},
        "total": {"value": "14750", "confidence": 0.91},
    },
    "line_items": [
        {"description": "A4 paper (box)", "quantity": 10, "unit_price": 950, "amount": 9500},
        {"description": "Toner cartridge", "quantity": 2, "unit_price": 1500, "amount": 3000},
    ],
}

REQUIRED_FIELDS = ["vendor", "invoice_number", "invoice_date", "subtotal", "tax", "total"]


def _mock_enabled():
    return os.environ.get("MOCK_EXTRACTION") == "1" or not os.environ.get("GEMINI_API_KEY")


def _load_prompt():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _parse_response(text):
    """Model sometimes wraps JSON in ```json fences — strip and parse."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _validate(result):
    if "fields" not in result:
        raise ValueError("missing 'fields'")
    for name in REQUIRED_FIELDS:
        item = result["fields"].setdefault(name, {"value": "", "confidence": 0.3})
        conf = float(item.get("confidence", 0.3))
        item["confidence"] = max(0.0, min(1.0, conf))
    result.setdefault("line_items", [])
    result.setdefault("currency", "INR")
    return result


def extract_invoice(image_path, max_retries=2):
    """Return validated extraction dict for the given invoice image."""
    if _mock_enabled():
        return json.loads(json.dumps(MOCK_RESULT))  # deep copy

    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "contents": [{
            "parts": [
                {"text": _load_prompt()},
                {"inline_data": {"mime_type": mime, "data": image_b64}},
            ]
        }],
        "generationConfig": {"temperature": 0.0, "response_mime_type": "application/json"},
    }

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                API_URL,
                params={"key": os.environ["GEMINI_API_KEY"]},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _validate(_parse_response(text))
        except Exception as err:  # network, quota, malformed JSON — retry once
            last_err = err
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Extraction failed after {max_retries + 1} attempts: {last_err}")
