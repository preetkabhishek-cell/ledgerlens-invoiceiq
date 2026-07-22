"""Tiny extraction eval: runs the extractor over the labelled sample invoices
and reports per-field accuracy plus whether confidence was honest (i.e. wrong
answers should not come with high confidence).

Run from the repo root:
    python eval/eval_extraction.py           # real API (needs GEMINI_API_KEY)
    MOCK_EXTRACTION=1 python eval/eval_extraction.py   # plumbing check only
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction import extract_invoice  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), "sample_invoices")


def norm(v):
    return str(v).strip().lower().replace(",", "").rstrip("0").rstrip(".") \
        if any(c.isdigit() for c in str(v)) else str(v).strip().lower()


def main():
    with open(os.path.join(HERE, "labels.json"), encoding="utf-8") as f:
        labels = json.load(f)

    total = correct = 0
    overconfident = []  # wrong value with confidence >= 0.8

    for filename, expected in labels.items():
        path = os.path.join(SAMPLES, filename)
        if not os.path.exists(path):
            print(f"!! {filename} missing — run sample_invoices/make_samples.py first")
            continue
        result = extract_invoice(path)
        print(f"\n== {filename} ==")
        for field, exp_value in expected.items():
            if field == "currency":
                got, conf = result.get("currency", ""), 1.0
            else:
                item = result["fields"].get(field, {})
                got, conf = item.get("value", ""), item.get("confidence", 0.0)
            ok = norm(got) == norm(exp_value)
            total += 1
            correct += ok
            flag = "OK " if ok else "MISS"
            if not ok and conf >= 0.8:
                overconfident.append((filename, field, got, conf))
            print(f"  [{flag}] {field:15} expected={exp_value!r:28} got={got!r} (conf {conf:.2f})")

    print(f"\nField accuracy: {correct}/{total} = {correct / max(total, 1):.0%}")
    if overconfident:
        print("Overconfident misses (wrong but conf >= 0.8):")
        for row in overconfident:
            print("  ", row)
    else:
        print("No overconfident misses — confidence scores are honest on this set.")


if __name__ == "__main__":
    main()
