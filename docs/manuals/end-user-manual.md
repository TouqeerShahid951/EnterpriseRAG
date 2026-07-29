# Prudentia AI End User Manual

Last updated: 2026-07-18

This manual explains how to use the Prudentia AI web application after it is
running. It is written for Chat Members, Document Contributors, Audit Viewers,
and scoped admins. If the application itself is not running yet, use the
[Operator Manual](operator-manual.md) first.

## 1. What Prudentia AI Does

Prudentia AI is a local enterprise RAG workspace. It lets authorized users:

- Ask evidence-grounded questions over approved documents.
- Inspect citations, excerpts, pages, and source evidence.
- Upload supported files into controlled Knowledge Spaces when permitted.
- Track indexing and resolve Review Queue items when permitted.
- Query approved live SQL Server or PostgreSQL sources when available.
- Generate downloadable DOCX, PDF, or PPTX artifacts from supported prompts.

The application is permission-aware. If a page is not visible in your sidebar,
your role or Knowledge Space membership does not include that page.

## 2. Role Guide

Every account has an account type. The account type controls which pages and
actions appear. Knowledge Space membership and clearance level further limit
what the user can see inside those pages.

### Platform Admin

Why it exists: Owns the whole platform and makes deployment-wide decisions.

Can do:

- Manage all users, including other Platform Admins.
- Manage all Knowledge Spaces and visible documents.
- Configure model providers, runtime roles, **Ingestion Controls**, and vLLM
  limits.
- Use RAG Evaluation, System Audit, Review Queue, database connectors, uploads,
  document lifecycle actions, and Query Intelligence.

Cannot do:

- Bypass organizational policy for sharing, retention, or data handling.
- Make vLLM work unless the operator has actually prepared the vLLM services and
  model cache.

### System Admin

Why it exists: Runs global operations without full platform configuration power.

Can do:

- Manage users except Platform Admin accounts.
- Manage Knowledge Spaces, documents, uploads, folder sources, database
  connectors, review work, audit review, and ingestion recovery.
- Query and upload across the workspace according to global admin access.

Cannot do:

- Access Platform Admin-only Runtime Settings.
- Run RAG Evaluation.
- Create, edit, or delete Platform Admin accounts.

### Space Admin

Why it exists: Owns Knowledge Space governance and scoped user management.

Can do:

- Open User Management for allowed accounts in assigned spaces.
- Create, edit, disable, reset passwords for, and delete Chat Member and
  Document Contributor accounts inside assigned spaces.
- Create, edit, and delete allowed Knowledge Spaces.
- Upload, reingest, restore, trash, and in some cases permanently delete
  documents inside assigned spaces.
- Manage folder sources and database connector scopes for assigned spaces.
- Open Review Queue and resolve pending OCR or PDF image-review items.
- Query documents and monitor ingestion in assigned spaces.

Cannot do:

- Manage Platform Admins, System Admins, other Space Admins, or Audit Viewers.
- Change global Runtime Settings.
- Run RAG Evaluation.
- Work outside assigned Knowledge Space and clearance boundaries.

### Document Contributor

Why it exists: Adds, maintains, and quality-checks source documents for a team
or space.

Can do:

- Query visible indexed documents.
- Upload supported files into writable assigned Knowledge Spaces.
- Open Review Queue and resolve pending OCR or PDF image-review items.
- Track ingestion jobs.
- Reingest, restore, or move writable documents to Trash where permitted.

Cannot do:

- Manage users or Knowledge Spaces.
- Approve database connector scopes.
- View System Audit.
- Change platform settings.

### Chat Member

Why it exists: Uses approved knowledge for evidence-grounded answers.

Can do:

- Ask questions in Query Intelligence.
- Select a Knowledge Space.
- Use `@` tags to scope questions to visible documents.
- Inspect citations and evidence.
- View visible document library metadata and change their own password.

Cannot do:

- Upload, delete, restore, or reingest documents.
- Manage users, Knowledge Spaces, connectors, audit, review, evaluations, or
  Runtime Settings.

### Audit Viewer

Why it exists: Reviews governance activity without editing content or changing
system state.

Can do:

- Open System Audit.
- Search, filter, inspect, and export visible audit events.
- View visible document and Knowledge Space metadata where exposed.
- View ingestion activity and health summaries.

Cannot do:

- Query document content in Query Intelligence.
- Upload files.
- Manage users or spaces.
- Review OCR.
- Change documents, connectors, evaluations, or Runtime Settings.

`User Manager` and `Reviewer` are legacy account types kept for existing
records and compatibility. New assignments should use **Space Admin** for scoped
user management and **Document Contributor** for upload plus review.

## 3. Before You Start

You need these items:

- The web application URL. Local deployments commonly use `http://localhost:3000`.
- Your email address and password.
- The Knowledge Space you should work in, such as `/finance`, `/legal`, or
  `/manuals`.
- Any rules from your organization about which documents may be uploaded,
  queried, downloaded, or shared.

If you cannot sign in or do not know your password, ask a Platform Admin,
System Admin, or Space Admin to reset your password.

## 4. Sign In

1. Open the Prudentia AI URL in a browser.
2. Enter your email address and password.
3. Select **Authenticate Session**.
4. If the app sends you to **Account Management**, enter your current password
   and set a new password of at least 8 characters.
5. Confirm that the sidebar shows the expected Knowledge Space.

Sessions expire after inactivity. If the session timeout dialog appears, choose
**Stay signed in** to continue or **Sign out** to end the session. If the session
has already expired, sign in again.

## 5. Main Navigation

The sidebar is organized into four areas:

| Area | Pages you may see | Purpose |
| --- | --- | --- |
| Operate | System Overview, Query Intelligence, Ingestion Health | Ask questions and monitor system state. |
| Corpus | Add Files, Abbreviation Glossary, Folder Sources, Database Connectors, Activity, Document Library | Add, inspect, govern, and track source material. |
| Evaluate | Review Queue, RAG Evaluation | Resolve review holds or inspect evaluation quality where permitted. |
| Govern | System Audit, User Management, Runtime Settings | Administrative and governance pages. |

Use the account button in the sidebar footer to open **Account Management**,
change your password, switch theme, or sign out.

## 6. Knowledge Spaces

Knowledge Spaces are access scopes for documents and live database sources. A
space can represent a team, project, department, or document collection.

Before asking questions or uploading files:

1. Check the active Knowledge Space in the sidebar header.
2. Switch to the correct space if your account has more than one.
3. Confirm that the document count looks reasonable for the work you are doing.

Queries, document lists, uploads, folder sources, and database scopes are all
filtered by Knowledge Space and clearance level.

## 7. Ask Questions

1. Open **Query Intelligence**.
2. Confirm the active Knowledge Space.
3. Choose a source mode:

| Mode | Use it when |
| --- | --- |
| Auto | You want Prudentia to search the most likely source first and expand only when its evidence is weak or empty. |
| Documents | The answer must come from indexed files only. |
| Live DB | The answer should come from approved live SQL data only. |
| Hybrid | The answer needs both document context and live database facts. |

4. Type a focused question.
5. Press **Enter** or select **Send**. Use **Shift+Enter** for a new line.
6. Watch the progress panel while Prudentia routes the query, retrieves
   evidence, and drafts the answer.
7. Inspect the citations before relying on the answer.

The composer starts in **Auto** whenever you start or load a conversation. A
manual source choice applies to the active conversation; it is not reused as a
global preference in another conversation.

Good questions name the policy, date, person, contract, report, section, or
comparison you need. Within one conversation, you may ask follow-ups such as
**Why?**, **What about contractors?**, or **Compare that with the previous
policy**. Prudentia resolves a clear follow-up against recent turns, then runs a
fresh permission-filtered retrieval. If the reference is ambiguous, it asks a
clarifying question without searching. A self-contained new topic does not
inherit the previous topic's source preference.

Conversation context is limited to the current saved chat; it is not carried to
another chat. Deleting a chat removes its transcript from future query context.

If an administrator has defined an abbreviation, you may ask with either its
short form or full definition. For example, `AD` and `Assistant Director` are
matched in both directions without changing the question shown in your chat.
When the definition came from an imported PDF, its citation identifies the
source PDF and page; the glossary PDF itself is not searched as corpus content.

## 8. Scope a Question To Specific Documents

Use `@` in the Query Intelligence composer to search documents in the active
Knowledge Space. Select one or more documents to narrow retrieval to those
files.

Document tags apply to **Auto**, **Documents**, and **Hybrid** questions. They
do not apply to **Live DB** only questions.

## 9. Verify Answers With Evidence

Every important answer should be checked against its evidence.

1. Select a source chip or inline citation.
2. Review the evidence inspector.
3. Confirm the document title, page, excerpt, Knowledge Space, and effective
   date when available.
4. Treat warnings as review signals. Warnings can mean low faithfulness,
   degraded retrieval, conflicting sources, or missing highlights.

Evidence can include PDF page highlights, DOCX text excerpts, image evidence,
or live database rows. If highlighting is unavailable, open the original source
file and compare manually.

## 10. Chat History And Generated Files

Completed conversations appear in the chat history rail.

- Use **New chat** when changing topics.
- Reopen a saved chat to continue a related task.
- Delete old chats that are no longer useful.
- Reply normally when Prudentia asks which earlier topic or answer you meant.
- Generated files appear as download links when a generation job completes.
- If the generation job asks clarification questions, answer them in the job
  panel before retrying or continuing.

Generated file access follows your account and permission version. Do not share
generated files outside the same access and clearance rules as the source
documents.

## 11. Upload Documents

If **Add Files** appears in your sidebar, you can upload supported files into a
writable Knowledge Space.

Supported files:

- PDF
- DOCX
- JPG or JPEG
- PNG
- JSON

Each file must be non-empty and no larger than 50 MB.

Upload steps:

1. Open **Document Intake > Add Files**.
2. Select one or more supported files.
3. Choose the writable Knowledge Space.
4. Choose the clearance level. You cannot upload above your own clearance.
5. Enable **GraphRAG** only when the document should participate in
   relationship, theme, risk, trend, or corpus-level analysis.
6. Optionally add effective date, expiry date, description, and supersedes IDs.
   Supersedes IDs are for single-file replacements.
7. Select **Upload documents**.
8. Watch **Recent upload jobs** for progress and warnings.

If an upload is rejected, check the file type, size, Knowledge Space, clearance,
and whether virus scanning is healthy.

## 12. Track Indexing Activity

Open **Document Intake > Activity** to see upload, folder, restore, and reingest
jobs.

Common statuses:

| Status | Meaning |
| --- | --- |
| Scheduled | Waiting for its planned start time. |
| Queued | Accepted and waiting for a worker. |
| Processing | Being parsed, enriched, chunked, embedded, and indexed. |
| Needs review | Waiting for human OCR, extraction, or PDF image review. |
| Indexed | Complete and searchable. |
| Failed | Ingestion stopped with an error. |
| Cancelled | The job was manually stopped. |

Users with write access can cancel scheduled, queued, or active jobs. If a job
looks stuck, share the job ID, document title, and time observed with an
administrator or operator.

## 13. Browse The Document Library

The Document Library may include:

- **Overview**: summary metrics, attention items, and recent activity.
- **Knowledge Spaces**: folder tree and direct documents in selected spaces.
- **Documents**: searchable table of visible documents.
- **Trash**: soft-deleted documents that authorized users can restore or delete.

Overview and Knowledge Spaces share one access-filtered document snapshot.
Library documents includes visible, non-deleted current and superseded records.
Current, Indexed, Processing, and Needs attention count each current document
once. Needs attention includes failed, unknown, and human-review documents, but
not cancelled documents. Upload validation failures that did not create a
document stay on the Upload page and are not library issues.

Retrying a failed document moves that same document into Processing; it does not
add another issue. If the retry fails again, the document returns as one issue.
Uploading a different document does not clear an existing failed document. When
a replacement succeeds, the replaced record moves from Current to Superseded;
until then the old current version remains in place.

Open a document to inspect metadata, summary, topics, entities, cross
references, extracted claims, version history, and download links. Available
actions depend on your role and access.

## 14. Review Queue

If **Review Queue** appears in your sidebar, you can resolve OCR/extraction
blocks and PDF image-analysis holds before affected documents continue.

Its badge counts distinct documents with pending review work that you can
resolve, not individual blocks or images. A document remains counted after you
open it or make a partial decision. It leaves the count when no pending review
work remains, including after the final approval, rejection, skip decision, or
job cancellation. **Activity** has no badge because it is a job history and
status view.

For OCR blocks:

1. Open **Review Queue** and choose **OCR blocks**.
2. Select a pending block.
3. Compare the OCR text with the page preview.
4. Edit **Corrected extraction text**.
5. Select **Approve correction** to save the corrected text, or **Reject block**
   if the block should not continue.

Approval requires non-empty corrected text.

For PDF image batches:

1. Choose **PDF images**.
2. Select a held document batch.
3. Review the candidate thumbnails and recommended markers.
4. Select the images to analyze, or choose the recommended set.
5. Use **Analyze selected**, **Analyze recommended**, **Skip selected**, or
   **Skip all pending**.

The ingestion job resumes when no OCR blocks or image candidates remain pending.

## 15. Read The System Audit

If **System Audit** appears in your sidebar, use it to review visible
authentication, document, ingestion, query, and workspace events.

You can search and filter by category, event type, actor, target, Knowledge
Space, and time window. Use **Export CSV** when you need to preserve or share an
audit slice according to your organization's policy.

Audit is for review and escalation. It is not an editing surface.

## 16. Safe Usage Rules

- Do not rely on an important answer without checking citations.
- Use the correct Knowledge Space before querying or uploading.
- Do not upload documents above your clearance or outside your team scope.
- Do not share original files, citations, answers, or generated artifacts beyond
  the same access rules as the source material.
- When replacing a document, use supersedes metadata so the older version stays
  auditable.
- Report repeated model, indexing, source viewer, or upload errors with the job
  ID, document title, and time observed.

## 17. Troubleshooting

| Problem | What to check | What to do |
| --- | --- | --- |
| You cannot sign in | Email, password, active account state | Ask an admin to reset your password or reactivate the account. |
| A page is missing | Role and Knowledge Space memberships | Ask an admin to confirm your permissions. |
| No documents appear | Active space, clearance, lifecycle filters | Switch spaces or ask an admin to verify access. |
| You cannot query | Indexed documents, model runtime, selected source mode | Wait for indexing, switch source mode, or report the runtime issue. |
| No Live DB source appears | Approved catalog for your space and clearance | Ask a connector admin to approve a suitable scope. |
| Upload is rejected | Type, size, empty file, writable space, virus scan | Use a supported file under 50 MB and select a writable space. |
| Document says Needs review | OCR, extraction, or PDF image triage paused ingestion | A Document Contributor, Space Admin, System Admin, or Platform Admin must resolve the pending Review Queue item. |
| Answer has warnings | Low grounding, conflict, degraded retrieval | Inspect citations manually before using the answer. |
| Source highlight is missing | No page coordinates or exact text match | Open the original source and compare manually. |
| Graph enrichment is absent | GraphRAG was not selected, disabled, or worker unavailable | Standard retrieval still works; ask an admin if graph analysis is required. |

## 18. Glossary

| Term | Meaning |
| --- | --- |
| Knowledge Space | A document access scope such as `/finance` or `/manuals`. |
| Clearance | A level that controls whether a user can see a document. |
| Current document | The active version used for retrieval. |
| Superseded document | An older version kept for audit and history. |
| Trash | Soft-deleted documents that can be restored by authorized users. |
| Ingestion job | The background task that parses, enriches, embeds, and indexes a file. |
| Citation | A link between an answer claim and supporting source evidence. |
| Faithfulness | A grounding check that estimates whether an answer is supported by evidence. |
| Approved database scope | A reviewed set of database tables, columns, relationships, Knowledge Space, and clearance allowed for live read-only SQL. |
| GraphRAG | Optional graph enrichment for corpus-level themes, relationships, and patterns. |
