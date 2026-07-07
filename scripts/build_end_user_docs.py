from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DOCX_PATH = DOCS_DIR / "Prudentia-AI-End-User-Walkthrough.docx"
PDF_PATH = DOCS_DIR / "Prudentia-AI-End-User-Walkthrough.pdf"

TITLE = "Prudentia AI End User Walkthrough"
SUBTITLE = "Search documents and live data, choose ingestion profiles, verify evidence, and use optional GraphRAG"
UPDATED = "2026-07-07"

BLUE = RGBColor(46, 116, 181)
DARK_BLUE = RGBColor(31, 77, 120)
INK = RGBColor(28, 37, 48)
MUTED = RGBColor(91, 103, 112)
LIGHT_BLUE = "E8EEF5"
LIGHT_GRAY = "F2F4F7"
NOTE_FILL = "F4F6F9"
CAUTION_FILL = "FFF6D8"

CONTENT_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120


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


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    build_docx(DOCX_PATH)
    build_pdf(PDF_PATH)
    print(f"Wrote {DOCX_PATH}")
    print(f"Wrote {PDF_PATH}")


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


def configure_docx_page(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)


def configure_docx_styles(doc: Document) -> None:
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for name in ("List Bullet", "List Number"):
        style = styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(11)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = 1.25
        style.paragraph_format.left_indent = Inches(0.375)
        style.paragraph_format.first_line_indent = Inches(-0.188)

    h1 = styles["Heading 1"]
    h1.font.name = "Calibri"
    h1.font.size = Pt(16)
    h1.font.color.rgb = BLUE
    h1.font.bold = True
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after = Pt(10)
    h1.paragraph_format.line_spacing = 1.25
    h1.paragraph_format.keep_with_next = True

    h2 = styles["Heading 2"]
    h2.font.name = "Calibri"
    h2.font.size = Pt(13)
    h2.font.color.rgb = BLUE
    h2.font.bold = True
    h2.paragraph_format.space_before = Pt(14)
    h2.paragraph_format.space_after = Pt(7)
    h2.paragraph_format.line_spacing = 1.25
    h2.paragraph_format.keep_with_next = True

    h3 = styles["Heading 3"]
    h3.font.name = "Calibri"
    h3.font.size = Pt(12)
    h3.font.color.rgb = DARK_BLUE
    h3.font.bold = True
    h3.paragraph_format.space_before = Pt(10)
    h3.paragraph_format.space_after = Pt(5)
    h3.paragraph_format.line_spacing = 1.25
    h3.paragraph_format.keep_with_next = True


def add_docx_cover(doc: Document) -> None:
    section = doc.sections[0]
    set_section_header_footer(section)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(34)
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run("END USER GUIDE")
    set_run_font(run, size=10, color=MUTED, bold=True)

    title = doc.add_paragraph()
    title.paragraph_format.space_after = Pt(8)
    title.paragraph_format.keep_with_next = True
    run = title.add_run(TITLE)
    set_run_font(run, size=28, color=DARK_BLUE, bold=True)

    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(18)
    run = sub.add_run(SUBTITLE)
    set_run_font(run, size=13, color=MUTED)

    add_table(
        doc,
        ["Field", "Details"],
        [
            ("Audience", "Chat Members, Document Contributors, Audit Viewers, Space Admins, System Admins, and Platform Admins"),
            ("Scope", "Document and live-data queries, connectors, ingestion profiles, optional GraphRAG, evidence, activity, governance, and Runtime Settings"),
            ("Not covered", "Deployment internals, secret rotation, database administration, and developer operations"),
            ("Updated", UPDATED),
        ],
        [1900, 7460],
        compact=True,
    )
    add_note_box(
        doc,
        "Tip: Read the Quick Start first, then jump to the feature that appears in your sidebar.",
    )
    doc.add_page_break()


def set_section_header_footer(section) -> None:
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    header.paragraph_format.space_after = Pt(0)
    run = header.add_run("Prudentia AI End User Walkthrough")
    set_run_font(run, size=9, color=MUTED, bold=True)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.paragraph_format.space_after = Pt(0)
    run = footer.add_run("Page ")
    set_run_font(run, size=9, color=MUTED)
    add_field(footer, "PAGE")
    run = footer.add_run(" of ")
    set_run_font(run, size=9, color=MUTED)
    add_field(footer, "NUMPAGES")


def add_field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)


def add_h1(doc: Document, text: str) -> None:
    doc.add_paragraph(text, style="Heading 1")


def add_h2(doc: Document, text: str) -> None:
    doc.add_paragraph(text, style="Heading 2")


def add_para(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.25
    run = p.add_run(text)
    set_run_font(run, size=11, color=INK)


def add_bullets(doc: Document, items: Iterable[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        run = p.add_run(item)
        set_run_font(run, size=11, color=INK)


def add_numbered_list(doc: Document, items: Iterable[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        run = p.add_run(item)
        set_run_font(run, size=11, color=INK)


def add_note_box(doc: Document, text: str, fill: str = NOTE_FILL) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_geometry(table, [CONTENT_WIDTH_DXA], indent=160)
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    set_cell_margins(cell, top=120, bottom=120, start=160, end=160)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(text)
    set_run_font(run, size=10.5, color=INK, bold=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_table(
    doc: Document,
    headers: list[str],
    rows: list[tuple[str, ...]],
    widths_dxa: list[int],
    compact: bool = False,
) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_geometry(table, widths_dxa, indent=TABLE_INDENT_DXA)
    table.style = "Table Grid"

    header_cells = table.rows[0].cells
    set_repeat_table_header(table.rows[0])
    for idx, text in enumerate(headers):
        set_cell_text(header_cells[idx], text, bold=True, fill=LIGHT_BLUE, size=9.5 if compact else 10)
        set_cell_width(header_cells[idx], widths_dxa[idx])

    for row in rows:
        cells = table.add_row().cells
        for idx, text in enumerate(row):
            set_cell_text(cells[idx], text, size=9.5 if compact else 10)
            set_cell_width(cells[idx], widths_dxa[idx])
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = tr_pr.find(qn("w:tblHeader"))
    if tbl_header is None:
        tbl_header = OxmlElement("w:tblHeader")
        tr_pr.append(tbl_header)
    tbl_header.set(qn("w:val"), "true")


def set_cell_text(cell, text: str, bold: bool = False, fill: str | None = None, size: float = 10) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_margins(cell, top=80, bottom=80, start=120, end=120)
    if fill:
        set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run(text)
    set_run_font(run, size=size, color=INK, bold=bold)


def set_table_geometry(table, widths_dxa: list[int], indent: int = 120) -> None:
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.insert(0, tbl_w)
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(sum(widths_dxa)))
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), str(indent))

    tbl_grid = tbl.tblGrid
    for child in list(tbl_grid):
        tbl_grid.remove(child)
    for width in widths_dxa:
        grid_col = OxmlElement("w:gridCol")
        grid_col.set(qn("w:w"), str(width))
        tbl_grid.append(grid_col)


def set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:type"), "dxa")
    tc_w.set(qn("w:w"), str(width_dxa))


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top: int, bottom: int, start: int, end: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for tag, value in (("top", top), ("bottom", bottom), ("start", start), ("end", end)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_run_font(run, size: float | None = None, color: RGBColor | None = None, bold: bool | None = None) -> None:
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    run._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    if bold is not None:
        run.bold = bold


def save_docx(doc: Document, path: Path) -> None:
    doc.save(path)


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


class NumberedPdf(BaseDocTemplate):
    pass


def draw_pdf_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5B6770"))
    canvas.drawString(doc.leftMargin, 0.45 * inch, "Prudentia AI End User Walkthrough")
    canvas.drawRightString(letter[0] - doc.rightMargin, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("GuideTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=27, leading=32, textColor=colors.HexColor("#1F4D78"), alignment=TA_LEFT, spaceAfter=8),
        "subtitle": ParagraphStyle("GuideSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=12.5, leading=16, textColor=colors.HexColor("#5B6770"), spaceAfter=18),
        "h1": ParagraphStyle("GuideH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#2E74B5"), spaceBefore=14, spaceAfter=7),
        "h2": ParagraphStyle("GuideH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.HexColor("#2E74B5"), spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("GuideBody", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=13, textColor=colors.HexColor("#1C2530"), spaceAfter=6),
        "small": ParagraphStyle("GuideSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#5B6770"), spaceAfter=3),
        "bullet": ParagraphStyle("GuideBullet", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=13, leftIndent=16, firstLineIndent=-9, textColor=colors.HexColor("#1C2530"), spaceAfter=4),
        "note": ParagraphStyle("GuideNote", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=9.8, leading=12.5, textColor=colors.HexColor("#1C2530"), spaceAfter=0),
        "table": ParagraphStyle("GuideTable", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1C2530")),
        "table_header": ParagraphStyle("GuideTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1C2530")),
    }


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


def pdf_bullets(styles: dict[str, ParagraphStyle], items: list[str]) -> list:
    return [Paragraph(f"- {escape_pdf_text(item)}", styles["bullet"]) for item in items]


def pdf_numbered_items(styles: dict[str, ParagraphStyle], items: list[str]) -> list:
    return [Paragraph(f"{idx}. {escape_pdf_text(item)}", styles["bullet"]) for idx, item in enumerate(items, start=1)]


def pdf_note(styles: dict[str, ParagraphStyle], text: str) -> Table:
    table = Table([[Paragraph(escape_pdf_text(text), styles["note"])]], colWidths=[6.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DADFE6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def pdf_table(styles: dict[str, ParagraphStyle], headers: list[str], rows: list[tuple[str, ...]], widths: list[float]) -> Table:
    data = [[Paragraph(escape_pdf_text(cell), styles["table_header"]) for cell in headers]]
    data.extend([[Paragraph(escape_pdf_text(cell), styles["table"]) for cell in row] for row in rows])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B9C4D1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def escape_pdf_text(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


if __name__ == "__main__":
    main()
