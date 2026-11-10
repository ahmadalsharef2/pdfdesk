"""E-invoices (EN 16931): ZUGFeRD / Factur-X (a PDF/A-3 with the invoice as embedded CII XML) and XRechnung
(CII or UBL XML on its own).

- read: find the XML inside a PDF, or read an XML file, into one plain dict whatever the syntax;
- check: the EN 16931 core rules that can be checked without the official Schematron (required data, sums,
  VAT breakdown) plus the German XRechnung extras and the PDF/A-3 packaging. Not a replacement for the
  KoSIT validator;
- create: an invoice dict -> visual PDF (two designs, German or English) + CII XML -> PDF/A-3 with the XML
  embedded as ``factur-x.xml`` and the Factur-X XMP, or the XML alone for XRechnung.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import os
import re
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import pymupdf
from lxml import etree

from ..lang import tr
from .registry import command

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
EN16931 = "urn:cen.eu:en16931:2017"
XRECHNUNG = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
PEPPOL_PROCESS = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
PROFILES = {            # guideline ID -> (name, Factur-X conformance level, is a full EN 16931 invoice)
    "urn:factur-x.eu:1p0:minimum": ("Factur-X / ZUGFeRD MINIMUM", "MINIMUM", False),
    "urn:factur-x.eu:1p0:basicwl": ("Factur-X / ZUGFeRD BASIC WL", "BASIC WL", False),
    "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic": ("Factur-X / ZUGFeRD BASIC", "BASIC", True),
    EN16931: ("Factur-X / ZUGFeRD EN 16931 (Comfort)", "EN 16931", True),
    "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended": ("Factur-X / ZUGFeRD EXTENDED", "EXTENDED", True),
}
XML_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "zugferd_invoice.xml", "xrechnung.xml", "order-x.xml")
TYPE_CODES = {"380": "Invoice", "381": "Credit note", "384": "Corrected invoice", "326": "Partial invoice",
              "389": "Self-billed invoice", "875": "Partial construction invoice", "877": "Final construction invoice"}
UNITS = {"C62": "pcs", "H87": "pcs", "HUR": "h", "DAY": "days", "MON": "months", "KGM": "kg", "MTR": "m",
         "LTR": "l", "MTK": "m²", "LS": "lump sum", "XPP": "pcs"}
UNITS_DE = {"C62": "Stk", "H87": "Stk", "HUR": "Std", "DAY": "Tage", "MON": "Monate", "KGM": "kg", "MTR": "m",
            "LTR": "l", "MTK": "m²", "LS": "pauschal", "XPP": "Stk"}
# VAT treatments offered when creating an invoice: key -> (label, category code, rate fixed at 0, reason)
VAT_TREATMENTS = {
    "standard": ("Standard VAT", "S", False, ""),
    "small": ("Small business, no VAT (§ 19 UStG)", "E", True,
              "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung)."),
    "reverse": ("Reverse charge (§ 13b UStG)", "AE", True, "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge)"),
    "intra-eu": ("Intra-EU supply, VAT exempt", "K", True, "Steuerfreie innergemeinschaftliche Lieferung"),
    "export": ("Export outside the EU", "G", True, "Steuerfreie Ausfuhrlieferung"),
    "exempt": ("VAT exempt (other reason)", "E", True, ""),
    "not-subject": ("Not subject to VAT", "O", True, "Nicht steuerbarer Umsatz"),
}
CATEGORY_NAMES = {"S": "Standard rate", "Z": "Zero rate", "E": "Exempt", "AE": "Reverse charge",
                  "K": "Intra-EU supply", "G": "Export", "O": "Not subject to VAT", "L": "Canary Islands",
                  "M": "Ceuta and Melilla"}
CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(CENT, ROUND_HALF_UP)


def dec(x) -> Decimal:
    try:
        return Decimal(str(x).strip().replace(",", ".")) if str(x).strip() else Decimal(0)
    except Exception:  # noqa: BLE001
        return Decimal(0)


# ---- finding and reading ------------------------------------------------------------------------------
def _parser():
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=False)


def find_xml(doc: pymupdf.Document) -> tuple[str, bytes] | None:
    """The e-invoice XML embedded in a PDF: a known file name first, else any XML whose root is an invoice."""
    names = doc.embfile_names()
    for n in sorted(names, key=lambda n: (n.lower() not in XML_NAMES, n)):
        if not n.lower().endswith(".xml"):
            continue
        data = doc.embfile_get(n)
        try:
            root = etree.fromstring(data, _parser())
        except etree.XMLSyntaxError:
            continue
        if etree.QName(root).localname in ("CrossIndustryInvoice", "Invoice", "CreditNote"):
            return n, data
    return None


class _X:
    """Small XPath helper bound to one element."""
    def __init__(self, el):
        self.el = el

    def t(self, path: str, default: str = "") -> str:
        r = self.el.xpath(path, namespaces=NS) if self.el is not None else []
        if not r:
            return default
        v = r[0]
        return (v if isinstance(v, str) else (v.text or "")).strip()

    def all(self, path: str) -> list["_X"]:
        return [_X(e) for e in (self.el.xpath(path, namespaces=NS) if self.el is not None else [])]

    def one(self, path: str) -> "_X":
        r = self.el.xpath(path, namespaces=NS) if self.el is not None else []
        return _X(r[0] if r else None)


def _date(s: str) -> str:
    s = (s or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10]


def _cii_party(p: _X) -> dict:
    return {"name": p.t("ram:Name"), "id": p.t("ram:ID"),
            "street": p.t("ram:PostalTradeAddress/ram:LineOne"), "street2": p.t("ram:PostalTradeAddress/ram:LineTwo"),
            "zip": p.t("ram:PostalTradeAddress/ram:PostcodeCode"), "city": p.t("ram:PostalTradeAddress/ram:CityName"),
            "country": p.t("ram:PostalTradeAddress/ram:CountryID"),
            "vat_id": p.t("ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']"),
            "tax_number": p.t("ram:SpecifiedTaxRegistration/ram:ID[@schemeID='FC']"),
            "legal_id": p.t("ram:SpecifiedLegalOrganization/ram:ID"),
            "contact": p.t("ram:DefinedTradeContact/ram:PersonName"),
            "phone": p.t("ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber"),
            "email": p.t("ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID"),
            "electronic_address": p.t("ram:URIUniversalCommunication/ram:URIID")}


def _read_cii(root) -> dict:
    x = _X(root)
    tx = x.one("rsm:SupplyChainTradeTransaction")
    ag, dl, st = (tx.one("ram:ApplicableHeaderTradeAgreement"), tx.one("ram:ApplicableHeaderTradeDelivery"),
                  tx.one("ram:ApplicableHeaderTradeSettlement"))
    sm = st.one("ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    pm = st.one("ram:SpecifiedTradeSettlementPaymentMeans")
    lines = []
    for li in tx.all("ram:IncludedSupplyChainTradeLineItem"):
        tax = li.one("ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax")
        lines.append({"id": li.t("ram:AssociatedDocumentLineDocument/ram:LineID"),
                      "name": li.t("ram:SpecifiedTradeProduct/ram:Name"),
                      "description": li.t("ram:SpecifiedTradeProduct/ram:Description"),
                      "quantity": li.t("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"),
                      "unit": li.t("ram:SpecifiedLineTradeDelivery/ram:BilledQuantity/@unitCode"),
                      "price": li.t("ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"),
                      "price_base": li.t("ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:BasisQuantity", "1"),
                      "vat_category": tax.t("ram:CategoryCode"), "vat_rate": tax.t("ram:RateApplicablePercent"),
                      "net": li.t("ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")})
    taxes = [{"category": t.t("ram:CategoryCode"), "rate": t.t("ram:RateApplicablePercent"),
              "basis": t.t("ram:BasisAmount"), "amount": t.t("ram:CalculatedAmount"),
              "exemption_reason": t.t("ram:ExemptionReason"), "exemption_code": t.t("ram:ExemptionReasonCode")}
             for t in st.all("ram:ApplicableTradeTax")]
    cur = st.t("ram:InvoiceCurrencyCode")
    return {
        "syntax": "CII", "profile": x.t("rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"),
        "process": x.t("rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID"),
        "number": x.t("rsm:ExchangedDocument/ram:ID"), "type_code": x.t("rsm:ExchangedDocument/ram:TypeCode"),
        "issue_date": _date(x.t("rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")),
        "notes": [n.t("ram:Content") for n in x.all("rsm:ExchangedDocument/ram:IncludedNote")],
        "buyer_reference": ag.t("ram:BuyerReference"),
        "order_reference": ag.t("ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID"),
        "seller": _cii_party(ag.one("ram:SellerTradeParty")), "buyer": _cii_party(ag.one("ram:BuyerTradeParty")),
        "delivery_date": _date(dl.t("ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString")),
        "period": (_date(st.t("ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString")),
                   _date(st.t("ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString"))),
        "currency": cur,
        "payment": {"means_code": pm.t("ram:TypeCode"), "reference": st.t("ram:PaymentReference"),
                    "iban": pm.t("ram:PayeePartyCreditorFinancialAccount/ram:IBANID"),
                    "account_name": pm.t("ram:PayeePartyCreditorFinancialAccount/ram:AccountName"),
                    "bic": pm.t("ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID")},
        "payment_terms": st.t("ram:SpecifiedTradePaymentTerms/ram:Description"),
        "preceding": st.t("ram:InvoiceReferencedDocument/ram:IssuerAssignedID"),
        "due_date": _date(st.t("ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString")),
        "lines": lines, "taxes": taxes,
        "totals": {"line_total": sm.t("ram:LineTotalAmount"), "charges": sm.t("ram:ChargeTotalAmount"),
                   "allowances": sm.t("ram:AllowanceTotalAmount"), "tax_basis": sm.t("ram:TaxBasisTotalAmount"),
                   "tax_total": sm.t(f"ram:TaxTotalAmount[@currencyID='{cur}']") or sm.t("ram:TaxTotalAmount"),
                   "grand_total": sm.t("ram:GrandTotalAmount"), "prepaid": sm.t("ram:TotalPrepaidAmount"),
                   "rounding": sm.t("ram:RoundingAmount"), "due": sm.t("ram:DuePayableAmount")},
    }


def _ubl_party(p: _X) -> dict:
    tax_ids = [(t.t("cbc:CompanyID"), t.t("cac:TaxScheme/cbc:ID")) for t in p.all("cac:PartyTaxScheme")]
    return {"name": p.t("cac:PartyName/cbc:Name") or p.t("cac:PartyLegalEntity/cbc:RegistrationName"),
            "id": p.t("cac:PartyIdentification/cbc:ID"),
            "street": p.t("cac:PostalAddress/cbc:StreetName"), "street2": p.t("cac:PostalAddress/cbc:AdditionalStreetName"),
            "zip": p.t("cac:PostalAddress/cbc:PostalZone"), "city": p.t("cac:PostalAddress/cbc:CityName"),
            "country": p.t("cac:PostalAddress/cac:Country/cbc:IdentificationCode"),
            "vat_id": next((c for c, s in tax_ids if s == "VAT"), ""),
            "tax_number": next((c for c, s in tax_ids if s != "VAT"), ""),
            "legal_id": p.t("cac:PartyLegalEntity/cbc:CompanyID"),
            "contact": p.t("cac:Contact/cbc:Name"), "phone": p.t("cac:Contact/cbc:Telephone"),
            "email": p.t("cac:Contact/cbc:ElectronicMail"), "electronic_address": p.t("cbc:EndpointID")}


def _read_ubl(root) -> dict:
    x = _X(root)
    credit = etree.QName(root).localname == "CreditNote"
    line_tag, qty_tag = ("cac:CreditNoteLine", "cbc:CreditedQuantity") if credit else ("cac:InvoiceLine", "cbc:InvoicedQuantity")
    lines = []
    for li in x.all(line_tag):
        lines.append({"id": li.t("cbc:ID"), "name": li.t("cac:Item/cbc:Name"),
                      "description": li.t("cac:Item/cbc:Description"),
                      "quantity": li.t(qty_tag), "unit": li.t(f"{qty_tag}/@unitCode"),
                      "price": li.t("cac:Price/cbc:PriceAmount"), "price_base": li.t("cac:Price/cbc:BaseQuantity", "1"),
                      "vat_category": li.t("cac:Item/cac:ClassifiedTaxCategory/cbc:ID"),
                      "vat_rate": li.t("cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
                      "net": li.t("cbc:LineExtensionAmount")})
    taxes = [{"category": s.t("cac:TaxCategory/cbc:ID"), "rate": s.t("cac:TaxCategory/cbc:Percent"),
              "basis": s.t("cbc:TaxableAmount"), "amount": s.t("cbc:TaxAmount"),
              "exemption_reason": s.t("cac:TaxCategory/cbc:TaxExemptionReason"),
              "exemption_code": s.t("cac:TaxCategory/cbc:TaxExemptionReasonCode")}
             for s in x.all("cac:TaxTotal/cac:TaxSubtotal")]
    pm, mt = x.one("cac:PaymentMeans"), x.one("cac:LegalMonetaryTotal")
    cur = x.t("cbc:DocumentCurrencyCode")
    return {
        "syntax": "UBL", "profile": x.t("cbc:CustomizationID"), "process": x.t("cbc:ProfileID"),
        "number": x.t("cbc:ID"), "type_code": x.t("cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode"),
        "issue_date": x.t("cbc:IssueDate"), "notes": [n.t(".") for n in x.all("cbc:Note")],
        "buyer_reference": x.t("cbc:BuyerReference"), "order_reference": x.t("cac:OrderReference/cbc:ID"),
        "seller": _ubl_party(x.one("cac:AccountingSupplierParty/cac:Party")),
        "buyer": _ubl_party(x.one("cac:AccountingCustomerParty/cac:Party")),
        "delivery_date": x.t("cac:Delivery/cbc:ActualDeliveryDate"),
        "period": (x.t("cac:InvoicePeriod/cbc:StartDate"), x.t("cac:InvoicePeriod/cbc:EndDate")),
        "currency": cur,
        "payment": {"means_code": pm.t("cbc:PaymentMeansCode"), "reference": pm.t("cbc:PaymentID"),
                    "iban": pm.t("cac:PayeeFinancialAccount/cbc:ID"),
                    "account_name": pm.t("cac:PayeeFinancialAccount/cbc:Name"),
                    "bic": pm.t("cac:PayeeFinancialAccount/cac:FinancialInstitutionBranch/cbc:ID")},
        "payment_terms": x.t("cac:PaymentTerms/cbc:Note"), "due_date": x.t("cbc:DueDate"),
        "preceding": x.t("cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
        "lines": lines, "taxes": taxes,
        "totals": {"line_total": mt.t("cbc:LineExtensionAmount"), "charges": mt.t("cbc:ChargeTotalAmount"),
                   "allowances": mt.t("cbc:AllowanceTotalAmount"), "tax_basis": mt.t("cbc:TaxExclusiveAmount"),
                   "tax_total": x.t(f"cac:TaxTotal/cbc:TaxAmount[@currencyID='{cur}']") or x.t("cac:TaxTotal/cbc:TaxAmount"),
                   "grand_total": mt.t("cbc:TaxInclusiveAmount"), "prepaid": mt.t("cbc:PrepaidAmount"),
                   "rounding": mt.t("cbc:PayableRoundingAmount"), "due": mt.t("cbc:PayableAmount")},
    }


def parse(data: bytes) -> dict:
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError:
        raise ValueError(tr("This file is not XML, so it is no e-invoice.")) from None
    name = etree.QName(root).localname
    if name == "CrossIndustryInvoice":
        inv = _read_cii(root)
    elif name in ("Invoice", "CreditNote"):
        inv = _read_ubl(root)
    else:
        raise ValueError(f"not an e-invoice (root element {name})")
    inv["standard"] = standard_name(inv["profile"])
    return inv


def standard_name(profile: str) -> str:
    if "xrechnung" in profile.lower():
        return "XRechnung " + profile.rsplit("_", 1)[-1] if "_" in profile else "XRechnung"
    if profile in PROFILES:
        return PROFILES[profile][0]
    if profile.startswith(EN16931):
        return "EN 16931 (" + profile[len(EN16931):].strip("#") + ")" if len(profile) > len(EN16931) else "EN 16931"
    return profile or "unknown"


@command("Invoice.Read")
def read(src) -> dict | None:
    """The e-invoice of a PDF (Document or path) or of an XML file, or None when the PDF has none."""
    if isinstance(src, (bytes, bytearray)):
        return parse(bytes(src))
    if isinstance(src, str) and src.lower().endswith(".xml"):
        with open(src, "rb") as f:
            inv = parse(f.read())
        inv["source"] = os.path.basename(src)
        return inv
    doc = pymupdf.open(src) if isinstance(src, str) else src
    found = find_xml(doc)
    if not found:
        return None
    inv = parse(found[1])
    inv["source"] = found[0]
    return inv


# ---- checking -------------------------------------------------------------------------------------------
def _pdf_checks(doc: pymupdf.Document, xml_name: str) -> list[tuple[str, str, str]]:
    """(level, rule, message) for the PDF/A-3 packaging ZUGFeRD / Factur-X need."""
    out = []
    xmp = doc.get_xml_metadata() or ""
    part = ""
    if "pdfaid" in xmp:
        try:
            root = etree.fromstring(xmp.encode(), _parser())
            part = (root.xpath("string(//@*[local-name()='part'] | //*[local-name()='part'])") or "").strip()
        except etree.XMLSyntaxError:
            pass
    out.append(("ok" if part == "3" else "error", "PDF/A-3",
                "The file claims PDF/A-3" if part == "3" else
                f"ZUGFeRD needs PDF/A-3; this file claims {'PDF/A-' + part if part else 'no PDF/A level'}"))
    fx_name = ""
    if "DocumentFileName" in xmp:
        try:
            root = etree.fromstring(xmp.encode(), _parser())
            fx_name = (root.xpath("string(//@*[local-name()='DocumentFileName'] | //*[local-name()='DocumentFileName'])") or "").strip()
        except etree.XMLSyntaxError:
            pass
    out.append(("ok" if fx_name == xml_name else "warning", "XMP",
                f"Factur-X metadata names {fx_name}" if fx_name == xml_name else
                "The Factur-X XMP metadata does not name the attached XML" + (f" (it says {fx_name})" if fx_name else "")))
    rel = ""
    for x in range(1, doc.xref_length()):
        if doc.xref_get_key(x, "Type")[1] == "/Filespec" and xml_name in (doc.xref_get_key(x, "UF")[1] + doc.xref_get_key(x, "F")[1]):
            rel = doc.xref_get_key(x, "AFRelationship")[1].lstrip("/")
            break
    out.append(("ok" if rel in ("Alternative", "Data", "Source") else "warning", "AFRelationship",
                f"The XML is attached as {rel} data" if rel else "The attachment has no /AFRelationship (PDF/A-3 wants one)"))
    af = doc.xref_get_key(doc.pdf_catalog(), "AF")
    out.append(("ok" if af[0] != "null" else "warning", "/AF", "The catalog lists the XML as an associated file"
                if af[0] != "null" else "The catalog has no /AF entry for the XML"))
    return out


@command("Invoice.Check")
def check(src) -> list[tuple[str, str, str]]:
    """Checks on an e-invoice: [(level, rule, message)], level 'ok', 'warning' or 'error'."""
    doc = None
    if isinstance(src, pymupdf.Document) or (isinstance(src, str) and src.lower().endswith(".pdf")):
        doc = pymupdf.open(src) if isinstance(src, str) else src
        found = find_xml(doc)
        if not found:
            return [("error", "ZUGFeRD", "This PDF has no embedded e-invoice XML")]
        inv = parse(found[1])
        inv["source"] = found[0]
    else:
        inv = src if isinstance(src, dict) else read(src)
    out: list[tuple[str, str, str]] = []

    def need(rule, value, what):
        out.append(("ok", rule, what) if value else ("error", rule, f"Missing: {what}"))

    prof = inv["profile"]
    full = PROFILES.get(prof, ("", "", prof.startswith(EN16931)))[2]
    out.append(("ok" if full else "error" if prof in PROFILES else "warning", "BR-01",
                f"Specification: {inv['standard']}" if full else
                f"{inv['standard']}: not a complete EN 16931 invoice (not valid as an e-invoice in Germany)"
                if prof in PROFILES else f"Unknown specification identifier: {prof or '(none)'}"))
    need("BR-02", inv["number"], "invoice number")
    need("BR-03", inv["issue_date"], "issue date")
    need("BR-04", inv["type_code"], "invoice type code")
    need("BR-05", inv["currency"], "currency")
    s, b = inv["seller"], inv["buyer"]
    need("BR-06", s["name"], "seller name")
    need("BR-07", b["name"], "buyer name")
    need("BR-08", s["city"] or s["zip"] or s["street"], "seller postal address")
    need("BR-09", s["country"], "seller country code")
    need("BR-10", b["city"] or b["zip"] or b["street"], "buyer postal address")
    need("BR-11", b["country"], "buyer country code")
    need("BR-16", inv["lines"], "at least one invoice line")
    t = {k: dec(v) for k, v in inv["totals"].items()}
    for rule, key, what in (("BR-12", "line_total", "sum of line net amounts"), ("BR-13", "tax_basis", "total without VAT"),
                            ("BR-14", "grand_total", "total with VAT"), ("BR-15", "due", "amount due")):
        need(rule, inv["totals"][key], what)

    def same(rule, a, b_, what):
        ok = abs(a - b_) <= CENT
        out.append(("ok" if ok else "error", rule, f"{what}: {b_}" if ok else f"{what}: expected {money(a)}, invoice says {b_}"))

    if inv["lines"]:
        same("BR-CO-10", sum((dec(li["net"]) for li in inv["lines"]), Decimal(0)), t["line_total"], "Sum of line amounts")
        bad = [li["id"] or str(k + 1) for k, li in enumerate(inv["lines"])
               if li["price"] and li["quantity"] and
               abs(money(dec(li["quantity"]) * dec(li["price"]) / (dec(li["price_base"]) or 1)) - dec(li["net"])) > CENT]
        out.append(("warning", "Lines", f"Line amount is not quantity × price on line(s) {', '.join(bad)} "
                    "(fine if the line has its own allowances or charges)") if bad else
                   ("ok", "Lines", "Every line amount is quantity × price"))
    same("BR-CO-13", t["line_total"] - t["allowances"] + t["charges"], t["tax_basis"], "Total without VAT")
    same("BR-CO-14", sum((dec(x["amount"]) for x in inv["taxes"]), Decimal(0)), t["tax_total"], "VAT total")
    same("BR-CO-15", t["tax_basis"] + t["tax_total"], t["grand_total"], "Total with VAT")
    same("BR-CO-16", t["grand_total"] - t["prepaid"] + t["rounding"], t["due"], "Amount due")
    need("BR-CO-18", inv["taxes"], "VAT breakdown")
    if inv["taxes"]:
        same("VAT basis", sum((dec(x["basis"]) for x in inv["taxes"]), Decimal(0)), t["tax_basis"], "Sum of VAT bases")
    for x in inv["taxes"]:
        cat = x["category"]
        exp = money(dec(x["basis"]) * dec(x["rate"]) / 100)
        if cat in ("S", "Z", "L", "M"):
            ok = abs(exp - dec(x["amount"])) <= CENT
            out.append(("ok" if ok else "error", f"BR-{cat}-08" if cat in "SZ" else "VAT",
                        f"VAT {x['rate']} % on {x['basis']} = {x['amount']}" if ok else
                        f"VAT {x['rate']} % on {x['basis']} should be {exp}, invoice says {x['amount']}"))
        else:
            if dec(x["amount"]):
                out.append(("error", f"BR-{cat}-09", f"{CATEGORY_NAMES.get(cat, cat)}: VAT amount must be 0"))
            out.append(("ok" if x["exemption_reason"] or x["exemption_code"] else "error", f"BR-{cat}-10",
                        f"{CATEGORY_NAMES.get(cat, cat)}: exemption reason given" if x["exemption_reason"] or x["exemption_code"]
                        else f"{CATEGORY_NAMES.get(cat, cat)}: an exemption reason (text or code) is required"))
    cats = {x["category"] for x in inv["taxes"]} | {li["vat_category"] for li in inv["lines"]}
    for cat in sorted(cats & {"S", "Z", "E"}):
        need(f"BR-{cat}-02", s["vat_id"] or s["tax_number"], f"seller VAT ID or tax number ({CATEGORY_NAMES[cat].lower()} lines)")
    if "G" in cats:
        need("BR-G-02", s["vat_id"], "seller VAT ID (export)")
    if "AE" in cats:
        need("BR-AE-02", s["vat_id"] and (b["vat_id"] or b["legal_id"]), "seller and buyer VAT IDs (reverse charge)")
    if "K" in cats:
        need("BR-IC-02", s["vat_id"] and b["vat_id"], "seller and buyer VAT IDs (intra-EU supply)")
    if t["due"] > 0:
        need("BR-CO-25", inv["due_date"] or inv["payment_terms"], "due date or payment terms (amount due is positive)")
    if inv["payment"]["means_code"] in ("30", "58"):
        need("BR-61", inv["payment"]["iban"], "IBAN for payment by credit transfer")
    if "xrechnung" in prof.lower():
        need("XRechnung", inv["buyer_reference"], "buyer reference / Leitweg-ID (BT-10)")
        need("XRechnung", s["contact"] and s["phone"] and s["email"], "seller contact name, phone and e-mail (BG-6)")
        need("XRechnung", s["electronic_address"], "seller electronic address (BT-34)")
        need("XRechnung", b["electronic_address"], "buyer electronic address (BT-49)")
        need("XRechnung", inv["payment"]["means_code"], "payment instructions (BG-16)")
        need("XRechnung", s["city"] and s["zip"] and b["city"] and b["zip"], "seller and buyer city and post code")
    if doc is not None:
        out += _pdf_checks(doc, inv["source"])
    return out


# ---- writing CII ------------------------------------------------------------------------------------------
def compute(inv: dict) -> dict:
    """Fill line amounts, the VAT breakdown and the totals of an invoice dict made by the create dialog."""
    treat = VAT_TREATMENTS[inv.get("vat_treatment", "standard")]
    lines = []
    for k, li in enumerate(l for l in inv["lines"] if (l.get("name") or "").strip()):
        q, p = dec(li.get("quantity", 1)), dec(li.get("price", 0))
        rate = Decimal(0) if treat[2] else dec(li.get("vat_rate", 19))
        cat = treat[1] if treat[1] != "S" else ("S" if rate else "Z")
        lines.append({**li, "id": str(k + 1), "quantity": q, "price": p, "vat_rate": rate, "vat_category": cat,
                      "unit": li.get("unit") or "C62", "net": money(q * p)})
    groups: dict[tuple, Decimal] = {}
    for li in lines:
        groups[(li["vat_category"], li["vat_rate"])] = groups.get((li["vat_category"], li["vat_rate"]), Decimal(0)) + li["net"]
    reason = inv.get("exemption_reason") or treat[3]
    taxes = [{"category": c, "rate": r, "basis": money(b), "amount": money(b * r / 100),
              "exemption_reason": reason if c not in ("S", "Z") else ""} for (c, r), b in sorted(groups.items())]
    line_total = money(sum((li["net"] for li in lines), Decimal(0)))
    tax_total = money(sum((x["amount"] for x in taxes), Decimal(0)))
    prepaid = money(inv.get("prepaid", 0))
    grand = line_total + tax_total
    return {**inv, "lines": lines, "taxes": taxes,
            "totals": {"line_total": line_total, "tax_basis": line_total, "tax_total": tax_total,
                       "grand_total": grand, "prepaid": prepaid, "due": grand - prepaid,
                       "allowances": Decimal(0), "charges": Decimal(0), "rounding": Decimal(0)}}


def _e(parent, tag, text=None, **attrs):
    prefix, name = tag.split(":")
    el = etree.SubElement(parent, f"{{{NS[prefix]}}}{name}", **attrs)
    if text is not None:
        el.text = str(text)
    return el


def _dt(parent, tag, iso: str):
    _e(_e(parent, tag), "udt:DateTimeString", iso.replace("-", ""), format="102")


def _party(parent, tag, p: dict, seller: bool):
    el = _e(parent, tag)
    _e(el, "ram:Name", p["name"])
    if seller and p.get("legal_id"):
        _e(_e(el, "ram:SpecifiedLegalOrganization"), "ram:ID", p["legal_id"])
    if p.get("contact") or p.get("phone") or p.get("email"):
        c = _e(el, "ram:DefinedTradeContact")
        if p.get("contact"):
            _e(c, "ram:PersonName", p["contact"])
        if p.get("phone"):
            _e(_e(c, "ram:TelephoneUniversalCommunication"), "ram:CompleteNumber", p["phone"])
        if p.get("email"):
            _e(_e(c, "ram:EmailURIUniversalCommunication"), "ram:URIID", p["email"])
    a = _e(el, "ram:PostalTradeAddress")
    if p.get("zip"):
        _e(a, "ram:PostcodeCode", p["zip"])
    if p.get("street"):
        _e(a, "ram:LineOne", p["street"])
    if p.get("street2"):
        _e(a, "ram:LineTwo", p["street2"])
    if p.get("city"):
        _e(a, "ram:CityName", p["city"])
    _e(a, "ram:CountryID", (p.get("country") or "DE").upper())
    if p.get("electronic_address"):
        _e(_e(el, "ram:URIUniversalCommunication"), "ram:URIID", p["electronic_address"], schemeID="EM")
    if p.get("vat_id"):
        _e(_e(el, "ram:SpecifiedTaxRegistration"), "ram:ID", p["vat_id"], schemeID="VA")
    if seller and p.get("tax_number"):
        _e(_e(el, "ram:SpecifiedTaxRegistration"), "ram:ID", p["tax_number"], schemeID="FC")


def _tax(parent, x: dict, line: bool):
    t = _e(parent, "ram:ApplicableTradeTax")
    if not line:
        _e(t, "ram:CalculatedAmount", money(x["amount"]))
    _e(t, "ram:TypeCode", "VAT")
    if not line and x.get("exemption_reason"):
        _e(t, "ram:ExemptionReason", x["exemption_reason"])
    if not line:
        _e(t, "ram:BasisAmount", money(x["basis"]))
    _e(t, "ram:CategoryCode", x["category"] if not line else x["vat_category"])
    rate = x["rate"] if not line else x["vat_rate"]
    if (x["category"] if not line else x["vat_category"]) != "O":
        _e(t, "ram:RateApplicablePercent", f"{Decimal(rate):f}")


@command("Invoice.ToXml")
def to_xml(inv: dict) -> bytes:
    """CII XML (ZUGFeRD 2.x / Factur-X EN 16931, or XRechnung 3.0 when inv['xrechnung'])."""
    inv = compute(inv) if not isinstance(inv["totals"].get("due"), Decimal) else inv
    root = etree.Element(f"{{{NS['rsm']}}}CrossIndustryInvoice",
                         nsmap={k: NS[k] for k in ("rsm", "ram", "qdt", "udt")})
    ctx = _e(root, "rsm:ExchangedDocumentContext")
    _e(_e(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter"), "ram:ID", PEPPOL_PROCESS)
    _e(_e(ctx, "ram:GuidelineSpecifiedDocumentContextParameter"), "ram:ID", XRECHNUNG if inv.get("xrechnung") else EN16931)
    d = _e(root, "rsm:ExchangedDocument")
    _e(d, "ram:ID", inv["number"])
    _e(d, "ram:TypeCode", inv.get("type_code") or "380")
    _dt(d, "ram:IssueDateTime", inv["issue_date"])
    for n in [inv.get("note")] + [x["exemption_reason"] for x in inv["taxes"] if x.get("exemption_reason")][:1]:
        if n:
            _e(_e(d, "ram:IncludedNote"), "ram:Content", n)
    tx = _e(root, "rsm:SupplyChainTradeTransaction")
    for li in inv["lines"]:
        it = _e(tx, "ram:IncludedSupplyChainTradeLineItem")
        _e(_e(it, "ram:AssociatedDocumentLineDocument"), "ram:LineID", li["id"])
        pr = _e(it, "ram:SpecifiedTradeProduct")
        _e(pr, "ram:Name", li["name"])
        if li.get("description"):
            _e(pr, "ram:Description", li["description"])
        _e(_e(_e(it, "ram:SpecifiedLineTradeAgreement"), "ram:NetPriceProductTradePrice"), "ram:ChargeAmount", f"{li['price']:f}")
        _e(_e(it, "ram:SpecifiedLineTradeDelivery"), "ram:BilledQuantity", f"{li['quantity']:f}", unitCode=li["unit"])
        ls = _e(it, "ram:SpecifiedLineTradeSettlement")
        _tax(ls, li, line=True)
        _e(_e(ls, "ram:SpecifiedTradeSettlementLineMonetarySummation"), "ram:LineTotalAmount", li["net"])
    ag = _e(tx, "ram:ApplicableHeaderTradeAgreement")
    if inv.get("buyer_reference"):
        _e(ag, "ram:BuyerReference", inv["buyer_reference"])
    _party(ag, "ram:SellerTradeParty", inv["seller"], seller=True)
    _party(ag, "ram:BuyerTradeParty", inv["buyer"], seller=False)
    if inv.get("order_reference"):
        _e(_e(ag, "ram:BuyerOrderReferencedDocument"), "ram:IssuerAssignedID", inv["order_reference"])
    dl = _e(tx, "ram:ApplicableHeaderTradeDelivery")
    if inv.get("delivery_date"):
        _dt(_e(dl, "ram:ActualDeliverySupplyChainEvent"), "ram:OccurrenceDateTime", inv["delivery_date"])
    st = _e(tx, "ram:ApplicableHeaderTradeSettlement")
    pay = inv.get("payment") or {}
    if pay.get("reference") or inv["number"]:
        _e(st, "ram:PaymentReference", pay.get("reference") or inv["number"])
    _e(st, "ram:InvoiceCurrencyCode", inv["currency"])
    if pay.get("iban"):
        pm = _e(st, "ram:SpecifiedTradeSettlementPaymentMeans")
        _e(pm, "ram:TypeCode", pay.get("means_code") or "58")
        acc = _e(pm, "ram:PayeePartyCreditorFinancialAccount")
        _e(acc, "ram:IBANID", pay["iban"].replace(" ", "").upper())
        if pay.get("account_name"):
            _e(acc, "ram:AccountName", pay["account_name"])
        if pay.get("bic"):
            _e(_e(pm, "ram:PayeeSpecifiedCreditorFinancialInstitution"), "ram:BICID", pay["bic"].replace(" ", "").upper())
    for x in inv["taxes"]:
        _tax(st, x, line=False)
    if inv.get("payment_terms") or inv.get("due_date"):
        pt = _e(st, "ram:SpecifiedTradePaymentTerms")
        if inv.get("payment_terms"):
            _e(pt, "ram:Description", inv["payment_terms"])
        if inv.get("due_date"):
            _dt(pt, "ram:DueDateDateTime", inv["due_date"])
    t = inv["totals"]
    sm = _e(st, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    _e(sm, "ram:LineTotalAmount", t["line_total"])
    _e(sm, "ram:TaxBasisTotalAmount", t["tax_basis"])
    _e(sm, "ram:TaxTotalAmount", t["tax_total"], currencyID=inv["currency"])
    _e(sm, "ram:GrandTotalAmount", t["grand_total"])
    if t["prepaid"]:
        _e(sm, "ram:TotalPrepaidAmount", t["prepaid"])
    _e(sm, "ram:DuePayableAmount", t["due"])
    if inv.get("preceding"):
        _e(_e(st, "ram:InvoiceReferencedDocument"), "ram:IssuerAssignedID", inv["preceding"])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ---- the visual invoice ----------------------------------------------------------------------------------
LABELS = {
    "en": {"380": "Invoice", "381": "Credit note", "384": "Corrected invoice", "326": "Partial invoice",
           "number": "Invoice no.", "date": "Date", "delivery": "Delivery date", "due": "Due date",
           "ref": "Your reference", "order": "Order", "pos": "#", "item": "Description", "qty": "Qty",
           "unit": "Unit", "price": "Unit price", "vat": "VAT", "amount": "Amount", "net": "Net total",
           "vat_on": "VAT {r} % on {b}", "total": "Total", "prepaid": "Paid", "due_amount": "Amount due",
           "bank": "Bank details", "vat_id": "VAT ID", "tax_no": "Tax no.", "from": "From", "to": "Bill to",
           "terms": "Payment terms", "page": "e-invoice", "refers": "Refers to invoice"},
    "de": {"380": "Rechnung", "381": "Gutschrift", "384": "Rechnungskorrektur", "326": "Teilrechnung",
           "number": "Rechnungsnr.", "date": "Datum", "delivery": "Leistungsdatum", "due": "Fällig am",
           "ref": "Ihre Referenz", "order": "Bestellung", "pos": "Pos.", "item": "Beschreibung", "qty": "Menge",
           "unit": "Einheit", "price": "Einzelpreis", "vat": "USt.", "amount": "Betrag", "net": "Nettobetrag",
           "vat_on": "USt. {r} % auf {b}", "total": "Gesamtbetrag", "prepaid": "Bereits bezahlt",
           "due_amount": "Zu zahlen", "bank": "Bankverbindung", "vat_id": "USt-IdNr.", "tax_no": "Steuernr.",
           "from": "Von", "to": "Rechnung an", "terms": "Zahlungsbedingungen", "page": "E-Rechnung",
           "refers": "Bezug auf Rechnung"},
}
CURRENCY_SIGN = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def _fmt(x, lang: str, cur: str = "") -> str:
    v = money(dec(x) if not isinstance(x, Decimal) else x)
    s = f"{v:,.2f}"
    if lang == "de":
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    sign = CURRENCY_SIGN.get(cur, cur)
    return f"{s} {sign}".strip() if cur else s


def _qty(x, lang: str) -> str:
    v = dec(x).normalize()
    s = f"{v:f}"
    return s.replace(".", ",") if lang == "de" else s


def _d(iso: str, lang: str) -> str:
    if not iso:
        return ""
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%d.%m.%Y") if lang == "de" else d.strftime("%d %b %Y")


def _addr(p: dict) -> str:
    e = html.escape
    rows = [f"<b>{e(p.get('name', ''))}</b>"] + [e(x) for x in (p.get("contact"), p.get("street"), p.get("street2")) if x]
    city = " ".join(x for x in (p.get("zip"), p.get("city")) if x)
    if city:
        rows.append(e(city))
    if p.get("country") and p["country"].upper() not in ("", "DE"):
        rows.append(e(p["country"].upper()))
    return "<br>".join(rows)


@command("Invoice.ToHtml")
def to_html(inv: dict, lang: str = "de", design: str = "classic", accent: str = "#b3261e",
            logo: str | None = None) -> str:
    """HTML for the visual invoice (PyMuPDF Story CSS subset). Takes a computed or a parsed invoice."""
    L, e, cur = LABELS[lang], html.escape, inv["currency"]
    s, b, t = inv["seller"], inv["buyer"], inv["totals"]
    units = UNITS_DE if lang == "de" else UNITS
    title = L.get(inv.get("type_code") or "380", L["380"])
    modern = design == "modern"
    head_bg = accent if modern else "#ffffff"
    head_fg = "#ffffff" if modern else accent
    th_style = f"background-color:{accent};color:#fff" if modern else f"border-bottom:1.5px solid {accent};color:{accent}"
    logo_html = f'<img src="{e(os.path.basename(logo))}" height="46">' if logo else ""
    meta = [(L["number"], inv["number"]), (L["date"], _d(inv["issue_date"], lang))]
    if inv.get("delivery_date"):
        meta.append((L["delivery"], _d(inv["delivery_date"], lang)))
    if inv.get("due_date"):
        meta.append((L["due"], _d(inv["due_date"], lang)))
    if inv.get("buyer_reference"):
        meta.append((L["ref"], inv["buyer_reference"]))
    if inv.get("order_reference"):
        meta.append((L["order"], inv["order_reference"]))
    if inv.get("preceding"):
        meta.append((L["refers"], inv["preceding"]))
    meta_rows = "".join(f"<tr><td style='color:#777;padding:1px 8px 1px 0'>{e(k)}</td><td style='text-align:right'>"
                        f"<b>{e(str(v))}</b></td></tr>" for k, v in meta)
    rows = []
    for k, li in enumerate(inv["lines"]):
        bg = "background-color:#f6f3f8;" if (modern and k % 2) else ""
        desc = e(li["name"]) + (f"<br><span style='color:#777;font-size:8pt'>{e(li['description'])}</span>"
                                if li.get("description") else "")
        rate = "" if li.get("vat_category") == "O" else f"{_qty(li.get('vat_rate') or 0, lang)} %"
        rows.append(f"<tr style='{bg}'><td style='padding:4px 3px;border-bottom:0.5px solid #ddd'>{e(str(li['id']))}</td>"
                    f"<td style='padding:4px 3px;border-bottom:0.5px solid #ddd'>{desc}</td>"
                    f"<td style='text-align:right;padding:4px 3px;border-bottom:0.5px solid #ddd'>{_qty(li['quantity'], lang)}</td>"
                    f"<td style='padding:4px 3px;border-bottom:0.5px solid #ddd'>{e(units.get(li.get('unit') or '', li.get('unit') or ''))}</td>"
                    f"<td style='text-align:right;padding:4px 3px;border-bottom:0.5px solid #ddd'>{_fmt(li['price'] or 0, lang)}</td>"
                    f"<td style='text-align:right;padding:4px 3px;border-bottom:0.5px solid #ddd'>{rate}</td>"
                    f"<td style='text-align:right;padding:4px 3px;border-bottom:0.5px solid #ddd'>{_fmt(li['net'], lang)}</td></tr>")
    sums = [(L["net"], _fmt(t["tax_basis"] or t["line_total"], lang, cur), False)]
    for x in inv["taxes"]:
        if x["category"] in ("S", "Z", "L", "M") and dec(x["rate"]):
            sums.append((L["vat_on"].format(r=_qty(x["rate"], lang), b=_fmt(x["basis"], lang, cur)),
                         _fmt(x["amount"], lang, cur), False))
    sums.append((L["total"], _fmt(t["grand_total"], lang, cur), True))
    if dec(t.get("prepaid")):
        sums.append((L["prepaid"], "− " + _fmt(t["prepaid"], lang, cur), False))
        sums.append((L["due_amount"], _fmt(t["due"], lang, cur), True))
    sum_rows = "".join(
        f"<tr><td style='text-align:right;padding:2px 8px;{'font-weight:bold;border-top:1px solid ' + accent if bold else 'color:#555'}'>{e(k)}</td>"
        f"<td style='text-align:right;padding:2px 3px;{'font-weight:bold;border-top:1px solid ' + accent if bold else ''}'>{v}</td></tr>"
        for k, v, bold in sums)
    notes = [x["exemption_reason"] for x in inv["taxes"] if x.get("exemption_reason")]
    notes += [n for n in ([inv.get("note")] + list(inv.get("notes") or [])) if n and n not in notes]
    terms = inv.get("payment_terms") or ""
    pay = inv.get("payment") or {}
    iban = " ".join(re.findall(".{1,4}", (pay.get("iban") or "").replace(" ", "")))
    bank = " · ".join(x for x in (pay.get("account_name"), ("IBAN " + iban) if iban else "",
                                  ("BIC " + pay["bic"]) if pay.get("bic") else "") if x)
    ids = " · ".join(x for x in ((L["vat_id"] + " " + s["vat_id"]) if s.get("vat_id") else "",
                                 (L["tax_no"] + " " + s["tax_number"]) if s.get("tax_number") else "") if x)
    contact = " · ".join(x for x in (s.get("phone"), s.get("email")) if x)
    seller_line = " · ".join(x for x in (s.get("name"), s.get("street"), " ".join(y for y in (s.get("zip"), s.get("city")) if y)) if x)
    return f"""<html><body style="font-family:sans-serif;font-size:9.5pt;color:#222">
<table style="width:100%;background-color:{head_bg};border-collapse:collapse"><tr>
<td style="padding:{'10px 12px' if modern else '0 0 6px 0'};vertical-align:middle">
<span style="font-size:22pt;font-weight:bold;color:{head_fg}">{e(title)}</span><br>
<span style="font-size:8pt;color:{'#eee' if modern else '#888'}">{e(s.get('name', ''))}</span></td>
<td style="text-align:right;vertical-align:middle;padding:{'10px 12px' if modern else '0'}">{logo_html}</td></tr></table>
<p style="font-size:7pt;color:#888;margin:14px 0 2px 0">{e(seller_line)}</p>
<table style="width:100%;border-collapse:collapse"><tr>
<td style="vertical-align:top;width:58%;line-height:1.35">{_addr(b)}
{('<br><span style="color:#777;font-size:8pt">' + e(L['vat_id'] + ' ' + b['vat_id']) + '</span>') if b.get('vat_id') else ''}</td>
<td style="vertical-align:top"><table style="border-collapse:collapse;width:100%">{meta_rows}</table></td></tr></table>
<p style="margin:16px 0 6px 0"></p>
<table style="width:100%;border-collapse:collapse">
<tr><th style="{th_style};text-align:left;padding:4px 3px">{L['pos']}</th><th style="{th_style};text-align:left;padding:4px 3px">{L['item']}</th>
<th style="{th_style};text-align:right;padding:4px 3px">{L['qty']}</th><th style="{th_style};text-align:left;padding:4px 3px">{L['unit']}</th>
<th style="{th_style};text-align:right;padding:4px 3px">{L['price']}</th><th style="{th_style};text-align:right;padding:4px 3px">{L['vat']}</th>
<th style="{th_style};text-align:right;padding:4px 3px">{L['amount']}</th></tr>
{''.join(rows)}</table>
<table style="width:100%;border-collapse:collapse;margin-top:8px"><tr><td style="width:45%"></td><td>
<table style="width:100%;border-collapse:collapse">{sum_rows}</table></td></tr></table>
{''.join(f'<p style="margin:10px 0 0 0">{e(n)}</p>' for n in notes)}
{f'<p style="margin:10px 0 0 0"><b>{L["terms"]}:</b> {e(terms)}</p>' if terms else ''}
<p style="margin:26px 0 0 0;padding-top:6px;border-top:0.5px solid #ccc;font-size:7.5pt;color:#666">
{e(seller_line)}{('<br>' + e(contact)) if contact else ''}{('<br>' + e(ids)) if ids else ''}
{('<br><b>' + L['bank'] + ':</b> ' + e(bank)) if bank else ''}</p>
</body></html>"""


def render(inv: dict, lang="de", design="classic", accent="#b3261e", logo=None) -> pymupdf.Document:
    html_text = to_html(inv, lang, design, accent, logo)
    story = pymupdf.Story(html=html_text, archive=pymupdf.Archive(os.path.dirname(logo)) if logo else None)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    box = pymupdf.paper_rect("a4")
    more = True
    while more:
        dev = writer.begin_page(box)
        more, _ = story.place(box + (50, 45, -50, -45))
        story.draw(dev)
        writer.end_page()
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    doc.set_metadata({"title": f"{LABELS[lang].get(inv.get('type_code') or '380')} {inv['number']}",
                      "author": inv["seller"].get("name", ""), "subject": "E-Rechnung" if lang == "de" else "E-invoice",
                      "creator": "pdfdesk", "producer": "pdfdesk"})
    return doc


@command("Invoice.Visualize")
def visualize(src, lang: str = "de") -> pymupdf.Document:
    """A readable PDF of an XML e-invoice (XRechnung or ZUGFeRD XML), with the XML attached."""
    if isinstance(src, str):
        with open(src, "rb") as f:
            data = f.read()
        name = os.path.basename(src)
    else:
        data, name = bytes(src), "invoice.xml"
    inv = parse(data)
    doc = render(inv, lang)
    doc.embfile_add(name, data, filename=name, desc="E-invoice XML")
    return doc


# ---- PDF/A-3 packaging ----------------------------------------------------------------------------------
FX_NS = "urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#"
_EXT = """<rdf:Description rdf:about="" xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/"
 xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#" xmlns:pdfaProperty="http://www.aiim.org/pdfa/ns/property#">
 <pdfaExtension:schemas><rdf:Bag><rdf:li rdf:parseType="Resource">
  <pdfaSchema:schema>Factur-X PDFA Extension Schema</pdfaSchema:schema>
  <pdfaSchema:namespaceURI>urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#</pdfaSchema:namespaceURI>
  <pdfaSchema:prefix>fx</pdfaSchema:prefix>
  <pdfaSchema:property><rdf:Seq>
   <rdf:li rdf:parseType="Resource"><pdfaProperty:name>DocumentFileName</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>The name of the embedded XML document</pdfaProperty:description></rdf:li>
   <rdf:li rdf:parseType="Resource"><pdfaProperty:name>DocumentType</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>The type of the hybrid document in capital letters, e.g. INVOICE or ORDER</pdfaProperty:description></rdf:li>
   <rdf:li rdf:parseType="Resource"><pdfaProperty:name>Version</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>The actual version of the standard applying to the embedded XML document</pdfaProperty:description></rdf:li>
   <rdf:li rdf:parseType="Resource"><pdfaProperty:name>ConformanceLevel</pdfaProperty:name><pdfaProperty:valueType>Text</pdfaProperty:valueType><pdfaProperty:category>external</pdfaProperty:category><pdfaProperty:description>The conformance level of the embedded XML document</pdfaProperty:description></rdf:li>
  </rdf:Seq></pdfaSchema:property>
 </rdf:li></rdf:Bag></pdfaExtension:schemas></rdf:Description>"""


def _conformance(xml: bytes) -> str:
    prof = parse(xml)["profile"]
    if "xrechnung" in prof.lower():
        return "XRECHNUNG"
    return PROFILES.get(prof, ("", "EN 16931", True))[1]


@command("Invoice.Embed")
def embed(pdf_path: str, xml: bytes, out: str, make_pdfa: bool = True, name: str = "factur-x.xml") -> str:
    """Make a ZUGFeRD / Factur-X file: PDF/A-3 conversion (Ghostscript through OCRmyPDF), then the XML attached
    as an associated file (/AF, AFRelationship Alternative) and the Factur-X XMP properties."""
    import pikepdf
    src = pdf_path
    if make_pdfa:
        from .convert import to_pdfa
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
        to_pdfa(pdf_path, tmp, part=3)
        src = tmp
    now = dt.datetime.now(dt.timezone.utc).strftime("D:%Y%m%d%H%M%S+00'00'")
    with pikepdf.open(src) as pdf:
        spec = pikepdf.AttachedFileSpec(pdf, xml, description="Factur-X / ZUGFeRD invoice", filename=name,
                                        mime_type="text/xml", creation_date=now, mod_date=now,
                                        relationship=pikepdf.Name.Alternative)
        pdf.attachments[name] = spec
        fs = pdf.Root.Names.EmbeddedFiles.Names
        ref = next(fs[i + 1] for i in range(0, len(fs), 2) if str(fs[i]) == name)
        pdf.Root.AF = pikepdf.Array([ref])
        xmp = bytes(pdf.Root.Metadata.read_bytes()) if "/Metadata" in pdf.Root else b""
        pdf.Root.Metadata = pikepdf.Stream(pdf, _xmp_with_fx(xmp, name, _conformance(xml)))
        pdf.Root.Metadata.Type, pdf.Root.Metadata.Subtype = pikepdf.Name.Metadata, pikepdf.Name.XML
        pdf.save(out)
    if src != pdf_path:
        os.unlink(src)
    return out


def _xmp_with_fx(xmp: bytes, name: str, level: str) -> bytes:
    rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    if xmp.strip():
        root = etree.fromstring(xmp, _parser())
    else:
        root = etree.fromstring(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="%s"/></x:xmpmeta>'
                                % rdf_ns.encode())
    rdf = root if etree.QName(root).localname == "RDF" else root.find(f".//{{{rdf_ns}}}RDF")
    for d in list(rdf):
        if any(k.startswith(f"{{{FX_NS}}}") for k in d.attrib) or d.find(f"{{{FX_NS}}}DocumentType") is not None \
                or d.find("{http://www.aiim.org/pdfa/ns/extension/}schemas") is not None:
            rdf.remove(d)
    fx = etree.SubElement(rdf, f"{{{rdf_ns}}}Description", nsmap={"fx": FX_NS})
    fx.set(f"{{{rdf_ns}}}about", "")
    for k, v in (("DocumentType", "INVOICE"), ("DocumentFileName", name), ("Version", "1.0"),
                 ("ConformanceLevel", level)):
        etree.SubElement(fx, f"{{{FX_NS}}}{k}").text = v
    rdf.append(etree.fromstring(_EXT.replace('rdf:about=""', f'xmlns:rdf="{rdf_ns}" rdf:about=""').encode()))
    body = etree.tostring(root, encoding="UTF-8")
    if b"<?xpacket" not in body:
        body = b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + body + b'\n<?xpacket end="w"?>'
    return body


@command("Invoice.Create")
def create(inv: dict, out_pdf: str | None = None, out_xml: str | None = None, lang: str = "de",
           design: str = "classic", accent: str = "#b3261e", logo: str | None = None) -> dict:
    """Write the invoice: a ZUGFeRD PDF/A-3 (out_pdf) and/or the XML alone (out_xml, e.g. for XRechnung)."""
    inv = compute(inv)
    xml = to_xml(inv)
    if out_xml:
        with open(out_xml, "wb") as f:
            f.write(xml)
    if out_pdf:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
        render(inv, lang, design, accent, logo).save(tmp, garbage=3, deflate=True)
        try:
            embed(tmp, xml, out_pdf)
        finally:
            os.unlink(tmp)
    return {"xml": xml, "totals": inv["totals"], "invoice": inv}
