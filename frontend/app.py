from __future__ import annotations

import json

import os

import time

from pathlib import Path

from uuid import uuid4

from typing import Any


 

import requests

import streamlit as st

from dotenv import load_dotenv

from formatting import display_english_date



 

# --------------------------------------------------

# Configuration

# --------------------------------------------------


 

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


 

API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000").rstrip("/")

TIMEOUT = (5, 60)


 

NAVIGATION = [

    "Dashboard",

    "Upload Invoice",

    "Invoices",

    "Invoice Assistant (Chat)",

    "Review Queue",

    "Audit Logs",

]


 

st.set_page_config(

    page_title="Invoice Auditor",

    page_icon="🧾",

    layout="wide",

    initial_sidebar_state="expanded",

)



 

# --------------------------------------------------

# UI Styling

# --------------------------------------------------


 

st.markdown(

    """

    <style>

    /* Main application */

    .stApp {

        background-color: #F5F7FB;

        color: #172033;

    }


 

    [data-testid="stMain"] {

        background-color: #F5F7FB;

    }


 

    .block-container {

        max-width: 1500px;

        padding-top: 1.8rem;

        padding-bottom: 2.5rem;

    }


 

    /* Main headings and text */

    .stApp h1,

    .stApp h2,

    .stApp h3,

    .stApp h4,

    .stApp p,

    .stApp label,

    .stApp [data-testid="stCaptionContainer"] {

        color: #172033;

    }


 

    .stApp h1 {

        font-weight: 750;

        letter-spacing: -0.6px;

    }


 

    /* Sidebar */

    [data-testid="stSidebar"] {

        background-color: #101C31;

        border-right: 1px solid #263650;

    }


 

    [data-testid="stSidebar"] h1,

    [data-testid="stSidebar"] h2,

    [data-testid="stSidebar"] h3,

    [data-testid="stSidebar"] p,

    [data-testid="stSidebar"] label,

    [data-testid="stSidebar"] span {

        color: #EDF3FF;

    }


 

    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {

        color: #B7C5DA;

    }


 

    /* Sidebar navigation */

    [data-testid="stSidebar"] [role="radiogroup"] label {

        background-color: transparent;

        border-radius: 9px;

        padding: 8px 10px;

    }


 

    [data-testid="stSidebar"] [role="radiogroup"] label:hover {

        background-color: #263650;

    }


 

    /* Metric cards */

    [data-testid="stMetric"] {

        background-color: #FFFFFF;

        border: 1px solid #E1E7F0;

        border-radius: 12px;

        padding: 17px 19px;

        box-shadow: 0 3px 10px rgba(20, 37, 64, 0.045);

    }


 

    [data-testid="stMetricLabel"],

    [data-testid="stMetricLabel"] p {

        color: #526078 !important;

    }


 

    [data-testid="stMetricValue"],

    [data-testid="stMetricValue"] div {

        color: #172033 !important;

        font-weight: 700;

    }


 

    [data-testid="stMetricDelta"] {

        color: #475569;

    }

   

   


 

    /* Text inputs and text areas */

    .stTextInput input,

    .stTextArea textarea,

    .stNumberInput input {

        background-color: #FFFFFF !important;

        color: #172033 !important;

        border: 1px solid #CBD5E1 !important;

        border-radius: 8px !important;

    }


 

    .stTextInput input::placeholder,

    .stTextArea textarea::placeholder {

        color: #8491A5 !important;

        opacity: 1;

    }


 

    /* Select boxes and dropdowns */

    [data-baseweb="select"] > div {

        background-color: #FFFFFF !important;

        border-color: #CBD5E1 !important;

    }


 

    [data-baseweb="select"] input,

    [data-baseweb="select"] span,

    [data-baseweb="select"] div {

        color: #172033;

    }


 

    [data-baseweb="popover"],

    [data-baseweb="menu"],

    [role="listbox"] {

        background-color: #FFFFFF;

        color: #172033;

    }


 

    [role="option"] {

        color: #172033 !important;

    }


 

    /* File uploader */

    [data-testid="stFileUploader"] {

        background-color: #FFFFFF;

        border: 1px dashed #A8B6CC;

        border-radius: 12px;

        padding: 12px;

    }


 

    [data-testid="stFileUploader"] section,

    [data-testid="stFileUploader"] section * {

        color: #172033 !important;

    }


 

    /* Buttons */

    .stButton > button {

        background-color: #FFFFFF;

        color: #172033 !important;

        border: 1px solid #CBD5E1;

        border-radius: 8px;

        font-weight: 600;

        min-height: 40px;

        transition: all 0.15s ease;

    }


 

    .stButton > button:hover {

        background-color: #EFF6FF;

        border-color: #2563EB;

        color: #1D4ED8 !important;

    }


 

    .stButton > button[kind="primary"] {

        background-color: #2563EB;

        color: #FFFFFF !important;

        border: 1px solid #2563EB;

    }


 

    .stButton > button[kind="primary"]:hover {

        background-color: #1D4ED8;

        color: #FFFFFF !important;

    }


 

    /* Dataframes and tables */

    [data-testid="stDataFrame"] {

        background-color: #FFFFFF;

        border: 1px solid #E1E7F0;

        border-radius: 10px;

        overflow: hidden;

    }


 

    /* Tabs */

    .stTabs [data-baseweb="tab-list"] {

        gap: 12px;

        border-bottom: 1px solid #DCE3ED;

    }


 

    .stTabs [data-baseweb="tab"] {

        color: #526078;

    }


 

    .stTabs [aria-selected="true"] {

        color: #2563EB !important;

        border-bottom-color: #2563EB !important;

    }


 

    /* JSON and code */

    [data-testid="stJson"],

    [data-testid="stCode"],

    pre {

        background-color: #FFFFFF !important;

        color: #172033 !important;

        border-radius: 8px;

    }


 

    /* Alerts */

    [data-testid="stAlert"] {

        border-radius: 10px;

    }


 

    /* Dividers */

    hr {

        border-color: #E1E7F0;

    }


 

    /* Links */

    .stApp a {

        color: #2563EB;

    }


 

    /* Progress bar */

    [data-testid="stProgressBar"] > div {

        background-color: #DCE7F7;

        border-radius: 10px;

    }


 

    [data-testid="stProgressBar"] > div > div {

        background-color: #2563EB;

    }

   

    /* File uploader outer container */

    [data-testid="stFileUploader"] {

        background-color: #FFFFFF !important;

        border: 1px solid #D8E2F0 !important;

        border-radius: 12px !important;

        padding: 16px !important;

    }


 

    /* Inner drag-and-drop area */

    [data-testid="stFileUploader"] section,

    [data-testid="stFileUploader"] section > div,

    [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] {

        background-color: #F8FAFF !important;

        color: #172033 !important;

        border-radius: 10px !important;

    }


 

    /* All uploader text */

    [data-testid="stFileUploader"] label,

    [data-testid="stFileUploader"] p,

    [data-testid="stFileUploader"] span,

    [data-testid="stFileUploader"] small,

    [data-testid="stFileUploader"] div {

        color: #172033;

    }


 

    /* Upload button */

    [data-testid="stFileUploader"] button {

        background-color: #FFFFFF !important;

        color: #1D4ED8 !important;

        border: 1px solid #2563EB !important;

        border-radius: 8px !important;

        font-weight: 600 !important;

    }


 

    /* Upload button hover */

    [data-testid="stFileUploader"] button:hover {

        background-color: #EFF6FF !important;

        color: #1D4ED8 !important;

        border-color: #1D4ED8 !important;

    }


 

    /* File type and size information */

    [data-testid="stFileUploader"] small {

        color: #64748B !important;

    }


 

    /* Uploaded file name */

    [data-testid="stFileUploaderFileName"],

    [data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] {

        color: #172033 !important;

    }

   

   

    /* Make all metric values consistent and prevent oversized text */

    [data-testid="stMetricValue"],

    [data-testid="stMetricValue"] div {

    color: #172033 !important;

    font-size: 25px !important;

    font-weight: 650 !important;

    }


 

    /* Keep long vendor names and dates from looking oversized */

    [data-testid="stMetric"] {

    min-width: 0;

    overflow: hidden;

    }


 

    [data-testid="stMetricValue"] {

    overflow: hidden;

    text-overflow: ellipsis;

    white-space: nowrap;

    }


 

    /* Original and translated invoice text areas */

    .stTextArea textarea {

    background-color: #FFFFFF !important;

    color: #000000 !important;

    -webkit-text-fill-color: #000000 !important;

    opacity: 1 !important;

    font-size: 15px !important;

    line-height: 1.6 !important;

    }


 

    /* Text area labels */

    .stTextArea label,

    .stTextArea label p {

    color: #172033 !important;

    }


 

    /* Placeholder text, if any */

    .stTextArea textarea::placeholder {

    color: #64748B !important;

    -webkit-text-fill-color: #64748B !important;

    opacity: 1 !important;

    }

   

   

    /* Force readable invoice text */

    .stTextArea textarea,

    .stTextArea textarea:disabled,

    .stTextArea textarea[disabled] {

        background-color: #FFFFFF !important;

        color: #000000 !important;

        -webkit-text-fill-color: #000000 !important;

        opacity: 1 !important;

        font-size: 15px !important;

        line-height: 1.6 !important;

        caret-color: #000000 !important;

    }


 

    /* Keep text area labels readable */

    .stTextArea label,

    .stTextArea label p {

        color: #172033 !important;

    }

    </style>

    """,

    unsafe_allow_html=True,

)



 

# --------------------------------------------------

# API Helper

# --------------------------------------------------


 

def api_request(method: str, path: str, **kwargs: Any) -> Any | None:

    try:

        response = requests.request(

            method,

            f"{API_URL}{path}",

            timeout=TIMEOUT,

            **kwargs,

        )


 

        if not response.ok:

            try:

                detail = response.json().get("detail", response.text)

            except (requests.exceptions.JSONDecodeError, ValueError):

                detail = response.text


 

            st.error(

                f"Agent API returned HTTP {response.status_code}: {detail}"

            )

            return None


 

        return response.json()


 

    except requests.RequestException:

        st.error(

            "Could not reach the Invoice Auditor service. "

            "Check that the agent is running and retry."

        )

        return None



 

# --------------------------------------------------

# Invoice Data

# --------------------------------------------------


 

def get_invoices(refresh: bool = False) -> list[dict[str, Any]]:

    if refresh or not isinstance(

        st.session_state.get("invoice_rows"), list

    ):

        invoices = api_request(

            "GET",

            "/invoices",

            params={"limit": 500},

        )


 

        if invoices is not None:

            st.session_state["invoice_rows"] = invoices


 

    cached = st.session_state.get("invoice_rows")

    return cached if isinstance(cached, list) else []



 

def invoice_label(invoice: dict[str, Any]) -> str:

    number = invoice.get("invoice_number") or invoice["filename"]

    return (

        f"{number} · {invoice['filename']} · "

        f"{invoice['status']}"

    )



 

# --------------------------------------------------

# Invoice Details

# --------------------------------------------------


 

@st.cache_data(ttl=600, show_spinner=False)
def get_validation_rules() -> dict[str, Any]:
    rules = api_request("GET", "/rules")
    return rules if isinstance(rules, dict) else {}


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "— (missing)"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


FIELD_LABELS = {

    "invoice_no": "invoice number",

    "invoice_date": "invoice date",

    "po_number": "purchase order number",

    "vendor_id": "vendor ID",

    "vendor_name": "vendor name",

    "currency": "currency",

    "total_amount": "total amount",

    "tax_amount": "tax amount",

    "subtotal": "subtotal",

    "item_code": "item code",

    "description": "description",

    "qty": "quantity",

    "unit_price": "unit price",

    "total": "line total",

}



 

# Findings produced by matching the invoice against the ERP system of record.

ERP_CATEGORIES = {

    "po_not_found",

    "vendor_not_found",

    "vendor_mismatch",

    "item_not_in_sku_master",

    "item_not_in_po",

    "missing_item_on_invoice",

    "quantity_mismatch",

    "price_mismatch",

    "currency_mismatch",

    "tax_mismatch",

}



 

# Informational company rules that never block approval; mirrors
# validation_policies.advisory_categories in rules.yml.

ADVISORY_CATEGORIES = {

    "stale_invoice",

    "future_date",

    "missing_optional_field",

}



 

# Only these contradict the ERP outright; the "not found" cases are data gaps a human can fix.

ERP_CONFLICT_CATEGORIES = {

    "vendor_mismatch",

    "quantity_mismatch",

    "price_mismatch",

    "currency_mismatch",

    "tax_mismatch",

}



 

def field_label(field: Any) -> str:

    name = str(field or "").strip()

    return FIELD_LABELS.get(name, name.replace("_", " ") or "field")



 

def friendly_finding(finding: dict[str, Any]) -> str:

    """Rewrite a technical finding message as plain English for a business reviewer."""

    category = finding.get("category", "")

    details = finding.get("details") or {}

    field = field_label(details.get("field"))

    item = details.get("item_code") or "this item"

    line = details.get("line_index")

    line_no = f"line {int(line) + 1}" if isinstance(line, int) else "a line"

    difference = details.get("difference_pct")


 

    messages = {

        "missing_field": f"The {field} is missing from the invoice. It is required before the invoice can be approved.",

        "missing_line_item_field": f"The {field} is missing on {line_no} of the invoice. Every line must state it.",

        "missing_line_items": "No line items could be read from the invoice, so nothing can be matched against the purchase order.",

        "invalid_date": "The invoice date is missing or unreadable. A valid invoice date is required.",

        "future_date": "The invoice date is in the future, which is not allowed.",

        "stale_invoice": "The invoice is too old to be processed under the current policy.",

        "invalid_currency": f"The currency '{details.get('value') or '—'}' on the invoice is not one this company accepts.",

        "line_item_math": f"On {line_no}, the stated total does not equal quantity × unit price.",

        "total_mismatch": "The invoice total does not match the sum of its line items and tax.",

        "tax_calculation": (

            f"The tax does not add up: subtotal {details.get('subtotal') or '—'} plus tax "

            f"{details.get('tax_amount') or '—'} should equal {details.get('expected') or '—'}, "

            f"but the invoice states {details.get('actual') or '—'}."

        ),

        "invalid_data_type": (

            f"The {field} holds a value that is not in the expected format "

            f"({details.get('expected_type') or 'the configured type'})."

        ),

        "po_not_found": f"Purchase order '{details.get('po_number') or '—'}' does not exist in the ERP, so the invoice cannot be matched to an order.",

        "vendor_not_found": f"Vendor '{details.get('vendor_id') or '—'}' is not registered in the ERP vendor master.",

        "vendor_mismatch": "The vendor billing this invoice is not the vendor recorded on the purchase order.",

        "item_not_in_sku_master": f"Item '{item}' is not a product registered in the ERP.",

        "item_not_in_po": f"Item '{item}' was billed but is not on the purchase order.",

        "missing_item_on_invoice": f"Item '{item}' was ordered on the purchase order but does not appear on this invoice.",

        "quantity_mismatch": f"The quantity billed for '{item}' differs from the ordered quantity"

                             + (f" by {difference}%." if difference is not None else "."),

        "price_mismatch": f"The unit price billed for '{item}' differs from the agreed purchase-order price"

                          + (f" by {difference}%." if difference is not None else "."),

        "currency_mismatch": "The invoice is billed in a different currency than the purchase order.",

        "tax_mismatch": "The tax charged on the invoice does not match the tax rates registered in the ERP"

                        + (f" (off by {difference}%)." if difference is not None else "."),

    }

    return messages.get(category) or finding.get("message", "A validation issue was found.")



 

def finding_rows(findings: list[dict[str, Any]]) -> list[dict[str, str]]:

    """Table rows for the validation report: no raw detail payloads."""

    severity_icons = {"error": "🔴 Error", "warning": "🟠 Warning", "info": "🔵 Info"}

    return [

        {

            "Severity": severity_icons.get(finding.get("severity"), finding.get("severity", "")),

            "Checked against": "ERP" if finding.get("category") in ERP_CATEGORIES else "Company rule",

            "Issue": finding.get("category", "").replace("_", " ").title(),

            "What it means": friendly_finding(finding),

        }

        for finding in findings

    ]



 

def audit_verdict(findings: list[dict[str, Any]], recommendation: str | None) -> tuple[str, str, str]:

    """Return (level, badge, explanation) for an invoice: rejected, review or approved."""

    erp_errors = [

        finding for finding in findings

        if finding.get("category") in ERP_CONFLICT_CATEGORIES and finding.get("severity") == "error"

    ]

    if erp_errors or recommendation == "reject":

        reason = (

            "It conflicts with the ERP system of record, which a reviewer cannot override."

            if erp_errors

            else "The audit rejected this invoice."

        )

        return "reject", "❌ CANNOT APPROVE", reason

    blocking = [

        finding for finding in findings

        if finding.get("category") not in ADVISORY_CATEGORIES

    ]

    if blocking or recommendation == "manual_review":

        return "manual_review", "🟠 MANUAL REVIEW REQUIRED", (

            "Company validation rules were broken, so a human needs to check this invoice before it is paid."

        )

    return "approve", "✅ APPROVED", "No validation or ERP problems were found."



 

def _erp_line(erp: dict[str, Any], item_code: str | None) -> dict[str, Any] | None:
    po = (erp or {}).get("purchase_order") or {}
    for line in po.get("line_items", []) or []:
        if str(line.get("item_code", "")).upper() == str(item_code or "").upper():
            return line
    return None


def build_comparison(
    finding: dict[str, Any],
    rules: dict[str, Any],
    erp: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Describe a finding as invoice value vs the rule or ERP value it violates."""
    category = finding.get("category", "")
    details = finding.get("details") or {}
    tolerances = rules.get("tolerances", {}) or {}
    required = rules.get("required_fields", {}) or {}
    item_code = details.get("item_code")

    invoice_label = "Invoice value"
    expected_label = "Expected value"
    invoice_value: Any = details.get("invoice_value", details.get("actual"))
    expected_value: Any = details.get("erp_value", details.get("expected"))
    source = "Validation rule"
    reference = ""
    context: dict[str, Any] = {}

    if category in {"missing_field", "missing_line_item_field"}:
        field = details.get("field", "")
        scope = "header" if category == "missing_field" else "line_item"
        invoice_label = f"Invoice field '{field}'"
        invoice_value = fields.get(field) if scope == "header" else None
        expected_label = "Required by company rules"
        expected_value = "Must be provided"
        reference = "Company rule: required invoice fields" if scope == "header" else "Company rule: required line-item fields"
        context = {f"required_fields.{scope}": required.get(scope, [])}

    elif category == "missing_line_items":
        invoice_label = "Line items on invoice"
        invoice_value = len(fields.get("line_items") or [])
        expected_label = "Required by company rules"
        expected_value = "Must list at least 1 line item"
        reference = "Company rule: every invoice must have line items"
        context = {"required_fields.line_item": required.get("line_item", [])}

    elif category == "invalid_currency":
        invoice_label = "Invoice currency"
        invoice_value = details.get("value") or fields.get("currency")
        expected_label = "Accepted currencies"
        expected_value = ", ".join(rules.get("accepted_currencies", []) or [])
        reference = "Company rule: accepted currencies"
        context = {
            "accepted_currencies": rules.get("accepted_currencies", []),
            "invalid_currency_action": (rules.get("validation_policies", {}) or {}).get("invalid_currency_action"),
        }

    elif category == "line_item_math":
        line = details.get("line_index")
        invoice_label = f"Line {int(line) + 1} total on invoice" if line is not None else "Line total on invoice"
        expected_label = "Quantity × unit price"
        reference = "Arithmetic consistency check"

    elif category == "total_mismatch":
        invoice_label = "Invoice total amount"
        expected_label = "Line totals + tax"
        reference = "Company rule: invoice total must match the line items"
        context = {"total_mismatch_action": (rules.get("validation_policies", {}) or {}).get("total_mismatch_action")}

    elif category == "tax_calculation":
        invoice_label = "Invoice total amount"
        expected_label = "Subtotal + tax"
        reference = "Company rule: tax must add up to the invoice total"

    elif category == "invalid_data_type":
        invoice_label = f"Invoice field '{details.get('field', '')}'"
        invoice_value = details.get("value")
        expected_label = "Required format"
        expected_value = {
            "float": "A number",
            "str": "Text",
            "date": "A date",
        }.get(str(details.get("expected_type")), "The configured format")
        reference = "Company rule: field data types"

    elif category in {"invalid_date", "future_date", "stale_invoice"}:
        invoice_label = "Invoice date"
        invoice_value = fields.get("invoice_date")
        expected_label = "Date rule"
        date_rules = rules.get("date_validation", {}) or {}
        accepted_formats = date_rules.get("accepted_formats") or []
        expected_value = {
            "invalid_date": (
                f"A readable date ({', '.join(accepted_formats)})"
                if accepted_formats
                else "A valid invoice date is required"
            ),
            "future_date": f"At most {date_rules.get('max_future_days', 7)} day(s) in the future",
            "stale_invoice": f"Not older than {date_rules.get('stale_invoice_days', 365)} day(s)",
        }[category]
        reference = "Company rule: invoice date"
        context = {"date_validation": date_rules} if date_rules else {}

    elif category == "po_not_found":
        invoice_label = "Purchase order on invoice"
        invoice_value = details.get("po_number") or fields.get("po_number")
        expected_label = "ERP purchase order"
        expected_value = "No such purchase order in the ERP"
        source = "ERP"
        reference = "ERP purchase-order register"

    elif category == "vendor_not_found":
        invoice_label = "Vendor on invoice"
        invoice_value = details.get("vendor_id") or fields.get("vendor_id")
        expected_label = "ERP vendor master"
        expected_value = "No such vendor in the ERP"
        source = "ERP"
        reference = "ERP vendor master"

    elif category == "item_not_in_sku_master":
        invoice_label = "Item code on invoice"
        invoice_value = item_code
        expected_label = "ERP SKU master"
        expected_value = "No such product in the ERP"
        source = "ERP"
        reference = "ERP product (SKU) master"

    elif category == "item_not_in_po":
        invoice_label = "Item code on invoice"
        invoice_value = item_code
        expected_label = "Purchase order line items"
        po = (erp or {}).get("purchase_order") or {}
        expected_value = ", ".join(
            str(line.get("item_code")) for line in po.get("line_items", []) or []
        ) or "No purchase-order lines available"
        source = "ERP"
        reference = f"ERP purchase order {po.get('po_number') or fields.get('po_number') or '—'}"

    elif category == "missing_item_on_invoice":
        invoice_label = "Item on invoice"
        invoice_value = None
        expected_label = "Ordered in the ERP"
        expected_value = f"{item_code} must be billed"
        source = "ERP"
        reference = "This purchase-order line was never invoiced"

    elif category in {"quantity_mismatch", "price_mismatch"}:
        noun = "Quantity" if category == "quantity_mismatch" else "Unit price"
        invoice_label = f"{noun} on invoice ({item_code})"
        expected_label = f"{noun} agreed in the ERP"
        source = "ERP"
        tolerance_key = (
            "quantity_difference_percent" if category == "quantity_mismatch" else "price_difference_percent"
        )
        reference = f"Company rule: allowed tolerance {tolerances.get(tolerance_key, '—')}%"
        context = {
            "difference_pct": details.get("difference_pct"),
            "allowed_tolerance_pct": tolerances.get(tolerance_key),
            "erp_purchase_order_line": _erp_line(erp, item_code),
        }

    elif category == "tax_mismatch":
        invoice_label = "Tax amount on invoice"
        expected_label = "Tax rate registered in the ERP"
        source = "ERP"
        reference = f"Company rule: allowed tax tolerance {tolerances.get('tax_difference_percent', '—')}%"
        context = {
            "difference_pct": details.get("difference_pct"),
            "allowed_tolerance_pct": tolerances.get("tax_difference_percent"),
            "erp_sku_gst_rates": {
                str(sku.get("sku") or sku.get("item_code")): sku.get("gst_rate")
                for sku in ((erp or {}).get("skus") or [])
                if isinstance(sku, dict)
            },
        }

    elif category == "currency_mismatch":
        invoice_label = "Currency on invoice"
        expected_label = "Currency agreed in the ERP"
        source = "ERP"
        reference = "Currency must match the purchase order"

    elif category == "vendor_mismatch":
        invoice_label = "Vendor on invoice"
        expected_label = "Vendor registered in the ERP"
        source = "ERP"
        reference = "Invoice vendor must match the purchase-order vendor"

    else:
        invoice_label = "Invoice value"
        expected_label = "Expected value"
        reference = finding.get("message", "")

    # When the invoice simply does not carry the value, say so on the expected side.
    if invoice_value in (None, "") and category != "missing_item_on_invoice":
        expected_value = "Must be provided on the invoice"

    return {
        "invoice_label": invoice_label,
        "invoice_value": invoice_value,
        "expected_label": expected_label,
        "expected_value": expected_value,
        "source": source,
        "reference": reference,
        "context": {key: value for key, value in context.items() if value not in (None, {}, [])},
    }


def render_finding_comparisons(detail: dict[str, Any]) -> None:
    """Render each validation finding beside the rule or ERP value it breaches."""
    findings = detail.get("findings") or []
    if not findings:
        st.success("No validation findings were recorded for this invoice.")
        return

    rules = get_validation_rules()
    erp = detail.get("erp") or {}
    fields = detail.get("extracted_fields") or {}

    comparisons = [build_comparison(f, rules, erp, fields) for f in findings]
    erp_based = [c for c in comparisons if c["source"] == "ERP"]
    summary = st.columns(3)
    summary[0].metric("Total findings", len(findings))
    summary[1].metric("Company rule breaches", len(comparisons) - len(erp_based))
    summary[2].metric("ERP mismatches", len(erp_based))

    severity_icons = {"error": "🔴", "warning": "🟠", "info": "🔵"}
    for finding, comparison in zip(findings, comparisons):
        icon = severity_icons.get(finding.get("severity"), "⚪")
        checked = "ERP" if comparison["source"] == "ERP" else "Company rule"
        with st.container(border=True):
            st.markdown(
                f"{icon} **{finding.get('category', 'finding').replace('_', ' ').title()}** "
                f"· _{finding.get('severity', '')}_ · checked against: **{checked}**"
            )
            st.caption(friendly_finding(finding))

            left, middle, right = st.columns([5, 1, 5])
            with left:
                st.markdown("**📄 On the invoice**")
                st.markdown(f"`{comparison['invoice_label']}`")
                st.markdown(f"### {_format_value(comparison['invoice_value'])}")
            with middle:
                st.markdown("<div style='text-align:center;font-size:28px;'>⚖️</div>", unsafe_allow_html=True)
            with right:
                icon_right = "🏛️" if comparison["source"] == "ERP" else "📏"
                heading = "ERP record" if comparison["source"] == "ERP" else "Company rule"
                st.markdown(f"**{icon_right} {heading}**")
                st.markdown(f"`{comparison['expected_label']}`")
                st.markdown(f"### {_format_value(comparison['expected_value'])}")

            if comparison["reference"]:
                st.caption(f"Reference: {comparison['reference']}")
            if comparison["context"]:
                with st.expander("Technical detail"):
                    st.json(comparison["context"])


def render_document_text(text: Any, label: str, key: str, empty_message: str) -> None:

    """Render invoice text readably: JSON is pretty-printed, plain text keeps its layout."""

    content = (text or "").strip() if isinstance(text, str) else ""

    if not content:

        st.warning(empty_message)

        return


 

    if content[0] in "{[":

        try:

            st.caption(label)

            st.json(json.loads(content))

            return

        except json.JSONDecodeError:

            pass


 

    st.caption(label)

    st.code(content, language=None)

    st.download_button(

        "⬇️ Download as text",

        data=content.encode("utf-8"),

        file_name=f"{key}.txt",

        mime="text/plain",

        key=f"dl-{key}",

    )



 

def render_detail(detail: dict[str, Any]) -> None:

    fields = detail.get("extracted_fields") or {}

    translated_fields = detail.get("translated_fields") or {}

    # Prefer translated values, but always fall back to what was extracted so a

    # non-English invoice without a translation still shows its details.

    display_fields = {**fields, **translated_fields} if translated_fields else fields

    report = detail.get("report") or {}

    recommendation = report.get("recommendation")


 

    st.subheader(

        display_fields.get("invoice_no") or detail["filename"]

    )

    st.caption(f"{detail['filename']} · {detail['id']}")


 

    st.write(

        f"**Status:** {detail['status'].replace('_', ' ').title()}"

    )


 

    if detail.get("error_message"):

        st.error(detail["error_message"])


 

        if st.button(

            "Retry processing",

            key=f"retry-{detail['id']}",

        ):

            if api_request(

                "POST",

                f"/invoices/{detail['id']}/process",

            ):

                st.success("Retry queued. Refresh this page to see progress.")

                st.rerun()


 

    if detail.get("status") == "completed":

        _, verdict_badge, _ = audit_verdict(detail.get("findings") or [], recommendation)

        st.write(f"**Audit verdict:** {verdict_badge}")


 

    overview = st.columns(4)


 

    overview[0].metric(

        "Vendor",

        display_fields.get("vendor_name") or "—",

    )


 

    overview[1].metric(

        "Invoice date",

        display_english_date(display_fields.get("invoice_date")),

    )


 

    amount = display_fields.get("total_amount")


 

    overview[2].metric(

        "Total amount",

        f"{amount:,.2f}"

        if isinstance(amount, (int, float))

        and not isinstance(amount, bool)

        else "—",

    )


 

    overview[3].metric(

        "Currency",

        display_fields.get("currency") or "—",

    )


 

    tabs = st.tabs(

        [

            "Extracted fields",

            "Original text",

            "Translated text",

            "Validation report",

            "Evidence & comparison",

            "Activity",

        ]

    )


 

    with tabs[0]:

        st.json(

            fields or {"message": "No extracted fields available yet."}

        )


 

    with tabs[1]:

        render_document_text(

            detail.get("original_text"),

            "Original invoice text",

            f"original-text-{detail['id']}",

            "No text was extracted from this document.",

        )


 

    with tabs[2]:

        render_document_text(

            detail.get("translated_text"),

            "English text used for review",

            f"translated-text-{detail['id']}",

            "Translated text is empty or was not returned by the API.",

        )


 

    with tabs[3]:

        findings = detail.get("findings") or []

        level, badge, explanation = audit_verdict(findings, recommendation)


 

        with st.container(border=True):

            st.markdown(f"### {badge}")

            st.write(explanation)

            if level == "reject":

                st.error("Do not pay this invoice. Return it to the vendor for correction.")

            elif level == "manual_review":

                st.warning("A reviewer must approve or reject this invoice in the Review Queue.")

            else:

                st.success("This invoice can be approved.")


 

        if findings:

            st.markdown("#### What was found")

            st.dataframe(

                finding_rows(findings),

                use_container_width=True,

                hide_index=True,

                column_config={"What it means": st.column_config.TextColumn(width="large")},

            )

        else:

            st.success("No validation findings were recorded.")


 

        if report and report.get("summary"):

            with st.expander("Full audit narrative"):

                st.markdown(report["summary"])


 

    with tabs[4]:

        st.markdown("#### Invoice vs rule / ERP comparison")

        st.caption(

            "Each validation problem is shown beside the company rule or the ERP record "

            "record it conflicts with."

        )

        render_finding_comparisons(detail)


 

        evidence = (

            detail.get("evidence")

            or report.get("data", {}).get("evidence")

            or []

        )


 

        st.divider()

        st.markdown("#### Source passages used as evidence")

        st.caption(

            "The exact extracts from the document that the audit relied on, most relevant first."

        )

        if evidence:

            for position, source in enumerate(

                sorted(evidence, key=lambda item: item.get("score") or 0, reverse=True), start=1

            ):

                score = source.get("score")

                relevance = f"{float(score) * 100:.0f}% match" if isinstance(score, (int, float)) else "—"

                label = (

                    f"{position}. {source.get('filename', detail['filename'])} — "

                    f"page {source.get('page', '—')} · {relevance}"

                )

                with st.expander(label, expanded=position == 1):

                    st.code((source.get("text") or "").strip() or "(empty passage)", language=None)

        else:

            st.info("No indexed evidence is available for this invoice.")


 

    with tabs[5]:

        events = detail.get("events") or []


 

        if events:

            st.dataframe(

                events,

                use_container_width=True,

                hide_index=True,

            )

        else:

            st.info("No processing events have been recorded.")



 

# --------------------------------------------------

# Processing Stage Results

# --------------------------------------------------


 

def stage_results(

    detail: dict[str, Any],

) -> list[dict[str, str]]:

    stage_labels = [

        ("extract", "Extraction", "Text extraction completed"),

        ("translate", "Translation", None),

        ("validate", "Validation", "Structural validation completed"),

        ("rag_index", "Indexing", "Indexed "),

    ]


 

    latest: dict[str, dict[str, Any]] = {}


 

    for event in detail.get("events", []):

        latest[event["stage"]] = event


 

    results = []


 

    for stage, label, success_text in stage_labels:

        event = latest.get(stage)

        message = event.get("message", "") if event else ""


 

        if event and event.get("level") == "ERROR":

            status = "Failed"


 

        elif event and (

            (

                success_text

                and success_text in message

            )

            or (

                stage == "translate"

                and (

                    message.startswith("Translated invoice")

                    or message == "Translation not required"

                )

            )

        ):

            status = "Succeeded"


 

        elif detail["status"] == "failed" and event:

            status = "Failed"


 

        elif detail["status"] == "completed":

            status = "Succeeded"


 

        else:

            status = "In progress" if event else "Waiting"


 

        results.append(

            {

                "Step": label,

                "Result": status,

            }

        )


 

    return results



 

# --------------------------------------------------

# Dashboard

# --------------------------------------------------


 

def show_dashboard() -> None:

    st.title("📊 Dashboard")

    st.caption(

        "A live overview of invoice processing and connected services."

    )


 

    summary = api_request("GET", "/dashboard/summary") or {}


 

    metrics = st.columns(4)


 

    metrics[0].metric(

        "Total invoices",

        summary.get("total_invoices", 0),

    )

    metrics[1].metric(

        "Validated",

        summary.get("validated_invoices", 0),

    )

    metrics[2].metric(

        "Needs review",

        summary.get("invoices_needing_review", 0),

    )

    metrics[3].metric(

        "Failed",

        summary.get("failed_invoices", 0),

    )


 

    st.divider()


 

    activity_col, services_col = st.columns([1.2, 1])


 

    with activity_col:

        st.subheader("🕒 Recent activity")


 

        activity = api_request(

            "GET",

            "/audit-logs",

            params={"limit": 8},

        ) or []


 

        if activity:

            st.dataframe(

                [

                    {

                        "Time": event["created_at"],

                        "Invoice": event["filename"],

                        "Event": event["stage"].replace("_", " ").title(),

                        "Status": event["level"],

                        "Details": event["message"],

                    }

                    for event in activity

                ],

                use_container_width=True,

                hide_index=True,

            )

        else:

            st.info("No invoice activity yet.")


 

    with services_col:

        st.subheader("🔌 Service health")


 

        health = api_request("GET", "/health/services") or {}

        services = health.get("services", {})


 

        if services:

            for name, result in services.items():

                healthy = result.get("status") == "healthy"

                icon = "🟢" if healthy else "🔴"


 

                st.markdown(

                    f"{icon} **{name.replace('_', ' ').title()}** — "

                    f"{result.get('detail', result.get('status', 'unknown'))}"

                )

        else:

            st.warning("Service health is currently unavailable.")



 

# --------------------------------------------------

# Upload Invoice

# --------------------------------------------------


 

STATUS_BADGES = {

    "new": "🆕 Not registered",

    "pending": "🕓 Awaiting processing",

    "queued": "⏳ Queued",

    "processing": "⚙️ Processing",

    "completed": "✅ Completed",

    "failed": "❌ Failed",

}



 

def _folder_rows(files: list[dict[str, Any]], with_status: bool) -> list[dict[str, Any]]:

    """Plain name/size listing; a status column is added once processing has run."""

    rows = []

    for item in files:

        row = {"File": item["filename"], "Size": f"{item['size_bytes']:,} bytes"}

        row["Metadata"] = item.get("metadata_file") or "—"

        if with_status:

            row["Status"] = STATUS_BADGES.get(item["status"], item["status"])

        rows.append(row)

    return rows



 

def refresh_folder_files() -> list[dict[str, Any]]:

    """Re-read the monitored folder and cache the result for this session."""

    payload = api_request("GET", "/ingestion/folder/files")

    files = payload.get("files", []) if isinstance(payload, dict) else []

    st.session_state["folder_files"] = files

    return files



 

def render_file_status(item: dict[str, Any]) -> None:

    """Show what happened to one file after processing."""

    st.markdown(f"#### {item['filename']}")

    invoice_id = item.get("invoice_id")

    if not invoice_id:

        st.info("This file has not been registered yet. Scan the folder and process it.")

        return


 

    detail = api_request("GET", f"/invoices/{invoice_id}")

    if not detail:

        st.warning("The status for this file could not be retrieved.")

        return


 

    status = detail["status"]

    if status == "completed":

        st.success("Processing completed.")

    elif status == "failed":

        st.error(detail.get("error_message") or "Processing failed.")

    elif status == "pending":

        st.info("Detected in the folder and waiting to be processed.")

    else:

        st.warning(f"Processing is still running (status: {status}).")


 

    st.progress(min(item.get("progress", 0) / 100, 1.0), text=item.get("current_stage") or "—")

    st.dataframe(stage_results(detail), use_container_width=True, hide_index=True)


 

    findings = detail.get("findings") or []

    if findings:

        st.caption(f"{len(findings)} validation finding(s) recorded. Open the Invoices page for the full evidence.")

    st.caption(f"Invoice ID: `{invoice_id}`")



 

def run_folder_processing(targets: list[dict[str, Any]], reprocess: bool = False) -> None:

    """Queue the selected documents and track overall completion on a single bar."""

    response = api_request(

        "POST",

        "/ingestion/folder/process",

        json={"filenames": [item["filename"] for item in targets], "reprocess": reprocess},

    )

    if not isinstance(response, dict):

        return


 

    queued = response.get("queued", [])

    skipped = response.get("skipped", [])

    st.session_state["invoice_rows"] = None

    if not queued:

        st.info("Nothing left to process in the monitored folder.")

        refresh_folder_files()

        return


 

    pending_ids = {item["invoice_id"] for item in queued}

    details: dict[str, dict[str, Any]] = {}

    progress_bar = st.progress(0.0, text=f"Processing 0/{len(queued)} invoices…")

    deadline = time.monotonic() + 600


 

    while pending_ids and time.monotonic() < deadline:

        for invoice_id in list(pending_ids):

            detail = api_request("GET", f"/invoices/{invoice_id}")

            if detail:

                details[invoice_id] = detail

                if detail["status"] in {"completed", "failed"}:

                    pending_ids.discard(invoice_id)


 

        done = sum(detail.get("progress", 0) for detail in details.values())

        finished = len(queued) - len(pending_ids)

        progress_bar.progress(

            min(done / (len(queued) * 100), 1.0),

            text=f"Processing {finished}/{len(queued)} invoices…",

        )

        if pending_ids:

            time.sleep(2)


 

    failed = [detail for detail in details.values() if detail["status"] == "failed"]

    progress_bar.progress(1.0, text=f"Processed {len(queued)} invoice(s).")

    st.session_state["folder_processed"] = True

    skipped_note = f" {len(skipped)} file(s) were already processed and were skipped." if skipped else ""

    st.session_state["folder_flash"] = (

        f"Processed {len(queued)} invoice(s); {len(failed)} failed.{skipped_note} "

        "Select a row in the table above to see its status."

    )

    refresh_folder_files()



 

def render_folder_monitor() -> None:

    """Show the state of the monitored incoming folder and allow an on-demand scan."""

    status = api_request("GET", "/ingestion/folder")

    if not isinstance(status, dict):

        return


 

    with st.container(border=True):

        st.markdown("#### 📁 Monitored incoming folder")

        columns = st.columns([3, 1, 1])

        columns[0].markdown(f"`{status.get('folder', 'unknown')}`")

        columns[1].metric("Files present", status.get("files_in_folder", 0))

        state = "🟢 Watching" if status.get("running") and status.get("enabled") else "⚪ Paused"

        columns[2].markdown(f"**{state}**")


 

        last_scan = status.get("last_scan_at")

        caption = f"Polled every {status.get('interval_seconds', '?')}s · accepts " + ", ".join(

            extension.lstrip(".").upper() for extension in status.get("accepted_extensions", [])

        )

        if last_scan:

            caption += f" · last scan {last_scan[:19].replace('T', ' ')} UTC"

        st.caption(caption)

        if status.get("last_error"):

            st.warning(f"Last scan error: {status['last_error']}")



 

def show_upload() -> None:

    st.title("📤 Upload Invoice")

    st.caption(

        "Step 1 — drop invoices into the monitored folder. Step 2 — scan the folder to list "

        "its files. Step 3 — process them, then select a file to see its status."

    )


 

    render_folder_monitor()


 

    st.subheader("1 · Add files to the monitored folder")

    uploaded_files = st.file_uploader(

        "Choose a PDF, DOCX or image invoice (optionally with its .meta.json sidecar)",

        type=["pdf", "docx", "png", "jpg", "jpeg", "json"],

        accept_multiple_files=True,

        key="multiple_invoice_upload",

    )


 

    if uploaded_files:

        if st.button("📥 Upload to monitored folder", type="primary", key="upload-to-folder"):

            result = api_request(

                "POST",

                "/ingestion/folder/upload",

                files=[

                    ("files", (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream"))

                    for uploaded in uploaded_files

                ],

            )

            if isinstance(result, dict):

                saved = result.get("saved", [])

                duplicates = result.get("duplicates", [])

                rejected = result.get("rejected", [])


 

                if duplicates:

                    names = ", ".join(f"**{item['filename']}**" for item in duplicates)

                    st.warning(

                        f"Already present in the monitored folder, so {'it was' if len(duplicates) == 1 else 'they were'} "

                        f"not uploaded again: {names}"

                    )

                    with st.expander("Why these files were skipped"):

                        for item in duplicates:

                            st.markdown(f"- `{item['filename']}` — {item['reason']}")


 

                if saved:

                    st.success(

                        "Copied into the monitored folder: "

                        + ", ".join(item["filename"] for item in saved)

                        + ". Scan the folder below to list and process them."

                    )

                elif not duplicates and not rejected:

                    st.info("Nothing was uploaded.")


 

                for item in rejected:

                    st.error(f"{item['filename']} was not accepted — {item['detail']}")

                refresh_folder_files()


 

    st.subheader("2 · Scan the monitored folder")

    scan_columns = st.columns([1, 1, 3])

    if scan_columns[0].button("🔎 Scan folder", key="scan-incoming-folder"):

        result = api_request("POST", "/ingestion/folder/scan")

        if isinstance(result, dict):

            st.session_state["folder_files"] = result.get("files", [])

            st.session_state["invoice_rows"] = None

            st.session_state["folder_selected"] = None

    if scan_columns[1].button("🔄 Refresh list", key="refresh-folder-list"):

        refresh_folder_files()

        st.session_state["folder_selected"] = None


 

    files = st.session_state.get("folder_files")

    if files is None:

        st.info("Press **Scan folder** to list the invoices currently in the monitored folder.")

        return


 

    files = refresh_folder_files()

    if not files:

        st.warning("The monitored folder is empty. Upload an invoice above or copy one into the folder.")

        return


 

    with_status = any(item["status"] != "pending" for item in files)

    selection = st.dataframe(

        _folder_rows(files, with_status),

        use_container_width=True,

        hide_index=True,

        on_select="rerun" if with_status else "ignore",

        selection_mode="single-row",

        key=f"folder-file-table-{len(files)}-{int(with_status)}",

    )


 

    flash = st.session_state.pop("folder_flash", None)

    if flash:

        st.success(flash)


 

    pending = [item for item in files if item["status"] not in {"completed", "queued", "processing"}]

    running = [item for item in files if item["status"] in {"queued", "processing"}]

    targets, reprocess = (pending, False) if pending else (files, True)

    label = (

        f"▶️ Process {len(targets)} file(s)" if pending

        else f"♻️ Reprocess all {len(files)} file(s)"

    )

    if running:

        st.caption(f"{len(running)} file(s) are still being processed and are not counted above.")

    if st.button(label, type="primary", key="process-folder-invoices"):

        run_folder_processing(targets, reprocess=reprocess)

        st.rerun()


 

    if with_status:

        rows = (selection.selection or {}).get("rows", []) if hasattr(selection, "selection") else []

        if rows and rows[0] < len(files):

            with st.container(border=True):

                render_file_status(files[rows[0]])

        else:

            st.caption("Select a file in the table above to see its processing status.")



 

# --------------------------------------------------

# Invoices

# --------------------------------------------------


 

def show_invoices() -> None:

    st.title("🧾 Invoices")

    header = st.columns([3, 1])

    with header[0]:

        st.caption(

            "Browse extracted invoice details and validation results."

        )

    with header[1]:

        st.write("")

        if st.button("🔄 Refresh invoices", use_container_width=True):

            get_invoices(refresh=True)

            st.rerun()


 

    invoices = get_invoices()


 

    if not invoices:

        st.info("No invoices registered yet. Upload an invoice to get started.")

        return


 

    st.dataframe(

        [

            {

                "Invoice number": invoice.get("invoice_number") or "—",

                "Vendor": invoice.get("vendor") or "—",

                "Date": invoice.get("invoice_date") or "—",

                "Amount": invoice.get("amount"),

                "Currency": invoice.get("currency") or "—",

                "Status": invoice["status"].replace("_", " ").title(),

            }

            for invoice in invoices

        ],

        use_container_width=True,

        hide_index=True,

    )


 

    # Look the label up by id so a refresh that drops an invoice cannot break the picker.

    labels_by_id = {invoice["id"]: invoice_label(invoice) for invoice in invoices}


 

    selected_id = st.selectbox(

        "Choose an invoice",

        list(labels_by_id),

        format_func=lambda value: labels_by_id.get(value, str(value)),

        key="invoice-details-select",

    )


 

    if st.button("View Details", type="primary"):

        st.session_state["selected_invoice_id"] = selected_id


 

    detail_id = st.session_state.get("selected_invoice_id")


 

    if detail_id:

        detail = api_request(

            "GET",

            f"/invoices/{detail_id}",

        )


 

        if detail:

            render_detail(detail)



 

# --------------------------------------------------

# Invoice Assistant (conversational RAG with memory)

# --------------------------------------------------


 

def _chat_session_id() -> str:
    """Keep one chat session per browser tab so the last 30 messages survive a reload."""
    session_id = st.session_state.get("chat_session_id")
    if not session_id:
        try:
            session_id = st.query_params.get("chat")
        except Exception:
            session_id = None
    if not session_id:
        session_id = f"ui-{uuid4().hex[:12]}"
    st.session_state["chat_session_id"] = session_id
    try:
        if st.query_params.get("chat") != session_id:
            st.query_params["chat"] = session_id
    except Exception:
        pass
    return session_id


def _load_server_history(session_id: str) -> None:
    """Hydrate the chat panel from the server-side memory once per session."""
    if st.session_state.get("chat_history_loaded") == session_id:
        return
    payload = api_request("GET", f"/rag/chat/{session_id}/history")
    messages = (payload or {}).get("messages", []) if isinstance(payload, dict) else []
    st.session_state["chat_turns"] = [
        {"role": message.get("role", "user"), "content": message.get("content", ""), "sources": []}
        for message in messages
    ]
    st.session_state["chat_history_loaded"] = session_id


def show_questions() -> None:
    st.title("💬 Invoice Assistant (RAG Chat)")

    session_id = _chat_session_id()
    _load_server_history(session_id)
    invoices = get_invoices()

    scope = st.selectbox(
        "Knowledge scope",
        ["All invoices"] + [invoice["id"] for invoice in invoices],
        format_func=lambda value: (
            "All invoices (full knowledge base)"
            if value == "All invoices"
            else next(
                invoice_label(row)
                for row in invoices
                if row["id"] == value
            )
        ),
        key="rag-invoice",
    )

    turns = st.session_state.get("chat_turns", [])

    with st.expander("Example questions", expanded=not turns):
        st.markdown(
            "- Why did **INV_EN_002.pdf** get flagged for manual review?\n"
            "- What is the extracted text of invoice **FAC-2025-003**?\n"
            "- Which invoices failed processing and why?\n"
            "- Compare the invoice total with the purchase order for **PO-1003**.\n"
            "- Who approved the last invoice and what note did they leave?"
        )

    for index, turn in enumerate(turns):
        with st.chat_message("assistant" if turn["role"] == "assistant" else "user"):
            st.markdown(turn["content"])
            sources = turn.get("sources") or []
            if sources:
                with st.expander(f"Evidence used ({len(sources)} passage(s))"):
                    for source in sources:
                        st.caption(
                            f"{source.get('filename')} · invoice {source.get('invoice_id')} · "
                            f"page {source.get('page')} · score {source.get('score', 0):.2f}"
                        )
                        st.write(source.get("text", ""))
                        st.divider()

    question = st.chat_input("Ask about any invoice…")
    if not question or not question.strip():
        return

    question = question.strip()
    st.session_state.setdefault("chat_turns", []).append(
        {"role": "user", "content": question, "sources": []}
    )

    payload: dict[str, Any] = {"question": question, "session_id": session_id}
    if scope != "All invoices":
        payload["invoice_id"] = scope

    with st.spinner("Searching the invoice knowledge base…"):
        response = api_request("POST", "/rag/chat", json=payload)

    if response:
        st.session_state["chat_turns"].append({
            "role": "assistant",
            "content": response.get("answer", ""),
            "sources": response.get("sources", []),
        })
        st.session_state["chat_turns"] = st.session_state["chat_turns"][-30:]
    else:
        st.session_state["chat_turns"].append({
            "role": "assistant",
            "content": "The assistant could not answer that question. Please retry.",
            "sources": [],
        })
    st.rerun()


# --------------------------------------------------
# Review Queue (human in the loop)
# --------------------------------------------------

def review_decision(invoice: dict[str, Any]) -> str | None:
    """Return the binding human decision, ignoring legacy acknowledgements."""
    status = invoice.get("review_status")
    return status if status in {"approve", "reject"} else None


def effective_decision(invoice: dict[str, Any]) -> str | None:
    """A human decision wins; otherwise the audit's own verdict stands.

    Only invoices the audit flagged for manual review are left awaiting a decision:
    a clean invoice is already approved and a rejected one already settled.
    """
    decision = review_decision(invoice)
    if decision:
        return decision
    verdict = invoice.get("audit_verdict") or invoice.get("recommendation")
    if verdict in {"reject", "human_rejected"}:
        return "reject"
    if verdict in {"approve", "auto_approve", "human_approved"}:
        return "approve"
    count = invoice.get("finding_count")
    if count and count ==0 :
        return "approve"
    return None


REVIEW_FILTERS = {
    "Awaiting decision": lambda invoice: effective_decision(invoice) is None,
    "Approved": lambda invoice: effective_decision(invoice) == "approve",
    "Rejected": lambda invoice: effective_decision(invoice) == "reject",
    "All invoices": lambda invoice: True,
}


def _render_image(data: Any, caption: str) -> None:
    try:
        st.image(data, caption=caption, use_container_width=True)
    except TypeError:
        st.image(data, caption=caption, use_column_width=True)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_invoice_file(invoice_id: str) -> tuple[bytes, str] | None:
    try:
        response = requests.get(f"{API_URL}/invoices/{invoice_id}/file", timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if not response.ok:
        return None
    return response.content, response.headers.get("content-type", "")


def render_document(detail: dict[str, Any]) -> None:
    """Show the original invoice document next to the review actions."""
    invoice_id = detail["id"]
    payload = fetch_invoice_file(invoice_id)
    if payload is None:
        st.warning("The original document could not be loaded from the agent service.")
        return

    content, content_type = payload
    st.download_button(
        "⬇️ Download original file",
        data=content,
        file_name=detail["filename"],
        mime=content_type or "application/octet-stream",
        key=f"download-{invoice_id}",
    )

    if "pdf" in content_type or detail["filename"].lower().endswith(".pdf"):
        try:
            import fitz

            with fitz.open(stream=content, filetype="pdf") as document:
                total_pages = document.page_count
                page_number = 1
                if total_pages > 1:
                    page_number = st.number_input(
                        f"Page (1–{total_pages})",
                        min_value=1,
                        max_value=total_pages,
                        value=1,
                        step=1,
                        key=f"pdf-page-{invoice_id}",
                    )
                page = document.load_page(int(page_number) - 1)
                image = page.get_pixmap(dpi=140).tobytes("png")
            _render_image(image, f"{detail['filename']} · page {int(page_number)}")
        except Exception:
            st.info("Inline PDF preview is unavailable. Use the download button above.")
    elif content_type.startswith("image/"):
        _render_image(content, detail["filename"])
    elif "json" in content_type or detail["filename"].lower().endswith(".json"):
        try:
            st.json(json.loads(content.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            st.code(content.decode("utf-8", errors="replace")[:5000])
    elif detail["filename"].lower().endswith(".docx") or "wordprocessingml" in content_type:
        extracted = (detail.get("original_text") or "").strip()
        if extracted:
            st.text_area(
                "Word document text",
                value=extracted[:20000],
                height=420,
                key=f"docx-preview-{invoice_id}",
                disabled=True,
            )
        else:
            st.info("No text was extracted from this Word document. Use the download button above.")
    else:
        st.code(content.decode("utf-8", errors="replace")[:5000])


def _submit_decision(detail: dict[str, Any], decision: str, reviewer: str, note: str) -> None:
    if decision == "reject" and not note.strip():
        st.error("A rejection requires a note explaining the reason.")
        return
    result = api_request(
        "POST",
        f"/invoices/{detail['id']}/decision",
        json={
            "decision": decision,
            "note": note.strip() or None,
            "reviewer": reviewer.strip() or "human-reviewer",
        },
    )
    if result:
        st.session_state["review_flash"] = (
            f"Decision '{decision}' recorded for {detail['filename']}."
        )
        st.session_state[f"edit-review-{detail['id']}"] = False
        st.session_state["invoice_rows"] = None
        st.rerun()


def _render_decision_form(detail: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """Capture a new decision, or amend the one already recorded."""
    invoice_id = detail["id"]
    options = ["approve", "reject"]
    default_index = options.index(previous["decision"]) if previous and previous["decision"] in options else 0

    reviewer = st.text_input(
        "Reviewer",
        value=(previous or {}).get("reviewer") or st.session_state.get("reviewer_name", "human-reviewer"),
        key=f"reviewer-{invoice_id}",
    )
    st.session_state["reviewer_name"] = reviewer

    if previous:
        decision = st.radio(
            "Updated decision",
            options,
            index=default_index,
            horizontal=True,
            format_func=lambda value: "✅ Approve" if value == "approve" else "❌ Reject",
            key=f"decision-choice-{invoice_id}",
        )
        note = st.text_area(
            "Decision note",
            value=previous.get("note") or "",
            placeholder="Explain the approval or rejection reason…",
            key=f"review-note-{invoice_id}",
        )
        actions = st.columns(2)
        if actions[0].button("💾 Save updated review", type="primary", key=f"save-review-{invoice_id}", use_container_width=True):
            _submit_decision(detail, decision, reviewer, note)
        if actions[1].button("Cancel", key=f"cancel-review-{invoice_id}", use_container_width=True):
            st.session_state[f"edit-review-{invoice_id}"] = False
            st.rerun()
        return

    note = st.text_area(
        "Decision note",
        placeholder="Explain the approval or rejection reason…",
        key=f"review-note-{invoice_id}",
    )
    actions = st.columns(2)
    if actions[0].button("✅ Approve", type="primary", key=f"approve-{invoice_id}", use_container_width=True):
        _submit_decision(detail, "approve", reviewer, note)
    if actions[1].button("❌ Reject", key=f"reject-{invoice_id}", use_container_width=True):
        _submit_decision(detail, "reject", reviewer, note)


def render_review_actions(detail: dict[str, Any]) -> None:
    """Show the recorded human decision, or capture a new one."""
    invoice_id = detail["id"]
    st.subheader("Human decision")

    reviews = detail.get("reviews") or []
    decisions = [review for review in reviews if review.get("decision") in {"approve", "reject"}]
    previous = decisions[-1] if decisions else None
    edit_flag = f"edit-review-{invoice_id}"

    if previous and not st.session_state.get(edit_flag):
        verdict = "✅ Approved" if previous["decision"] == "approve" else "❌ Rejected"
        st.success(f"{verdict} by **{previous['reviewer']}**")
        st.caption(f"Recorded {previous['created_at']}")
        st.markdown(f"**Note:** {previous.get('note') or '—'}")
        if st.button("✏️ Edit human review", key=f"start-edit-{invoice_id}", use_container_width=True):
            st.session_state[edit_flag] = True
            st.rerun()
        if len(decisions) > 1:
            with st.expander(f"Earlier decisions ({len(decisions) - 1})"):
                for review in reversed(decisions[:-1]):
                    st.markdown(
                        f"- **{review['decision']}** by {review['reviewer']} on "
                        f"{review['created_at']} — {review.get('note') or 'no note'}"
                    )
    else:
        _render_decision_form(detail, previous)
        render_field_editor(detail)


def render_field_editor(detail: dict[str, Any]) -> None:
    """Correct the extracted field values of an invoice under review."""
    invoice_id = detail["id"]
    with st.expander("✏️ Edit extracted fields"):
        fields = dict(detail.get("extracted_fields") or {})
        if not fields:
            st.info("This invoice has no extracted fields to edit yet.")
            return

        editable_keys = [
            "invoice_no",
            "invoice_date",
            "po_number",
            "vendor_id",
            "vendor_name",
            "currency",
            "total_amount",
            "tax_amount",
            "subtotal",
        ]
        with st.form(f"edit-fields-{invoice_id}"):
            updates: dict[str, Any] = {}
            columns = st.columns(3)
            for index, key in enumerate(editable_keys):
                current = fields.get(key)
                label = key.replace("_", " ").title()
                if key in {"total_amount", "tax_amount", "subtotal"}:
                    value = columns[index % 3].number_input(
                        label,
                        value=float(current) if isinstance(current, (int, float)) and not isinstance(current, bool) else 0.0,
                        step=0.01,
                        format="%.2f",
                        key=f"edit-{key}-{invoice_id}",
                    )
                    updates[key] = float(value)
                else:
                    value = columns[index % 3].text_input(
                        label,
                        value="" if current is None else str(current),
                        key=f"edit-{key}-{invoice_id}",
                    )
                    updates[key] = value.strip() or None

            edit_note = st.text_input("Correction note", key=f"edit-note-{invoice_id}")
            approve_after_edit = st.checkbox(
                "Approve this invoice after saving the corrections",
                key=f"edit-approve-{invoice_id}",
            )
            if st.form_submit_button("💾 Save corrections", type="primary"):
                changed = {
                    key: value
                    for key, value in updates.items()
                    if value != fields.get(key)
                }
                if not changed:
                    st.info("No field values were changed.")
                else:
                    result = api_request(
                        "PATCH",
                        f"/invoices/{invoice_id}/fields",
                        json={
                            "fields": changed,
                            "note": edit_note.strip() or None,
                            "reviewer": st.session_state.get("reviewer_name", "human-reviewer").strip() or "human-reviewer",
                            "approve": approve_after_edit,
                        },
                    )
                    if result:
                        st.session_state["review_flash"] = (
                            f"Updated {len(result.get('changes', {}))} field(s) "
                            f"on {detail['filename']}."
                        )
                        st.session_state["invoice_rows"] = None
                        st.rerun()


def show_review_queue() -> None:
    st.title("🔎 Review Queue")
    st.caption(
        "Click any row to open the document, then approve, edit or reject it. "
        "Every decision is written to the audit log and to the assistant's knowledge base."
    )

    invoices = get_invoices()
    if not invoices:
        st.info("No invoices registered yet. Upload an invoice to get started.")
        return

    flash = st.session_state.pop("review_flash", None)
    if flash:
        st.success(flash)

    header = st.columns([3, 1])
    with header[0]:
        filter_name = st.radio(
            "Filter",
            list(REVIEW_FILTERS),
            horizontal=True,
            key="review-filter-v2",
        )
    with header[1]:
        st.write("")
        if st.button("🔄 Refresh queue", use_container_width=True):
            get_invoices(refresh=True)
            st.rerun()

    queue = [invoice for invoice in invoices if REVIEW_FILTERS[filter_name](invoice)]
    if not queue:
        st.success(f"No invoices match the '{filter_name}' filter.")
        return

    metrics = st.columns(4)
    metrics[0].metric("In this view", len(queue))
    metrics[1].metric(
        "Awaiting decision",
        sum(1 for invoice in invoices if effective_decision(invoice) is None),
    )
    metrics[2].metric(
        "Approved",
        sum(1 for invoice in invoices if effective_decision(invoice) == "approve"),
    )
    metrics[3].metric(
        "Rejected",
        sum(1 for invoice in invoices if effective_decision(invoice) == "reject"),
    )
    st.caption(
        f"Showing {len(queue)} of {len(invoices)} invoice(s); decision counts cover all invoices."
    )

    table_rows = [
        {
            "Document": invoice["filename"],
            "Invoice number": invoice.get("invoice_number") or "—",
            "Vendor": invoice.get("vendor") or "—",
            "Amount": invoice.get("amount"),
            "Currency": invoice.get("currency") or "—",
            "Progress": int(invoice.get("progress") or 0),
            "Stage": invoice.get("current_stage") or invoice["status"].replace("_", " ").title(),
            "Status": invoice["status"].replace("_", " ").title(),
            "Findings": invoice.get("finding_count", 0),
            "Recommendation": (
                invoice.get("audit_verdict") or invoice.get("recommendation") or "pending"
            ).replace("_", " ").title(),
            "Human decision": (
                review_decision(invoice).title() if review_decision(invoice)
                else "Auto-rejected (ERP)" if invoice.get("audit_verdict") == "reject"
                else "Awaiting"
            ),
            "Reason": (
                invoice.get("error_message")
                or ("Conflicts with the ERP record" if invoice.get("audit_verdict") == "reject" else None)
                or ("Needs a reviewer" if invoice.get("audit_verdict") == "manual_review" else None)
                or "No issues found"
            ),
        }
        for invoice in queue
    ]

    selection = st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"review-queue-table-{filter_name}",
        column_config={
            "Progress": st.column_config.ProgressColumn(
                "Pipeline progress",
                help="Share of processing stages completed for this document",
                min_value=0,
                max_value=100,
                format="%d%%",
            ),
            "Amount": st.column_config.NumberColumn("Amount", format="%.2f"),
        },
    )

    selected_rows = selection.selection.rows if hasattr(selection, "selection") else []
    if selected_rows and 0 <= selected_rows[0] < len(queue):
        st.session_state["review_selected_id"] = queue[selected_rows[0]]["id"]

    selected_id = st.session_state.get("review_selected_id")
    if selected_id not in {invoice["id"] for invoice in queue}:
        selected_id = None

    if not selected_id:
        st.info("👆 Click a row in the table to open that document and take a decision.")
        return

    detail = api_request("GET", f"/invoices/{selected_id}")
    if not detail:
        return

    st.divider()
    st.subheader(f"📄 {detail['filename']}")
    st.caption(
        f"Invoice id {detail['id']} · status {detail['status']} · "
        f"pipeline {detail.get('progress', 0)}% ({detail.get('current_stage', '—')})"
    )
    st.progress(min(100, int(detail.get("progress") or 0)) / 100)

    document_column, review_column = st.columns([3, 2], gap="large")
    with document_column:
        render_document(detail)
    with review_column:
        findings = detail.get("findings") or []
        if findings:
            st.warning(f"{len(findings)} validation finding(s) require attention.")
            for finding in findings:
                st.markdown(f"- **[{finding['severity']}] {finding['category']}** — {finding['message']}")
        else:
            st.success("No validation findings were recorded.")
        render_review_actions(detail)

    with st.expander("Full invoice detail, evidence and activity", expanded=False):
        render_detail(detail)


# --------------------------------------------------

# Audit Logs

# --------------------------------------------------


 

def show_audit_logs() -> None:

    st.title("📋 Audit Logs")

    st.caption(

        "Timestamped upload, extraction, translation, validation, "

        "indexing, and review activity."

    )


 

    invoices = get_invoices()


 

    selection = st.selectbox(

        "Filter by invoice",

        ["All invoices"] + [invoice["id"] for invoice in invoices],

        format_func=lambda value: (

            "All invoices"

            if value == "All invoices"

            else next(

                invoice_label(row)

                for row in invoices

                if row["id"] == value

            )

        ),

        key="audit-invoice-filter",

    )


 

    params: dict[str, Any] = {"limit": 500}


 

    if selection != "All invoices":

        params["invoice_id"] = selection


 

    events = api_request(

        "GET",

        "/audit-logs",

        params=params,

    )


 

    if events:

        st.dataframe(

            [

                {

                    "Timestamp": event["created_at"],

                    "Invoice": event["filename"],

                    "Invoice ID": event["invoice_id"],

                    "Event": event["stage"].replace("_", " ").title(),

                    "Status": event["level"],

                    "Details": event["message"],

                }

                for event in events

            ],

            use_container_width=True,

            hide_index=True,

        )


 

    elif events is not None:

        st.info("No audit events match this filter.")



 

# --------------------------------------------------

# Sidebar Navigation

# --------------------------------------------------


 

with st.sidebar:

    st.title("🧾 Invoice Auditor")

    st.caption("Invoice processing and evidence review")

    st.divider()


 

    selected_page = st.radio(

        "Workspace",

        NAVIGATION,

        label_visibility="collapsed",

    )



 

# --------------------------------------------------

# Page Routing

# --------------------------------------------------


 

if selected_page == "Dashboard":

    show_dashboard()


 

elif selected_page == "Upload Invoice":

    show_upload()


 

elif selected_page == "Invoices":

    show_invoices()


 

elif selected_page == "Invoice Assistant (Chat)":

    show_questions()


 

elif selected_page == "Review Queue":

    show_review_queue()


 

else:

    show_audit_logs()


 