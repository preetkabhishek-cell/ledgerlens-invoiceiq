"""LedgerLens — photographed invoices in, clean ledger out.

Flow: upload -> perceptual-hash dedupe check -> Gemini vision extraction with
per-field confidence -> fields under 0.8 go to the human review queue ->
approved invoices land in the ledger -> one-click CSV export.
"""

import csv
import io
import os
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, flash, redirect, render_template, request,
    send_from_directory, session, url_for, Response,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

import database as db
from currency import ledger_total_inr, RATES_TO_INR
from dedupe import average_hash
from extraction import extract_invoice

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-secret")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

db.init_db()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# auth ------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard") if "user" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db.get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user"] = email
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# core flow -------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        stats=db.dashboard_stats(),
        queue=db.review_queue(),
    )


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("invoice")
    if not file or not file.filename:
        flash("Choose an invoice image first.")
        return redirect(url_for("dashboard"))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        flash(f"Unsupported file type {ext} — use PNG/JPG/WEBP.")
        return redirect(url_for("dashboard"))

    filename = secure_filename(file.filename)
    # avoid clobbering an earlier upload of the same name
    base, i = filename, 1
    while os.path.exists(os.path.join(UPLOAD_DIR, filename)):
        name, e = os.path.splitext(base)
        filename = f"{name}_{i}{e}"
        i += 1
    path = os.path.join(UPLOAD_DIR, filename)
    file.save(path)

    # Stretch 1: duplicate detection before we spend an API call
    img_hash = average_hash(path)
    original = db.find_hash_match(img_hash)
    invoice_id = db.insert_invoice(filename, img_hash)
    if original:
        db.mark_duplicate(invoice_id, original)
        flash(f"Looks like a duplicate of invoice #{original} — parked, not added to the ledger.")
        return redirect(url_for("invoice_view", invoice_id=invoice_id))

    try:
        result = extract_invoice(path)
    except RuntimeError as err:
        flash(f"Extraction failed: {err}")
        return redirect(url_for("dashboard"))

    db.save_extraction(invoice_id, result)
    return redirect(url_for("invoice_view", invoice_id=invoice_id))


@app.route("/invoice/<int:invoice_id>", methods=["GET", "POST"])
@login_required
def invoice_view(invoice_id):
    if request.method == "POST":
        corrections = {
            int(k.split("_", 1)[1]): v
            for k, v in request.form.items()
            if k.startswith("field_") and k.split("_", 1)[1].isdigit()
        }
        db.apply_review(invoice_id, corrections)
        flash("Corrections saved — invoice approved." )
        return redirect(url_for("ledger"))
    inv, fields, items = db.invoice_detail(invoice_id)
    if inv is None:
        flash("No such invoice.")
        return redirect(url_for("dashboard"))
    return render_template(
        "invoice.html", inv=inv, fields=fields, items=items,
        threshold=db.REVIEW_THRESHOLD,
    )


@app.route("/ledger")
@login_required
def ledger():
    rows = db.ledger_rows()
    total_inr, skipped = ledger_total_inr(rows)
    return render_template(
        "ledger.html", rows=rows, total_inr=total_inr,
        skipped=skipped, rates=RATES_TO_INR,
    )


@app.route("/export.csv")
@login_required
def export_csv():
    rows = db.ledger_rows()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id", "vendor", "invoice_number", "invoice_date",
        "subtotal", "tax", "total", "currency", "uploaded_at",
    ])
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ledgerlens_export.csv"},
    )


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
