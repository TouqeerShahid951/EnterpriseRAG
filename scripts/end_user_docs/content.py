"""Canonical end-user walkthrough copy and reference tables."""

from dataclasses import dataclass


TITLE = "Prudentia AI End User Walkthrough"
SUBTITLE = "Search documents and live data, choose ingestion profiles, verify evidence, and use optional GraphRAG"
UPDATED = "2026-07-07"

@dataclass(frozen=True)
class FeatureRow:
    feature: str
    what_you_do: str
    where: str


FEATURE_ROWS = [
    FeatureRow("Query Intelligence", "Ask questions, watch the retrieval progress, and inspect cited evidence.", "Operate > Query Intelligence"),
    FeatureRow("Knowledge Space selector", "Choose the document scope used for queries and uploads.", "Sidebar header"),
    FeatureRow("Document Library", "Browse, search, inspect, download, and manage visible documents.", "Corpus > Document Library"),
    FeatureRow("Add Files", "Upload PDF, DOCX, JPG, JPEG, PNG, or JSON files and choose an ingestion profile.", "Corpus > Document Intake > Add Files"),
    FeatureRow("Activity", "Track upload, folder, restore, and reingestion jobs.", "Corpus > Document Intake > Activity"),
    FeatureRow("Folder Sources", "Upload local folder snapshots.", "Corpus > Document Intake > Folder Sources"),
    FeatureRow("Database Connectors", "Approve SQL Server or PostgreSQL scopes for live read-only answers.", "Corpus > Document Intake > Database Connectors"),
    FeatureRow("Review Queue", "Resolve OCR blocks and PDF image-analysis holds before indexing continues.", "Evaluate > Review Queue"),
    FeatureRow("System Audit", "Review visible authentication, document, and ingestion activity.", "Govern > System Audit"),
    FeatureRow("User Management", "Create users, reset passwords, assign account types, spaces, and clearance when permitted.", "Govern > User Management"),
    FeatureRow("Runtime Settings", "Assign inference roles, tune services, and manage ingestion controls.", "Govern > Runtime Settings"),
]


ROLE_ROWS = [
    ("Platform Admin", "Full platform ownership: users, spaces, Runtime Settings, RAG Evaluation, audit, connectors, uploads, review, and documents."),
    ("System Admin", "Global operations: users except Platform Admins, spaces, documents, uploads, review, audit, and recovery."),
    ("Space Admin", "Assigned-space administration: scoped users, spaces, uploads, review, folder sources, connectors, and document lifecycle."),
    ("Document Contributor", "Document work: chat, upload, track ingestion, resolve Review Queue items, and maintain writable documents."),
    ("Chat Member", "Everyday use: chat with visible documents, scope questions, inspect evidence, and browse visible library metadata."),
    ("Audit Viewer", "Governance review: inspect visible audit events and metadata without changing system state."),
]


STATUS_ROWS = [
    ("Scheduled", "Waiting for a planned start time."),
    ("Queued", "Accepted and waiting for an ingestion worker."),
    ("Processing", "Being parsed, enriched, chunked, embedded, and indexed."),
    ("Needs review", "Paused for human OCR, extraction, or PDF image review."),
    ("Indexed", "Complete and searchable."),
    ("Failed", "Stopped with an error that needs investigation."),
    ("Cancelled", "Manually stopped before completion."),
]


TROUBLESHOOTING_ROWS = [
    ("A page is missing", "Your account does not have that route.", "Ask an admin to confirm your role and Knowledge Space memberships."),
    ("You cannot query", "The active space has no indexed current documents, or the model runtime is unavailable.", "Switch space, wait for indexing, or report the runtime issue."),
    ("No documents appear", "Wrong active space, insufficient clearance, or no documents are current.", "Check the space selector and ask your workspace admin to verify access."),
    ("Upload is rejected", "Unsupported type, empty file, file over 50 MB, or no writable space.", "Use PDF, DOCX, JPG, JPEG, PNG, or JSON and choose a writable Knowledge Space."),
    ("A document needs review", "OCR, extraction, or PDF image triage paused indexing.", "A Document Contributor, Space Admin, System Admin, or Platform Admin should resolve the pending Review Queue item."),
    ("An ingestion job looks stuck", "Worker heartbeat, parsing, OCR, or model services may be delayed.", "Open Activity or Ingestion Health and share the job ID with operations."),
    ("Source highlight is unavailable", "The source may lack page coordinates or exact text matching.", "Use the original document link and compare page, excerpt, and citation details."),
    ("The answer has a warning", "Sources may conflict, faithfulness may be low, or the response is degraded.", "Inspect citations manually before using the answer."),
    ("No Live DB source appears", "No approved catalog is visible for your space and clearance.", "Ask a connector admin to test the profile and approve the minimum required schema scope."),
    ("Graph enrichment is absent", "GraphRAG was not selected, is disabled, or its worker is unavailable.", "Standard retrieval still works. Check the GraphRAG choice and Ingestion Health when graph analysis is needed."),
]


GLOSSARY_ROWS = [
    ("Knowledge Space", "A document access scope such as /finance or /manuals."),
    ("Current document", "The active version used for retrieval."),
    ("Superseded document", "An older version kept for audit and history."),
    ("Trash", "Soft-deleted documents that can be restored by authorized users."),
    ("Ingestion job", "The background task that parses, enriches, embeds, and indexes a file."),
    ("Citation", "A link between an answer claim and its supporting source evidence."),
    ("Faithfulness", "A grounding check that estimates whether the answer is supported by retrieved evidence."),
    ("Generated artifact", "A downloadable DOCX, PDF, or PPTX produced from a qualifying request."),
    ("Approved database scope", "A reviewed set of database tables, columns, relationships, space, and clearance allowed for live read-only SQL."),
    ("Ingestion profile", "Fast, Balanced, or High accuracy parsing selected for a new document."),
    ("GraphRAG", "Optional entity-and-relationship enrichment for corpus-level themes and patterns."),
]


INGESTION_PROFILE_ROWS = [
    ("Fast", "Native text first, no vision, and capped Docling repair.", "High-volume, text-native files"),
    ("Balanced", "Native text first with a larger Docling repair budget.", "Mixed collections and moderate layout complexity"),
    ("High accuracy", "Deeper layout repair with preference for full-document repair.", "Scans, tables, and fidelity-sensitive layouts"),
]
