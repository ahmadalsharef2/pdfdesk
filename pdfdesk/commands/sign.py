"""Signatures (plan phase 6).

* Fill & Sign / Quick Sign: a typed, drawn or image signature placed as page content (not a digital signature).
* Digital signatures with pyHanko: create a self-signed ID (.pfx), sign, certify, validate.
"""
from __future__ import annotations

import datetime as dt
import io
import os

import pymupdf

from ..core import fonts
from .registry import command

# ---- visual signatures ---------------------------------------------------------------------------------


@command("Sign.Typed")
def typed(doc, page: int, rect, name: str, color=(0, 0, 0.55)):
    p = doc[page - 1]
    r = pymupdf.Rect(rect)
    ff = fonts.script_font()
    fname = "sigscript" if ff else "tiit"
    if ff:
        p.insert_font(fontname=fname, fontfile=ff)
        f = pymupdf.Font(fontfile=ff)
    else:
        f = pymupdf.Font("tiit")
    # largest size that fits the box in one line
    size = min(r.height * 0.75, r.width / max(1e-3, f.text_length(name, 1)) * 0.95)
    x = r.x0 + (r.width - f.text_length(name, size)) / 2
    y = r.y0 + r.height * 0.5 + size * 0.35
    p.insert_text((x, y), name, fontname=fname, fontsize=size, color=color)
    return r


@command("Sign.Image")
def image(doc, page: int, rect, path: str | None = None, data: bytes | None = None):
    p = doc[page - 1]
    p.insert_image(pymupdf.Rect(rect), filename=path, stream=data, keep_proportion=True)
    return pymupdf.Rect(rect)


@command("Sign.Ink")
def ink(doc, page: int, strokes, color=(0, 0, 0.55), width: float = 1.8):
    """Strokes in page coordinates; drawn as page content."""
    p = doc[page - 1]
    sh = p.new_shape()
    for s in strokes:
        pts = [pymupdf.Point(q) for q in s]
        if len(pts) > 1:
            sh.draw_polyline(pts)
    sh.finish(color=color, width=width, closePath=False, lineCap=1, lineJoin=1)
    sh.commit()


CAPTION_FIELDS = ("name", "position", "company", "email", "phone", "address", "date")


def caption_lines(profile: dict, today: dt.date | None = None) -> list[str]:
    """Signer details -> caption lines. profile: {field: value, ..., "show": [fields], "layout": ...};
    "date" needs no value, it is the signing date. Layout "lines" (default): one detail per line;
    "compact": two lines, who (name, position, company) and contact (email, phone, address, date)."""
    show = set(profile.get("show", ()))
    val = {k: (profile.get(k) or "").strip() for k in CAPTION_FIELDS}
    val["date"] = (today or dt.date.today()).isoformat()
    if profile.get("layout") == "compact":
        groups = (("name", "position", "company"), ("email", "phone", "address", "date"))
    else:
        groups = tuple((k,) for k in CAPTION_FIELDS)
    lines = [" · ".join(val[k] for k in g if k in show and val[k]) for g in groups]
    return [ln for ln in lines if ln]


@command("Sign.Caption")
def caption(doc, page: int, rect, lines: list[str], color=(0.4, 0.4, 0.4), max_size: float = 7.0):
    """A hairline under the signature box and small grey detail lines below it, as page content."""
    p = doc[page - 1]
    r = pymupdf.Rect(rect)
    if not lines:
        return None
    ff = fonts.unicode_font()
    p.insert_font(fontname="sigcap", fontfile=ff)
    f = pymupdf.Font(fontfile=ff)
    widest = max(f.text_length(ln, 1) for ln in lines)
    size = max(5.0, min(max_size, r.width / max(1e-3, widest)))   # shrink to the box, but stay readable
    p.draw_line((r.x0, r.y1), (r.x1, r.y1), color=color, width=0.4)
    y = r.y1 + size * 1.25
    x0, x1 = r.x0, r.x1
    for ln in lines:
        x = r.x0 + (r.width - f.text_length(ln, size)) / 2
        p.insert_text((x, y), ln, fontname="sigcap", fontsize=size, color=color)
        x0, x1 = min(x0, x), max(x1, x + f.text_length(ln, size))
        y += size * 1.25
    return pymupdf.Rect(x0, r.y1, x1, y - size)   # down to the last line's descenders; wider if text overflows


@command("Sign.Place")
def place(doc, page: int, rect, spec: dict, lines: list[str] | None = None):
    """Fill & Sign: the signature (typed, ink or image spec) and its caption, placed as one object on the
    page, so Edit Object can move or resize it later. Returns the object's box."""
    r = pymupdf.Rect(rect)
    pad = 150                                            # room for a caption wider than the signature
    tmp = pymupdf.open()
    tmp.new_page(width=r.width + 2 * pad, height=r.height + 120)
    box = pymupdf.Rect(pad, 0, pad + r.width, r.height)
    if spec["kind"] == "typed":
        typed(tmp, 1, box, spec["name"])
    elif spec["kind"] == "image":
        image(tmp, 1, box, path=spec.get("path"), data=spec.get("data"))
    else:
        ink(tmp, 1, fit_strokes(spec["strokes"], spec["size"], box))
    clip = box | caption(tmp, 1, box, lines) if lines else box
    target = pymupdf.Rect(clip.x0 - pad + r.x0, r.y0, clip.x1 - pad + r.x0, r.y0 + clip.height)
    doc[page - 1].show_pdf_page(target, tmp, 0, clip=clip)
    return target


def fit_strokes(strokes, src_size, rect):
    """Scale strokes drawn on a canvas of src_size=(w,h) into rect, keeping aspect ratio."""
    r = pymupdf.Rect(rect)
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    if not xs:
        return []
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    bw, bh = max(bx1 - bx0, 1), max(by1 - by0, 1)
    k = min(r.width / bw, r.height / bh) * 0.9
    ox = r.x0 + (r.width - bw * k) / 2
    oy = r.y0 + (r.height - bh * k) / 2
    return [[(ox + (x - bx0) * k, oy + (y - by0) * k) for x, y in s] for s in strokes]


# ---- digital IDs -----------------------------------------------------------------------------------------

@command("Sign.CreateID")
def create_id(path: str, name: str, password: str, email: str | None = None, org: str | None = None,
              years: int = 5):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, name)]
    if org:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org))
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    subj = x509.Name(attrs)
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365 * years))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION,
                                                  ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
            .sign(key, hashes.SHA256()))
    blob = pkcs12.serialize_key_and_certificates(name.encode(), key, cert, None,
                                                 serialization.BestAvailableEncryption(password.encode()))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)
    os.chmod(path, 0o600)
    with open(os.path.splitext(path)[0] + ".cer", "wb") as f:   # public certificate, for the trust list
        f.write(cert.public_bytes(serialization.Encoding.DER))
    return path


def _pdf_box(page: pymupdf.Page, rect) -> tuple[float, float, float, float]:
    """PyMuPDF rect (top-left origin, unrotated) -> PDF user-space box (bottom-left origin)."""
    r = pymupdf.Rect(rect) * page.transformation_matrix  # transformation_matrix maps both ways for flips
    return (min(r.x0, r.x1), min(r.y0, r.y1), max(r.x0, r.x1), max(r.y0, r.y1))


@command("Sign.Digital")
def digital(src: str | bytes, dst: str, pfx: str, password: str, page: int | None = None, rect=None,
            reason: str | None = None, location: str | None = None, field_name: str | None = None,
            certify: str | None = None):
    """Sign src (path or bytes) into dst. rect=None -> invisible signature.
    certify: None | 'none' (no changes) | 'forms' (form fill + sign) | 'annotations' (+ comments)."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko.stamp import TextStampStyle

    data = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
    signer = signers.SimpleSigner.load_pkcs12(pfx, passphrase=password.encode())
    if signer is None:
        raise ValueError("could not open the digital ID (wrong password?)")
    w = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
    field_name = field_name or f"Signature{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
    spec = None
    if rect is not None and page is not None:
        d = pymupdf.open("pdf", data)
        box = _pdf_box(d[page - 1], rect)
        spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=page - 1, box=box)
    perms = {"none": fields.MDPPerm.NO_CHANGES, "forms": fields.MDPPerm.FILL_FORMS,
             "annotations": fields.MDPPerm.ANNOTATE}
    meta = signers.PdfSignatureMetadata(field_name=field_name, reason=reason, location=location,
                                        certify=certify is not None,
                                        docmdp_permissions=perms[certify] if certify else fields.MDPPerm.FILL_FORMS)
    lines = ["Digitally signed by %(signer)s", "Date: %(ts)s"]
    if reason:
        lines.append(f"Reason: {reason}")
    if location:
        lines.append(f"Location: {location}")
    style = TextStampStyle(stamp_text="\n".join(lines), border_width=1)
    pdf_signer = signers.PdfSigner(meta, signer, stamp_style=style, new_field_spec=spec)
    with open(dst, "wb") as out:
        pdf_signer.sign_pdf(w, output=out)
    return dst


@command("Sign.Validate")
def validate(path: str, trusted_pfx: list[tuple[str, str]] | None = None, trusted_certs: list[str] | None = None):
    """Return one dict per signature: field, signer, intact, valid, trusted, coverage, modification level."""
    from pyhanko.keys import load_cert_from_pemder
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign import validation
    from pyhanko_certvalidator import ValidationContext

    roots = []
    for pfx, pw in trusted_pfx or []:
        from cryptography.hazmat.primitives.serialization import pkcs12
        from asn1crypto import x509 as ax509
        _k, cert, _ = pkcs12.load_key_and_certificates(open(pfx, "rb").read(), pw.encode())
        from cryptography.hazmat.primitives.serialization import Encoding
        roots.append(ax509.Certificate.load(cert.public_bytes(Encoding.DER)))
    for c in trusted_certs or []:
        roots.append(load_cert_from_pemder(c))
    vc = ValidationContext(trust_roots=roots, allow_fetching=False)
    out = []
    with open(path, "rb") as f:
        r = PdfFileReader(f, strict=False)
        for sig in r.embedded_signatures:
            st = validation.validate_pdf_signature(sig, vc)
            out.append({
                "field": sig.field_name,
                "signer": st.signing_cert.subject.human_friendly if st.signing_cert else "",
                "intact": bool(st.intact),
                "valid": bool(st.valid),
                "trusted": bool(st.trusted),
                "coverage": str(st.coverage.name if st.coverage else ""),
                "modification_level": str(st.modification_level.name if st.modification_level else ""),
                "docmdp_ok": getattr(st, "docmdp_ok", None),
                "signed_at": str(getattr(st, "signer_reported_dt", "") or ""),
                "summary": st.summary(),
            })
    return out
