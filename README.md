# AI Invoice Auditor — Intelligent Invoice Validation & Auditing System

An AI-powered invoice auditing system that automates invoice processing, extracts important information from invoices, validates invoice data against business rules and ERP records, and generates audit reports using an agentic AI workflow.

The system combines **LangGraph, Retrieval-Augmented Generation (RAG), FastAPI, PostgreSQL, Qdrant, Redis, AWS Bedrock, and Streamlit** to create a modular, containerized invoice auditing solution.

## Overview

Manual invoice auditing can be time-consuming and prone to human error. Invoices must be checked against purchase orders, vendor records, business policies, and other financial information before approval.

The AI Invoice Auditor automates this process by processing uploaded invoices, extracting relevant fields, performing validation checks, retrieving supporting policy information, and producing an audit result.

### Key Features

- **Automated Invoice Processing:** Upload and process invoices through the Streamlit interface.
- **Invoice Data Extraction:** Extract invoice numbers, vendor details, dates, amounts, and other relevant fields from invoice documents.
- **Business Rule Validation:** Validate extracted information against configurable rules defined in `rules.yml`.
- **ERP Validation:** Compare invoice information with purchase orders and other records available through the Mock ERP service.
- **RAG-Based Policy Retrieval:** Retrieve relevant policy documents and contextual information using embeddings and Qdrant.
- **Agentic Workflow:** Use LangGraph to coordinate extraction, validation, and report-generation stages.
- **Audit Reporting:** Generate findings and determine whether invoices should be approved, rejected, or sent for further review according to the configured rules.
- **Duplicate Detection:** Use invoice file hashes and database constraints to help identify duplicate submissions.
- **Persistent Storage:** Store invoice records, audit findings, and workflow-related data in PostgreSQL.
- **Containerized Deployment:** Run the application's services using Docker Compose.
- **Interactive User Interface:** Use Streamlit to upload invoices and review audit outcomes.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| LangGraph | Orchestration of the invoice auditing workflow |
| FastAPI | Backend API and invoice-processing endpoints |
| Streamlit | User interface for uploading and reviewing invoices |
| AWS Bedrock | Foundation model access for AI-powered processing |
| RAG | Retrieval of relevant policy and contextual information |
| Embeddings | Convert text into vector representations for semantic search |
| Qdrant | Vector database for retrieving relevant information |
| PostgreSQL | Persistent storage for invoice and audit data |
| SQLAlchemy | Database models and data access |
| Redis | Backend support for workflow infrastructure and related operations |
| Mock ERP | Simulated ERP API for purchase-order and business-data validation |
| Docker | Containerization of application services |
| Docker Compose | Service orchestration and networking |
| YAML | Configuration of business validation rules |

## System Architecture

The application consists of six primary services:

| Service | Responsibility | Default Port |
|---|---|---|
| Streamlit | User interface and invoice submission | `8501` |
| FastAPI Agent | Invoice processing and workflow API | `8000` |
| Mock ERP | Simulated ERP records and validation endpoints | `8001` |
| PostgreSQL | Relational database and persistent application data | `5432` |
| Qdrant | Vector storage and semantic retrieval | `6333` |
| Redis | Workflow infrastructure and supporting operations | `6379` |

Ports are the default or configured service ports; actual host exposure depends on your Docker Compose configuration.

### Architecture Flow

```text
                 User
                  |
                  v
           Streamlit UI
                  |
                  v
            FastAPI Agent
                  |
                  v
           LangGraph Workflow
                  |
          +-------+--------+
          |       |        |
          v       v        v
      Extraction Validation Report
          |       |        |
          |       +--------+------+
          |                        |
          v                        v
       RAG / Qdrant             Mock ERP
          |                        |
          v                        v
    Policy Context          PO / ERP Records
          |                        |
          +------------+-----------+
                       |
                       v
               Audit Findings
                       |
                       v
                  PostgreSQL
                       |
                       v
                Audit Results
                       |
                       v
                  Streamlit UI
```

PostgreSQL, Redis, Qdrant, and Mock ERP are separate services. Docker Compose provides service-to-service networking so the containers can communicate using their service names.

## Invoice Auditing Workflow

### 1. Invoice Ingestion

The user uploads an invoice through Streamlit. The backend accepts the file, performs applicable file checks, and starts invoice processing.

The system can also support folder-based invoice ingestion when configured.

### 2. Invoice Information Extraction

The extraction stage processes the invoice and identifies relevant fields, such as:

- Invoice number
- Vendor name and details
- Invoice date and due date
- Purchase order number
- Line items and quantities
- Subtotal, tax, and total amount

The exact fields extracted depend on the invoice content and the configured extraction logic.

### 3. RAG-Based Context Retrieval

The RAG component retrieves relevant policy or reference information for the auditing process.

The general flow is:

1. Prepare the relevant text and document chunks.
2. Generate embeddings for the text.
3. Store or retrieve vectors through Qdrant.
4. Search for relevant information.
5. Supply retrieved context to the appropriate AI processing stage.

RAG provides contextual information; it does not replace deterministic business-rule or ERP validation.

### 4. Business Rule Validation

The system validates extracted invoice information against configurable business rules maintained in `rules.yml`.

Depending on the configured rules, checks can include:

- Required-field validation
- Invoice amount validation
- Vendor-related rules
- Date and consistency checks
- Other company-specific validation policies

Separating business rules from application code makes it easier to update validation policies without rewriting the entire workflow.

### 5. ERP Validation

The backend communicates with the Mock ERP service to validate invoice information against simulated enterprise records.

Examples include:

- Checking whether a purchase order exists.
- Comparing invoice details with purchase order information.
- Checking relevant vendor or order data.
- Identifying mismatches between the invoice and ERP records.

The ERP service simulates external enterprise-system interactions and can be replaced with an actual ERP integration in a future deployment.

### 6. Audit Report Generation

The report-generation stage combines relevant extraction results, validation findings, and policy information to produce an audit outcome.

Depending on the configured validation logic, an invoice may be:

- **Approved:** No blocking validation issues were identified.
- **Rejected:** A blocking validation failure was identified.
- **Needs Review:** Further verification or manual intervention is required.

The final outcome depends on the implemented validation and reporting rules. Advisory findings can be treated differently from blocking failures.

### 7. Persistence and Results

The application persists invoice and audit information in PostgreSQL. The user can review the processing results and associated findings through the Streamlit interface.

Duplicate detection can use a file's SHA-256 hash together with database constraints to help prevent repeated submissions from being treated as entirely new documents.

## LangGraph Workflow

LangGraph coordinates the main processing stages and passes relevant state between nodes.

A simplified representation is:

```text
START
  |
  v
Extraction Node
  |
  v
Validation Node
  |
  v
Report Node
  |
  v
Persist / Return Results
  |
  v
END
```

The workflow can use shared state to pass extracted invoice fields, validation findings, and error information between stages.

The key responsibilities are:

- **Extraction Node:** Extract structured information from the invoice.
- **Validation Node:** Apply business rules and check relevant ERP records and supporting context.
- **Report Node:** Consolidate findings and determine the audit outcome.
- **Persistence:** Save the relevant invoice and audit information through the application's database layer.

The exact graph edges and persistence behavior depend on the implementation.

## Project Structure

The following is a representative structure. Adapt the paths to match the actual directories in your repository.

```text
invoice-auditor/
├── agent/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   └── ...
│   ├── Dockerfile
│   └── requirements.txt
├── streamlit/
│   ├── app.py
│   └── Dockerfile
├── mockerp/
│   ├── ...
│   └── Dockerfile
├── rules.yml
├── docker-compose.yml
├── langgraph.json
├── .env.example
├── .gitignore
└── README.md
```

## Prerequisites

Install the following tools before running the project:

- Python 3.11 or the version specified by your project
- Docker Desktop
- Docker Compose
- AWS credentials and access to the configured Bedrock model
- Git

## Installation and Setup

### 1. Clone the Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd invoice-auditor
```

Replace the repository URL and directory name with your actual values.

### 2. Configure Environment Variables

Create a `.env` file in the location expected by your Docker Compose configuration.

Example configuration:

```env
# PostgreSQL
POSTGRES_DB=invoice_auditor
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change_me

# Agent database connection
DATABASE_URL=postgresql://postgres:change_me@postgres:5432/invoice_auditor

# Redis
REDIS_URL=redis://redis:6379/0

# Qdrant
QDRANT_URL=http://qdrant:6333

# Mock ERP
ERP_API_URL=http://mockerp:8001

# AWS Bedrock
AWS_REGION=<YOUR_AWS_REGION>
AWS_ACCESS_KEY_ID=<YOUR_AWS_ACCESS_KEY_ID>
AWS_SECRET_ACCESS_KEY=<YOUR_AWS_SECRET_ACCESS_KEY>
```

These are illustrative settings. Use the actual environment variable names, database configuration, AWS authentication method, and model settings required by your code. If your application uses an AWS profile or IAM role, configure that instead of storing access keys in `.env`.

**Security:** Never commit `.env`, AWS credentials, API keys, or passwords to GitHub.

### 3. Start the Application

From the directory containing `docker-compose.yml`, run:

```bash
docker compose up --build -d
```

Check the running services:

```bash
docker compose ps
```

View the logs:

```bash
docker compose logs -f
```

View logs for a specific service:

```bash
docker compose logs -f agent
docker compose logs -f streamlit
docker compose logs -f mockerp
```

Use the actual service names from your Compose file if they differ.

### 4. Access the Application

Once the services are healthy and running, open the configured Streamlit URL in your browser:

```text
http://localhost:8501
```

The FastAPI backend will typically be available at:

```text
http://localhost:8000
```

If FastAPI's Swagger documentation is enabled:

```text
http://localhost:8000/docs
```

Qdrant's HTTP API is typically available at:

```text
http://localhost:6333
```

These URLs assume the corresponding ports are published to the host by Docker Compose.

### 5. Stop the Application

```bash
docker compose down
```

To remove the Compose-managed volumes as well:

```bash
docker compose down -v
```

**Warning:** Removing volumes can permanently delete persisted database or vector-store data. Do not use the second command when you need to preserve existing data.

## Configuration

### Business Rules

The `rules.yml` file defines configurable validation policies used by the auditing workflow.

Example of a simplified rule format:

```yaml
validation_policies:
  required_fields:
    - vendor_name
    - invoice_date
    - total_amount
```

This is an illustrative example, not necessarily the exact schema used by your project. Use the keys and structure supported by your actual validation code.

### Mock ERP Data

The Mock ERP service provides simulated enterprise records for testing invoice validation.

It can represent purchase orders and related ERP information against which extracted invoice data is compared.

Use the sample data and API endpoints provided in your repository to test matching and mismatching invoices.

### RAG and Vector Storage

Qdrant stores vector representations used for semantic retrieval. The retrieval component finds relevant contextual information to support invoice auditing.

The quality of retrieval depends on document preparation, chunking, embedding selection, and the retrieval configuration.

### Database

PostgreSQL stores relational application data. The application uses SQLAlchemy for database models and database operations.

The deployment can also use PostgreSQL schemas to separate application concerns, depending on the configured database setup.

## Testing the Project

Use representative invoices to verify the main workflow.

Suggested test scenarios:

| Test Scenario | Expected Behavior |
|---|---|
| Valid invoice | Passes the configured blocking validations |
| Missing required field | Produces a validation finding |
| Invalid purchase order | Reports an ERP validation issue |
| Invoice amount mismatch | Identifies the applicable mismatch |
| Duplicate invoice file | Detects a repeated file where duplicate checks apply |
| Advisory policy issue | Records the advisory finding according to configured rules |
| Unreadable or invalid file | Handles the processing error appropriately |
| ERP service unavailable | Handles the service failure according to the implemented error logic |

The actual outcome depends on the configured rules, invoice content, and error-handling behavior.

## Error Handling and Reliability

The project separates invoice extraction, validation, reporting, and persistence into distinct stages. This makes the workflow easier to maintain and debug.

Important considerations include:

- Handling malformed or unreadable invoice documents.
- Handling missing or incorrectly extracted fields.
- Distinguishing advisory findings from blocking validation failures.
- Handling ERP API errors and unavailable services.
- Handling database connection failures.
- Logging relevant processing information for troubleshooting.
- Avoiding duplicate processing when the same invoice file is submitted again.

AI-generated extraction results should be validated before they are used for business decisions.

## Future Enhancements

Potential improvements include:

- Integration with a real ERP system.
- Human-in-the-loop review for uncertain or disputed invoices.
- More comprehensive invoice-format support.
- Improved duplicate and fraud detection.
- Detailed audit history and reporting dashboards.
- Automated evaluation of extraction and retrieval quality.
- Authentication and role-based access control.
- Deployment to a cloud environment with production-grade secrets management and monitoring.

## Learning Outcomes

This project demonstrates practical experience with:

- Agentic AI and LangGraph workflow orchestration.
- Retrieval-Augmented Generation and vector search.
- LLM-powered document processing.
- REST API development using FastAPI.
- Database design and ORM operations using SQLAlchemy.
- Relational and vector database integration.
- Docker-based multi-service application deployment.
- Business-rule validation and external API integration.
- Building an interactive AI application with Streamlit.

## Author

**Nitin Sharma**

Computer Science and Engineering | AI, Agentic AI, and Generative AI

GitHub: [Your GitHub Profile](https://github.com/)

LinkedIn: [Your LinkedIn Profile](https://www.linkedin.com/)

---

*Disclaimer: This project is intended for learning, development, and demonstration purposes. Audit results should be reviewed according to the requirements of the organization using the system.*
