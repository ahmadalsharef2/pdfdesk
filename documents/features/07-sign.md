# Phase 6 — Signatures

All digital-signature work uses pyHanko. Test certificates come from a throwaway CA made by the test
suite. pyHanko's own test tooling can run a local timestamp server and OCSP responder.

### F70 Digital IDs

- **Foxit** (p. 337): create a self-signed digital ID (name, organisation, email, key algorithm,
  key usage, validity) saved as a `.pfx` file or in the Windows store; use an existing ID from a file or
  a smart card or token.
- **pdfdesk:** the `cryptography` package creates PKCS#12 files in `~/.local/share/pdfdesk/ids/`. Tokens
  and smart cards go through PKCS#11 (`python-pkcs11`, OpenSC).
- **Example:** before: no IDs. After: a self-signed RSA-2048 ID "Test User". **Check:** the `.pfx` opens
  with its password and the certificate has the chosen subject and key usage.

### F71 Sign

- **Foxit** (pp. 338–341): drag a box or use a signature field. Pick a digital ID and an appearance
  (name, date, distinguished name, reason, location, logo, image of a handwritten signature, labels).
  "Lock document after signing". Sign, then save as a new revision. Signature panel.
- **pdfdesk:** pyHanko `signers.sign_pdf` with `PdfSignatureMetadata`. Appearances from pyHanko stamp
  styles with pdfdesk's own appearance editor. Signing is always an incremental save.
- **Example:** before: C3 v1. After: a visible signature on p. 6 with reason "Approved". **Check:**
  pyHanko validation reports the signature intact and covering the whole file, and the appearance shows
  the reason.

### F72 Certify

- **Foxit** (p. 347, Business): only the author certifies. Permitted actions after certifying: no
  changes; form filling and signing; form filling, signing and commenting. A change outside the
  permission invalidates the certification.
- **pdfdesk:** pyHanko certification signature with DocMDP permission level 1, 2 or 3.
- **Example:** before: C4. After: certified with "form filling and signing". A filled field keeps the
  certification valid; adding a comment breaks it. **Check:** pyHanko's modification analysis for each
  case.

### F73 Timestamps

- **Foxit** (pp. 347–348): a timestamp in a signature, or a document timestamp, from a configured
  timestamp server that is in the trusted list.
- **pdfdesk:** RFC 3161 through pyHanko's `HTTPTimeStamper`. Servers are set in preferences.
- **Example:** before: C3 v1. After: a document timestamp from a local test timestamp server.
  **Check:** validation reports the timestamp token valid and its time.

### F74 Validate, versions, long-term validation

- **Foxit** (pp. 342–346, 348–349):
  - Validate one or all signatures, with status icons.
  - Signature Properties: signer, time, reason, location, validity summary, certificate details.
  - View the signed version of a revision, and compare it with the current version.
  - Long-term validation: add revocation data so a signature can still be checked later.
  - Trusted Certificates window.
- **pdfdesk:** pyHanko validation with a trust list in pdfdesk's settings. OCSP and CRL lookups. LTV
  adds revocation data to the DSS. "View signed version" saves the bytes covered by the signature as a
  temporary PDF. "Compare versions" opens that with F55.
- **Example:** before: the F71 output with one extra comment added after signing. After: validation
  says "signed, with changes after signing". The signed version opens without the comment, and Compare
  shows one annotation change. **Check:** pyHanko's status and the F55 change list.

### F75 PAdES

- **Foxit:** `fsigpades.dll` points to PAdES support.
- **pdfdesk:** pyHanko PAdES baseline profiles B-B, B-T, B-LT and B-LTA.
- **Example:** before: C3 v1. After: PAdES B-LTA signature. **Check:** pyHanko reports the PAdES level
  B-LTA.
- **Open:** which PAdES levels Foxit offers in its user interface. Black-box: look at the signing
  dialog's options in Foxit.

### F76 Fill & Sign and Quick PDF Signature

- **Foxit** (pp. 352–354, v10 notes p. 9): signatures made by typing, drawing or using an image, placed
  as page content, not as a digital signature. Fill & Sign adds text, check marks, crosses, dots, lines
  and boxes anywhere on a flat form. Saved signatures are reused.
- **pdfdesk:** PyMuPDF inserts the signature image or ink as page content. Saved signatures go in
  `~/.local/share/pdfdesk/signatures/`.
- **Example:** before: C3 v1 p. 6. After: a drawn signature and today's date typed on the signature line.
  **Check:** the page has one new image or path object and the date text. No `/Sig` field is created.

### F77 DocuSign

Built in phase 13. See [14-share.md](14-share.md), F164.
