"""Invoice tab dialogs: create an e-invoice (a form whose fields follow the choices made in it), and show the
data and check results of an e-invoice found in a PDF or XML file."""
from __future__ import annotations

import datetime as dt
import html
import re

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..commands import invoice as inv_cmds
from ..lang import tr
from . import prefs, theme
from .dialogs import ColorButton, size_for_screen

UNIT_CHOICES = [("C62", "piece"), ("HUR", "hour"), ("DAY", "day"), ("MON", "month"), ("LS", "lump sum"),
                ("KGM", "kg"), ("MTR", "metre"), ("MTK", "m²"), ("LTR", "litre")]
TYPES = [("380", "Invoice"), ("381", "Credit note"), ("326", "Partial invoice"), ("384", "Corrected invoice")]
OUTPUTS = [("pdf", "ZUGFeRD PDF (PDF/A-3 with the XML inside)"), ("both", "ZUGFeRD PDF + separate XML file"),
           ("xml", "XML only (XRechnung)")]
SELLER_KEYS = ("name", "street", "zip", "city", "country", "vat_id", "tax_number", "contact", "phone", "email",
               "electronic_address", "iban", "bic", "account_name")


def _next_number(last: str) -> str:
    year = str(dt.date.today().year)
    m = re.search(r"(\d+)(\D*)$", last or "")
    if not m:
        return f"RE-{year}-0001"
    n = str(int(m.group(1)) + 1).zfill(len(m.group(1)))
    return last[:m.start(1)] + n + m.group(2)


class InvoiceDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("Create E-Invoice"))
        size_for_screen(self, 760, 620)
        self.saved = prefs.get_json("invoice/seller", {})
        saved_prefs = prefs.get_json("invoice/prefs", {})
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)

        # -- Invoice & customer
        w = QWidget()
        self.f_main = f = QFormLayout(w)
        self.type = QComboBox()
        for code, label in TYPES:
            self.type.addItem(tr(label), code)
        self.number = QLineEdit(_next_number(saved_prefs.get("invoice/last_number", "")))
        self.preceding = QLineEdit(placeholderText=tr("Number of the invoice this one corrects or credits"))
        self.issue = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.delivery = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.due_days = QSpinBox(minimum=0, maximum=365, value=int(saved_prefs.get("due_days", 14)), suffix=tr(" days"))
        self.currency = QComboBox(editable=True)
        self.currency.addItems([tr(s) for s in ("EUR", "CHF", "USD", "GBP")])
        self.public = QCheckBox(tr("Customer is a public authority (XRechnung)"))
        self.b = {k: QLineEdit() for k in ("name", "street", "zip", "city", "vat_id", "email", "electronic_address",
                                           "leitweg", "order")}
        self.b_country = QLineEdit("DE", maxLength=2)
        self.b["leitweg"].setPlaceholderText(tr("e.g. 04011000-12345-34"))
        self.b["electronic_address"].setPlaceholderText(tr("Customer's e-invoice address (e-mail)"))
        f.addRow(tr("Document:"), self.type)
        f.addRow(tr("Invoice number:"), self.number)
        f.addRow(tr("Refers to invoice:"), self.preceding)
        f.addRow(tr("Invoice date:"), self.issue)
        f.addRow(tr("Delivery / service date:"), self.delivery)
        f.addRow(tr("Payment due in:"), self.due_days)
        f.addRow(tr("Currency:"), self.currency)
        f.addRow(QLabel("<b>" + tr("Customer") + "</b>"))
        f.addRow("", self.public)
        f.addRow(tr("Name / company:"), self.b["name"])
        f.addRow(tr("Street:"), self.b["street"])
        row = QHBoxLayout()
        row.addWidget(self.b["zip"], 1)
        row.addWidget(self.b["city"], 3)
        row.addWidget(self.b_country)
        self.b_country.setFixedWidth(44)
        f.addRow(tr("Post code, city, country:"), row)
        f.addRow(tr("Customer VAT ID:"), self.b["vat_id"])
        f.addRow(tr("Leitweg-ID:"), self.b["leitweg"])
        f.addRow(tr("E-invoice address:"), self.b["electronic_address"])
        f.addRow(tr("Order / reference:"), self.b["order"])
        self.tabs.addTab(w, tr("Invoice && Customer"))

        # -- Items and VAT
        w = QWidget()
        iv = QVBoxLayout(w)
        top = QFormLayout()
        self.vat = QComboBox()
        for key, (label, *_rest) in inv_cmds.VAT_TREATMENTS.items():
            self.vat.addItem(tr(label), key)
        self.vat.setCurrentIndex(max(0, self.vat.findData(saved_prefs.get("vat", "standard"))))
        self.reason = QLineEdit()
        top.addRow(tr("VAT:"), self.vat)
        top.addRow(tr("Note on the invoice:"), self.reason)
        self.f_items = top
        iv.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr(s) for s in ("Description", "Quantity", "Unit", "Unit price (net)", "VAT %")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._totals)
        iv.addWidget(self.table, 1)
        row = QHBoxLayout()
        add, rem = QPushButton(tr("Add line")), QPushButton(tr("Remove line"))
        add.clicked.connect(lambda: self._add_line())
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) or self._totals())
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        self.paid = QCheckBox(tr("Already paid"))
        self.paid.toggled.connect(self._totals)
        row.addWidget(self.paid)
        iv.addLayout(row)
        self.tabs.addTab(w, tr("Items && VAT"))

        # -- Your details (remembered)
        w = QWidget()
        self.f_seller = f = QFormLayout(w)
        self.s = {k: QLineEdit(self.saved.get(k, "")) for k in SELLER_KEYS}
        if not self.s["country"].text():
            self.s["country"].setText("DE")
        self.s["country"].setMaxLength(2)
        self.s["country"].setFixedWidth(44)
        labels = {"name": "Company / name:", "street": "Street:", "zip": "Post code:", "city": "City:",
                  "country": "Country:", "vat_id": "VAT ID (USt-IdNr.):", "tax_number": "Tax number (Steuernr.):",
                  "contact": "Contact person:", "phone": "Phone:", "email": "E-mail:",
                  "electronic_address": "E-invoice address:", "iban": "IBAN:", "bic": "BIC:",
                  "account_name": "Account holder:"}
        for k in SELLER_KEYS:
            if k == "contact":
                f.addRow(QLabel("<b>" + tr("Contact") + "</b>"))
            if k == "iban":
                f.addRow(QLabel("<b>" + tr("Bank account") + "</b>"))
            f.addRow(tr(labels[k]), self.s[k])
        self.tabs.addTab(w, tr("Your Details"))

        # -- Design and output
        w = QWidget()
        f = QFormLayout(w)
        self.design = QComboBox()
        self.design.addItem(tr("Classic"), "classic")
        self.design.addItem(tr("Modern (coloured header)"), "modern")
        self.design.setCurrentIndex(max(0, self.design.findData(saved_prefs.get("design", "classic"))))
        self.lang = QComboBox()
        self.lang.addItem("Deutsch", "de")
        self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(max(0, self.lang.findData(saved_prefs.get("lang", "de"))))
        self.accent = ColorButton(text=tr("Accent colour"))
        acc = saved_prefs.get("accent", theme.ACCENT)
        self.accent.set_color(tuple(int(acc[i:i + 2], 16) / 255 for i in (1, 3, 5)), emit=False)
        self.logo = QLineEdit(saved_prefs.get("logo", ""), placeholderText=tr("PNG or JPEG (optional)"))
        pick = QPushButton(tr("Choose…"))
        pick.clicked.connect(lambda: (p := QFileDialog.getOpenFileName(self, tr("Logo"), "", tr("Images (*.png *.jpg *.jpeg)"))[0])
                             and self.logo.setText(p))
        row = QHBoxLayout()
        row.addWidget(self.logo, 1)
        row.addWidget(pick)
        self.output = QComboBox()
        for key, label in OUTPUTS:
            self.output.addItem(tr(label), key)
        f.addRow(tr("Design:"), self.design)
        f.addRow(tr("Language:"), self.lang)
        f.addRow(tr("Accent colour:"), self.accent)
        f.addRow(tr("Logo:"), row)
        f.addRow(tr("Save as:"), self.output)
        self.tabs.addTab(w, tr("Design && Output"))

        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-weight:bold;padding:4px")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Create"))
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.total_label, 1)
        bottom.addWidget(bb)
        v.addLayout(bottom)

        for line in saved_prefs.get("lines") or [{}]:
            self._add_line(line)
        self.type.currentIndexChanged.connect(self._dynamic)
        self.public.toggled.connect(self._dynamic)
        self.vat.currentIndexChanged.connect(self._vat_changed)
        self.currency.currentTextChanged.connect(self._totals)
        self._vat_changed()
        self._dynamic()
        self.result = None

    # ---- the parts of the form that follow the choices -------------------------------------------------------
    def _add_line(self, line: dict | None = None):
        line = line or {}
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c, val in ((0, line.get("name", "")), (1, line.get("quantity", "1")), (3, line.get("price", "")),
                       (4, line.get("vat_rate", "19"))):
            it = QTableWidgetItem(str(val))
            if c:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, c, it)
        unit = QComboBox()
        for code, label in UNIT_CHOICES:
            unit.addItem(tr(label), code)
        unit.setCurrentIndex(max(0, unit.findData(line.get("unit", "C62"))))
        self.table.setCellWidget(r, 2, unit)
        self.table.blockSignals(False)
        self._vat_changed(keep_reason=True)

    def _vat_changed(self, *_a, keep_reason=False):
        label, cat, zero, reason = inv_cmds.VAT_TREATMENTS[self.vat.currentData()]
        if not keep_reason:
            self.reason.setText(reason)
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 4)
            if it is None:
                continue
            if zero:
                it.setText("0")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            else:
                if it.text() == "0" and not (it.flags() & Qt.ItemIsEditable):
                    it.setText("19")
                it.setFlags(it.flags() | Qt.ItemIsEditable)
        self.table.blockSignals(False)
        self.f_items.setRowVisible(self.reason, True)
        self._dynamic()

    def _dynamic(self, *_a):
        """Show and require what the current choices need (like the official forms do)."""
        public = self.public.isChecked()
        vat = self.vat.currentData()
        f = self.f_main
        f.setRowVisible(self.preceding, self.type.currentData() in ("381", "384"))
        f.setRowVisible(self.b["leitweg"], public)
        f.setRowVisible(self.b["electronic_address"], public)
        need_buyer_vat = vat in ("reverse", "intra-eu")
        f.labelForField(self.b["vat_id"]).setText(tr("Customer VAT ID *:") if need_buyer_vat else tr("Customer VAT ID:"))
        for k in ("contact", "phone", "email", "electronic_address"):
            lab = self.f_seller.labelForField(self.s[k])
            lab.setText(lab.text().rstrip(" *:").rstrip(":") + (" *:" if public else ":"))
        if public and self.output.currentData() == "pdf":
            self.output.setCurrentIndex(self.output.findData("both"))
        self._totals()

    def values(self) -> dict:
        lines = []
        for r in range(self.table.rowCount()):
            cell = lambda c: (self.table.item(r, c).text().strip() if self.table.item(r, c) else "")
            lines.append({"name": cell(0), "quantity": cell(1) or "1", "unit": self.table.cellWidget(r, 2).currentData(),
                          "price": cell(3) or "0", "vat_rate": cell(4) or "0"})
        public = self.public.isChecked()
        s = {k: w.text().strip() for k, w in self.s.items()}
        issue = self.issue.date().toPython()
        inv = {
            "number": self.number.text().strip(), "type_code": self.type.currentData(),
            "issue_date": issue.isoformat(), "delivery_date": self.delivery.date().toPython().isoformat(),
            "due_date": (issue + dt.timedelta(days=self.due_days.value())).isoformat(),
            "currency": self.currency.currentText().strip().upper() or "EUR",
            "vat_treatment": self.vat.currentData(), "exemption_reason": self.reason.text().strip()
            if inv_cmds.VAT_TREATMENTS[self.vat.currentData()][2] else "",
            "note": "" if inv_cmds.VAT_TREATMENTS[self.vat.currentData()][2] else self.reason.text().strip(),
            "xrechnung": public, "buyer_reference": self.b["leitweg"].text().strip() if public else "",
            "order_reference": self.b["order"].text().strip(), "preceding": self.preceding.text().strip()
            if self.type.currentData() in ("381", "384") else "",
            "seller": {k: s[k] for k in SELLER_KEYS if k not in ("iban", "bic", "account_name")},
            "buyer": {"name": self.b["name"].text().strip(), "street": self.b["street"].text().strip(),
                      "zip": self.b["zip"].text().strip(), "city": self.b["city"].text().strip(),
                      "country": self.b_country.text().strip().upper() or "DE", "vat_id": self.b["vat_id"].text().strip(),
                      "electronic_address": self.b["electronic_address"].text().strip() if public else ""},
            "payment": {"iban": s["iban"], "bic": s["bic"], "account_name": s["account_name"] or s["name"]},
            "lines": lines,
        }
        if not s["electronic_address"] and public:
            inv["seller"]["electronic_address"] = s["email"]
        if self.due_days.value():
            days = self.due_days.value()
            inv["payment_terms"] = (f"Zahlbar innerhalb von {days} Tagen ohne Abzug." if self.lang.currentData() == "de"
                                    else f"Payable within {days} days without deduction.")
        else:
            inv["payment_terms"] = "Zahlbar sofort ohne Abzug." if self.lang.currentData() == "de" else "Payable immediately."
        return inv

    def _totals(self, *_a):
        try:
            c = inv_cmds.compute(self.values())
        except Exception:  # noqa: BLE001
            return
        t, cur = c["totals"], self.currency.currentText()
        lang = "en"
        self.total_label.setText(tr("Net {net}   ·   VAT {vat}   ·   Total {total}", net=inv_cmds._fmt(t["line_total"], lang, cur),
                                    vat=inv_cmds._fmt(t["tax_total"], lang, cur), total=inv_cmds._fmt(t["grand_total"], lang, cur))
                                 + ("   " + tr("(paid)") if self.paid.isChecked() else ""))

    def _missing(self, inv: dict) -> list[str]:
        out = []
        s, b = inv["seller"], inv["buyer"]
        for label, val in (("invoice number", inv["number"]), ("your company name", s["name"]),
                           ("your street", s["street"]), ("your post code", s["zip"]), ("your city", s["city"]),
                           ("customer name", b["name"]), ("customer city", b["city"]),
                           ("at least one item with a description", any(li["name"] for li in inv["lines"]))):
            if not val:
                out.append(tr(label))
        if not (s["vat_id"] or s["tax_number"]) and inv["vat_treatment"] != "not-subject":
            out.append(tr("your VAT ID or tax number"))
        if inv["vat_treatment"] in ("reverse", "intra-eu", "export"):
            if not s["vat_id"]:
                out.append(tr("your VAT ID (needed for this VAT treatment)"))
            if not b["vat_id"] and inv["vat_treatment"] != "export":
                out.append(tr("the customer's VAT ID (needed for this VAT treatment)"))
        if inv["xrechnung"]:
            for label, val in (("Leitweg-ID", inv["buyer_reference"]), ("customer e-invoice address", b["electronic_address"]),
                               ("contact person", s["contact"]), ("phone", s["phone"]), ("e-mail", s["email"]),
                               ("customer post code", b["zip"])):
                if not val:
                    out.append(tr(label) + " (XRechnung)")
        if not inv["payment"]["iban"] and not self.paid.isChecked():
            out.append(tr("your IBAN (or tick Already paid)"))
        if inv["type_code"] in ("381", "384") and not inv["preceding"]:
            out.append(tr("the invoice number this one refers to"))
        return out

    def _accept(self):
        inv = self.values()
        miss = self._missing(inv)
        if miss:
            QMessageBox.warning(self, tr("Create E-Invoice"), tr("Please fill in:") + "\n• " + "\n• ".join(miss))
            return
        if self.paid.isChecked():
            c = inv_cmds.compute(inv)
            inv["prepaid"] = str(c["totals"]["grand_total"])
            inv["payment_terms"] = "Bereits bezahlt." if self.lang.currentData() == "de" else "Already paid."
        prefs.put_json("invoice/seller", {k: w.text().strip() for k, w in self.s.items()})
        prefs.put("invoice/last_number", inv["number"])
        r, g, b = (round(x * 255) for x in (self.accent.rgb or tuple(int(theme.ACCENT[i:i + 2], 16) / 255 for i in (1, 3, 5))))
        prefs.put_json("invoice/prefs", {
            "design": self.design.currentData(), "lang": self.lang.currentData(), "accent": f"#{r:02x}{g:02x}{b:02x}",
            "logo": self.logo.text().strip(), "due_days": self.due_days.value(), "vat": self.vat.currentData()})
        self.result = {"invoice": inv, "design": self.design.currentData(), "lang": self.lang.currentData(),
                       "accent": f"#{r:02x}{g:02x}{b:02x}", "logo": self.logo.text().strip() or None,
                       "output": self.output.currentData()}
        self.accept()

    @staticmethod
    def ask(parent):
        d = InvoiceDialog(parent)
        return d.result if d.exec() == QDialog.Accepted else None


# ---- viewing and checking ------------------------------------------------------------------------------
ICONS = {"ok": ("✔", "#2e9e5b"), "warning": ("⚠", "#c77c00"), "error": ("✖", "#d33a3a")}


def checks_html(checks) -> str:
    n_err = sum(1 for c in checks if c[0] == "error")
    n_warn = sum(1 for c in checks if c[0] == "warning")
    head = (f"<p style='color:#2e9e5b;font-size:13pt'><b>✔ {tr('No problems found')}</b></p>" if not n_err and not n_warn else
            f"<p style='font-size:13pt'><b style='color:#d33a3a'>{tr('{n} error(s)', n=n_err)}</b>, "
            f"<b style='color:#c77c00'>{tr('{n} warning(s)', n=n_warn)}</b></p>")
    order = {"error": 0, "warning": 1, "ok": 2}
    rows = "".join(f"<tr><td style='color:{ICONS[l][1]};padding:2px 6px'>{ICONS[l][0]}</td>"
                   f"<td style='color:#777;padding:2px 8px'>{html.escape(r)}</td><td>{html.escape(m)}</td></tr>"
                   for l, r, m in sorted(checks, key=lambda c: order[c[0]]))
    note = tr("These are the EN 16931 core rules that can be checked without the official Schematron, plus XRechnung "
              "and PDF/A-3 packaging checks. For a binding result use the KoSIT validator or the Mustang validator.")
    return head + f"<table cellspacing=0>{rows}</table><p style='color:#888;font-size:8pt'>{note}</p>"


class InvoiceViewDialog(QDialog):
    """The invoice as a readable page plus its checks; Save XML exports the embedded file."""

    def __init__(self, parent, inv: dict, checks, xml: bytes | None, lang: str = "de"):
        super().__init__(parent)
        self.setWindowTitle(tr("E-Invoice") + f" — {inv['standard']}")
        size_for_screen(self, 820, 760)
        self.xml = xml
        v = QVBoxLayout(self)
        info = QLabel(f"<b>{html.escape(inv['standard'])}</b> · {inv['syntax']} " + tr("syntax")
                      + (" · " + tr("file") + f" <i>{html.escape(inv.get('source', ''))}</i>" if inv.get("source") else ""))
        v.addWidget(info)
        tabs = QTabWidget()
        page = QTextBrowser()
        page.setHtml(inv_cmds.to_html(inv, lang))
        tabs.addTab(page, tr("Invoice"))
        chk = QTextBrowser()
        chk.setHtml(checks_html(checks))
        tabs.addTab(chk, tr("Check"))
        if xml:
            src = QTextBrowser()
            src.setPlainText(xml.decode("utf-8", "replace"))
            src.setLineWrapMode(QTextBrowser.NoWrap)
            tabs.addTab(src, "XML")
        v.addWidget(tabs, 1)
        n_err = sum(1 for c in checks if c[0] == "error")
        tabs.setTabText(1, tr("Check ({n} errors)", n=n_err) if n_err else tr("Check") + " ✔")
        row = QHBoxLayout()
        if xml:
            b = QPushButton(tr("Save XML…"))
            b.clicked.connect(self._save_xml)
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self.tabs = tabs

    def _save_xml(self):
        p = QFileDialog.getSaveFileName(self, tr("Save XML"), "invoice.xml", tr("XML (*.xml)"))[0]
        if p:
            with open(p, "wb") as f:
                f.write(self.xml)
