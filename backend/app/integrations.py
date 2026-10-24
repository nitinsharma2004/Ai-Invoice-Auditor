from __future__ import annotations


 

import re

from functools import lru_cache

from math import isfinite

from typing import Any


 

from dotenv import load_dotenv

import httpx

import redis

import yaml

from botocore.exceptions import BotoCoreError

from langchain_aws import BedrockEmbeddings, ChatBedrockConverse

from langchain_core.documents import Document

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_qdrant import QdrantVectorStore

from qdrant_client import QdrantClient, models as qdrant_models

from qdrant_client.http.exceptions import UnexpectedResponse

# from ragas import evaluate

# from ragas.dataset_schema import EvaluationDataset

# from ragas.embeddings import LangchainEmbeddingsWrapper

# from ragas.llms import LangchainLLMWrapper

# from ragas.metrics import answer_relevancy, faithfulness


 

from backend.app.schemas import InvoiceFields

from backend.app.settings import (

    AWS_REGION,

    BEDROCK_CHAT_MODEL_ID,

    BEDROCK_EMBEDDING_MODEL_ID,

    ERP_API_URL,

    QDRANT_COLLECTION,

    QDRANT_URL,

    REDIS_CACHE_TTL_SECONDS,

    RULES_PATH,

    REDIS_URL,

)


 

class BedrockConfigurationError(RuntimeError):

    pass



 

class InvoiceQueryError(RuntimeError):

    pass



 

def _require_bedrock() -> tuple[str, str, str]:

    if not AWS_REGION or not BEDROCK_CHAT_MODEL_ID or not BEDROCK_EMBEDDING_MODEL_ID:

        raise BedrockConfigurationError(

            "AWS Bedrock is not configured. Set AWS_REGION, BEDROCK_CHAT_MODEL_ID, "

            "and BEDROCK_EMBEDDING_MODEL_ID, and configure AWS credentials."

        )

    return AWS_REGION, BEDROCK_CHAT_MODEL_ID, BEDROCK_EMBEDDING_MODEL_ID



 

def get_chat_model() -> ChatBedrockConverse:

    region, model_id, _ = _require_bedrock()

    from dotenv import load_dotenv

    load_dotenv()

    return ChatBedrockConverse(model=model_id, region_name=region, temperature=0)




 

def get_embeddings() -> BedrockEmbeddings:

    region, _, model_id = _require_bedrock()

   
    return BedrockEmbeddings(model_id=model_id, region_name=region)


def get_vector_store() -> QdrantVectorStore:

    embeddings = get_embeddings()

    client = QdrantClient(url=QDRANT_URL, timeout=10)

    if not client.collection_exists(QDRANT_COLLECTION):

        vector_size = len(embeddings.embed_query("invoice auditor"))

        client.create_collection(

            collection_name=QDRANT_COLLECTION,

            vectors_config=qdrant_models.VectorParams(

                size=vector_size,

                distance=qdrant_models.Distance.COSINE,

            ),

        )

    return QdrantVectorStore(client=client, collection_name=QDRANT_COLLECTION, embedding=embeddings)



 

def index_invoice(

    invoice_id: str,

    filename: str,

    raw_text: str,

    document_type: str,

    pages: list[dict[str, Any]] | None = None,

) -> int:

    splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=120)

    page_chunks = [

        (page.get("page", number), chunk)

        for number, page in enumerate(pages or [{"page": 1, "text": raw_text}], start=1)

        for chunk in splitter.split_text(str(page.get("text", "")))

    ]

    if not page_chunks:

        return 0

    store = get_vector_store()

    store.client.delete(

        collection_name=QDRANT_COLLECTION,

        points_selector=qdrant_models.FilterSelector(

            filter=qdrant_models.Filter(

                must=[

                    qdrant_models.FieldCondition(

                        key="metadata.invoice_id",

                        match=qdrant_models.MatchValue(value=invoice_id),

                    )

                ]

            )

        ),

    )

    docs = []

    for index, (page_number, chunk) in enumerate(page_chunks):

        docs.append(Document(

            page_content=chunk,

            metadata={"invoice_id": invoice_id, "filename": filename, "document_type": document_type, "chunk": index, "page": page_number},

        ))

    store.add_documents(docs)

    return len(docs)


def index_invoice_knowledge(invoice_id: str, filename: str, knowledge_text: str) -> int:
    """Index the audit knowledge (status, findings, decision) of a single invoice."""
    if not knowledge_text or not knowledge_text.strip():
        return 0

    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    chunks = splitter.split_text(knowledge_text)
    if not chunks:
        return 0

    store = get_vector_store()
    store.client.delete(
        collection_name=QDRANT_COLLECTION,
        points_selector=qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="metadata.invoice_id",
                        match=qdrant_models.MatchValue(value=invoice_id),
                    ),
                    qdrant_models.FieldCondition(
                        key="metadata.document_type",
                        match=qdrant_models.MatchValue(value="audit_knowledge"),
                    ),
                ]
            )
        ),
    )

    store.add_documents([
        Document(
            page_content=chunk,
            metadata={
                "invoice_id": invoice_id,
                "filename": filename,
                "document_type": "audit_knowledge",
                "chunk": index,
                "page": 0,
            },
        )
        for index, chunk in enumerate(chunks)
    ])
    return len(chunks)


def retrieve_invoice_chunks(
    question: str,
    invoice_id: str | None = None,
    k: int = 5,
    score_threshold: float = 0.15,
) -> list[dict[str, Any]]:

    store = get_vector_store()

    qfilter = None

    if invoice_id:

        qfilter = qdrant_models.Filter(

            must=[qdrant_models.FieldCondition(key="metadata.invoice_id", match=qdrant_models.MatchValue(value=invoice_id))]

        )

    matches = store.similarity_search_with_score(question, k=k, filter=qfilter)

    relevant = [(document, score) for document, score in matches if score >= score_threshold]

    return [

        {

            "filename": document.metadata.get("filename"),

            "invoice_id": document.metadata.get("invoice_id"),

            "chunk": document.metadata.get("chunk"),

            "document_type": document.metadata.get("document_type"),

            "page": document.metadata.get("page"),

            "score": float(score),

            "text": document.page_content,

        }

        for document, score in relevant

    ]



 

def query_invoice(question: str, invoice_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:

    try:

        sources = retrieve_invoice_chunks(question, invoice_id)

    except (httpx.HTTPError, UnexpectedResponse) as exc:

        raise InvoiceQueryError("Could not retrieve evidence from Qdrant.") from exc

    if not sources:

        return "I could not find relevant invoice evidence for this question.", []

    contexts = "\n\n".join(

        f"Source: {source.get('filename')}, invoice_id: {source.get('invoice_id')}, page: {source.get('page')}\n{source['text']}"

        for source in sources

    )

    try:

        response = get_chat_model().invoke(

            "Answer only from the evidence below. If it does not answer the question, say so. "

            "Cite source filenames and invoice identifiers.\n\n"

            f"Evidence:\n{contexts}\n\nQuestion: {question}"

        )

    except BotoCoreError as exc:

        raise InvoiceQueryError("Could not generate an answer with AWS Bedrock.") from exc

    return str(response.content), sources



 

def generate_audit_summary(

    invoice_fields: dict,

    findings: list[dict],

    erp_data: dict,

    evidence: list[dict[str, Any]] | None = None,

    quality_feedback: dict[str, float] | None = None,

) -> str:

    feedback = ""

    if quality_feedback:

        feedback = (

            "\nThe previous draft did not meet the quality threshold "

            f"(faithfulness={quality_feedback['faithfulness']:.2f}, "

            f"answer_relevancy={quality_feedback['answer_relevancy']:.2f}). "

            "Revise it to be fully supported by the supplied facts and directly relevant. "

            "Do not add facts."

        )

    response = get_chat_model().invoke(

        "Write a concise invoice audit summary using only the supplied structured information. "

        "Use retrieved evidence only as supporting context. Do not claim approval when errors or missing data exist.\n"

        f"Invoice: {invoice_fields}\nFindings: {findings}\nERP match: {erp_data}\nEvidence: {evidence or []}"

        f"{feedback}"

    )

    return str(response.content)



 

# def evaluate_audit_summary(

#     question: str,

#     summary: str,

#     contexts: list[str],

# ) -> dict[str, float]:

#     dataset = EvaluationDataset.from_list([{

#         "user_input": question,

#         "response": summary,

#         "retrieved_contexts": contexts,

#     }])

#     result = evaluate(

#         dataset,

#         metrics=[faithfulness, answer_relevancy],

#         llm=LangchainLLMWrapper(get_chat_model()),

#         embeddings=LangchainEmbeddingsWrapper(get_embeddings()),

#     )

#     scores = result.to_pandas().mean(numeric_only=True).to_dict()

#     validated = {

#         metric: float(scores[metric])

#         for metric in ("faithfulness", "answer_relevancy")

#     }

#     if any(not isfinite(score) or not 0 <= score <= 1 for score in validated.values()):

#         raise ValueError("RAGAS returned invalid quality scores.")

#     return validated


 

from typing import Any


 

def translate_invoice_text(text: str) -> str:

    """Translate invoice text into English using the configured chat model."""

    if not text or not text.strip():

        return text


 

    response = get_chat_model().invoke(

        "Translate the following invoice text into English.\n"

        "Translate all readable headings, labels, descriptions, and sentences.\n"

        "If the text is already English, return it unchanged.\n"

        "Preserve company names, invoice numbers, item codes, dates, "

        "numeric values, currency amounts, and the original line structure "

        "where possible. Do not omit information, summarize, or invent facts.\n"

        "Return only the translated invoice text, without explanations.\n\n"

        f"Invoice text:\n{text}"

    )


 

    content = response.content


 

    if not isinstance(content, str):

        raise ValueError("The translation model returned unexpected content.")


 

    translated = content.strip()


 

    if not translated:

        raise ValueError("The translation model returned empty text.")


 

    return translated



 

def extract_invoice_fields(text: str) -> InvoiceFields:

    """Extract structured invoice fields from invoice text."""

    structured_model = get_chat_model().with_structured_output(

        InvoiceFields

    )


 

    fields = structured_model.invoke(

        "Extract invoice header fields and line items from the document below. "

        "Use null for values that are not present. Preserve company names, "

        "invoice identifiers, dates, amounts, currencies, and item codes. "

        "Set detected_language to the language of the provided document. "

        "Do not infer missing values.\n\n"

        f"Document:\n{text}"

    )


 

    # if isinstance(fields, dict):

    #     fields = InvoiceFields.model_validate(fields)


 

    if fields.additional_fields is None:

        fields = fields.model_copy(

            update={"additional_fields": {}}

        )


 

    return fields



 

@lru_cache(maxsize=1)

def get_redis_client() -> redis.Redis:

    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)



 

def list_erp_vendors() -> list[dict]:

    """Fetch the ERP vendor master so vendors can be resolved by name."""

    cache = get_redis_client()

    cache_key = "erp:vendors:all"

    import json

    try:

        cached = cache.get(cache_key)

        if cached:

            return json.loads(cached)

    except redis.RedisError:

        pass

    try:

        with httpx.Client(base_url=ERP_API_URL, timeout=5) as client:

            response = client.get("/api/erp/vendors")

        response.raise_for_status()

        data = response.json()

    except (httpx.HTTPError, ValueError):

        return []

    vendors = data.get("vendors", data) if isinstance(data, dict) else data

    if not isinstance(vendors, list):

        return []

    try:

        cache.setex(cache_key, REDIS_CACHE_TTL_SECONDS, json.dumps(vendors))

    except redis.RedisError:

        pass

    return vendors


 

def _vendor_key(value: str) -> str:

    """Normalise a company name so 'Global Logistics Ltd.' matches 'Global Logistics Ltd'."""

    import re as _re

    cleaned = _re.sub(r"[^a-z0-9 ]+", " ", str(value).lower())

    cleaned = _re.sub(r"\b(ltd|limited|llc|inc|incorporated|gmbh|sa|sl|srl|bv|nv|plc|co|company|corp|corporation|pvt|private)\b", " ", cleaned)

    return " ".join(cleaned.split())


 

def resolve_vendor_by_name(vendor_name: str | None) -> dict | None:

    """Find the ERP vendor record matching an invoice's vendor name.

    Invoices print the trading name, not the ERP vendor id, so the id has to be

    resolved from the vendor master before the invoice can be matched.

    """

    if not vendor_name:

        return None

    target = _vendor_key(vendor_name)

    if not target:

        return None

    for vendor in list_erp_vendors():

        if not isinstance(vendor, dict):

            continue

        candidate = _vendor_key(vendor.get("vendor_name", ""))

        if candidate and (candidate == target or candidate in target or target in candidate):

            return vendor

    return None


 

def get_erp_record(kind: str, identifier: str | None) -> dict | None:

    if not identifier:

        return None

    cache = get_redis_client()

    cache_key = f"erp:{kind}:{identifier.upper()}"

    try:

        cached = cache.get(cache_key)

        if cached:

            import json

            return json.loads(cached)

    except redis.RedisError:

        pass

    from urllib.parse import quote

    encoded_identifier = quote(identifier, safe="")

    path = {"po": f"/api/erp/po/{encoded_identifier}", "vendor": f"/api/erp/vendor/{encoded_identifier}",

            "sku": f"/api/erp/sku/{encoded_identifier}"}[kind]

    with httpx.Client(base_url=ERP_API_URL, timeout=5) as client:

        response = client.get(path)

    if response.status_code == 404:

        return None

    response.raise_for_status()

    data = response.json()

    try:

        import json

        cache.setex(cache_key, REDIS_CACHE_TTL_SECONDS, json.dumps(data))

    except redis.RedisError:

        pass

    return data



 

# def extract_fields_from_text(text: str) -> InvoiceFields:

#     def find(pattern: str) -> str | None:

#         match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)

#         return match.group(1).strip() if match else None


 

#     def amount(pattern: str) -> float | None:

#         value = find(pattern)

#         if not value:

#             return None

#         try:

#             return float(value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("₹", ""))

#         except ValueError:

#             return None


 

#     currency = find(r"\b(USD|EUR|INR|GBP)\b")

#     if not currency:

#         symbol = find(r"([$€£₹])")

#         rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}

#         currency = rules.get("currency_symbol_map", {}).get(symbol or "")

#     return InvoiceFields(

#         invoice_no=find(r"(?:invoice(?:\s*(?:no|number|#))?|bill\s*no)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]+)"),

#         invoice_date=find(

#             r"(?:invoice\s*date|date)\s*[:#-]?\s*("

#             r"[0-9]{1,4}[./-][0-9]{1,2}[./-][0-9]{1,4}"

#             r"|[0-9]{1,2}[-/ ](?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"

#             r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"

#             r"dec(?:ember)?)[-/ ]?[0-9]{2,4}"

#             r"|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"

#             r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"

#             r"dec(?:ember)?)\s+[0-9]{1,2},?\s+[0-9]{4})"

#         ),

#         po_number=find(r"(?:purchase\s*order|po(?:\s*(?:number|no|#))?)\s*[:#-]?\s*(PO[- ]?[A-Z0-9-]+)"),

#         vendor_id=find(r"\b(VEND[- ]?[A-Z0-9-]+)\b"),

#         currency=currency,

#         total_amount=amount(r"\b(?:grand\s*)?total\b(?:\s*amount)?\s*[:=]?\s*[$€£₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)"),

#         tax_amount=amount(r"(?:tax|gst|vat)(?:\s*amount)?\s*[:=]?\s*[$€£₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)"),

#         subtotal=amount(r"sub\s*total\s*[:=]?\s*[$€£₹]?\s*([0-9,]+(?:\.[0-9]{1,2})?)"),

#     )


 