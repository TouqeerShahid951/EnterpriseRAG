"""Compose the end-user walkthrough as a PDF document."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

from .content import (
    FEATURE_ROWS,
    GLOSSARY_ROWS,
    INGESTION_PROFILE_ROWS,
    ROLE_ROWS,
    STATUS_ROWS,
    SUBTITLE,
    TITLE,
    TROUBLESHOOTING_ROWS,
    UPDATED,
)
from .pdf_components import (
    NumberedPdf,
    draw_pdf_footer,
    pdf_bullets,
    pdf_note,
    pdf_numbered_items,
    pdf_styles,
    pdf_table,
)


def build_pdf(path: Path) -> None:
    styles = pdf_styles()
    doc = NumberedPdf(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="normal", frames=[frame], onPage=draw_pdf_footer)])

    story = []
    story.extend(pdf_cover(styles))
    story.append(PageBreak())
    story.extend(pdf_quick_start(styles))
    story.extend(pdf_role_guide(styles))
    story.extend(pdf_feature_map(styles))
    story.extend(pdf_section(styles, "Sign In and Navigate", [
        "Open the web application URL provided by your organization. Local deployments commonly use http://localhost:3000.",
        "Sign in with your email and password. Change the initial password in Account Management when needed.",
        "Use the sidebar sections to move through Operate, Corpus, Evaluate, and Govern pages.",
        "Use the account area in the sidebar footer to view session details, change password, switch theme, or sign out.",
    ]))
    story.extend(pdf_section(styles, "Work With Knowledge Spaces", [
        "Select the active space before asking questions or uploading from chat.",
        "Queries retrieve from the active space and any document scope you add with @ tags.",
        "Uploads inherit the selected writable space.",
        "If expected documents are missing, first confirm that the active space is correct.",
    ], lead="Knowledge Spaces are the document boundaries used by the system."))
    story.extend(pdf_numbered_section(styles, "Ask Grounded Questions", [
        "Open Query Intelligence.",
        "Confirm the active Knowledge Space.",
        "Choose Auto, Documents, Live DB, or Hybrid. Select one approved DB source when needed.",
        "Type a specific question. Mention dates, document names, entities, or constraints when useful.",
        "Press Enter or click Send. Use Shift+Enter for a new line.",
        "Watch the progress panel as the system routes the query, retrieves evidence, and drafts the answer.",
        "Read the answer and inspect the citations.",
    ]))
    story.extend(pdf_query_sources_section(styles))
    story.extend(pdf_section(styles, "Verify Answers With Evidence", [
        "PDF sources can show page navigation and highlighted regions.",
        "DOCX sources can show matching text where available.",
        "Image sources can show image highlights or extracted image evidence.",
        "Low faithfulness, degraded response, conflict, or grounding warnings mean you should verify manually before sharing or acting.",
    ]))
    story.extend(pdf_section(styles, "Use Chat History and Generated Files", [
        "Completed conversations appear in the chat history rail.",
        "Use New chat to reset context.",
        "Reopen previous conversations when continuing the same task.",
        "Delete old conversations that are no longer useful.",
        "When document generation starts, answer clarification questions and download the DOCX, PDF, or PPTX when ready.",
    ]))
    story.extend(pdf_section(styles, "Use Optional GraphRAG", [
        "Select GraphRAG during upload or reingestion only for documents that should participate in relationship and corpus-level analysis.",
        "Leaving GraphRAG off keeps standard document search available and does not create a graph task.",
        "Opted-in documents are searchable before the separate graph task necessarily finishes.",
        "Ask for themes, patterns, trends, recurring issues, risks, relationships, or executive overviews across opted-in documents.",
        "Graph answers cite source chunks. Exact counts and exhaustive lists use structured or standard retrieval.",
    ]))
    story.extend(pdf_upload_section(styles))
    story.extend(pdf_activity_section(styles))
    story.extend(pdf_section(styles, "Browse the Document Library", [
        "Document Overview shows active documents, current versions, processing items, attention items, and Trash count.",
        "Knowledge Spaces shows the folder tree and direct documents in selected spaces.",
        "Documents lets you search and filter by lifecycle and ingestion status.",
        "Trash contains soft-deleted documents that authorized users can restore or permanently delete.",
        "The Document Inspector shows metadata, extracted facts, version history, downloads, and allowed lifecycle actions.",
    ]))
    story.extend(pdf_section(styles, "Use Folder Sources", [
        "Choose a folder from the browser to stage a point-in-time copy with relative paths preserved.",
        "Folder snapshots are one-time schedules. Re-browse the folder later to ingest newer local edits.",
        "Use schedule run details to review queued, skipped, and failed files.",
    ]))
    story.extend(pdf_database_connectors_section(styles))
    story.extend(pdf_numbered_section(styles, "Use Review Queue - OCR Blocks", [
        "Open Review Queue and choose OCR blocks.",
        "Select a pending block grouped under a document.",
        "Compare the OCR text with the source page preview.",
        "Edit Corrected extraction text.",
        "Click Approve correction to save, or Reject block if it should not continue.",
    ], lead="If Review Queue appears in your sidebar, use it to resolve OCR blocks before indexing continues."))
    story.extend(pdf_numbered_section(styles, "Use Review Queue - PDF Images", [
        "Choose PDF images.",
        "Select a held document image batch.",
        "Review candidate thumbnails and recommended markers.",
        "Choose Analyze selected, Analyze recommended, Skip selected, or Skip all pending.",
    ], lead="Large PDF image-analysis batches can pause here for human triage. The job resumes when no candidates remain pending."))
    story.extend(pdf_section(styles, "Read the System Audit", [
        "Events are newest first.",
        "Each row shows event type, target, actor, payload summary, and created time.",
        "Audit is for review and escalation. It is not an editing surface.",
    ], lead="If System Audit appears in your sidebar, use it to review visible authentication, document, ingestion, and workspace events."))
    story.extend(pdf_configs_section(styles))
    story.extend(pdf_troubleshooting(styles))
    story.extend(pdf_section(styles, "Safe Usage Practices", [
        "Do not rely on an answer without checking citations for important decisions.",
        "Use the correct Knowledge Space before querying or uploading.",
        "Do not upload documents above your clearance or outside your team scope.",
        "When replacing a file, use supersedes metadata so the older version stays auditable.",
        "Do not share generated files beyond the same access and clearance rules as the source documents.",
        "Report repeated model, indexing, or source-viewer errors with the job ID, document title, and time observed.",
    ]))
    story.extend(pdf_glossary(styles))

    doc.build(story)

def pdf_cover(styles: dict[str, ParagraphStyle]) -> list:
    return [
        Spacer(1, 0.55 * inch),
        Paragraph("END USER GUIDE", styles["small"]),
        Paragraph(TITLE, styles["title"]),
        Paragraph(SUBTITLE, styles["subtitle"]),
        pdf_table(
            styles,
            ["Field", "Details"],
            [
                ("Audience", "Chat Members, Document Contributors, Audit Viewers, Space Admins, System Admins, and Platform Admins"),
                ("Scope", "Document and live-data queries, connectors, ingestion profiles, optional GraphRAG, evidence, activity, governance, and Runtime Settings"),
                ("Not covered", "Deployment internals, secret rotation, database administration, and developer operations"),
                ("Updated", UPDATED),
            ],
            [1.35 * inch, 5.15 * inch],
        ),
        Spacer(1, 12),
        pdf_note(styles, "Tip: Read the Quick Start first, then jump to the feature that appears in your sidebar."),
    ]


def pdf_quick_start(styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph("How to Use This Guide", styles["h1"]),
        pdf_note(styles, "Your sidebar is permission-aware. If a feature described here does not appear, your account does not include that permission."),
        *pdf_numbered_items(styles, [
            "Sign in with your workspace email and password.",
            "Check the active Knowledge Space in the sidebar header.",
            "Open Query Intelligence and ask a focused question.",
            "Inspect citations before relying on an answer.",
            "Use Add Files, Activity, Review Queue, or Audit only when those pages appear in your sidebar.",
        ]),
    ]


def pdf_role_guide(styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph("Know Your Account Type", styles["h1"]),
        Paragraph("Your account type controls which pages and actions appear. Knowledge Space membership and clearance still limit what you can see inside those pages.", styles["body"]),
        pdf_table(styles, ["Account type", "Typical access"], ROLE_ROWS, [1.55 * inch, 4.95 * inch]),
        pdf_note(styles, "Legacy User Manager and Reviewer records may exist in older data. New assignments use Space Admin for scoped user management and Document Contributor for upload plus review."),
    ]


def pdf_feature_map(styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph("Feature Map", styles["h1"]),
        Paragraph("Use this map to connect common tasks to the page where they happen.", styles["body"]),
        pdf_table(
            styles,
            ["Feature", "What you do", "Where to go"],
            [(row.feature, row.what_you_do, row.where) for row in FEATURE_ROWS],
            [1.35 * inch, 3.25 * inch, 1.9 * inch],
        ),
    ]


def pdf_section(styles: dict[str, ParagraphStyle], title: str, bullets: list[str], lead: str | None = None) -> list:
    story = [Paragraph(title, styles["h1"])]
    if lead:
        story.append(Paragraph(lead, styles["body"]))
    story.extend(pdf_bullets(styles, bullets))
    return [KeepTogether(story)]


def pdf_numbered_section(styles: dict[str, ParagraphStyle], title: str, items: list[str], lead: str | None = None) -> list:
    story = [Paragraph(title, styles["h1"])]
    if lead:
        story.append(Paragraph(lead, styles["body"]))
    story.extend(pdf_numbered_items(styles, items))
    return [KeepTogether(story)]


def pdf_query_sources_section(styles: dict[str, ParagraphStyle]) -> list:
    return [KeepTogether([
        Paragraph("Choose a Query Source", styles["h1"]),
        pdf_table(
            styles,
            ["Mode", "Use it for"],
            [
                ("Auto", "Let Prudentia choose visible documents, approved live data, or both."),
                ("Documents", "Use indexed files in the active space and optional @ document tags."),
                ("Live DB", "Use current structured facts from approved SQL Server or PostgreSQL scopes."),
                ("Hybrid", "Combine indexed document evidence with live database rows."),
            ],
            [1.25 * inch, 5.25 * inch],
        ),
        Paragraph("In Live DB or Hybrid mode, select one source or leave All visible DB sources selected. If a selected source cannot answer, use Search all sources when offered.", styles["body"]),
    ])]


def pdf_upload_section(styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph("Upload Documents", styles["h1"]),
        Paragraph("If Add Files appears in your sidebar, you can upload supported source files into a writable Knowledge Space.", styles["body"]),
        pdf_table(
            styles,
            ["Item", "Details"],
            [
                ("Supported files", "PDF, DOCX, JPG, JPEG, PNG, and JSON"),
                ("Maximum size", "50 MB per file"),
                ("Required metadata", "A writable Knowledge Space"),
                ("Processing choice", "Fast, Balanced, or High accuracy; optional GraphRAG opt-in"),
                ("Optional metadata", "Effective date, expiry date, description, and supersedes IDs for single-file replacements"),
                ("Result", "Each file receives its own ingestion job"),
            ],
            [1.75 * inch, 4.75 * inch],
        ),
        KeepTogether([
            Paragraph("Upload Workflow", styles["h2"]),
            *pdf_numbered_items(styles, [
                "Open Document Intake > Add Files.",
                "Select one or more supported files.",
                "Choose the writable Knowledge Space.",
                "Choose the ingestion profile and enable GraphRAG only when graph analysis is needed.",
                "Add dates, description, or supersession details if needed.",
                "Click Upload documents.",
                "Watch Recent upload jobs for progress and warnings.",
            ]),
        ]),
    ]


def pdf_database_connectors_section(styles: dict[str, ParagraphStyle]) -> list:
    return [KeepTogether([
        Paragraph("Use Database Connectors", styles["h1"]),
        Paragraph("Platform Admins, System Admins, and Space Admins can prepare SQL Server or PostgreSQL for governed live read-only answers. Record-sync schedules are retired; rows are queried at question time and are not copied into the document corpus.", styles["body"]),
        *pdf_numbered_items(styles, [
            "Add a read-only profile with host, port, database, credentials, and required driver or SSL mode.",
            "Save the encrypted profile and click Test.",
            "Click Read Schema to inspect tables, columns, relationships, indexes, and raw schema JSON.",
            "Click Prepare Review and review names, business rules, descriptions, synonyms, allowed fields, and sensitivity flags.",
            "Assign the owner Knowledge Space, optional shared Knowledge Spaces, and clearance, then Enable Live DB Access after review.",
            "Choose Live DB or Hybrid in Query Intelligence and select the approved source.",
        ]),
        pdf_note(styles, "Only approved, non-sensitive tables, columns, and relationships can be queried. Write statements, wildcards, unapproved joins, system schemas, and chained SQL are blocked."),
    ])]


def pdf_configs_section(styles: dict[str, ParagraphStyle]) -> list:
    return [
        KeepTogether([
            Paragraph("Use Runtime Settings", styles["h1"]),
            Paragraph("Runtime Settings is Platform Admin-only under Govern. It contains Models & Roles, Inference Services, and Ingestion Controls.", styles["body"]),
        ]),
        KeepTogether([
            Paragraph("Models & Roles", styles["h2"]),
            *pdf_bullets(styles, [
                "Choose an Ollama or vLLM starting stack, check service discovery, and assign synthesis, reasoning, router, faithfulness, ingestion, vision, embedding, and reranker roles.",
                "Embedding changes require document reindexing.",
                "Tune output and evidence budgets, timeouts, Ollama thinking, and the query planner.",
                "Test draft validates without activation; Save & activate validates again and makes the draft active without a container restart.",
            ]),
        ]),
        KeepTogether([
            Paragraph("Inference Services", styles["h2"]),
            Paragraph("Check provider availability and manage vLLM text, embedding, and vision limits. Applying limits restarts only the selected service and interrupts requests that use it.", styles["body"]),
        ]),
        KeepTogether([
            Paragraph("Ingestion Controls", styles["h2"]),
            pdf_table(styles, ["Profile", "Behavior", "Best for"], INGESTION_PROFILE_ROWS, [1.15 * inch, 3.15 * inch, 2.2 * inch]),
            *pdf_bullets(styles, [
                "Worker concurrency is 1-10 per replica; one is recommended for the default 8 GB environment.",
                "OCR below the review threshold pauses in Review Queue.",
                "PDF image batches above the image review threshold pause before vision analysis; set the threshold to 0 to skip this gate.",
                "Vision layout repair re-reads complex PDF pages after Docling and trades throughput for fidelity.",
                "Graph enrichment controls whether completed documents expose the graph enrichment action.",
            ]),
        ]),
    ]


def pdf_activity_section(styles: dict[str, ParagraphStyle]) -> list:
    return [
        Paragraph("Track Indexing Activity", styles["h1"]),
        Paragraph("Open Activity to monitor upload, folder, restore, and reingestion jobs.", styles["body"]),
        pdf_table(styles, ["Status", "Meaning"], STATUS_ROWS, [1.5 * inch, 5.0 * inch]),
        *pdf_bullets(styles, [
            "Filter by status, origin, Knowledge Space, date range, or search text.",
            "Open a job to review stage details, warnings, attempts, and parser provenance.",
            "If you have write access, you may cancel jobs that are still scheduled, queued, or processing.",
            "Use Ingestion Health to see active pipeline, failed jobs, review queues, and recent failures.",
            "GraphRAG activity shows queue, worker, and active-task status for documents that opted in to graph enrichment.",
        ]),
    ]


def pdf_troubleshooting(styles: dict[str, ParagraphStyle]) -> list:
    return [KeepTogether([
        Paragraph("Troubleshooting", styles["h1"]),
        pdf_table(styles, ["Issue", "Likely cause", "What to do"], TROUBLESHOOTING_ROWS, [1.45 * inch, 2.45 * inch, 2.6 * inch]),
    ])]


def pdf_glossary(styles: dict[str, ParagraphStyle]) -> list:
    return [KeepTogether([
        Paragraph("Glossary", styles["h1"]),
        pdf_table(styles, ["Term", "Meaning"], GLOSSARY_ROWS, [1.75 * inch, 4.75 * inch]),
    ])]
