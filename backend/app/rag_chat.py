"""Conversational RAG over the full invoice knowledge base.

The assistant combines three knowledge sources:

* authoritative structured knowledge read directly from PostgreSQL
  (invoice fields, findings, ERP match, audit report, processing events,
  human review decisions),
* semantic passages retrieved from the Qdrant invoice index,
* short-term conversation memory (last 30 messages per chat session).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import redis
from botocore.exceptions import BotoCoreError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from qdrant_client.http.exceptions import UnexpectedResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.integrations import (
    InvoiceQueryError,
    get_chat_model,
    get_redis_client,
    retrieve_invoice_chunks,
)
from backend.app.models import Invoice, ProcessingEvent, ReviewDecision

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 30
HISTORY_TTL_SECONDS = 60 * 60 * 24 * 7
MAX_DETAILED_INVOICES = 5
MAX_TEXT_CHARS = 4000
MAX_CATALOG_ROWS = 300

_MEMORY_FALLBACK: dict[str, list[dict[str, str]]] = {}

SYSTEM_PROMPT = (
    "You are the Invoice Auditor assistant. You answer questions about invoices that were "
    "uploaded, extracted, translated, validated, matched against the ERP system and audited "
    "by this platform.\n"
    "Rules:\n"
    "1. Answer using ONLY the knowledge base context and the conversation history provided.\n"
    "2. The 'DATABASE KNOWLEDGE' section is authoritative; the 'RETRIEVED PASSAGES' section is "
    "raw invoice text used as supporting evidence.\n"
    "3. When explaining why an invoice needs manual review, was rejected or failed, quote the "
    "concrete validation findings, ERP mismatches, error messages or audit recommendation.\n"
    "4. When asked for extracted text, return the stored invoice text verbatim (trim very long "
    "text and say that it was trimmed).\n"
    "5. Reference invoices by filename and invoice number, and mention the invoice id when useful.\n"
    "6. Use the conversation history to resolve follow-up references such as 'it' or 'that invoice'.\n"
    "7. If the knowledge base does not contain the answer, say so plainly instead of guessing.\n"
    "Answer in clear, concise markdown."
)


# --------------------------------------------------
# Conversation memory (last 30 messages)
# --------------------------------------------------
def _history_key(session_id: str) -> str:
    return f"rag-chat-history:{session_id}"


def load_history(session_id: str) -> list[dict[str, str]]:
    try:
        raw = get_redis_client().lrange(_history_key(session_id), -MAX_HISTORY_MESSAGES, -1)
        return [json.loads(item) for item in raw]
    except (redis.RedisError, json.JSONDecodeError):
        return list(_MEMORY_FALLBACK.get(session_id, []))[-MAX_HISTORY_MESSAGES:]


def append_message(session_id: str, role: str, content: str) -> None:
    message = {
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client = get_redis_client()
        key = _history_key(session_id)
        client.rpush(key, json.dumps(message))
        client.ltrim(key, -MAX_HISTORY_MESSAGES, -1)
        client.expire(key, HISTORY_TTL_SECONDS)
    except redis.RedisError:
        bucket = _MEMORY_FALLBACK.setdefault(session_id, [])
        bucket.append(message)
        del bucket[:-MAX_HISTORY_MESSAGES]


def clear_history(session_id: str) -> None:
    try:
        get_redis_client().delete(_history_key(session_id))
    except redis.RedisError:
        pass
    _MEMORY_FALLBACK.pop(session_id, None)


def _history_messages(history: list[dict[str, str]]) -> list[Any]:
    messages: list[Any] = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        content = str(item.get("content", ""))
        if not content.strip():
            continue
        if item.get("role") == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


# --------------------------------------------------
# Invoice selection
# --------------------------------------------------
def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in _normalise(value).split() if len(token) > 2}


def _invoice_identifiers(invoice: Invoice) -> list[str]:
    fields = invoice.extracted.fields if invoice.extracted else {}
    candidates = [
        invoice.id,
        invoice.filename,
        invoice.filename.rsplit(".", 1)[0],
        str(fields.get("invoice_no") or ""),
        str(fields.get("po_number") or ""),
        str(fields.get("vendor_id") or ""),
        str(fields.get("vendor_name") or ""),
    ]
    return [item for item in candidates if item and item.strip()]


def _matches_question(invoice: Invoice, question: str, question_tokens: set[str]) -> bool:
    haystack = _normalise(question)
    for identifier in _invoice_identifiers(invoice):
        normalised = _normalise(identifier)
        if not normalised:
            continue
        if normalised in haystack:
            return True
        identifier_tokens = {token for token in normalised.split() if len(token) > 2}
        if identifier_tokens and identifier_tokens <= question_tokens:
            return True
    return False


def _status_filter(question: str) -> list[str]:
    lowered = question.lower()
    wanted: list[str] = []
    if "fail" in lowered or "error" in lowered:
        wanted.append("failed")
    if "manual review" in lowered or "manual_review" in lowered or "review" in lowered:
        wanted.append("manual_review")
    if "reject" in lowered:
        wanted.append("reject")
    if "approv" in lowered:
        wanted.append("auto_approve")
    return wanted


def select_invoices(
    db: Session,
    question: str,
    invoice_id: str | None,
    retrieved_invoice_ids: list[str],
) -> list[Invoice]:
    if invoice_id:
        invoice = db.get(Invoice, invoice_id)
        return [invoice] if invoice else []

    all_invoices = db.query(Invoice).order_by(Invoice.created_at.desc()).limit(MAX_CATALOG_ROWS).all()
    question_tokens = _tokens(question)

    selected: list[Invoice] = [
        invoice for invoice in all_invoices if _matches_question(invoice, question, question_tokens)
    ]
    selected_ids = {invoice.id for invoice in selected}

    for candidate_id in retrieved_invoice_ids:
        if candidate_id in selected_ids:
            continue
        invoice = next((item for item in all_invoices if item.id == candidate_id), None) or db.get(Invoice, candidate_id)
        if invoice:
            selected.append(invoice)
            selected_ids.add(invoice.id)

    if not selected:
        wanted_statuses = _status_filter(question)
        for invoice in all_invoices:
            recommendation = invoice.report.recommendation if invoice.report else None
            if invoice.status in wanted_statuses or (recommendation and recommendation in wanted_statuses):
                selected.append(invoice)
                selected_ids.add(invoice.id)

    return selected[:MAX_DETAILED_INVOICES]


# --------------------------------------------------
# Knowledge rendering
# --------------------------------------------------
def _trim(text: str | None, limit: int = MAX_TEXT_CHARS) -> str:
    value = (text or "").strip()
    if not value:
        return "(empty)"
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n... [text trimmed after {limit} characters]"


def describe_invoice(invoice: Invoice, include_text: bool = True) -> str:
    fields = invoice.extracted.fields if invoice.extracted else {}
    report = invoice.report
    lines = [
        f"### Invoice {invoice.filename} (id={invoice.id})",
        f"- Pipeline status: {invoice.status}",
        f"- Uploaded: {invoice.created_at.isoformat()} | Last update: {invoice.updated_at.isoformat()}",
        f"- Content type: {invoice.content_type}",
    ]
    if invoice.error_message:
        lines.append(f"- Processing error: {invoice.error_message}")

    if fields:
        lines.append(f"- Extracted fields: {json.dumps(fields, ensure_ascii=False, default=str)[:2500]}")
    else:
        lines.append("- Extracted fields: none stored")

    if report:
        lines.append(f"- Audit recommendation: {report.recommendation}")
        lines.append(f"- Audit summary: {report.summary}")
        erp = report.data.get("erp") if isinstance(report.data, dict) else None
        if erp:
            lines.append(f"- ERP match data: {json.dumps(erp, ensure_ascii=False, default=str)[:1500]}")
        quality = report.data.get("quality_evaluation") if isinstance(report.data, dict) else None
        if quality:
            lines.append(f"- Summary quality evaluation: {json.dumps(quality, default=str)}")
    else:
        lines.append("- Audit recommendation: not generated yet")

    if invoice.findings:
        lines.append("- Validation findings:")
        for finding in invoice.findings:
            details = json.dumps(finding.details, ensure_ascii=False, default=str)[:500]
            lines.append(
                f"  * [{finding.severity}] {finding.category}: {finding.message} details={details}"
            )
    else:
        lines.append("- Validation findings: none")

    if invoice.reviews:
        lines.append("- Human review decisions:")
        for review in sorted(invoice.reviews, key=lambda item: item.created_at):
            lines.append(
                f"  * {review.created_at.isoformat()} {review.decision} by {review.reviewer}"
                f" note={review.note or '—'} changes={json.dumps(review.changes, default=str)[:300]}"
            )

    events = sorted(invoice.events, key=lambda item: item.created_at)
    if events:
        lines.append("- Processing timeline:")
        for event in events[-25:]:
            lines.append(
                f"  * {event.created_at.isoformat()} [{event.level}] {event.stage}: {event.message}"
            )

    if include_text:
        raw_text = invoice.extracted.raw_text if invoice.extracted else ""
        lines.append("- Extracted (original) invoice text:")
        lines.append(f"```\n{_trim(raw_text)}\n```")
        translated = None
        if report and isinstance(report.data, dict):
            translated = report.data.get("translated_text")
        if translated and translated.strip() and translated.strip() != (raw_text or "").strip():
            lines.append("- English translated invoice text:")
            lines.append(f"```\n{_trim(translated)}\n```")

    return "\n".join(lines)


def build_catalog(db: Session) -> str:
    total = db.query(func.count(Invoice.id)).scalar() or 0
    invoices = db.query(Invoice).order_by(Invoice.created_at.desc()).limit(MAX_CATALOG_ROWS).all()
    status_counts: dict[str, int] = {}
    recommendation_counts: dict[str, int] = {}
    rows = []
    for invoice in invoices:
        fields = invoice.extracted.fields if invoice.extracted else {}
        recommendation = invoice.report.recommendation if invoice.report else "pending"
        status_counts[invoice.status] = status_counts.get(invoice.status, 0) + 1
        recommendation_counts[recommendation] = recommendation_counts.get(recommendation, 0) + 1
        latest_review = max(invoice.reviews, key=lambda item: item.created_at, default=None)
        rows.append(
            "| {file} | {number} | {vendor} | {amount} {currency} | {status} | {recommendation} | {findings} | {review} | {id} |".format(
                file=invoice.filename,
                number=fields.get("invoice_no") or "—",
                vendor=fields.get("vendor_name") or fields.get("vendor_id") or "—",
                amount=fields.get("total_amount") if fields.get("total_amount") is not None else "—",
                currency=fields.get("currency") or "",
                status=invoice.status,
                recommendation=recommendation,
                findings=len(invoice.findings),
                review=latest_review.decision if latest_review else "—",
                id=invoice.id,
            )
        )

    header = (
        f"Total invoices in the system: {total}. "
        f"Status counts: {json.dumps(status_counts)}. "
        f"Audit recommendation counts: {json.dumps(recommendation_counts)}."
    )
    table = (
        "| File | Invoice no | Vendor | Amount | Status | Recommendation | Findings | Last review | Invoice id |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n" + "\n".join(rows)
    )
    return f"{header}\n\n{table}"


def recent_activity(db: Session, limit: int = 25) -> str:
    events = (
        db.query(ProcessingEvent, Invoice.filename)
        .join(Invoice)
        .order_by(ProcessingEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    if not events:
        return "No processing activity recorded."
    return "\n".join(
        f"* {event.created_at.isoformat()} [{event.level}] {filename} ({event.invoice_id}) "
        f"{event.stage}: {event.message}"
        for event, filename in events
    )


def review_history(db: Session, limit: int = 20) -> str:
    decisions = (
        db.query(ReviewDecision, Invoice.filename)
        .join(Invoice)
        .order_by(ReviewDecision.created_at.desc())
        .limit(limit)
        .all()
    )
    if not decisions:
        return "No human review decisions recorded yet."
    return "\n".join(
        f"* {decision.created_at.isoformat()} {filename} ({decision.invoice_id}): "
        f"{decision.decision} by {decision.reviewer} — {decision.note or 'no note'}"
        for decision, filename in decisions
    )


# --------------------------------------------------
# Answering
# --------------------------------------------------
def _retrieve(question: str, invoice_id: str | None) -> list[dict[str, Any]]:
    try:
        return retrieve_invoice_chunks(question, invoice_id, k=8)
    except (httpx.HTTPError, UnexpectedResponse, BotoCoreError):
        logger.warning("Vector retrieval unavailable; answering from the database only.")
        return []
    except Exception:
        logger.exception("Unexpected failure while retrieving invoice passages.")
        return []


def answer_question(
    db: Session,
    question: str,
    session_id: str = "default",
    invoice_id: str | None = None,
) -> dict[str, Any]:
    history = load_history(session_id)

    sources = _retrieve(question, invoice_id)
    retrieved_ids: list[str] = []
    for source in sources:
        candidate = source.get("invoice_id")
        if candidate and candidate not in retrieved_ids:
            retrieved_ids.append(candidate)

    invoices = select_invoices(db, question, invoice_id, retrieved_ids)

    knowledge_sections = [f"## Invoice catalogue\n{build_catalog(db)}"]
    if invoices:
        details = "\n\n".join(describe_invoice(invoice) for invoice in invoices)
        knowledge_sections.append(f"## Invoice details\n{details}")
    knowledge_sections.append(f"## Recent processing activity\n{recent_activity(db)}")
    knowledge_sections.append(f"## Human review decisions\n{review_history(db)}")

    passages = "\n\n".join(
        f"[{index + 1}] {source.get('filename')} (invoice_id={source.get('invoice_id')}, "
        f"page={source.get('page')}, score={source.get('score', 0):.3f})\n{source.get('text', '')}"
        for index, source in enumerate(sources)
    ) or "No vector passages matched this question."

    scope = (
        f"The user restricted the question to invoice_id={invoice_id}."
        if invoice_id
        else "The user is asking across all invoices."
    )

    user_prompt = (
        f"{scope}\n\n"
        f"=== DATABASE KNOWLEDGE (authoritative) ===\n"
        + "\n\n".join(knowledge_sections)
        + f"\n\n=== RETRIEVED PASSAGES ===\n{passages}\n\n"
        f"=== QUESTION ===\n{question}"
    )

    messages = [SystemMessage(content=SYSTEM_PROMPT), *_history_messages(history), HumanMessage(content=user_prompt)]

    try:
        response = get_chat_model().invoke(messages)
    except BotoCoreError as exc:
        raise InvoiceQueryError("Could not generate an answer with AWS Bedrock.") from exc

    content = response.content
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    answer = str(content).strip() or "I could not produce an answer for this question."

    append_message(session_id, "user", question)
    append_message(session_id, "assistant", answer)

    return {
        "answer": answer,
        "sources": sources,
        "session_id": session_id,
        "invoices_used": [
            {
                "invoice_id": invoice.id,
                "filename": invoice.filename,
                "status": invoice.status,
                "recommendation": invoice.report.recommendation if invoice.report else None,
            }
            for invoice in invoices
        ],
        "history": load_history(session_id),
    }


def search_invoices(db: Session, term: str, limit: int = 10) -> list[Invoice]:
    pattern = f"%{term}%"
    return (
        db.query(Invoice)
        .filter(or_(Invoice.filename.ilike(pattern), Invoice.id.ilike(pattern)))
        .limit(limit)
        .all()
    )
