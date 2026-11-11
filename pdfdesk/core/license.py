"""The product key. pdfdesk opens only after a valid key was entered once; every edition asks this module.

For now there is one key for everyone. Only its SHA-256 is kept here, so the key cannot be read out of an
installed app or out of the source. Whoever has the key gives it to the browser test as PDFDESK_KEY."""
from __future__ import annotations

import hashlib

KEY_SHA256 = "0d8a4541cc470b582f3f14ee36a6a463df2f3c770dc3cb64c68647b03712a3bc"


def valid(key) -> bool:
    """True for the product key, however it was typed (case, spaces and dashes do not matter)."""
    plain = "".join(c for c in str(key or "").upper() if c.isalnum())
    return hashlib.sha256(plain.encode()).hexdigest() == KEY_SHA256
