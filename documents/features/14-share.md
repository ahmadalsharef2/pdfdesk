# Phase 13 — Share, connectors, sensitivity labels

Each connector uses that service's own public API, never Foxit's plug-in. A connector without an
account to test against is not built until one exists (see question 2 in [plan.md](../plan.md)).

### F160 Email, Evernote, OneNote

- **Foxit** (pp. 241–242): email the current document; send to Evernote; send to OneNote.
- **pdfdesk:** `xdg-email --attach` opens the user's mail program. Evernote and OneNote (Microsoft Graph)
  through their APIs, if an account exists.
- **Example:** before: C3 v1 open. After: "Email" opens the mail program with the file attached.
  **Check:** the command line passed to `xdg-email`.

### F161 Shared review and email review

- **Foxit** (pp. 244–247): send a PDF for shared review (initiating is Business only) to a network
  folder, SharePoint or email. Participants' comments are published to the shared place and merged
  for everyone. A tracker (`TrackReview.exe`) lists reviews, deadlines and participants. Email review
  sends the PDF and collects comments sent back.
- **pdfdesk:** the review PDF carries a review ID and the shared-folder address in its metadata. Each
  participant's comments are written to the shared folder as one XFDF file per person, and merged on
  open and on "Check for new comments". The tracker is a panel over a local list of reviews. Email review
  uses F160 and F108's XFDF import.
- **Example:** before: C3 v1 and a shared folder. After: user A starts a review; users B and C (two test
  profiles) add 2 comments each; A checks for new comments. **Check:** A's copy shows 4 comments with the
  right authors, and the folder holds 2 XFDF files.
- **Open:** Foxit's shared-review folder layout, so pdfdesk and Foxit users could share one review.
  Black-box: start a review in Foxit and look at what it writes.

### F162 Cloud drives

- **Foxit** (Open and Save dialogs, Compare, Bates, export): Google Drive, OneDrive (personal and
  business), Dropbox, Box, Egnyte, ShareFile, Foxit Drive.
- **pdfdesk:** rclone covers Google Drive, OneDrive, Dropbox and Box (and SharePoint document
  libraries through its OneDrive backend). Egnyte and ShareFile use their REST APIs. Open and Save
  dialogs show a "Cloud" side panel. Foxit Drive is not built (Foxit's servers).
- **Example:** before: an rclone remote for the user's Google Drive. After: open a PDF from Drive, add a
  note, save. **Check:** the Drive file's modification time changes, and the downloaded copy has the note.

### F163 SharePoint

- **Foxit** (pp. 242–243, 419–420): open from and save to SharePoint; check out, check in and discard
  check-out.
- **pdfdesk:** Microsoft Graph API (drive items, check-out and check-in).
- **Example:** needs a SharePoint site. **Check:** a file checked out, edited and checked in shows a new
  version in the site's history.

### F164 DocuSign

- **Foxit** (pp. 350–351): sign with DocuSign, or send a PDF through DocuSign for others to sign.
- **pdfdesk:** DocuSign eSignature REST API. DocuSign's free developer sandbox is enough for testing.
- **Example:** before: C3 v1. After: sent to a test recipient in the sandbox. **Check:** the envelope's
  status from the API is "sent", and the signed copy downloads after the test recipient signs.

### F165 Document-management connectors

- **Foxit** (pp. 248–261): ndOffice, iManage Work, OpenText eDOCS, Documentum, Content Suite, Worldox,
  ShareFile, Epona DMSforLegal, Alfresco. Open, save, check in and out, versions, and Bates numbering
  from the system (v10).
- **pdfdesk:**
  - Alfresco: through CMIS. Alfresco Community Edition can run locally in Docker, so it can be tested
    without an account. Docker is not installed here; it would be added for this (apt, needs sudo).
  - Documentum and OpenText: CMIS where the server offers it.
  - iManage Work: its REST API.
  - Worldox, ndOffice and DMSforLegal: built only against a real server, because their APIs are not
    public.
- **Example:** before: Alfresco in Docker with a test folder. After: open C3 v1 from it, Bates-number it
  (F21), save back. **Check:** Alfresco shows a new version with the numbers.

### F166 Sensitivity labels (AIP / MIP)

- **Foxit** (pp. 308–321, Business):
  - Classify documents with Microsoft Information Protection labels; protect with templates or custom
    permissions; apply in batch.
  - Open protected files with the rights they grant.
  - RMS settings.
  - "Generate redacted and AIP-protected PDFs" (pp. 327–328): authorised users see the full document,
    and others see the redacted one.
  - Foxit's files: `plugins/AIPLabel.fpi`, `mip_*.dll`.
- **pdfdesk:** Microsoft's MIP SDK, which has Linux builds, called through a small native helper. This
  needs a Microsoft 365 tenant with labels set up, plus an app registration. Without one, nothing can be
  built or tested.
- **Example:** needs a tenant. **Check:** a labelled file opened in Office or Foxit shows the same label,
  and a protected file denies printing to a user without that right.
