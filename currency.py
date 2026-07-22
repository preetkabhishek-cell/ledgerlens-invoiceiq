"""Stretch goal 2 (partial) — multi-currency ledger totals.

Conversion works end-to-end, but rates come from a static table checked in
with the code, not a live FX API. This is a documented limitation: the point
was to prove the conversion path through the ledger, and a live rate feed can
be swapped in behind `to_inr()` without touching anything else.

Rates: 1 unit of currency -> INR (approximate, July 2026).
"""

RATES_TO_INR = {
    "INR": 1.0,
    "USD": 86.0,
    "EUR": 93.5,
    "GBP": 109.0,
    "AED": 23.4,
    "SGD": 63.8,
}


def to_inr(amount, currency):
    try:
        amount = float(str(amount).replace(",", ""))
    except (TypeError, ValueError):
        return None
    rate = RATES_TO_INR.get((currency or "INR").upper())
    if rate is None:
        return None
    return round(amount * rate, 2)


def ledger_total_inr(rows):
    """Sum of the `total` column across ledger rows, converted to INR.
    Rows whose total can't be parsed or whose currency is unknown are skipped
    and reported so the UI can show what was excluded."""
    total = 0.0
    skipped = []
    for row in rows:
        converted = to_inr(row.get("total"), row.get("currency"))
        if converted is None:
            skipped.append(row.get("invoice_number") or f"invoice #{row.get('id')}")
        else:
            total += converted
    return round(total, 2), skipped
