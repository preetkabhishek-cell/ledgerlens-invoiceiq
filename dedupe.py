"""Stretch goal 1 — duplicate-invoice detection via perceptual hashing.

We compute an 8x8 average hash (aHash) of the invoice image with Pillow only:
grayscale -> resize to 8x8 -> threshold each pixel against the mean -> 64-bit
string. Re-uploads of the same invoice (photographed again, re-scanned,
slightly cropped or recompressed) land within a few bits of each other, while
different invoices are far apart. Uploads within Hamming distance 5 of an
existing invoice are flagged as duplicates instead of entering the ledger.
"""

from PIL import Image


def average_hash(image_path, size=8):
    img = Image.open(image_path).convert("L").resize((size, size), Image.LANCZOS)
    pixels = list(img.getdata())
    mean = sum(pixels) / len(pixels)
    return "".join("1" if p > mean else "0" for p in pixels)


def hamming(hash_a, hash_b):
    if not hash_a or not hash_b or len(hash_a) != len(hash_b):
        return 64  # treat malformed hashes as maximally distant
    return sum(a != b for a, b in zip(hash_a, hash_b))
