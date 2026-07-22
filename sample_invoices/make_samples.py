"""Generate three synthetic invoice images for demos and the eval script.

Run:  python sample_invoices/make_samples.py
Creates invoice_1.png (clean), invoice_2.png (different vendor/currency),
invoice_3.png (blurry copy of invoice_1 — should be caught as a duplicate).
"""

import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))

INVOICES = [
    {
        "file": "invoice_1.png",
        "vendor": "Sharma Traders Pvt Ltd",
        "number": "ST-2026-0142",
        "date": "2026-07-01",
        "currency": "INR (Rs.)",
        "items": [("A4 paper (box)", 10, 950), ("Toner cartridge", 2, 1500)],
        "tax_rate": 0.18,
    },
    {
        "file": "invoice_2.png",
        "vendor": "Blue Harbor Supplies LLC",
        "number": "BH-88431",
        "date": "2026-06-24",
        "currency": "USD ($)",
        "items": [("Desk lamp", 4, 23.5), ("HDMI cable 2m", 12, 6.0), ("Mouse pads", 20, 3.25)],
        "tax_rate": 0.08,
    },
]


def draw_invoice(spec, out_path):
    img = Image.new("RGB", (900, 1100), "#fdfdfa")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 900, 110], fill="#1f2a44")
    d.text((40, 35), spec["vendor"], fill="white")
    d.text((40, 70), "TAX INVOICE", fill="#9fb0d0")
    d.text((620, 150), f"Invoice #: {spec['number']}", fill="black")
    d.text((620, 180), f"Date: {spec['date']}", fill="black")
    d.text((40, 150), f"Currency: {spec['currency']}", fill="black")

    y = 260
    d.line([40, y - 10, 860, y - 10], fill="#888")
    d.text((40, y), "Description", fill="black")
    d.text((520, y), "Qty", fill="black")
    d.text((620, y), "Unit", fill="black")
    d.text((740, y), "Amount", fill="black")
    y += 30
    d.line([40, y, 860, y], fill="#bbb")
    subtotal = 0.0
    for desc, qty, unit in spec["items"]:
        y += 34
        amount = qty * unit
        subtotal += amount
        d.text((40, y), desc, fill="black")
        d.text((520, y), str(qty), fill="black")
        d.text((620, y), f"{unit:,.2f}", fill="black")
        d.text((740, y), f"{amount:,.2f}", fill="black")
    tax = round(subtotal * spec["tax_rate"], 2)
    total = round(subtotal + tax, 2)
    y += 60
    d.line([500, y, 860, y], fill="#888")
    d.text((620, y + 12), "Subtotal:", fill="black")
    d.text((740, y + 12), f"{subtotal:,.2f}", fill="black")
    d.text((620, y + 42), f"Tax ({int(spec['tax_rate']*100)}%):", fill="black")
    d.text((740, y + 42), f"{tax:,.2f}", fill="black")
    d.text((620, y + 76), "TOTAL:", fill="black")
    d.text((740, y + 76), f"{total:,.2f}", fill="black")
    d.text((40, 1040), "Generated sample for LedgerLens demo — not a real invoice.", fill="#999")
    img.save(out_path)
    return subtotal, tax, total


def main():
    for spec in INVOICES:
        draw_invoice(spec, os.path.join(HERE, spec["file"]))
        print("wrote", spec["file"])
    # invoice_3: a slightly blurred, re-saved copy of invoice_1 -> dedupe target
    dup = Image.open(os.path.join(HERE, "invoice_1.png")).filter(ImageFilter.GaussianBlur(1.2))
    dup = dup.resize((880, 1076))
    dup.save(os.path.join(HERE, "invoice_3.png"))
    print("wrote invoice_3.png (near-duplicate of invoice_1)")


if __name__ == "__main__":
    main()
