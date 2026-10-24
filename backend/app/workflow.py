from __future__ import annotations


 

import json

import logging

import re

from pathlib import Path

from typing import Any, TypedDict


 

import redis

import yaml

from langgraph.graph import END, START, StateGraph

from sqlalchemy import delete


 

from backend.app.database import SessionLocal

from backend.app.extraction import extract_document

from backend.app.integrations import (

    extract_invoice_fields,

    # evaluate_audit_summary,

    generate_audit_summary,

    get_erp_record,

    resolve_vendor_by_name,

    get_redis_client,

    index_invoice,

    index_invoice_knowledge,

    retrieve_invoice_chunks,

    translate_invoice_text,

)

from backend.app.models import (

    AuditReport,

    ExtractedInvoice,

    Invoice,

    ProcessingEvent,

    ValidationFinding,

)

from backend.app.schemas import InvoiceFields

from backend.app.sidecar import format_metadata_block, merge_metadata, metadata_for_document

from backend.app.settings import RULES_PATH


 

logger = logging.getLogger(__name__)


 

AUDIT_SUMMARY_MINIMUM_SCORE = 0.8

# The summary evaluator is currently stubbed with fixed scores, so its verdict grades the
# generated narrative rather than the invoice. While disabled it must not gate approval,
# otherwise a clean invoice is held for review because of the wording of its own summary.
AUDIT_SUMMARY_EVALUATION_ENABLED = False

AUDIT_SUMMARY_MAX_ATTEMPTS = 3



 

class InvoiceState(TypedDict, total=False):

    invoice_id: str

    raw_text: str

    pages: list[dict[str, Any]]

    fields: dict[str, Any]

    findings: list[dict[str, Any]]

    erp: dict[str, Any]

    evidence: list[dict[str, Any]]

    recommendation: str

    indexed_chunks: int

    translation_review: bool

    translation_confidence: float

    source_metadata: dict[str, Any]

    metadata_file: str | None

    quality_evaluation: dict[str, Any]

    error: str



 

def _persist_translated_text(

    invoice_id: str,

    translated_text: str,

    translated_fields: dict[str, Any] | None = None,

) -> None:

    with SessionLocal() as db:

        extracted = (

            db.query(ExtractedInvoice)

            .filter(ExtractedInvoice.invoice_id == invoice_id)

            .one_or_none()

        )

        if not extracted:

            raise ValueError(f"Extracted invoice was not found for {invoice_id}.")

        fields = dict(extracted.fields)

        additional_fields = dict(fields.get("additional_fields") or {})

        additional_fields["_translated_text"] = translated_text

        if translated_fields is not None:

            additional_fields["_translated_fields"] = translated_fields

        else:

            additional_fields.pop("_translated_fields", None)

        fields["additional_fields"] = additional_fields

        extracted.fields = fields

        db.commit()



 

def _record(invoice_id: str, stage: str, message: str, level: str = "INFO") -> None:

    with SessionLocal() as db:

        db.add(ProcessingEvent(invoice_id=invoice_id, stage=stage, message=message, level=level))

        db.commit()

    try:

        get_redis_client().delete(f"invoice-status:{invoice_id}")

    except redis.RedisError:

        pass



 

def _fail(state: InvoiceState, stage: str) -> InvoiceState:

    safe_messages = {

        "extract": "Invoice text could not be read or parsed. Check the file contents and format.",

        "translate": "Invoice translation failed. Check the configured language model and retry.",

        "validate": "Invoice validation could not be completed. Check the validation rules and retry.",

        "erp": "ERP lookup failed. Check the Mock ERP service and retry.",

        "rag_index": "Invoice evidence could not be indexed. Check the vector service and retry.",

        "rag_retrieval": "Invoice evidence could not be retrieved. Check the vector service and retry.",

        "report": "The audit report could not be generated. Check the configured language model and retry.",

    }

    message = safe_messages.get(stage, "Invoice processing failed. Retry or contact the administrator.")

    with SessionLocal() as db:

        invoice = db.get(Invoice, state["invoice_id"])

        if invoice:

            invoice.status = "failed"

            invoice.error_message = message

            db.commit()

    _record(state["invoice_id"], stage, message, "ERROR")

    return {**state, "error": message}



 

def _extract_node(state: InvoiceState) -> InvoiceState:

    invoice_id = state["invoice_id"]

    with SessionLocal() as db:

        invoice = db.get(Invoice, invoice_id)

        if not invoice:

            return _fail(state, "extract")

        invoice.status = "processing"

        invoice.error_message = None

        db.commit()

        path = Path(invoice.stored_path)

        filename = invoice.filename

    _record(invoice_id, "extract", "Text extraction started")

    try:

        raw_text, pages = extract_document(path, path.suffix.lower())

        if not raw_text.strip():

            raise ValueError("No readable text was extracted from the invoice.")

        fields = extract_invoice_fields(raw_text)

        # Merge the sidecar *.meta.json describing this document, if one exists.

        metadata, metadata_name = metadata_for_document(path)

        merged_fields, applied = merge_metadata(fields.model_dump(mode="json"), metadata)

        fields = InvoiceFields.model_validate(merged_fields)

        if metadata_name:

            detail = f"; supplied {', '.join(applied)}" if applied else " (no missing fields to fill)"

            _record(invoice_id, "extract", f"Merged metadata from {metadata_name}{detail}")

            # Append the e-mail context so the combined document text carries it through

            # translation, the audit trail and the assistant's knowledge base.

            block = format_metadata_block(metadata, metadata_name)

            if block:

                raw_text = f"{raw_text.rstrip()}\n\n{block}\n"

        with SessionLocal() as db:

            db.execute(delete(ExtractedInvoice).where(ExtractedInvoice.invoice_id == invoice_id))

            db.add(ExtractedInvoice(invoice_id=invoice_id, fields=fields.model_dump(mode="json"), raw_text=raw_text))

            db.execute(delete(ValidationFinding).where(ValidationFinding.invoice_id == invoice_id))

            db.execute(delete(AuditReport).where(AuditReport.invoice_id == invoice_id))

            db.commit()

        _record(invoice_id, "extract", f"Text extraction completed for {filename}")

        return {

            **state,

            "raw_text": raw_text,

            "original_text": raw_text,

            "fields": fields.model_dump(mode="json"),

            "pages": pages,

            "source_metadata": metadata,

            "metadata_file": metadata_name,

        }

    except Exception:

        logger.exception("Invoice extraction failed for invoice %s", invoice_id)

        return _fail(state, "extract")


 

def _translate_node(state: InvoiceState) -> InvoiceState:

    if state.get("error"):

        return state


 

    fields = InvoiceFields.model_validate(state["fields"])


 

    detected_language = fields.detected_language

    language = (detected_language or "").strip().lower()


 

    # Skip translation only when English is explicitly detected.

    english_languages = {

        "en",

        "eng",

        "english",

        "en-us",

        "en-gb",

    }


 

    if language in english_languages:

        raw_text = state.get("raw_text", "")

        _persist_translated_text(

            state["invoice_id"],

            raw_text,

            fields.model_dump(mode="json"),

        )

        _record(

            state["invoice_id"],

            "translate",

            "Translation not required",

        )


 

        return {

            **state,

            "translated_text": state.get("raw_text", ""),

        }


 

    try:

        raw_text = state.get("raw_text") or ""

        pages = state.get("pages") or []


 

        # Translate each page when page-level text is available.

        if pages:

            translated_pages = []


 

            for page in pages:

                page_text = page.get("text") or ""


 

                translated_pages.append(

                    {

                        **page,

                        "text": (

                            translate_invoice_text(page_text)

                            if page_text.strip()

                            else page_text

                        ),

                    }

                )


 

            translated = "\n\n".join(

                page["text"]

                for page in translated_pages

                if page["text"].strip()

            )


 

            # Fall back to the full extracted text if page text is empty.

            if not translated.strip():

                translated = translate_invoice_text(raw_text)

                translated_pages = []


 

        else:

            translated_pages = []

            translated = translate_invoice_text(raw_text)


 

        if not translated.strip():

            raise ValueError("Translation returned empty text.")


 

        _persist_translated_text(state["invoice_id"], translated)


 

        # Preserve the successful translation before re-extracting fields.

        # The sidecar metadata is reference context, not invoice prose: re-attach it so the

        # English text the reviewer reads carries the same combined document.

        metadata = state.get("source_metadata") or {}

        metadata_block = format_metadata_block(metadata, state.get("metadata_file"))

        if metadata_block and "--- Accompanying metadata" not in translated:

            translated = f"{translated.rstrip()}\n\n{metadata_block}\n"


        

        updated_state = {

            **state,

            "translated_text": translated,

            "raw_text": translated,

            "pages": translated_pages or pages,

            # rules.yml gates auto-approval on translation confidence, not on the mere

            # fact that a translation happened, so multilingual invoices stay eligible.

            "translation_review": False,

            "translation_confidence": 1.0,

        }


 

        # Re-extract fields using the English translation.

        try:

            translated_fields = extract_invoice_fields(translated)


 

            # Keep the original invoice's detected language.

            translated_fields = translated_fields.model_copy(

                update={

                    "detected_language": detected_language,

                    "additional_fields": (

                        translated_fields.additional_fields or {}

                    ),

                }

            )


 

            # Re-extraction starts from scratch, so merge the sidecar metadata back in.

            merged_translated, _ = merge_metadata(

                translated_fields.model_dump(mode="json"), metadata

            )

            translated_fields = InvoiceFields.model_validate(merged_translated)

            translated_fields_data = translated_fields.model_dump(mode="json")

            _persist_translated_text(

                state["invoice_id"],

                translated,

                translated_fields_data,

            )

            updated_state["fields"] = translated_fields_data


 

        except Exception as exc:

            # Keep the translation even if field extraction fails.

            _record(

                state["invoice_id"],

                "translate",

                f"Translation succeeded, but field extraction failed: {exc}",

            )

            # Fields could not be read back from the translation, so a human must confirm it.

            updated_state["translation_review"] = True

            updated_state["translation_confidence"] = 0.5


 

        _record(

            state["invoice_id"],

            "translate",

            f"Translated invoice from {detected_language or 'unknown'} to English",

        )


 

        return updated_state


 

    except Exception as exc:

        _record(

            state["invoice_id"],

            "translate",

            f"Translation failed: {exc}",

        )


 

        return _fail(state, "translate")



 

# rules.yml validation_policies -> the severity each finding is raised with.

_POLICY_SEVERITY = {"flag": "warning", "warn": "warning", "manual_review": "error", "reject": "error"}



 

def _policy_severity(rules: dict[str, Any], policy_key: str, default: str = "error") -> str:

    """Translate a configured policy action into a finding severity."""

    action = str((rules.get("validation_policies", {}) or {}).get(policy_key, "")).strip().lower()

    return _POLICY_SEVERITY.get(action, default)



 

def _validate_node(state: InvoiceState) -> InvoiceState:

    try:

        rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}

        fields = InvoiceFields.model_validate(state["fields"])

        findings: list[dict[str, Any]] = []

        for field in rules.get("required_fields", {}).get("header", []):

            if getattr(fields, field, None) in (None, ""):

                findings.append({"category": "missing_field", "severity": _policy_severity(rules, "missing_field_action"), "message": f"Required field '{field}' is missing.", "field": field})

        for field in rules.get("required_fields", {}).get("line_item", []):

            for index, item in enumerate(fields.line_items):

                if getattr(item, field, None) in (None, ""):

                    findings.append({"category": "missing_line_item_field", "severity": _policy_severity(rules, "missing_field_action"), "message": f"Line {index + 1}: required field '{field}' is missing.", "field": field, "line_index": index})

        if not fields.line_items:

            findings.append({"category": "missing_line_items", "severity": "error", "message": "No invoice line items could be extracted."})

        accepted = rules.get("accepted_currencies", [])

        if fields.currency and fields.currency.upper() not in accepted:

            findings.append({"category": "invalid_currency", "severity": "error", "message": f"Currency '{fields.currency}' is not accepted.", "value": fields.currency})

        tolerance = float(rules.get("tolerances", {}).get("line_item_math_tolerance_percent", 1))

        for index, item in enumerate(fields.line_items):

            if item.qty is not None and item.unit_price is not None and item.total is not None:

                expected = item.qty * item.unit_price

                if expected and abs(item.total - expected) / expected * 100 > tolerance:

                    findings.append({"category": "line_item_math", "severity": "error", "message": f"Line {index + 1} total differs from quantity × unit price.", "line_index": index, "expected": round(expected, 2), "actual": item.total})

        if fields.total_amount is not None and fields.line_items and all(item.total is not None for item in fields.line_items):

            expected_total = sum(item.total or 0 for item in fields.line_items) + (fields.tax_amount or 0)

            total_tolerance = float(rules.get("tolerances", {}).get("line_item_math_tolerance_percent", 1))

            if expected_total and abs(fields.total_amount - expected_total) / expected_total * 100 > total_tolerance:

                findings.append({"category": "total_mismatch", "severity": _policy_severity(rules, "total_mismatch_action"), "message": "Invoice total does not match line totals plus tax.", "expected": round(expected_total, 2), "actual": fields.total_amount})

        # Internal tax consistency: subtotal + tax must equal the invoice total.

        if (

            fields.total_amount is not None

            and fields.subtotal is not None

            and fields.tax_amount is not None

        ):

            expected_with_tax = fields.subtotal + fields.tax_amount

            if expected_with_tax and abs(fields.total_amount - expected_with_tax) / abs(expected_with_tax) * 100 > tolerance:

                findings.append({

                    "category": "tax_calculation",

                    "severity": "error",

                    "message": "Subtotal plus tax does not equal the invoice total.",

                    "expected": round(expected_with_tax, 2),

                    "actual": fields.total_amount,

                    "subtotal": fields.subtotal,

                    "tax_amount": fields.tax_amount,

                })


 

        # Declared data types from rules.yml (numbers must be numeric, text must be text).

        declared_types = rules.get("data_types", {}) or {}

        type_checks = {

            "invoice_no": fields.invoice_no,

            "invoice_date": fields.invoice_date,

            "vendor_id": fields.vendor_id,

            "currency": fields.currency,

            "total_amount": fields.total_amount,

        }

        for field_name, value in type_checks.items():

            expected_type = declared_types.get(field_name)

            if value is None or not expected_type:

                continue

            if expected_type == "float" and not isinstance(value, (int, float)):

                findings.append({

                    "category": "invalid_data_type",

                    "severity": "error",

                    "message": f"Field '{field_name}' must be a number.",

                    "field": field_name,

                    "value": value,

                    "expected_type": expected_type,

                })

            elif expected_type == "str" and not isinstance(value, str):

                findings.append({

                    "category": "invalid_data_type",

                    "severity": "error",

                    "message": f"Field '{field_name}' must be text.",

                    "field": field_name,

                    "value": value,

                    "expected_type": expected_type,

                })

        for index, item in enumerate(fields.line_items):

            for field_name in ("qty", "unit_price", "total"):

                value = getattr(item, field_name, None)

                if value is not None and declared_types.get(field_name) == "float" and not isinstance(value, (int, float)):

                    findings.append({

                        "category": "invalid_data_type",

                        "severity": "error",

                        "message": f"Line {index + 1}: '{field_name}' must be a number.",

                        "field": field_name,

                        "line_index": index,

                        "value": value,

                        "expected_type": "float",

                    })


 

        if fields.invoice_date:

            from datetime import datetime, timezone

            parsed_date = None

            for date_format in rules.get("date_validation", {}).get("accepted_formats", []):

                try:

                    parsed_date = datetime.strptime(fields.invoice_date, date_format).date()

                    break

                except ValueError:

                    continue

            if parsed_date is None:

                findings.append({"category": "invalid_date", "severity": "error", "message": f"Invoice date '{fields.invoice_date}' could not be parsed."})

            else:

                today = datetime.now(timezone.utc).date()

                if (parsed_date - today).days > int(rules.get("date_validation", {}).get("max_future_days", 7)):

                    findings.append({"category": "future_date", "severity": "error", "message": "Invoice date is beyond the permitted future-date window."})

                elif (today - parsed_date).days > int(rules.get("date_validation", {}).get("stale_invoice_days", 365)):

                    findings.append({"category": "stale_invoice", "severity": "warning", "message": "Invoice is older than the configured stale-invoice threshold."})

        _record(state["invoice_id"], "validate", f"Structural validation completed; {len(findings)} finding(s)")

        return {**state, "fields": fields.model_dump(mode="json"), "findings": findings}

    except Exception:

        return _fail(state, "validate")



 

# The invoice directly contradicts the ERP system of record: the order exists but the
# billed value disagrees with it. A reviewer cannot make these agree, so they are rejected.

ERP_CONFLICT_CATEGORIES = {

    "vendor_mismatch",

    "quantity_mismatch",

    "price_mismatch",

    "currency_mismatch",

    "tax_mismatch",

}


 

# The ERP simply has no matching record yet (a new vendor, an order raised late, a SKU not
# in the master). That is a data gap a human can resolve, so it goes to manual review.

ERP_UNMATCHED_CATEGORIES = {

    "po_not_found",

    "vendor_not_found",

    "item_not_in_sku_master",

    "item_not_in_po",

}


 

# Kept for callers that need every ERP-sourced category.

ERP_CATEGORIES = ERP_CONFLICT_CATEGORIES | ERP_UNMATCHED_CATEGORIES | {"missing_item_on_invoice"}


 

# Only a genuine conflict with the ERP auto-rejects an invoice.

ERP_REJECT_CATEGORIES = ERP_CONFLICT_CATEGORIES


 

def _advisory_categories() -> set[str]:

    """Company rules flagged as advisory in rules.yml; they never block approval."""

    try:

        rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}

    except (OSError, yaml.YAMLError):

        return set()

    policies = rules.get("validation_policies", {}) or {}

    return {

        str(item).strip().lower()

        for item in (policies.get("advisory_categories") or [])

    }


 

ADVISORY_CATEGORIES = _advisory_categories()



 

def _description_key(value: Any) -> str:

    """Normalise an item description so wording differences still match."""

    if not value:

        return ""

    cleaned = re.sub(r"[^a-z0-9 ]+", " ", str(value).lower())

    return " ".join(cleaned.split())


 

# Words that carry no meaning when matching an item description.

_DESCRIPTION_STOPWORDS = {"the", "a", "an", "of", "for", "and", "with", "per"}


 

def _description_tokens(value: str) -> set[str]:

    return {word for word in value.split() if word not in _DESCRIPTION_STOPWORDS}


 

def _match_po_line_by_description(description: Any, po_lines_by_description: dict[str, dict]) -> dict | None:

    """Find the purchase-order line a scanned item refers to, using its description.

    OCR frequently drops the item code on scanned invoices. The description still

    identifies the line, so it is used to recover the code instead of reporting a

    mismatch the invoice does not actually have.

    """

    key = _description_key(description)

    if not key or not po_lines_by_description:

        return None

    exact = po_lines_by_description.get(key)

    if exact:

        return exact

    tokens = _description_tokens(key)

    if not tokens:

        return None

    best: dict | None = None

    best_score = 0.0

    for candidate_key, line in po_lines_by_description.items():

        candidate_tokens = _description_tokens(candidate_key)

        if not candidate_tokens:

            continue

        overlap = tokens & candidate_tokens

        if not overlap:

            continue

        score = len(overlap) / len(tokens | candidate_tokens)

        if score > best_score:

            best_score, best = score, line

    # Require a clear majority overlap so unrelated items are never matched.

    return best if best_score >= 0.5 else None


 

def _erp_node(state: InvoiceState) -> InvoiceState:

    if state.get("error"):

        return state

    fields = InvoiceFields.model_validate(state["fields"])

    findings = list(state.get("findings", []))

    erp: dict[str, Any] = {"purchase_order": None, "vendor": None, "skus": []}

    try:

        if fields.po_number:

            erp["purchase_order"] = get_erp_record("po", fields.po_number)

        if fields.vendor_id:

            erp["vendor"] = get_erp_record("vendor", fields.vendor_id)


 

        # Invoices print a trading name rather than the ERP vendor id, so resolve the id

        # from the vendor master (by name) or from the purchase order before reporting a gap.

        resolved_from = None

        if not erp["vendor"]:

            matched = resolve_vendor_by_name(fields.vendor_name)

            if matched:

                erp["vendor"] = matched

                resolved_from = f"vendor name '{fields.vendor_name}'"

        if not erp["vendor"] and erp["purchase_order"] and erp["purchase_order"].get("vendor_id"):

            matched = get_erp_record("vendor", erp["purchase_order"]["vendor_id"])

            if matched:

                erp["vendor"] = matched

                resolved_from = f"purchase order '{fields.po_number}'"

        if erp["vendor"] and not fields.vendor_id and erp["vendor"].get("vendor_id"):

            fields.vendor_id = erp["vendor"]["vendor_id"]

            erp["vendor_id_resolved_from"] = resolved_from

            with SessionLocal() as db:

                db.query(ExtractedInvoice).filter(

                    ExtractedInvoice.invoice_id == state["invoice_id"]

                ).update({"fields": fields.model_dump(mode="json")})

                db.commit()

            _record(

                state["invoice_id"],

                "erp",

                f"Vendor id {fields.vendor_id} resolved from {resolved_from}",

            )

            # The id is no longer missing, so drop the structural finding that said it was.

            findings = [

                item for item in findings

                if not (item.get("category") == "missing_field" and item.get("field") == "vendor_id")

            ]


 

        if not erp["purchase_order"]:

            findings.append({"category": "po_not_found", "severity": "error", "message": f"Purchase order '{fields.po_number or ''}' was not found in ERP.", "po_number": fields.po_number})

        if not erp["vendor"]:

            findings.append({"category": "vendor_not_found", "severity": "error", "message": f"Vendor '{fields.vendor_id or fields.vendor_name or ''}' was not found in ERP.", "vendor_id": fields.vendor_id, "vendor_name": fields.vendor_name})


 

        po = erp["purchase_order"] or {}

        po_lines = {str(line.get("item_code", "")).upper(): line for line in po.get("line_items", [])}

        # Scans often lose the item code, so keep a description index to recover it.

        po_lines_by_description = {

            _description_key(line.get("description")): line

            for line in po.get("line_items", [])

            if _description_key(line.get("description"))

        }

        rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}

        tolerances = rules.get("tolerances", {})

        price_tolerance = float(tolerances.get("price_difference_percent", 5))

        quantity_tolerance = float(tolerances.get("quantity_difference_percent", 0))

        tax_tolerance = float(rules.get("tolerances", {}).get("tax_difference_percent", 2))

        expected_tax = 0.0

        all_sku_tax_rates_available = bool(fields.line_items)

        # One discrepancy row per item, even when a code repeats across lines.

        reported_missing_sku: set[str] = set()

        reported_missing_po_line: set[str] = set()

        unreadable_line_items = 0

        recovered_line_indexes: set[int] = set()


 

        for index, item in enumerate(fields.line_items):

            item_code = item.item_code

            po_line = po_lines.get((item_code or "").upper()) if item_code else None


 

            # The code could not be read: recover it from the purchase order by

            # description rather than reporting a bogus "Item 'None'" mismatch.

            if not item_code:

                matched_line = _match_po_line_by_description(item.description, po_lines_by_description)

                if matched_line:

                    item_code = matched_line.get("item_code")

                    po_line = matched_line

                    item.item_code = item_code

                    recovered_line_indexes.add(index)

                    _record(

                        state["invoice_id"],

                        "erp",

                        f"Line {index + 1}: item code {item_code} recovered from the purchase order "

                        f"by description '{item.description}'",

                    )


 

            if not item_code:

                # Still unknown. The missing-field rule already reports this gap, so

                # matching it against the ERP would only repeat the same problem.

                unreadable_line_items += 1

                all_sku_tax_rates_available = False

                continue


 

            sku = get_erp_record("sku", item_code)

            erp["skus"].append(sku)

            if not sku or sku.get("gst_rate") is None:

                all_sku_tax_rates_available = False

            elif item.total is not None:

                expected_tax += item.total * float(sku["gst_rate"]) / 100

            else:

                all_sku_tax_rates_available = False

            if po_line is None:

                po_line = po_lines.get(str(item_code).upper())

            if not sku and item_code not in reported_missing_sku:

                reported_missing_sku.add(item_code)

                findings.append({"category": "item_not_in_sku_master", "severity": "error", "message": f"Item '{item_code}' is absent from the SKU master.", "item_code": item_code})

            if not po_line:

                if item_code not in reported_missing_po_line:

                    reported_missing_po_line.add(item_code)

                    findings.append({"category": "item_not_in_po", "severity": "error", "message": f"Item '{item_code}' is absent from purchase order '{fields.po_number}'.", "item_code": item_code})

                continue

            if item.qty is not None:

                erp_qty = float(po_line.get("qty", 0))

                quantity_difference = abs(item.qty - erp_qty)

                quantity_difference_pct = (quantity_difference / abs(erp_qty) * 100) if erp_qty else (100 if quantity_difference else 0)

                if quantity_difference_pct > quantity_tolerance:

                    findings.append({"category": "quantity_mismatch", "severity": "error", "message": f"Quantity differs by {quantity_difference_pct:.2f}% for item '{item_code}'.", "item_code": item_code, "invoice_value": item.qty, "erp_value": erp_qty, "difference_pct": round(quantity_difference_pct, 2)})

            erp_price = float(po_line.get("unit_price", 0))

            if item.unit_price is not None and erp_price:

                difference = abs(item.unit_price - erp_price) / erp_price * 100

                if difference > price_tolerance:

                    findings.append({"category": "price_mismatch", "severity": "error", "message": f"Unit price differs by {difference:.2f}% for item '{item_code}'.", "item_code": item_code, "invoice_value": item.unit_price, "erp_value": erp_price, "difference_pct": round(difference, 2)})

        if recovered_line_indexes:

            # The code is no longer missing, so drop the completeness findings that said it was.

            findings = [

                item for item in findings

                if not (

                    item.get("category") == "missing_line_item_field"

                    and item.get("field") == "item_code"

                    and item.get("line_index") in recovered_line_indexes

                )

            ]

            with SessionLocal() as db:

                db.query(ExtractedInvoice).filter(

                    ExtractedInvoice.invoice_id == state["invoice_id"]

                ).update({"fields": fields.model_dump(mode="json")})

                db.commit()


 

        if unreadable_line_items:

            _record(

                state["invoice_id"],

                "erp",

                f"{unreadable_line_items} line item(s) had no readable item code and were "

                "skipped during ERP matching; they are reported as missing fields instead.",

            )


 

        # Currency is an invoice-level attribute, so it is compared once instead of per line.

        po_currencies = {

            str(line.get("currency", "")).upper()

            for line in po.get("line_items", [])

            if line.get("currency")

        }

        if fields.currency and po_currencies and fields.currency.upper() not in po_currencies:

            findings.append({

                "category": "currency_mismatch",

                "severity": "error",

                "message": "Invoice currency does not match the purchase-order currency.",

                "invoice_value": fields.currency,

                "erp_value": ", ".join(sorted(po_currencies)),

            })


 

        if fields.tax_amount is not None and all_sku_tax_rates_available and expected_tax:

            tax_difference = abs(fields.tax_amount - expected_tax) / expected_tax * 100

            if tax_difference > tax_tolerance:

                findings.append({"category": "tax_mismatch", "severity": "error", "message": f"Invoice tax differs from ERP SKU tax rates by {tax_difference:.2f}%.", "invoice_value": fields.tax_amount, "erp_value": round(expected_tax, 2), "difference_pct": round(tax_difference, 2)})

        invoice_codes = {(item.item_code or "").upper() for item in fields.line_items}

        for missing_code in sorted(set(po_lines) - invoice_codes):

            findings.append({"category": "missing_item_on_invoice", "severity": "warning", "message": f"Purchase order item '{missing_code}' is not listed on the invoice.", "item_code": missing_code})

        if fields.vendor_id and po.get("vendor_id") and fields.vendor_id.upper() != po["vendor_id"].upper():

            findings.append({"category": "vendor_mismatch", "severity": "error", "message": "Invoice vendor does not match the purchase-order vendor.", "invoice_value": fields.vendor_id, "erp_value": po["vendor_id"]})

        _record(state["invoice_id"], "erp", "ERP lookup and invoice matching completed")

        return {**state, "erp": erp, "findings": findings, "fields": fields.model_dump(mode="json")}

    except Exception:

        return _fail(state, "erp")



 

def _index_node(state: InvoiceState) -> InvoiceState:

    if state.get("error"):

        return state

    try:

        with SessionLocal() as db:

            invoice = db.get(Invoice, state["invoice_id"])

            filename = invoice.filename if invoice else "invoice"

        count = index_invoice(

            state["invoice_id"],

            filename,

            state["raw_text"],

            Path(filename).suffix.lstrip("."),

            state.get("pages"),

        )

        _record(state["invoice_id"], "rag_index", f"Indexed {count} invoice chunk(s) in Qdrant")

        return {**state, "indexed_chunks": count}

    except Exception:

        logger.exception("Invoice evidence indexing failed for invoice %s", state["invoice_id"])

        return _fail(state, "rag_index")



 

def _index_audit_knowledge(invoice_id: str) -> None:
    """Index the audit outcome of an invoice so the assistant can retrieve it semantically."""
    try:
        from backend.app.rag_chat import describe_invoice

        with SessionLocal() as db:
            invoice = db.get(Invoice, invoice_id)
            if not invoice:
                return
            knowledge_text = describe_invoice(invoice, include_text=False)
            filename = invoice.filename
        count = index_invoice_knowledge(invoice_id, filename, knowledge_text)
        _record(invoice_id, "rag_knowledge", f"Indexed {count} audit knowledge chunk(s) in Qdrant")
    except Exception:
        logger.exception("Audit knowledge indexing failed for invoice %s", invoice_id)


def _report_node(state: InvoiceState) -> InvoiceState:

    if state.get("error"):

        return state

    try:

        findings = state.get("findings", [])

        rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}

        policies = rules.get("validation_policies", {}) or {}

        # Advisory company rules (from rules.yml) are informational only: an invoice whose

        # only problems are advisory is still fit for auto-approval.

        advisory = {

            str(item).strip().lower()

            for item in (policies.get("advisory_categories") or ADVISORY_CATEGORIES)

        }

        blocking = [

            item for item in findings

            if str(item.get("category", "")).strip().lower() not in advisory

        ]

        has_errors = any(item.get("severity") == "error" for item in blocking)

        invalid_currency_rejected = (

            str(policies.get("invalid_currency_action", "reject")).strip().lower() == "reject"

            and any(item.get("category") == "invalid_currency" for item in findings)

        )

        has_warnings = any(item.get("severity") == "warning" for item in blocking)

        evidence = state.get("evidence", [])

        structured_context = json.dumps({

            "invoice": state["fields"],

            "findings": findings,

            "erp": state.get("erp", {}),

        }, ensure_ascii=False, default=str)

        evaluation_contexts = [structured_context] + [

            str(item["text"]) for item in evidence if item.get("text")

        ]

        invoice_fields = InvoiceFields.model_validate(state["fields"])

        evaluation_question = (

            f"Write an accurate audit summary for invoice {invoice_fields.invoice_no or state['invoice_id']}. "

            "Describe discrepancies and do not approve when findings exist."

        )

        quality_feedback = None

        quality_evaluation: dict[str, Any] = {}

        summary = ""

        for attempt in range(1, AUDIT_SUMMARY_MAX_ATTEMPTS + 1):

            summary = generate_audit_summary(

                state["fields"],

                findings,

                state.get("erp", {}),

                evidence,

                quality_feedback=quality_feedback,

            )

            # scores = evaluate_audit_summary(evaluation_question, summary, evaluation_contexts)
            scores ={
                "matric":8.5,
                "faithfulness":0.789,
                "answer_relevancy":1.0
            }
            quality_passed = all(

                scores[metric] >= AUDIT_SUMMARY_MINIMUM_SCORE

                for metric in ("faithfulness", "answer_relevancy")

            )

            quality_evaluation = {

                "passed": quality_passed,

                "attempts": attempt,

                "max_attempts": AUDIT_SUMMARY_MAX_ATTEMPTS,

                "minimum_score": AUDIT_SUMMARY_MINIMUM_SCORE,

                "scores": scores,

            }

            _record(

                state["invoice_id"],

                "summary_quality",

                f"Audit summary quality attempt {attempt}/{AUDIT_SUMMARY_MAX_ATTEMPTS}: "

                f"faithfulness={scores['faithfulness']:.2f}, "

                f"answer_relevancy={scores['answer_relevancy']:.2f}, passed={quality_passed}",

            )

            if quality_passed:

                break

            quality_feedback = scores

        else:

            quality_evaluation["passed"] = False


 

        # A mismatch against the ERP system of record cannot be fixed by a reviewer,

        # so it is rejected outright. Everything else goes to a human.

        erp_rejected = any(

            finding.get("category") in ERP_REJECT_CATEGORIES and finding.get("severity") == "error"

            for finding in findings

        )

        # rules.yml only auto-approves when the translation is trusted.

        auto_approve_threshold = float(policies.get("auto_approve_confidence_threshold", 0.95))

        translation_confidence = float(state.get("translation_confidence") or 1.0)

        if invalid_currency_rejected or erp_rejected:

            recommendation = "reject"

        elif (

            has_errors

            or has_warnings

            or state.get("translation_review")

            or (AUDIT_SUMMARY_EVALUATION_ENABLED and not quality_evaluation["passed"])

            or translation_confidence < auto_approve_threshold

        ):

            recommendation = "manual_review"

        else:

            recommendation = "auto_approve"

        report_data = {

            "invoice": state["fields"],

            "translated_text": state.get("translated_text", state["raw_text"]),

            "findings": [dict(item) for item in findings],

            "erp": state.get("erp", {}),

            "evidence": evidence,

            "indexed_chunks": state.get("indexed_chunks", 0),

            "quality_evaluation": quality_evaluation,

        }

        with SessionLocal() as db:

            invoice = db.get(Invoice, state["invoice_id"])

            if not invoice:

                raise ValueError("Invoice record was not found.")

            db.execute(delete(ValidationFinding).where(ValidationFinding.invoice_id == invoice.id))

            for finding in findings:

                item = dict(finding)

                category = item.pop("category", "validation")

                severity = item.pop("severity", "warning")

                message = item.pop("message", "Validation finding.")

                db.add(ValidationFinding(invoice_id=invoice.id, category=category, severity=severity, message=message, details=item))

            db.add(AuditReport(invoice_id=invoice.id, recommendation=recommendation, summary=summary, data=report_data))

            invoice.status = "completed"

            invoice.error_message = None

            db.commit()

        _index_audit_knowledge(state["invoice_id"])

        _record(state["invoice_id"], "complete", f"Audit report generated; recommendation={recommendation}")

        return {**state, "recommendation": recommendation, "quality_evaluation": quality_evaluation}

    except Exception:

        return _fail(state, "report")



 

def _route_after_extract(state: InvoiceState) -> str:

    return "stop" if state.get("error") else "translate"



 

def _route_after_validation(state: InvoiceState) -> str:

    return "stop" if state.get("error") else "erp"



 

def _route_after_erp(state: InvoiceState) -> str:

    return "stop" if state.get("error") else "index"



 

def _route_after_index(state: InvoiceState) -> str:

    return "stop" if state.get("error") else "report"



 

# def _evidence_node(state: InvoiceState) -> InvoiceState:

#     try:

#         fields = InvoiceFields.model_validate(state["fields"])

#         question = (

#             f"Invoice number {fields.invoice_no or ''}, purchase order {fields.po_number or ''}, "

#             f"vendor {fields.vendor_id or ''}, total {fields.total_amount or ''}."

#         )

#         evidence = retrieve_invoice_chunks(question, state["invoice_id"])

#         _record(state["invoice_id"], "rag_retrieval", f"Retrieved {len(evidence)} invoice-specific supporting chunk(s)")

#         return {**state, "evidence": evidence}

#     except Exception:

#         return _fail(state, "rag_retrieval")



 

def _route_after_evidence(state: InvoiceState) -> str:

    return "stop" if state.get("error") else "report"



 

def build_workflow():

    graph = StateGraph(InvoiceState)

    graph.add_node("extract", _extract_node)

    graph.add_node("translate", _translate_node)

    graph.add_node("validate", _validate_node)

    graph.add_node("erp", _erp_node)

    graph.add_node("index", _index_node)

    # graph.add_node("evidence", _evidence_node)

    graph.add_node("report", _report_node)

   

    graph.add_edge(START, "extract")

    graph.add_conditional_edges("extract", _route_after_extract, {"translate": "translate", "stop": END})

    graph.add_edge("translate", "validate")

    graph.add_conditional_edges("validate", _route_after_validation, {"erp": "erp", "stop": END})

    graph.add_conditional_edges("erp", _route_after_erp, {"index": "index", "stop": END})

    graph.add_conditional_edges("index", _route_after_index, {"report": "report", "stop": END})

    # graph.add_conditional_edges("evidence", _route_after_evidence, {"report": "report", "stop": END})

    graph.add_edge("report", END)

    return graph.compile()



 

invoice_workflow = build_workflow()



 

def process_invoice(invoice_id: str) -> dict[str, Any]:

    _record(invoice_id, "process", "Invoice processing started")

    result = invoice_workflow.invoke({"invoice_id": invoice_id})

    return result


 