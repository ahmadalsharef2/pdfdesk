"""Document security that survives saving.

PyMuPDF (2.0 / MuPDF 1.28) drops encryption on any full save or tobytes(), even with PDF_ENCRYPT_KEEP;
only incremental saves keep it. So pdfdesk keeps the security settings next to the document and applies
them on every full save. When the settings are not fully known (file opened with only one of its two
passwords), saving asks instead of silently writing an unprotected file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pymupdf

METHODS = {"AES-256": pymupdf.PDF_ENCRYPT_AES_256, "AES-128": pymupdf.PDF_ENCRYPT_AES_128,
           "RC4-128": pymupdf.PDF_ENCRYPT_RC4_128}


@dataclass
class Security:
    user_pw: str | None          # None = not known
    owner_pw: str | None         # None = not known
    permissions: int
    method: int = pymupdf.PDF_ENCRYPT_AES_256

    @property
    def complete(self) -> bool:
        return self.user_pw is not None and self.owner_pw is not None

    def save_kwargs(self) -> dict:
        assert self.complete
        return {"encryption": self.method, "user_pw": self.user_pw, "owner_pw": self.owner_pw,
                "permissions": self.permissions}


def permissions(allow_print=True, allow_copy=True, allow_modify=False, allow_annotate=True) -> int:
    perm = pymupdf.PDF_PERM_ACCESSIBILITY
    if allow_print:
        perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        perm |= pymupdf.PDF_PERM_COPY
    if allow_modify:
        perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ASSEMBLE
    if allow_annotate:
        perm |= pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM
    return perm


def _encrypt_dict(doc) -> dict[str, str]:
    """Read /Encrypt from the trailer (inline dict or indirect object; key paths handle both)."""
    if doc.xref_get_key(-1, "Encrypt")[0] == "null":
        return {}
    out = {}
    for k in ("V", "R", "Length", "P", "CF"):
        t, v = doc.xref_get_key(-1, f"Encrypt/{k}")
        if t != "null":
            out[k] = v
    return out


def from_open(doc: pymupdf.Document, typed_pw: str | None, auth: int) -> Security | None:
    """Security of a file just opened. auth is doc.authenticate()'s result (2 user, 4 owner, 6 both)."""
    if not doc.metadata.get("encryption"):
        return None
    enc = _encrypt_dict(doc)
    r = int(enc.get("R", "0") or 0)
    method = pymupdf.PDF_ENCRYPT_AES_256 if r >= 5 else (
        pymupdf.PDF_ENCRYPT_AES_128 if "AESV2" in enc.get("CF", "") else pymupdf.PDF_ENCRYPT_RC4_128)
    try:
        perm = int(enc.get("P", "-4"))
    except ValueError:
        perm = -4
    perm &= 0xFFFFFFFF
    user = owner = None
    if typed_pw is None:            # opened without a password: user password is empty
        user = ""
    if auth & 2:
        user = typed_pw
    if auth & 4:
        owner = typed_pw
    if auth == 6:
        user = owner = typed_pw
    return Security(user, owner, perm if perm < 2**31 else perm - 2**32, method)


def restricted(doc: pymupdf.Document, auth: int) -> bool:
    """True when opened with only the user password and the file forbids changes."""
    return bool(doc.metadata.get("encryption")) and not (auth & 4) and not (doc.permissions & pymupdf.PDF_PERM_MODIFY)


def save(doc: pymupdf.Document, path: str, security: Security | None, incremental: bool) -> pymupdf.Document:
    """Save and return the document to keep working on (reopened from disk after a full save)."""
    if incremental and doc.name == path and doc.can_save_incrementally():
        doc.saveIncr()
        return doc
    if security is not None and not security.complete:
        raise PermissionError("security settings incomplete")
    kwargs = security.save_kwargs() if security else {"encryption": pymupdf.PDF_ENCRYPT_NONE}
    tmp = path + ".pdfdesk-tmp"
    doc.save(tmp, garbage=3, deflate=True, **kwargs)
    os.replace(tmp, path)
    new = pymupdf.open(path)
    if new.needs_pass:
        new.authenticate(security.owner_pw or security.user_pw)
    return new
