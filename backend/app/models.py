from __future__ import annotations


 

from datetime import datetime, timezone


 

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy.types import JSON


 

from backend.app.database import Base



 

def utcnow() -> datetime:

    return datetime.now(timezone.utc)



 

class Invoice(Base):

    __tablename__ = "invoices"

    __table_args__ = (UniqueConstraint("sha256", name="uq_invoice_sha256"),)


 

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    stored_path: Mapped[str] = mapped_column(Text, nullable=False)

    content_type: Mapped[str] = mapped_column(String(100), nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", index=True)

    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    extracted: Mapped[ExtractedInvoice | None] = relationship(back_populates="invoice", cascade="all, delete-orphan", uselist=False)

    findings: Mapped[list[ValidationFinding]] = relationship(back_populates="invoice", cascade="all, delete-orphan")

    report: Mapped[AuditReport | None] = relationship(back_populates="invoice", cascade="all, delete-orphan", uselist=False)

    events: Mapped[list[ProcessingEvent]] = relationship(back_populates="invoice", cascade="all, delete-orphan")

    reviews: Mapped[list[ReviewDecision]] = relationship(back_populates="invoice", cascade="all, delete-orphan")



 

class ExtractedInvoice(Base):

    __tablename__ = "extracted_invoices"


 

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), unique=True, nullable=False)

    fields: Mapped[dict] = mapped_column(JSON, nullable=False)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    invoice: Mapped[Invoice] = relationship(back_populates="extracted")



 

class ValidationFinding(Base):

    __tablename__ = "validation_findings"


 

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)

    category: Mapped[str] = mapped_column(String(40), nullable=False)

    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)

    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    invoice: Mapped[Invoice] = relationship(back_populates="findings")



 

class AuditReport(Base):

    __tablename__ = "audit_reports"


 

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), unique=True, nullable=False)

    recommendation: Mapped[str] = mapped_column(String(30), nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)

    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="report")



 

class ProcessingEvent(Base):

    __tablename__ = "processing_events"


 

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)

    stage: Mapped[str] = mapped_column(String(60), nullable=False)

    level: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")

    message: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="events")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)

    decision: Mapped[str] = mapped_column(String(30), nullable=False)

    reviewer: Mapped[str] = mapped_column(String(120), nullable=False, default="human-reviewer")

    note: Mapped[str | None] = mapped_column(Text)

    changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="reviews")



 