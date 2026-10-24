"""Pair invoice documents with their sidecar ``*.meta.json`` metadata files.

The monitored folder holds invoice documents (PDF, DOCX, images). A document may be
accompanied by a metadata file describing how it arrived -- the sending mailbox, the
e-mail subject, the declared language and the attachment it belongs to. Those files are
never invoices in their own right: they are merged into the invoice they describe so the
audit sees one record per real document.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.app.settings import DOCUMENT_EXTENSIONS, METADATA_EXTENSIONS, METADATA_SUFFIX

logger = logging.getLogger(__name__)

# "Invoice INV-1001 for PO-1001" -> invoice number and purchase order.
_INVOICE_NO_PATTERN = re.compile(r"\b(?:invoice|factura|rechnung|facture)\s*(?:no\.?|number|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/_-]{2,})", re.IGNORECASE)
# A compact "PO-1001" token is preferred; otherwise fall back to a spelled-out label.
_PO_TOKEN_PATTERN = re.compile(r"\b(PO[-_ ]?\d[A-Z0-9/_-]*)\b", re.IGNORECASE)
_PO_LABELLED_PATTERN = re.compile(r"\b(?:purchase\s*order|bestellung|orden|commande)\s*(?:no\.?|number|#|reference|ref)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/_-]{2,})", re.IGNORECASE)


def is_metadata_file(path: Path) -> bool:
    """True for sidecar metadata, which must never be registered as an invoice."""
    name = path.name.lower()
    if name.endswith(METADATA_SUFFIX):
        return True
    return path.suffix.lower() in METADATA_EXTENSIONS


def is_document(path: Path) -> bool:
    """True for a file the pipeline can actually extract an invoice from."""
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


def load_metadata(path: Path) -> dict[str, Any]:
    """Read one metadata file, returning an empty mapping when it is unusable."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Ignoring unreadable metadata file %s", path)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _declared_attachments(payload: dict[str, Any]) -> set[str]:
    attachments = payload.get("attachments")
    if isinstance(attachments, str):
        attachments = [attachments]
    if not isinstance(attachments, list):
        return set()
    return {str(item).strip().lower() for item in attachments if str(item).strip()}


def find_metadata_file(document: Path) -> Path | None:
    """Locate the metadata file describing ``document``.

    A metadata file is matched either by sharing the document's base name
    (``INV_EN_001.pdf`` -> ``INV_EN_001.meta.json``) or by naming the document in its
    ``attachments`` list, which also covers metadata named differently from the invoice.
    """
    directory = document.parent
    if not directory.is_dir():
        return None

    by_stem = directory / f"{document.stem}{METADATA_SUFFIX}"
    if by_stem.is_file():
        return by_stem

    target = document.name.lower()
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file() or not is_metadata_file(candidate):
            continue
        if target in _declared_attachments(load_metadata(candidate)):
            return candidate
    return None


def documents_for_metadata(metadata_path: Path) -> list[Path]:
    """Reverse lookup: every document a metadata file describes."""
    directory = metadata_path.parent
    if not directory.is_dir():
        return []

    declared = _declared_attachments(load_metadata(metadata_path))
    matches: list[Path] = []
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file() or not is_document(candidate):
            continue
        if candidate.name.lower() in declared:
            matches.append(candidate)
    if matches:
        return matches

    stem = metadata_path.name[: -len(METADATA_SUFFIX)] if metadata_path.name.lower().endswith(METADATA_SUFFIX) else metadata_path.stem
    return [path for path in sorted(directory.iterdir()) if is_document(path) and path.stem == stem]


def metadata_for_document(document: Path) -> tuple[dict[str, Any], str | None]:
    """Return ``(metadata, filename)`` for a document, or ``({}, None)`` when it has none."""
    path = find_metadata_file(document)
    if path is None:
        return {}, None
    return load_metadata(path), path.name


def _identifier_from_subject(subject: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(subject)
    if not match:
        return None
    value = match.group(1).strip().rstrip(".,;:")
    return value or None


def _po_from_subject(subject: str) -> str | None:
    """Prefer a literal ``PO-1001`` token so the ERP identifier stays intact."""
    token = _identifier_from_subject(subject, _PO_TOKEN_PATTERN)
    if token:
        return re.sub(r"^PO[-_ ]?", "PO-", token, flags=re.IGNORECASE).upper()
    return _identifier_from_subject(subject, _PO_LABELLED_PATTERN)


_METADATA_LABELS = {
    "sender": "Sender",
    "recipient": "Recipient",
    "subject": "Subject",
    "received_timestamp": "Received",
    "language": "Declared language",
    "attachments": "Attachments",
    "source": "Source",
}


def format_metadata_block(metadata: dict[str, Any], filename: str | None = None) -> str:
    """Render the sidecar metadata as readable text to append to the document.

    Keeping it in the document text means the e-mail context travels with the
    invoice through translation, the audit trail and the assistant's knowledge base.
    """
    if not metadata:
        return ""
    lines = [f"--- Accompanying metadata ({filename}) ---" if filename else "--- Accompanying metadata ---"]
    seen = set()
    for key, label in _METADATA_LABELS.items():
        if key not in metadata:
            continue
        seen.add(key)
        value = metadata.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        lines.append(f"{label}: {value}")
    for key, value in metadata.items():
        if key in seen or value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            value = ", ".join(f"{k}={v}" for k, v in value.items())
        lines.append(f"{str(key).replace('_', ' ').capitalize()}: {value}")
    return "\n".join(lines)


def merge_metadata(fields: dict[str, Any], metadata: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Fill gaps in the extracted fields from the sidecar metadata.

    The document itself stays authoritative: metadata only supplies values the
    extraction could not read, so a correct invoice is never overwritten.
    Returns the merged fields and a human-readable list of what was contributed.
    """
    if not metadata:
        return fields, []

    merged = dict(fields)
    applied: list[str] = []

    def fill(key: str, value: Any, label: str) -> None:
        if value in (None, "") or merged.get(key) not in (None, ""):
            return
        merged[key] = value
        applied.append(label)

    subject = str(metadata.get("subject") or "").strip()
    if subject:
        fill("invoice_no", _identifier_from_subject(subject, _INVOICE_NO_PATTERN), "invoice number (from the e-mail subject)")
        fill("po_number", _po_from_subject(subject), "purchase order (from the e-mail subject)")

    language = str(metadata.get("language") or "").strip()
    if language:
        fill("detected_language", language, "language (declared by the sender)")

    for key in ("invoice_no", "invoice_date", "po_number", "vendor_id", "vendor_name", "currency"):
        if key in metadata:
            fill(key, metadata.get(key), f"{key.replace('_', ' ')} (from metadata)")

    context = {key: value for key, value in metadata.items() if key != "attachments"}
    if context:
        additional = dict(merged.get("additional_fields") or {})
        additional["source_metadata"] = context
        merged["additional_fields"] = additional

    return merged, applied
