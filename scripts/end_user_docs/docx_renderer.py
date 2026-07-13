"""Compose the end-user walkthrough as a DOCX document."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from .content import (
    FEATURE_ROWS,
    GLOSSARY_ROWS,
    INGESTION_PROFILE_ROWS,
    ROLE_ROWS,
    STATUS_ROWS,
    TROUBLESHOOTING_ROWS,
)
from .docx_components import (
    CAUTION_FILL,
    add_bullets,
    add_docx_cover,
    add_h1,
    add_h2,
    add_note_box,
    add_numbered_list,
    add_para,
    add_table,
    configure_docx_page,
    configure_docx_styles,
    save_docx,
)


def build_docx(path: Path) -> None:
    doc = Document()
    configure_docx_page(doc)
    configure_docx_styles(doc)
    add_docx_cover(doc)

    add_h1(doc, "How to Use This Guide")
    add_note_box(
        doc,
        "Your sidebar is permission-aware. If a feature described here does not appear, your account does not include that permission. Connector governance and Runtime Settings are included for administrators who can see those pages.",
    )
    add_numbered_list(
        doc,
        [
            "Sign in with your workspace email and password.",
            "Check the active Knowledge Space in the sidebar header.",
            "Open Query Intelligence and ask a focused question.",
            "Inspect citations before relying on an answer.",
            "Use Add Files, Activity, Review Queue, or Audit only when those pages appear in your sidebar.",
        ],
    )

    add_h1(doc, "Know Your Account Type")
    add_para(doc, "Your account type controls which pages and actions appear. Knowledge Space membership and clearance still limit what you can see inside those pages.")
    add_table(
        doc,
        ["Account type", "Typical access"],
        ROLE_ROWS,
        [2300, 7060],
    )
    add_note_box(doc, "Legacy User Manager and Reviewer records may exist in older data. New assignments use Space Admin for scoped user management and Document Contributor for upload plus review.")

    add_h1(doc, "Feature Map")
    add_para(doc, "Use this map to connect common tasks to the page where they happen.")
    add_table(
        doc,
        ["Feature", "What you do", "Where to go"],
        [(row.feature, row.what_you_do, row.where) for row in FEATURE_ROWS],
        [1900, 4660, 2800],
    )

    add_h1(doc, "Sign In and Navigate")
    add_bullets(
        doc,
        [
            "Open the web application URL provided by your organization. Local deployments commonly use http://localhost:3000.",
            "Sign in with your email and password. If this is your first login, change the initial password in Account Management.",
            "Use the sidebar sections to move through Operate, Corpus, Evaluate, and Govern pages.",
            "Use the account area in the sidebar footer to view your session details, change your password, switch theme, or sign out.",
        ],
    )
    add_note_box(doc, "Only pages allowed by your account type and Knowledge Space memberships are shown.")

    add_h1(doc, "Work With Knowledge Spaces")
    add_para(
        doc,
        "Knowledge Spaces are the document boundaries used by the system. A space can represent a department, project, policy library, case set, or operating area.",
    )
    add_bullets(
        doc,
        [
            "Select the active space before asking questions or uploading from chat.",
            "Queries retrieve from the active space and any document scope you add with @ tags.",
            "Uploads inherit the selected writable space.",
            "If expected documents are missing, first confirm that the active space is correct.",
        ],
    )

    add_h1(doc, "Ask Grounded Questions")
    add_numbered_list(
        doc,
        [
            "Open Query Intelligence.",
            "Confirm the active Knowledge Space.",
            "Type a specific question. Mention dates, document names, entities, or constraints when useful.",
            "Press Enter or click Send. Use Shift+Enter for a new line.",
            "Watch the progress panel as the system routes the query, retrieves evidence, and drafts the answer.",
            "Read the answer and inspect the citations.",
        ],
    )
    add_h2(doc, "Useful Query Habits")
    add_bullets(
        doc,
        [
            "Ask for the exact policy, requirement, date, person, document section, or comparison you need.",
            "Use @ to scope retrieval to one or more specific documents in the active space.",
            "Start a new chat when changing topics so context does not blur the question.",
            "Treat warnings as review signals, not as final conclusions.",
        ],
    )
    add_h2(doc, "Choose a Query Source")
    add_table(
        doc,
        ["Mode", "Use it for"],
        [
            ("Auto", "Let Prudentia choose visible documents, approved live data, or both."),
            ("Documents", "Use only indexed files in the active space and optional @ document tags."),
            ("Live DB", "Use current structured facts from approved SQL Server or PostgreSQL scopes."),
            ("Hybrid", "Combine indexed document evidence with live database rows."),
        ],
        [1800, 7560],
    )
    add_para(doc, "In Live DB or Hybrid mode, select one approved database source or leave All visible DB sources selected. If a selected source cannot answer, use Search all sources when offered.")

    add_h1(doc, "Verify Answers With Evidence")
    add_para(
        doc,
        "Every useful answer should be checked against its citations. Select a source chip or inline citation to open the evidence inspector.",
    )
    add_bullets(
        doc,
        [
            "PDF sources can show page navigation and highlighted regions.",
            "DOCX sources can show matching text where available.",
            "Image sources can show image highlights or extracted image evidence.",
            "Low faithfulness, degraded response, conflict, or grounding warnings mean you should verify manually before sharing or acting.",
        ],
    )
    add_note_box(
        doc,
        "Before using an answer outside the workspace, confirm the cited document title, page or excerpt, Knowledge Space, and effective date.",
        fill=CAUTION_FILL,
    )

    add_h1(doc, "Use Optional GraphRAG")
    add_para(doc, "GraphRAG is opt-in. Select it during upload or reingestion only for documents that should participate in relationship, theme, risk, trend, and corpus-level analysis. Leaving it off keeps standard document retrieval fully available and does not create a graph task.")
    add_bullets(
        doc,
        [
            "Opted-in documents are indexed normally before a separate graph task extracts entities and relationships.",
            "A document can be searchable while graph enrichment is still queued or running.",
            "Ask for major themes, recurring issues, patterns, risks, trends, relationships, or an executive overview across opted-in documents.",
            "Graph answers remain grounded in source chunks and include normal citations. Exact counts and exhaustive lists use structured or standard retrieval.",
        ],
    )

    add_h1(doc, "Use Chat History and Generated Files")
    add_bullets(
        doc,
        [
            "Completed conversations appear in the chat history rail.",
            "Use New chat to reset context.",
            "Reopen previous conversations when continuing the same task.",
            "Delete old conversations that are no longer useful.",
            "If a request starts document generation, answer any clarification questions and download the resulting DOCX, PDF, or PPTX when available.",
        ],
    )

    add_h1(doc, "Upload Documents")
    add_para(doc, "If Add Files appears in your sidebar, you can upload supported source files into a writable Knowledge Space.")
    add_table(
        doc,
        ["Item", "Details"],
        [
            ("Supported files", "PDF, DOCX, JPG, JPEG, PNG, and JSON"),
            ("Maximum size", "50 MB per file"),
            ("Required metadata", "A writable Knowledge Space"),
            ("Processing choice", "Fast, Balanced, or High accuracy; optional GraphRAG opt-in"),
            ("Optional metadata", "Effective date, expiry date, description, and supersedes IDs for single-file replacements"),
            ("Result", "Each file receives its own ingestion job"),
        ],
        [2700, 6660],
    )
    add_numbered_list(
        doc,
        [
            "Open Document Intake > Add Files.",
            "Select one or more supported files.",
            "Choose the writable Knowledge Space.",
            "Choose Fast, Balanced, or High accuracy ingestion.",
            "Enable GraphRAG only when relationship or corpus-level analysis is needed.",
            "Add dates, description, or supersession details if needed.",
            "Click Upload documents.",
            "Watch Recent upload jobs for progress and warnings.",
        ],
    )

    add_h1(doc, "Track Indexing Activity")
    add_para(doc, "Open Activity to monitor upload, folder, restore, and reingestion jobs.")
    add_table(doc, ["Status", "Meaning"], STATUS_ROWS, [2200, 7160])
    add_bullets(
        doc,
        [
            "Filter by status, origin, Knowledge Space, date range, or search text.",
            "Open a job to review stage details, warnings, attempts, and parser provenance.",
            "If you have write access, you may cancel jobs that are still scheduled, queued, or processing.",
            "Use Ingestion Health to see active pipeline, failed jobs, review queues, and recent failures.",
            "GraphRAG activity shows queue depth, worker health, and active tasks for opted-in documents.",
        ],
    )

    add_h1(doc, "Browse the Document Library")
    add_para(doc, "Use Document Overview, Knowledge Spaces, Documents, and Trash to find and inspect visible files.")
    add_bullets(
        doc,
        [
            "Document Overview shows active documents, current versions, processing items, attention items, and Trash count.",
            "Knowledge Spaces shows the folder tree and direct documents in selected spaces.",
            "Documents lets you search and filter by lifecycle and ingestion status.",
            "Trash contains soft-deleted documents that authorized users can restore or permanently delete.",
        ],
    )
    add_h2(doc, "Document Inspector")
    add_bullets(
        doc,
        [
            "Review title, Knowledge Space, lifecycle, ingestion status, dates, description, summary, topics, entities, cross references, claims, and version history.",
            "Download the original source file when available.",
            "Users with write access can reingest, restore, or move documents to Trash.",
            "Permanent deletion is restricted and should only be used when retention policy allows it.",
        ],
    )

    add_h1(doc, "Use Folder Sources")
    add_para(doc, "If Folder Sources appears in your sidebar, you can upload local folder snapshots for bulk ingestion.")
    add_bullets(
        doc,
        [
            "Choose a folder from the browser to stage a point-in-time copy with relative paths preserved.",
            "Folder snapshots are one-time schedules. Re-browse the folder later to ingest newer local edits.",
            "Use schedule run details to review queued, skipped, and failed files.",
        ],
    )

    add_h1(doc, "Use Database Connectors")
    add_para(doc, "Platform Admins, System Admins, and Space Admins can prepare live read-only access to SQL Server and PostgreSQL. Database record-sync schedules are retired; approved data is queried at question time and is not copied into the document corpus.")
    add_numbered_list(
        doc,
        [
            "Open Document Intake > Database Connectors and add a read-only profile.",
            "Enter server or host, port, database, user, password, and the required driver or SSL mode.",
            "Save the encrypted profile, then click Test.",
            "Click Read Schema to inspect tables, columns, relationships, indexes, and raw schema JSON.",
            "Click Prepare Review, then correct the catalog name, business rules, descriptions, synonyms, allowed fields, and sensitivity flags.",
            "Assign the owner Knowledge Space, optional shared Knowledge Spaces, and clearance, then Enable Live DB Access after review.",
            "In Query Intelligence, choose Live DB or Hybrid and select the approved source.",
        ],
    )
    add_note_box(doc, "Only approved, non-sensitive tables, columns, and relationships can be queried. Write statements, wildcards, unapproved joins, system schemas, and chained SQL are blocked.", fill=CAUTION_FILL)

    add_h1(doc, "Use Review Queue")
    add_para(doc, "If Review Queue appears in your sidebar, use it to resolve OCR blocks and PDF image-analysis holds before indexing continues.")
    add_h2(doc, "OCR Blocks")
    add_numbered_list(
        doc,
        [
            "Open Review Queue and choose OCR blocks.",
            "Select a pending block grouped under a document.",
            "Compare the OCR text with the source page preview.",
            "Edit Corrected extraction text.",
            "Click Approve correction to save, or Reject block if it should not continue.",
        ],
    )
    add_h2(doc, "PDF Images")
    add_numbered_list(
        doc,
        [
            "Choose PDF images.",
            "Select a held document image batch.",
            "Review candidate thumbnails and recommended markers.",
            "Choose Analyze selected, Analyze recommended, Skip selected, or Skip all pending.",
        ],
    )
    add_note_box(doc, "OCR approval requires non-empty corrected text. Image batches resume when no candidates remain pending.")

    add_h1(doc, "Read the System Audit")
    add_para(
        doc,
        "If System Audit appears in your sidebar, use it to review visible authentication, document, ingestion, and workspace events.",
    )

    add_h1(doc, "Use Runtime Settings")
    add_para(doc, "Runtime Settings is Platform Admin-only under Govern and contains Models & Roles, Inference Services, and Ingestion Controls.")
    add_h2(doc, "Models & Roles")
    add_bullets(
        doc,
        [
            "Choose an Ollama local or vLLM text starting stack, check service discovery, and assign answer synthesis, reasoning, router, faithfulness, ingestion metadata, vision, embedding, and reranker roles.",
            "Changing the embedding provider or model requires reindexing existing documents.",
            "Tune JSON/Layout and evidence budgets, chat and embedding timeouts, Ollama model thinking, and the query planner.",
            "Test draft validates without activation. Save & activate validates again and makes the draft active without restarting containers.",
        ],
    )
    add_h2(doc, "Inference Services")
    add_para(doc, "Check provider availability and manage vLLM text, embedding, and vision limits. Applying limits restarts only the selected service and interrupts requests using it.")
    add_h2(doc, "Ingestion Controls")
    add_table(doc, ["Profile", "Behavior", "Best for"], INGESTION_PROFILE_ROWS, [1800, 4460, 3100], compact=True)
    add_bullets(
        doc,
        [
            "Worker concurrency is 1-10 per replica; one is recommended for the default 8 GB environment.",
            "OCR blocks below the review threshold pause in Review Queue.",
            "PDF image batches above the image review threshold pause before vision analysis; set the threshold to 0 to skip this gate.",
            "Vision layout repair re-reads complex PDF pages after Docling and trades throughput for fidelity.",
            "Graph enrichment controls whether completed documents expose the graph enrichment action.",
        ],
    )
    add_bullets(
        doc,
        [
            "Events are newest first.",
            "Each row shows event type, target, actor, payload summary, and created time.",
            "Audit is for review and escalation. It is not an editing surface.",
        ],
    )

    add_h1(doc, "Troubleshooting")
    add_table(
        doc,
        ["Issue", "Likely cause", "What to do"],
        TROUBLESHOOTING_ROWS,
        [2050, 3510, 3800],
    )

    add_h1(doc, "Safe Usage Practices")
    add_bullets(
        doc,
        [
            "Do not rely on an answer without checking citations for important decisions.",
            "Use the correct Knowledge Space before querying or uploading.",
            "Do not upload documents above your clearance or outside your team scope.",
            "When replacing a file, use supersedes metadata so the older version stays auditable.",
            "Do not share generated files beyond the same access and clearance rules as the source documents.",
            "Report repeated model, indexing, or source-viewer errors with the job ID, document title, and time observed.",
        ],
    )

    add_h1(doc, "Glossary")
    add_table(doc, ["Term", "Meaning"], GLOSSARY_ROWS, [2600, 6760])

    save_docx(doc, path)
