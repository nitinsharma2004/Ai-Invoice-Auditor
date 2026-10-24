from __future__ import annotations


 

import hashlib

from datetime import datetime, timezone

import json

import logging

import mimetypes

import yaml

import uuid

from contextlib import asynccontextmanager

from pathlib import Path

from typing import Any, Callable


 

import httpx

import redis

from botocore.exceptions import BotoCoreError

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile, status

from fastapi.exceptions import RequestValidationError

from fastapi.responses import FileResponse, JSONResponse

from qdrant_client.http.exceptions import UnexpectedResponse

from qdrant_client import QdrantClient

from sqlalchemy import func, or_, text

from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.orm import Session


 

from backend.app.database import Base, SessionLocal, engine, get_db

from backend.app.integrations import (

    BedrockConfigurationError,

    InvoiceQueryError,

    get_redis_client,

    index_invoice_knowledge,

    query_invoice,

)

from backend.app import rag_chat

from backend.app.models import (

    AuditReport,

    ExtractedInvoice,

    Invoice,

    ProcessingEvent,

    ReviewDecision,

    ValidationFinding,

)

from backend.app.schemas import (

    ChatRequest,

    InvoiceFieldUpdateRequest,

    InvoiceSummary,

    QueryRequest,

    FolderProcessRequest,

    ReviewDecisionRequest,

    UploadItemResult,

)

from backend.app.sidecar import find_metadata_file, is_document

from backend.app.settings import (

    ALLOWED_EXTENSIONS,

    ERP_API_URL,

    INCOMING_DIR,

    MAX_UPLOAD_BYTES,

    QDRANT_URL,

    RULES_PATH,

    UPLOAD_DIR,

)

from backend.app import folder_watch

from backend.app.workflow import ADVISORY_CATEGORIES, ERP_REJECT_CATEGORIES, process_invoice


 

logger = logging.getLogger(__name__)


 

@asynccontextmanager

async def lifespan(_: FastAPI):

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    INCOMING_DIR.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)

    folder_watch.start_watcher()

    try:

        yield

    finally:

        folder_watch.stop_watcher()



 

app = FastAPI(title="AI Invoice Auditor API", version="2.0.0", lifespan=lifespan)



 

@app.exception_handler(RequestValidationError)

async def request_validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:

    return JSONResponse(

        status_code=422,

        content={"detail": "Request validation failed. Check the submitted fields and retry."},

    )



 

def _drop_cached_status(invoice_id: str) -> None:

    try:

        get_redis_client().delete(f"invoice-status:{invoice_id}")

    except redis.RedisError:

        pass



 

def _run_processing(invoice_id: str) -> None:

    try:

        process_invoice(invoice_id)

    except Exception:

        with SessionLocal() as db:

            invoice = db.get(Invoice, invoice_id)

            if invoice:

                invoice.status = "failed"

                invoice.error_message = "Invoice processing failed unexpectedly. Retry or contact the administrator."

                db.add(ProcessingEvent(invoice_id=invoice_id, stage="process", level="ERROR", message=invoice.error_message))

                db.commit()

        _drop_cached_status(invoice_id)



 

async def _validated_upload(file: UploadFile) -> tuple[str, str, bytes, str]:

    """Validate one uploaded document and return (filename, extension, content, mime type)."""

    original_name = Path((file.filename or "").replace("\\", "/")).name

    extension = Path(original_name).suffix.lower()

    if not original_name or original_name in {".", ".."} or extension not in ALLOWED_EXTENSIONS:

        raise HTTPException(status_code=415, detail="Only PDF, DOCX, PNG, JPG/JPEG, and JSON invoice files are accepted.")


 

    content = await file.read(MAX_UPLOAD_BYTES + 1)

    await file.close()

    if not content:

        raise HTTPException(status_code=422, detail="The uploaded file is empty.")

    if len(content) > MAX_UPLOAD_BYTES:

        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_BYTES}-byte upload limit.")

    mime_type = (file.content_type or mimetypes.guess_type(original_name)[0] or "").lower()

    expected_mimes = {

        ".pdf": {"application/pdf"},

        ".png": {"image/png"},

        ".jpg": {"image/jpeg"},

        ".jpeg": {"image/jpeg"},

        ".json": {"application/json", "text/json"},

        ".docx": {

            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",

            "application/octet-stream",

        },

    }

    if mime_type not in expected_mimes[extension]:

        raise HTTPException(status_code=415, detail=f"Content type '{mime_type or 'unknown'}' does not match {extension}.")

    if extension == ".pdf" and not content.startswith(b"%PDF-"):

        raise HTTPException(status_code=422, detail="The uploaded file does not contain a valid PDF signature.")

    if extension == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):

        raise HTTPException(status_code=422, detail="The uploaded file does not contain a valid PNG signature.")

    if extension in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):

        raise HTTPException(status_code=422, detail="The uploaded file does not contain a valid JPEG signature.")

    if extension == ".docx" and not content.startswith(b"PK\x03\x04"):

        raise HTTPException(status_code=422, detail="The uploaded file does not contain a valid DOCX signature.")

    if extension == ".json":

        try:

            parsed = json.loads(content)

        except (UnicodeDecodeError, json.JSONDecodeError) as exc:

            raise HTTPException(status_code=422, detail=f"Invalid invoice JSON: {exc}") from exc

        if not isinstance(parsed, dict):

            raise HTTPException(status_code=422, detail="Invoice JSON must be a JSON object.")

    return original_name, extension, content, mime_type



 

async def _receive_upload(file: UploadFile, background_tasks: BackgroundTasks, db: Session) -> UploadItemResult:

    original_name, extension, content, mime_type = await _validated_upload(file)



 

    digest = hashlib.sha256(content).hexdigest()

    existing = db.query(Invoice).filter(Invoice.sha256 == digest).one_or_none()

    if existing:

        return UploadItemResult(invoice_id=existing.id, filename=existing.filename, status=existing.status, detail="Identical file already registered; existing invoice returned.")


 

    invoice_id = str(uuid.uuid4())

    # Uploads are dropped into the monitored incoming folder so that folder-ingested and

    # dashboard-uploaded invoices follow exactly the same path.

    try:

        destination = folder_watch.unique_destination(INCOMING_DIR, original_name[:255])

        destination.write_bytes(content)

    except OSError as exc:

        logger.exception("Could not write the upload into the incoming folder")

        raise HTTPException(status_code=500, detail="The incoming folder is not writable. Check the deployment configuration.") from exc

    folder_watch.mark_registered(destination)

    invoice = Invoice(

        id=invoice_id,

        filename=original_name[:255],

        stored_path=str(destination),

        content_type=mime_type,

        sha256=digest,

        status="queued",

    )

    try:

        db.add(invoice)

        db.add(ProcessingEvent(invoice_id=invoice_id, stage="upload", message=f"Invoice uploaded to the monitored folder as '{destination.name}' and queued for processing"))

        db.commit()

    except SQLAlchemyError:

        db.rollback()

        destination.unlink(missing_ok=True)

        existing = db.query(Invoice).filter(Invoice.sha256 == digest).one_or_none()

        if existing:

            return UploadItemResult(invoice_id=existing.id, filename=existing.filename, status=existing.status, detail="Identical file already registered; existing invoice returned.")

        raise HTTPException(status_code=500, detail="Invoice registration failed. Please retry.")

    background_tasks.add_task(_run_processing, invoice_id)

    return UploadItemResult(invoice_id=invoice_id, filename=original_name, status="queued")



 

@app.get("/health")

def health(db: Session = Depends(get_db)) -> dict[str, str]:

    try:

        db.execute(text("SELECT 1"))

    except Exception:

        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable.") from None

    return {"status": "healthy", "database": "connected"}



 

def _probe_service(operation: Callable[[], Any]) -> dict[str, str]:

    try:

        operation()

    except Exception as exc:

        logger.warning("Service health probe failed: %s", type(exc).__name__)

        return {"status": "unhealthy", "detail": type(exc).__name__}

    return {"status": "healthy", "detail": "Connected"}



 

@app.get("/health/services")

def services_health(db: Session = Depends(get_db)) -> dict[str, dict[str, dict[str, str]]]:

    def check_database() -> None:

        db.execute(text("SELECT 1"))


 

    def check_redis() -> None:

        get_redis_client().ping()


 

    def check_qdrant() -> None:

        QdrantClient(url=QDRANT_URL, timeout=2).get_collections()


 

    def check_mockerp() -> None:

        response = httpx.get(f"{ERP_API_URL.rstrip('/')}/health", timeout=2)

        response.raise_for_status()


 

    return {

        "services": {

            "agent": {"status": "healthy", "detail": "API is responding"},

            "postgresql": _probe_service(check_database),

            "redis": _probe_service(check_redis),

            "qdrant": _probe_service(check_qdrant),

            "mockerp": _probe_service(check_mockerp),

            "streamlit": {"status": "healthy", "detail": "Frontend is serving this dashboard"},

        }

    }



 

@app.get("/dashboard/summary")

def dashboard_summary(db: Session = Depends(get_db)) -> dict[str, int]:

    total = db.query(func.count(Invoice.id)).scalar() or 0

    validated = (

        db.query(func.count(Invoice.id))

        .join(AuditReport, AuditReport.invoice_id == Invoice.id)

        .filter(Invoice.status == "completed", AuditReport.recommendation == "auto_approve")

        .scalar()

        or 0

    )

    needs_review = (

        db.query(func.count(func.distinct(Invoice.id)))

        .outerjoin(AuditReport, AuditReport.invoice_id == Invoice.id)

        .outerjoin(ValidationFinding, ValidationFinding.invoice_id == Invoice.id)

        .filter(

            Invoice.status == "completed",

            or_(

                AuditReport.recommendation == "manual_review",

                ValidationFinding.severity.in_(("error", "warning")),

            ),

        )

        .scalar()

        or 0

    )

    failed = db.query(func.count(Invoice.id)).filter(Invoice.status == "failed").scalar() or 0

    return {

        "total_invoices": int(total),

        "validated_invoices": int(validated),

        "invoices_needing_review": int(needs_review),

        "failed_invoices": int(failed),

    }



 

@app.post("/invoices/upload", response_model=UploadItemResult, status_code=status.HTTP_202_ACCEPTED)

async def upload_invoice(

    background_tasks: BackgroundTasks,

    file: UploadFile = File(...),

    db: Session = Depends(get_db),

) -> UploadItemResult:

    return await _receive_upload(file, background_tasks, db)



 

@app.post("/invoices/upload/batch", response_model=list[UploadItemResult], status_code=status.HTTP_202_ACCEPTED)

async def upload_invoices(

    background_tasks: BackgroundTasks,

    files: list[UploadFile] = File(...),

    db: Session = Depends(get_db),

) -> list[UploadItemResult]:

    if not files:

        raise HTTPException(status_code=422, detail="Select at least one invoice to upload.")

    results = []

    for file in files:

        try:

            results.append(await _receive_upload(file, background_tasks, db))

        except HTTPException as exc:

            results.append(UploadItemResult(filename=Path(file.filename or "unknown").name, status="rejected", detail=str(exc.detail)))

    return results



 

@app.get("/invoices", response_model=list[InvoiceSummary])

def list_invoices(limit: int = 100, db: Session = Depends(get_db)) -> list[dict[str, Any]]:

    if not 1 <= limit <= 500:

        raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")

    invoices = db.query(Invoice).order_by(Invoice.created_at.desc()).limit(limit).all()

    result = []

    for invoice in invoices:

        fields = invoice.extracted.fields if invoice.extracted else {}

        findings = invoice.findings

        review = _latest_review(invoice)

        percent, stage = _progress(invoice)

        result.append({

            "id": invoice.id,

            "filename": invoice.filename,

            "content_type": invoice.content_type,

            "status": invoice.status,

            "error_message": invoice.error_message,

            "created_at": invoice.created_at,

            "updated_at": invoice.updated_at,

            "invoice_number": fields.get("invoice_no"),

            "vendor": fields.get("vendor_name") or fields.get("vendor_id"),

            "invoice_date": fields.get("invoice_date"),

            "amount": fields.get("total_amount"),

            "currency": fields.get("currency"),

            "recommendation": invoice.report.recommendation if invoice.report else None,

            "audit_verdict": _audit_verdict(invoice),

            "finding_count": len(findings),

            "review_status": review.decision if review else None,

            "review_note": review.note if review else None,

            "reviewed_at": review.created_at if review else None,

            "reviewer": review.reviewer if review else None,

            "progress": percent,

            "current_stage": stage,

        })

    return result



 

@app.get("/audit-logs")

def list_audit_logs(

    limit: int = 100,

    invoice_id: str | None = None,

    db: Session = Depends(get_db),

) -> list[dict[str, Any]]:

    if not 1 <= limit <= 500:

        raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")

    query = db.query(ProcessingEvent, Invoice.filename).join(Invoice)

    if invoice_id:

        query = query.filter(ProcessingEvent.invoice_id == invoice_id)

    return [

        {

            "id": event.id,

            "invoice_id": event.invoice_id,

            "filename": filename,

            "stage": event.stage,

            "level": event.level,

            "message": event.message,

            "created_at": event.created_at,

        }

        for event, filename in query.order_by(ProcessingEvent.created_at.desc()).limit(limit).all()

    ]



 

 

PIPELINE_STAGES = [

    ("upload", "Uploaded"),

    ("extract", "Extraction"),

    ("translate", "Translation"),

    ("validate", "Validation"),

    ("erp", "ERP match"),

    ("rag_index", "Indexing"),

    ("complete", "Audit report"),

]


def _progress(invoice: Invoice) -> tuple[int, str]:

    """Return completion percentage and the latest stage label for an invoice."""

    stages = {event.stage for event in invoice.events if event.level != "ERROR"}

    done = [label for stage, label in PIPELINE_STAGES if stage in stages]

    if invoice.status == "completed":

        return 100, "Audit report"

    if invoice.status == "failed":

        failed = next(

            (event.stage for event in sorted(invoice.events, key=lambda item: item.created_at, reverse=True)

             if event.level == "ERROR"),

            "processing",

        )

        percent = int(len(done) / len(PIPELINE_STAGES) * 100)

        return percent, f"Failed at {failed}"

    if invoice.status == "pending":

        return 0, "Awaiting processing"

    percent = int(len(done) / len(PIPELINE_STAGES) * 100)

    return percent, (done[-1] if done else "Queued")


def _audit_verdict(invoice: Invoice) -> str | None:

    """Reject on any ERP conflict, otherwise flag for review; mirrors the workflow rule.

    Derived from the findings so invoices audited before this rule existed are classified

    consistently without being reprocessed.

    """

    if invoice.status != "completed":

        return None

    stored = invoice.report.recommendation if invoice.report else None

    if stored in {"human_approved", "human_rejected"}:

        return "reject" if stored == "human_rejected" else "approve"

    findings = invoice.findings

    if any(f.category in ERP_REJECT_CATEGORIES and f.severity == "error" for f in findings):

        return "reject"

    if stored == "reject":

        return "reject"

    # Advisory findings are informational and never block approval.

    if any(f.category not in ADVISORY_CATEGORIES for f in findings) or stored == "manual_review":

        return "manual_review"

    return "approve"



 

def _latest_review(invoice: Invoice) -> ReviewDecision | None:

    return max(invoice.reviews, key=lambda item: item.created_at, default=None)


def _invoice_detail(invoice: Invoice) -> dict[str, Any]:

    extracted_fields = dict(invoice.extracted.fields) if invoice.extracted else None

    additional_fields = (

        dict(extracted_fields.get("additional_fields") or {})

        if extracted_fields

        else {}

    )

    persisted_translation = additional_fields.pop("_translated_text", None)

    translated_fields = additional_fields.pop("_translated_fields", None)

    translation_not_required = any(

        event.stage == "translate" and event.message == "Translation not required"

        for event in invoice.events

    )

    if extracted_fields is not None and "additional_fields" in extracted_fields:

        extracted_fields["additional_fields"] = additional_fields or None

    if translation_not_required and translated_fields is None:

        translated_fields = extracted_fields


 

    return {

        "id": invoice.id,

        "filename": invoice.filename,

        "content_type": invoice.content_type,

        "status": invoice.status,

        "error_message": invoice.error_message,

        "created_at": invoice.created_at,

        "updated_at": invoice.updated_at,

        "audit_verdict": _audit_verdict(invoice),

        "extracted_fields": extracted_fields,

        "translated_fields": translated_fields,

        "original_text": invoice.extracted.raw_text if invoice.extracted else None,

        "translated_text": (

            invoice.report.data.get("translated_text")

            if invoice.report and invoice.report.data.get("translated_text")

            else persisted_translation

            or (

                invoice.extracted.raw_text

                if translation_not_required and invoice.extracted

                else None

            )

        ),

        "findings": [

            {"category": finding.category, "severity": finding.severity, "message": finding.message, "details": finding.details}

            for finding in invoice.findings

        ],

        "erp": invoice.report.data.get("erp") if invoice.report else None,

        "evidence": invoice.report.data.get("evidence", []) if invoice.report else [],

        "report": {

            "recommendation": invoice.report.recommendation,

            "summary": invoice.report.summary,

            "data": invoice.report.data,

        } if invoice.report else None,

        "events": [

            {"stage": event.stage, "level": event.level, "message": event.message, "created_at": event.created_at}

            for event in sorted(invoice.events, key=lambda item: item.created_at)

        ],

        "reviews": [

            {

                "decision": review.decision,

                "reviewer": review.reviewer,

                "note": review.note,

                "changes": review.changes,

                "created_at": review.created_at,

            }

            for review in sorted(invoice.reviews, key=lambda item: item.created_at)

        ],

        "review_status": _latest_review(invoice).decision if _latest_review(invoice) else None,

        "progress": _progress(invoice)[0],

        "current_stage": _progress(invoice)[1],

    }



 

@app.get("/invoices/{invoice_id}")

def get_invoice(invoice_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:

    invoice = db.get(Invoice, invoice_id)

    if not invoice:

        raise HTTPException(status_code=404, detail="Invoice not found.")

    return _invoice_detail(invoice)



 

@app.get("/invoices/{invoice_id}/status")

def get_invoice_status(invoice_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:

    try:

        cached = get_redis_client().get(f"invoice-status:{invoice_id}")

        if cached:

            return json.loads(cached)

    except (redis.RedisError, json.JSONDecodeError):

        pass

    invoice = db.get(Invoice, invoice_id)

    if not invoice:

        raise HTTPException(status_code=404, detail="Invoice not found.")

    result = {"invoice_id": invoice.id, "status": invoice.status, "error_message": invoice.error_message, "updated_at": invoice.updated_at.isoformat()}

    try:

        get_redis_client().setex(f"invoice-status:{invoice_id}", 30, json.dumps(result))

    except redis.RedisError:

        pass

    return result



 

@app.get("/invoices/{invoice_id}/report")

def get_invoice_report(invoice_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:

    invoice = db.get(Invoice, invoice_id)

    if not invoice:

        raise HTTPException(status_code=404, detail="Invoice not found.")

    if not invoice.report:

        raise HTTPException(status_code=404, detail="Audit report is not available yet.")

    return {"invoice_id": invoice_id, "recommendation": invoice.report.recommendation, "summary": invoice.report.summary, "data": invoice.report.data}



 

@app.post("/invoices/{invoice_id}/process", status_code=status.HTTP_202_ACCEPTED)

def retry_invoice(invoice_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, str]:

    invoice = db.get(Invoice, invoice_id)

    if not invoice:

        raise HTTPException(status_code=404, detail="Invoice not found.")

    if invoice.status not in {"failed", "completed", "pending"}:

        raise HTTPException(status_code=409, detail=f"Cannot reprocess invoice while status is '{invoice.status}'.")

    invoice.status = "queued"

    invoice.error_message = None

    db.add(ProcessingEvent(invoice_id=invoice_id, stage="retry", message="Invoice reprocessing queued"))

    db.commit()

    _drop_cached_status(invoice_id)

    background_tasks.add_task(_run_processing, invoice_id)

    return {"invoice_id": invoice_id, "status": "queued"}



 

@app.post("/rag/query")

def rag_query(request: QueryRequest, db: Session = Depends(get_db)) -> dict[str, Any]:

    if request.invoice_id and not db.get(Invoice, request.invoice_id):

        raise HTTPException(status_code=404, detail="Invoice not found.")

    try:

        answer, sources = query_invoice(request.question, request.invoice_id)

    except (BedrockConfigurationError, BotoCoreError, httpx.HTTPError, InvoiceQueryError, UnexpectedResponse) as exc:

        raise HTTPException(

            status_code=503,

            detail="Invoice evidence service is unavailable or not configured. Check the service configuration and retry.",

        ) from exc

    return {"answer": answer, "sources": sources}


 

@app.get("/invoices/{invoice_id}/file")
def get_invoice_file(invoice_id: str, db: Session = Depends(get_db)):
    """Serve the stored invoice document so reviewers can read it in the dashboard."""
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    stored = Path(invoice.stored_path)
    for fallback in (INCOMING_DIR / stored.name, UPLOAD_DIR / stored.name):
        if stored.is_file():
            break
        stored = fallback
    if not stored.is_file():
        raise HTTPException(status_code=404, detail="The stored invoice document is no longer available.")
    return FileResponse(
        stored,
        media_type=invoice.content_type or "application/octet-stream",
        filename=invoice.filename,
    )


def _apply_review(
    db: Session,
    invoice: Invoice,
    decision: str,
    reviewer: str,
    note: str | None,
    changes: dict[str, Any] | None = None,
) -> ReviewDecision:
    record = ReviewDecision(
        invoice_id=invoice.id,
        decision=decision,
        reviewer=reviewer[:120],
        note=note,
        changes=changes or {},
    )
    db.add(record)
    db.add(ProcessingEvent(
        invoice_id=invoice.id,
        stage="human_review",
        level="INFO",
        message=f"Human reviewer {reviewer} recorded decision '{decision}'" + (f": {note}" if note else "."),
    ))
    if invoice.report:
        report_data = dict(invoice.report.data or {})
        report_data["human_review"] = {
            "decision": decision,
            "reviewer": reviewer,
            "note": note,
            "changes": changes or {},
        }
        invoice.report.data = report_data
        if decision == "approve":
            invoice.report.recommendation = "human_approved"
        elif decision == "reject":
            invoice.report.recommendation = "human_rejected"
    db.commit()
    _drop_cached_status(invoice.id)
    return record


def _reindex_knowledge(invoice_id: str) -> None:
    try:
        with SessionLocal() as db:
            invoice = db.get(Invoice, invoice_id)
            if not invoice:
                return
            knowledge = rag_chat.describe_invoice(invoice, include_text=False)
            filename = invoice.filename
        index_invoice_knowledge(invoice_id, filename, knowledge)
    except Exception:
        logger.warning("Could not refresh audit knowledge for invoice %s", invoice_id)


@app.post("/invoices/{invoice_id}/decision", status_code=status.HTTP_201_CREATED)
def submit_review_decision(
    invoice_id: str,
    request: ReviewDecisionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve, reject or acknowledge an invoice that requires human review."""
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    record = _apply_review(db, invoice, request.decision, request.reviewer, request.note)
    background_tasks.add_task(_reindex_knowledge, invoice_id)
    return {
        "invoice_id": invoice_id,
        "decision": record.decision,
        "reviewer": record.reviewer,
        "note": record.note,
        "created_at": record.created_at.isoformat(),
        "recommendation": invoice.report.recommendation if invoice.report else None,
        "audit_verdict": _audit_verdict(invoice),
    }


@app.patch("/invoices/{invoice_id}/fields")
def update_invoice_fields(
    invoice_id: str,
    request: InvoiceFieldUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Let a human reviewer correct extracted invoice fields."""
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if not invoice.extracted:
        raise HTTPException(status_code=409, detail="This invoice has no extracted fields to edit yet.")
    if not request.fields:
        raise HTTPException(status_code=422, detail="Provide at least one field to update.")

    current = dict(invoice.extracted.fields or {})
    changes: dict[str, Any] = {}
    for key, value in request.fields.items():
        if current.get(key) != value:
            changes[key] = {"from": current.get(key), "to": value}
            current[key] = value
    if not changes:
        return {"invoice_id": invoice_id, "changes": {}, "detail": "No field values changed."}

    invoice.extracted.fields = current
    if invoice.report:
        report_data = dict(invoice.report.data or {})
        report_data["invoice"] = current
        invoice.report.data = report_data
    db.add(invoice.extracted)
    db.commit()

    decision = "approve" if request.approve else "edited"
    note = request.note or "Extracted fields corrected by a human reviewer."
    _apply_review(db, invoice, decision, request.reviewer, note, changes)
    background_tasks.add_task(_reindex_knowledge, invoice_id)
    return {"invoice_id": invoice_id, "changes": changes, "fields": current, "decision": decision}


@app.post("/rag/chat")
def rag_chat_endpoint(request: ChatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Conversational RAG over every invoice in the knowledge base, with memory."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Ask a question to continue.")
    if request.invoice_id and not db.get(Invoice, request.invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found.")
    try:
        return rag_chat.answer_question(db, question, request.session_id, request.invoice_id)
    except (BedrockConfigurationError, BotoCoreError, httpx.HTTPError, InvoiceQueryError, UnexpectedResponse) as exc:
        logger.warning("Chat answering failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="The invoice assistant is unavailable or not configured. Check the service configuration and retry.",
        ) from exc


@app.get("/rag/chat/{session_id}/history")
def rag_chat_history(session_id: str) -> dict[str, Any]:
    history = rag_chat.load_history(session_id)
    return {"session_id": session_id, "messages": history, "max_messages": rag_chat.MAX_HISTORY_MESSAGES}


@app.delete("/rag/chat/{session_id}/history")
def clear_rag_chat_history(session_id: str) -> dict[str, str]:
    rag_chat.clear_history(session_id)
    return {"session_id": session_id, "status": "cleared"}


@app.post("/rag/knowledge/reindex", status_code=status.HTTP_202_ACCEPTED)
def reindex_knowledge(background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Rebuild the audit knowledge index for every invoice already in the database."""
    invoice_ids = [row[0] for row in db.query(Invoice.id).all()]
    for invoice_id in invoice_ids:
        background_tasks.add_task(_reindex_knowledge, invoice_id)
    return {"queued": len(invoice_ids)}


@app.get("/rules")
def get_validation_rules() -> dict[str, Any]:
    """Expose the configured validation rules so the UI can explain each finding."""
    try:
        return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=503, detail="Validation rules are unavailable.") from exc


@app.get("/ingestion/folder")
def ingestion_folder_status():
    """Report the state of the monitored incoming folder."""
    return folder_watch.watcher_status()


@app.post("/ingestion/folder/scan")
def ingestion_folder_scan(db: Session = Depends(get_db)):
    """Scan the monitored folder now and return every document it currently holds."""
    result = folder_watch.scan_once(process=False)
    result["files"] = _folder_files(db)
    return result


@app.post("/ingestion/folder/upload", status_code=status.HTTP_201_CREATED)
async def ingestion_folder_upload(files: list[UploadFile] = File(...)):
    """Drop uploaded documents into the monitored folder. No processing happens here."""
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one invoice to upload.")
    if len(files) > 25:
        raise HTTPException(status_code=422, detail="Upload at most 25 invoices at a time.")

    saved: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    existing_digests = folder_watch.folder_digests()
    batch_digests: dict[str, str] = {}

    for file in files:
        name = Path((file.filename or "").replace("\\", "/")).name or "unnamed"
        try:
            original_name, _, content, _ = await _validated_upload(file)
        except HTTPException as exc:
            rejected.append({"filename": name, "detail": exc.detail})
            continue

        target_name = original_name[:255]
        digest = hashlib.sha256(content).hexdigest()
        if (INCOMING_DIR / target_name).exists():
            duplicates.append({"filename": target_name, "reason": "a file with this name is already in the monitored folder"})
            continue
        if digest in existing_digests:
            duplicates.append({"filename": target_name, "reason": f"identical content is already in the folder as '{existing_digests[digest]}'"})
            continue
        if digest in batch_digests:
            duplicates.append({"filename": target_name, "reason": f"identical content was already uploaded in this batch as '{batch_digests[digest]}'"})
            continue

        try:
            destination = INCOMING_DIR / target_name
            destination.write_bytes(content)
        except OSError as exc:
            logger.exception("Could not write %s into the incoming folder", original_name)
            rejected.append({"filename": name, "detail": f"The monitored folder is not writable: {exc}"})
            continue
        existing_digests[digest] = destination.name
        batch_digests[digest] = destination.name
        saved.append({"filename": destination.name, "size_bytes": len(content), "path": str(destination)})

    return {"folder": str(INCOMING_DIR), "saved": saved, "duplicates": duplicates, "rejected": rejected}


def _folder_files(db: Session) -> list[dict[str, Any]]:
    """List every document in the monitored folder with its current pipeline state."""
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(
        (path for path in INCOMING_DIR.iterdir() if path.is_file() and not path.name.startswith(".")
         and is_document(path)),
        key=lambda path: path.name.lower(),
    )
    by_path = {
        invoice.stored_path: invoice
        for invoice in db.query(Invoice).filter(Invoice.stored_path.in_([str(path) for path in paths])).all()
    }
    rows: list[dict[str, Any]] = []
    for path in paths:
        stat = path.stat()
        invoice = by_path.get(str(path))
        progress, stage = _progress(invoice) if invoice else (0, "Not registered")
        rows.append({
            "filename": path.name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "extension": path.suffix.lower(),
            "invoice_id": invoice.id if invoice else None,
            "status": invoice.status if invoice else "new",
            "progress": progress,
            "current_stage": stage,
            "error_message": invoice.error_message if invoice else None,
            "metadata_file": (lambda m: m.name if m else None)(find_metadata_file(path)),
        })
    return rows


@app.get("/ingestion/folder/files")
def ingestion_folder_files(db: Session = Depends(get_db)):
    """Every document currently sitting in the monitored folder, with its pipeline state."""
    return {"folder": str(INCOMING_DIR), "files": _folder_files(db)}


@app.post("/ingestion/folder/process", status_code=status.HTTP_202_ACCEPTED)
def ingestion_folder_process(
    background_tasks: BackgroundTasks,
    request: FolderProcessRequest | None = None,
    db: Session = Depends(get_db),
):
    """Run the audit workflow for folder documents that have not been processed yet."""
    folder_watch.scan_once(process=False)
    requested = set(request.filenames) if request and request.filenames else None
    reprocess = bool(request and request.reprocess)

    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in _folder_files(db):
        if requested is not None and row["filename"] not in requested:
            continue
        if not row["invoice_id"]:
            skipped.append({"filename": row["filename"], "reason": "could not be registered"})
            continue
        if row["status"] in {"queued", "processing"}:
            queued.append({"filename": row["filename"], "invoice_id": row["invoice_id"]})
            continue
        if row["status"] == "completed" and not reprocess:
            skipped.append({"filename": row["filename"], "reason": "already processed"})
            continue
        invoice = db.get(Invoice, row["invoice_id"])
        invoice.status = "queued"
        invoice.error_message = None
        db.add(ProcessingEvent(invoice_id=invoice.id, stage="process", message="Processing requested from the monitored folder"))
        db.commit()
        _drop_cached_status(invoice.id)
        background_tasks.add_task(_run_processing, invoice.id)
        queued.append({"filename": row["filename"], "invoice_id": invoice.id})

    return {"queued": queued, "skipped": skipped}
