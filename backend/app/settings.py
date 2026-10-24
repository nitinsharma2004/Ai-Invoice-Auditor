
 

from __future__ import annotations


 

import os

from pathlib import Path


 

from dotenv import load_dotenv


 

# Find the project root based on this Python file's location.

PROJECT_ROOT = Path(__file__).resolve().parents[2]


 

# Load the .env file from the project root.

load_dotenv(PROJECT_ROOT / ".env")


 

DATA_ROOT = Path(

    os.getenv("SAMPLE_DATA_DIR", str(PROJECT_ROOT / "backend" / "data"))

).resolve()


 

RULES_PATH = Path(

    os.getenv("RULES_PATH", str(PROJECT_ROOT / "backend" / "config" / "rules.yml"))

).resolve()


 

RUNTIME_DIR = PROJECT_ROOT / "runtime"

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


 

UPLOAD_DIR = Path(

    os.getenv("UPLOAD_DIR", str(RUNTIME_DIR / "uploads"))

).resolve()

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


 

# Folder that is continuously monitored for new invoice documents.

INCOMING_DIR = Path(

    os.getenv("INCOMING_DIR", str(DATA_ROOT / "incoming"))

).resolve()


 

FOLDER_WATCH_ENABLED = os.getenv("FOLDER_WATCH_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}

FOLDER_WATCH_INTERVAL_SECONDS = max(2, int(os.getenv("FOLDER_WATCH_INTERVAL_SECONDS", "10")))

# A file must stop changing for this long before it is ingested, so half-copied files are skipped.

FOLDER_WATCH_SETTLE_SECONDS = max(1, int(os.getenv("FOLDER_WATCH_SETTLE_SECONDS", "3")))


 

DATABASE_URL = os.getenv("DATABASE_URL")


 

if not DATABASE_URL and os.getenv("DB_HOST"):

    from sqlalchemy import URL


 

    DATABASE_URL = URL.create(

        "postgresql+psycopg",

        username=os.getenv("DB_USER", "invoice_auditor"),

        password=os.getenv("DB_PASSWORD", ""),

        host=os.getenv("DB_HOST", "localhost"),

        port=int(os.getenv("DB_PORT", "5432")),

        database=os.getenv("DB_NAME", "invoice_auditor"),

    )


 

if not DATABASE_URL:

    DATABASE_URL = f"sqlite:///{RUNTIME_DIR / 'invoice_auditor.db'}"


 

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

ERP_API_URL = os.getenv("ERP_API_URL", "http://localhost:8001")


 

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "")

BEDROCK_CHAT_MODEL_ID = os.getenv("BEDROCK_CHAT_MODEL_ID", "")

BEDROCK_EMBEDDING_MODEL_ID = os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "")


 

QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "invoice_chunks")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))

# Invoice documents: the only file types an invoice is extracted from.

DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx"}

# Sidecar metadata describing a document (email sender, subject, language...).

# These are never invoices on their own; they are merged into the invoice they name.

METADATA_SUFFIX = ".meta.json"

METADATA_EXTENSIONS = {".json"}

ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | METADATA_EXTENSIONS

REDIS_CACHE_TTL_SECONDS = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "120"))


 

