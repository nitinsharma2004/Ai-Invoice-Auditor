"""Continuously monitor the incoming folder and ingest new invoice documents.

The project ingests multilingual invoices from a monitored folder: anything dropped
into ``INCOMING_DIR`` (by a user upload, a scanner, a network share or a manual copy)
is registered and pushed through the audit workflow exactly once.
"""

from __future__ import annotations

import hashlib

import logging
import mimetypes
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.database import SessionLocal
from backend.app.models import Invoice, ProcessingEvent
from backend.app.sidecar import is_metadata_file, metadata_for_document
from backend.app.settings import (
    DOCUMENT_EXTENSIONS,
    FOLDER_WATCH_ENABLED,
    FOLDER_WATCH_INTERVAL_SECONDS,
    FOLDER_WATCH_SETTLE_SECONDS,
    INCOMING_DIR,
    MAX_UPLOAD_BYTES,
)

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_state: dict[str, Any] = {
    "running": False,
    "last_scan_at": None,
    "last_error": None,
    "ingested_total": 0,
    "skipped_total": 0,
}
_state_lock = threading.Lock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None
_seen: dict[str, tuple[int, float]] = {}
# Files already registered (or rejected); unchanged entries are skipped without re-reading.
_handled: dict[str, tuple[int, float]] = {}


def _signature(path: Path) -> tuple[int, float] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime)


def unique_destination(directory: Path, filename: str) -> Path:
    """Return a free path inside ``directory`` for ``filename`` without overwriting."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for _ in range(50):
        candidate = directory / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Unable to allocate a unique filename in the incoming folder.")


def folder_digests() -> dict[str, str]:

    """Map the SHA-256 of every document already in the monitored folder to its filename."""

    digests: dict[str, str] = {}

    if not INCOMING_DIR.is_dir():

        return digests

    for path in INCOMING_DIR.iterdir():

        if not _is_candidate(path):

            continue

        try:

            digests.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path.name)

        except OSError:

            continue

    return digests


def _is_candidate(path: Path) -> bool:
    """Only real invoice documents are registered; ``*.meta.json`` is sidecar metadata."""
    if not path.is_file() or path.name.startswith("."):
        return False
    if is_metadata_file(path):
        return False
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


def _is_settled(path: Path) -> bool:
    """Skip files that are still being written: size and mtime must be stable."""
    try:
        stat = path.stat()
    except OSError:
        return False
    if time.time() - stat.st_mtime < FOLDER_WATCH_SETTLE_SECONDS:
        _seen[str(path)] = (stat.st_size, stat.st_mtime)
        return False
    previous = _seen.get(str(path))
    _seen[str(path)] = (stat.st_size, stat.st_mtime)
    return previous is None or previous == (stat.st_size, stat.st_mtime)


def register_file(path: Path, source: str = "folder") -> dict[str, Any]:
    """Register one document from the monitored folder. Returns the outcome."""
    extension = path.suffix.lower()
    if is_metadata_file(path) or extension not in DOCUMENT_EXTENSIONS:
        return {"status": "skipped", "reason": "metadata file, not an invoice document", "path": str(path)}
    content = path.read_bytes()
    if not content:
        return {"status": "skipped", "reason": "empty file", "path": str(path)}
    if len(content) > MAX_UPLOAD_BYTES:
        return {"status": "skipped", "reason": "file exceeds the upload size limit", "path": str(path)}

    metadata, metadata_name = metadata_for_document(path)
    digest = hashlib.sha256(content).hexdigest()
    with SessionLocal() as db:
        existing = db.query(Invoice).filter(Invoice.sha256 == digest).one_or_none()
        if existing:
            return {"status": "duplicate", "invoice_id": existing.id, "path": str(path)}

        invoice_id = str(uuid.uuid4())
        invoice = Invoice(
            id=invoice_id,
            filename=path.name[:255],
            stored_path=str(path),
            content_type=CONTENT_TYPES.get(extension) or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            sha256=digest,
            status="pending",
        )
        try:
            db.add(invoice)
            detected = f"Invoice detected in the monitored folder ({source}); awaiting processing"
            if metadata_name:
                detected += f"; metadata {metadata_name} attached"
            db.add(ProcessingEvent(
                invoice_id=invoice_id,
                stage="upload",
                message=detected,
            ))
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Could not register %s from the monitored folder", path)
            return {"status": "error", "reason": "database registration failed", "path": str(path)}

    return {
        "status": "ingested",
        "invoice_id": invoice_id,
        "path": str(path),
        "filename": path.name,
        "metadata_file": metadata_name,
    }


def scan_once(process: bool = False) -> dict[str, Any]:
    """Scan the monitored folder once and register everything that is not known yet.

    Registration only detects and lists documents; the audit workflow runs when the
    reviewer presses Process (or when ``process=True`` is requested explicitly).
    """
    from backend.app.workflow import process_invoice

    results: list[dict[str, Any]] = []
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INCOMING_DIR.iterdir()):
        if not _is_candidate(path):
            continue
        signature = _signature(path)
        if signature is not None and _handled.get(str(path)) == signature:
            continue
        if not _is_settled(path):
            continue
        try:
            outcome = register_file(path)
        except OSError as exc:
            outcome = {"status": "error", "reason": str(exc), "path": str(path)}
        if outcome["status"] != "error":
            _handled[str(path)] = signature or (0, 0.0)
        results.append(outcome)
        if outcome["status"] == "ingested" and process:
            try:
                process_invoice(outcome["invoice_id"])
            except Exception:  # noqa: BLE001 - the workflow records its own failure state
                logger.exception("Processing failed for folder invoice %s", outcome["invoice_id"])

    present = {str(path) for path in INCOMING_DIR.iterdir()}
    for cache in (_seen, _handled):
        for stale in [key for key in cache if key not in present]:
            cache.pop(stale, None)

    ingested = [item for item in results if item["status"] == "ingested"]
    with _state_lock:
        _state["last_scan_at"] = datetime.now(timezone.utc).isoformat()
        _state["ingested_total"] += len(ingested)
        _state["skipped_total"] += len(results) - len(ingested)
    return {
        "folder": str(INCOMING_DIR),
        "ingested": ingested,
        "skipped": [item for item in results if item["status"] not in {"ingested"}],
    }


def mark_registered(path: Path) -> None:
    """Remember a file the API already registered so the watcher does not re-read it."""
    signature = _signature(path)
    if signature is None:
        return
    _seen[str(path)] = signature
    _handled[str(path)] = signature


def _watch_loop() -> None:
    while not _stop_event.is_set():
        try:
            scan_once()
            with _state_lock:
                _state["last_error"] = None
        except Exception as exc:  # noqa: BLE001 - the watcher must never die
            logger.exception("Folder watch scan failed")
            with _state_lock:
                _state["last_error"] = str(exc)
        _stop_event.wait(FOLDER_WATCH_INTERVAL_SECONDS)


def start_watcher() -> None:
    global _thread
    if not FOLDER_WATCH_ENABLED:
        logger.info("Folder monitoring is disabled (FOLDER_WATCH_ENABLED=false).")
        return
    if _thread and _thread.is_alive():
        return
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    _stop_event.clear()
    _thread = threading.Thread(target=_watch_loop, name="incoming-folder-watch", daemon=True)
    _thread.start()
    with _state_lock:
        _state["running"] = True
    logger.info("Monitoring %s for new invoices every %ss", INCOMING_DIR, FOLDER_WATCH_INTERVAL_SECONDS)


def stop_watcher() -> None:
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)
    with _state_lock:
        _state["running"] = False


def watcher_status() -> dict[str, Any]:
    with _state_lock:
        snapshot = dict(_state)
    pending = 0
    if INCOMING_DIR.is_dir():
        pending = sum(1 for path in INCOMING_DIR.iterdir() if _is_candidate(path))
    snapshot.update({
        "enabled": FOLDER_WATCH_ENABLED,
        "folder": str(INCOMING_DIR),
        "interval_seconds": FOLDER_WATCH_INTERVAL_SECONDS,
        "files_in_folder": pending,
        "accepted_extensions": sorted(DOCUMENT_EXTENSIONS),
    })
    return snapshot
