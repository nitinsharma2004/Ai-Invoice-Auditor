from __future__ import annotations


 

import re

from datetime import datetime

from functools import lru_cache

from typing import Any


 

import yaml


 

from pydantic import BaseModel, ConfigDict, Field, field_validator


 

from backend.app.settings import RULES_PATH



 

def _coerce_optional_number(value: Any) -> Any:

    """Models sometimes answer with "null", "N/A" or a formatted amount such as "1.234,00 EUR"."""

    if not isinstance(value, str):

        return value

    cleaned = value.strip()

    if cleaned.lower() in {"", "null", "none", "n/a", "na", "-", "--", "unknown", "not found"}:

        return None

    cleaned = re.sub(r"[^\d,.\-]", "", cleaned)

    if not cleaned:

        return None

    if "," in cleaned and "." in cleaned:

        cleaned = cleaned.replace(",", "") if cleaned.rfind(".") > cleaned.rfind(",") else cleaned.replace(".", "").replace(",", ".")

    elif cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) in {1, 2}:

        cleaned = cleaned.replace(",", ".")

    else:

        cleaned = cleaned.replace(",", "")

    return cleaned or None



 

def _coerce_optional_text(value: Any) -> Any:

    if isinstance(value, str) and value.strip().lower() in {"null", "none", "n/a", "na", "not found", "unknown"}:

        return None

    return value



 

@lru_cache(maxsize=1)

def _currency_aliases() -> dict[str, str]:

    """Symbol/alias -> ISO code, driven by currency_symbol_map in rules.yml."""

    aliases = {"US$": "USD", "RS": "INR", "RS.": "INR", "INR.": "INR", "EURO": "EUR", "EUROS": "EUR"}

    try:

        rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}

    except (OSError, yaml.YAMLError):

        return aliases

    for symbol, code in (rules.get("currency_symbol_map") or {}).items():

        aliases[str(symbol).strip().upper()] = str(code).strip().upper()

    return aliases



 

def _normalise_currency(value: Any) -> Any:

    """Map currency symbols to ISO codes so '€' and 'EUR' are never treated as different."""

    value = _coerce_optional_text(value)

    if not isinstance(value, str):

        return value

    cleaned = value.strip()

    if not cleaned:

        return None

    aliases = _currency_aliases()

    key = cleaned.upper()

    if key in aliases:

        return aliases[key]

    for symbol, code in aliases.items():

        if symbol and symbol in cleaned:

            return code

    return key if len(key) == 3 and key.isalpha() else cleaned



 

class LineItem(BaseModel):

    item_code: str | None = None

    description: str | None = None

    qty: float | None = None

    unit_price: float | None = None

    total: float | None = None


 

    _clean_numbers = field_validator("qty", "unit_price", "total", mode="before")(_coerce_optional_number)

    _clean_text = field_validator("item_code", "description", mode="before")(_coerce_optional_text)



 

class InvoiceFields(BaseModel):

    invoice_no: str | None = None

    invoice_date: str | None = None

    po_number: str | None = None

    vendor_id: str | None = None

    vendor_name: str | None = None

    currency: str | None = None

    total_amount: float | None = None

    tax_amount: float | None = None

    subtotal: float | None = None

    line_items: list[LineItem] = Field(default_factory=list)

    detected_language: str | None = None

    additional_fields: dict[str, Any] | None = None


 

    _clean_numbers = field_validator("total_amount", "tax_amount", "subtotal", mode="before")(_coerce_optional_number)

    _clean_text = field_validator(

        "invoice_no", "invoice_date", "po_number", "vendor_id", "vendor_name",

        "detected_language", mode="before",

    )(_coerce_optional_text)

    _clean_currency = field_validator("currency", mode="before")(_normalise_currency)



 

class InvoiceSummary(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: str

    filename: str

    content_type: str

    status: str

    error_message: str | None

    created_at: datetime

    updated_at: datetime

    invoice_number: str | None = None

    vendor: str | None = None

    invoice_date: str | None = None

    amount: float | None = None

    currency: str | None = None

    recommendation: str | None

    audit_verdict: str | None = None

    finding_count: int = 0

    review_status: str | None = None

    review_note: str | None = None

    reviewed_at: datetime | None = None

    reviewer: str | None = None

    progress: int = 0

    current_stage: str | None = None



 

class UploadItemResult(BaseModel):

    invoice_id: str | None = None

    filename: str

    status: str

    detail: str | None = None



 

class QueryRequest(BaseModel):

    question: str = Field(min_length=3, max_length=2000)

    invoice_id: str | None = None


 

class ChatRequest(BaseModel):

    question: str = Field(min_length=1, max_length=4000)

    session_id: str = Field(default="default", min_length=1, max_length=120)

    invoice_id: str | None = None


class ChatMessage(BaseModel):

    role: str

    content: str

    created_at: str | None = None


class ReviewDecisionRequest(BaseModel):

    decision: str = Field(pattern="^(approve|reject)$")

    note: str | None = Field(default=None, max_length=2000)

    reviewer: str = Field(default="human-reviewer", max_length=120)


class InvoiceFieldUpdateRequest(BaseModel):

    fields: dict[str, Any] = Field(default_factory=dict)

    note: str | None = Field(default=None, max_length=2000)

    reviewer: str = Field(default="human-reviewer", max_length=120)

    approve: bool = False


 

class FolderProcessRequest(BaseModel):

    """Select which monitored-folder documents to push through the audit workflow."""

    filenames: list[str] | None = None

    reprocess: bool = False
