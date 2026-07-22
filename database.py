"""SQLite persistence for LedgerLens.

Schema
------
users     : evaluator/test login accounts
invoices  : one row per uploaded invoice image
fields    : one row per extracted field (vendor, date, total, ...) with the
            model's self-reported confidence and review status
line_items: extracted line items per invoice
"""

import sqlite3
from contextlib import contextmanager
from werkzeug.security import generate_password_hash

DB_PATH = "ledgerlens.db"

# Fields under this confidence are routed to the human review queue.
REVIEW_THRESHOLD = 0.8


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                image_hash TEXT,                -- perceptual hash for dedupe
                currency TEXT DEFAULT 'INR',
                status TEXT DEFAULT 'processing',  -- processing | needs_review | approved | duplicate
                duplicate_of INTEGER REFERENCES invoices(id),
                uploaded_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                name TEXT NOT NULL,             -- vendor | invoice_number | invoice_date | subtotal | tax | total
                value TEXT,
                confidence REAL,
                needs_review INTEGER DEFAULT 0, -- 1 when confidence < REVIEW_THRESHOLD
                reviewed INTEGER DEFAULT 0      -- 1 after a human confirmed/corrected it
            );

            CREATE TABLE IF NOT EXISTS line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                description TEXT,
                quantity REAL,
                unit_price REAL,
                amount REAL
            );
            """
        )
        # Seed the evaluator test account (idempotent).
        db.execute(
            "INSERT OR IGNORE INTO users (email, password_hash) VALUES (?, ?)",
            ("evaluator@demo.com", generate_password_hash("Demo@2026")),
        )


def insert_invoice(filename, image_hash, currency="INR"):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO invoices (filename, image_hash, currency) VALUES (?, ?, ?)",
            (filename, image_hash, currency),
        )
        return cur.lastrowid


def save_extraction(invoice_id, extraction):
    """Persist the model's extraction result and set invoice status."""
    any_low = False
    with get_db() as db:
        for name, item in extraction["fields"].items():
            conf = float(item.get("confidence", 0.0))
            low = 1 if conf < REVIEW_THRESHOLD else 0
            any_low = any_low or bool(low)
            db.execute(
                "INSERT INTO fields (invoice_id, name, value, confidence, needs_review)"
                " VALUES (?, ?, ?, ?, ?)",
                (invoice_id, name, str(item.get("value", "")), conf, low),
            )
        for li in extraction.get("line_items", []):
            db.execute(
                "INSERT INTO line_items (invoice_id, description, quantity, unit_price, amount)"
                " VALUES (?, ?, ?, ?, ?)",
                (invoice_id, li.get("description"), li.get("quantity"),
                 li.get("unit_price"), li.get("amount")),
            )
        currency = extraction.get("currency")
        if currency:
            db.execute("UPDATE invoices SET currency = ? WHERE id = ?", (currency, invoice_id))
        db.execute(
            "UPDATE invoices SET status = ? WHERE id = ?",
            ("needs_review" if any_low else "approved", invoice_id),
        )


def mark_duplicate(invoice_id, original_id):
    with get_db() as db:
        db.execute(
            "UPDATE invoices SET status = 'duplicate', duplicate_of = ? WHERE id = ?",
            (original_id, invoice_id),
        )


def find_hash_match(image_hash, max_distance=5):
    """Return the id of an existing non-duplicate invoice whose perceptual hash
    is within `max_distance` bits of `image_hash`, else None."""
    from dedupe import hamming
    with get_db() as db:
        rows = db.execute(
            "SELECT id, image_hash FROM invoices WHERE status != 'duplicate' AND image_hash IS NOT NULL"
        ).fetchall()
    for row in rows:
        if hamming(image_hash, row["image_hash"]) <= max_distance:
            return row["id"]
    return None


def review_queue():
    """Invoices that still have unreviewed low-confidence fields."""
    with get_db() as db:
        return db.execute(
            """
            SELECT i.*, COUNT(f.id) AS pending
            FROM invoices i
            JOIN fields f ON f.invoice_id = i.id
            WHERE f.needs_review = 1 AND f.reviewed = 0
            GROUP BY i.id ORDER BY i.uploaded_at DESC
            """
        ).fetchall()


def invoice_detail(invoice_id):
    with get_db() as db:
        inv = db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        fields = db.execute(
            "SELECT * FROM fields WHERE invoice_id = ? ORDER BY id", (invoice_id,)
        ).fetchall()
        items = db.execute(
            "SELECT * FROM line_items WHERE invoice_id = ? ORDER BY id", (invoice_id,)
        ).fetchall()
    return inv, fields, items


def apply_review(invoice_id, corrections):
    """corrections: {field_id: new_value}. Marks fields reviewed and, when none
    are left, flips the invoice to approved."""
    with get_db() as db:
        for field_id, value in corrections.items():
            db.execute(
                "UPDATE fields SET value = ?, reviewed = 1, confidence = 1.0"
                " WHERE id = ? AND invoice_id = ?",
                (value, field_id, invoice_id),
            )
        remaining = db.execute(
            "SELECT COUNT(*) c FROM fields WHERE invoice_id = ? AND needs_review = 1 AND reviewed = 0",
            (invoice_id,),
        ).fetchone()["c"]
        if remaining == 0:
            db.execute("UPDATE invoices SET status = 'approved' WHERE id = ?", (invoice_id,))


def ledger_rows():
    """Approved invoices flattened for the ledger view / CSV export."""
    with get_db() as db:
        invoices = db.execute(
            "SELECT * FROM invoices WHERE status = 'approved' ORDER BY uploaded_at DESC"
        ).fetchall()
        out = []
        for inv in invoices:
            f = {
                r["name"]: r["value"]
                for r in db.execute(
                    "SELECT name, value FROM fields WHERE invoice_id = ?", (inv["id"],)
                )
            }
            out.append({
                "id": inv["id"],
                "vendor": f.get("vendor", ""),
                "invoice_number": f.get("invoice_number", ""),
                "invoice_date": f.get("invoice_date", ""),
                "subtotal": f.get("subtotal", ""),
                "tax": f.get("tax", ""),
                "total": f.get("total", ""),
                "currency": inv["currency"],
                "uploaded_at": inv["uploaded_at"],
            })
        return out


def dashboard_stats():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) c FROM invoices").fetchone()["c"]
        approved = db.execute("SELECT COUNT(*) c FROM invoices WHERE status='approved'").fetchone()["c"]
        pending = db.execute("SELECT COUNT(*) c FROM invoices WHERE status='needs_review'").fetchone()["c"]
        dupes = db.execute("SELECT COUNT(*) c FROM invoices WHERE status='duplicate'").fetchone()["c"]
    return {"total": total, "approved": approved, "pending": pending, "duplicates": dupes}
