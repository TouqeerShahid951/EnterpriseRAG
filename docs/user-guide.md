# Prudentia AI User Guide

Last updated: 2026-06-23

This guide explains how to use the Prudentia AI / AgenticRAG workspace from the
web application. It covers every account type and the main workflows users see
in the sidebar.

For standalone handoff documentation, use the manual set in
[docs/manuals](manuals/README.md):

- [End User Manual](manuals/end-user-manual.md)
- [Administrator Manual](manuals/administrator-manual.md)
- [Operator Manual](manuals/operator-manual.md)

For offline Windows deployment and runtime setup, see
[Windows Airgapped Runtime Runbook](windows-airgap-runbook.md) and
[Airgap Runtime Mode](airgap-runtime.md).

## What This System Does

Prudentia AI is an enterprise RAG workspace for uploading controlled documents,
indexing them into Knowledge Spaces, asking grounded questions, querying
approved databases with live read-only SQL, reviewing low-confidence OCR,
auditing activity, evaluating answer quality, and using GraphRAG for corpus-level
themes and patterns.

The application is organized around these areas:

- **Operate**: workspace summary, ingestion health, and Query Intelligence.
- **Corpus**: document intake, folder sources, database connectors, activity,
  document library, and Knowledge Spaces.
- **Evaluate**: OCR review and RAG evaluation.
- **Govern**: audit trail, user management, and Configs for platform
  configuration.

Navigation is role-aware. If a page is missing from your sidebar, your account
does not currently have access to that page.

## Core Concepts

### Knowledge Spaces

Knowledge Spaces are document access scopes such as `/finance`,
`/legal/contracts`, or `/manuals`. Users are assigned one or more spaces.
Queries, document lists, uploads, and folder schedules are filtered by those
spaces.

Global administrators can work across all spaces. Scoped roles work only in the
spaces assigned to them.

### Clearance Levels

Documents and users can carry clearance levels:

- `NATO_UNCLASSIFIED`
- `NATO_RESTRICTED`
- `NATO_CONFIDENTIAL`
- `NATO_SECRET`
- `COSMIC_TOP_SECRET`

A user can only access documents at or below their own clearance level. Global
admin roles receive the maximum effective clearance.

### Document Lifecycle

Documents move through these lifecycle states:

- **Current**: the active version used for retrieval.
- **Superseded**: an older version retained for audit and version history.
- **Trash**: a soft-deleted document. Its indexed vectors are removed.
- **Permanently deleted**: original file, image assets, and vectors are removed.

Uploading a replacement can mark older documents as superseded. Trash keeps
documents recoverable until an authorized admin permanently deletes them.

### Ingestion Status

Each uploaded or scheduled file receives an ingestion job. Common statuses are:

- **Scheduled**: waiting for its planned start time.
- **Queued**: accepted and waiting for a worker.
- **Processing**: being parsed, enriched, chunked, embedded, and indexed.
- **Needs review**: low-confidence OCR or extraction needs human review.
- **Indexed**: complete and searchable.
- **Failed**: ingestion stopped with an error.
- **Cancelled**: the job was manually cancelled.

### Query Sources

The Query Intelligence composer can use four source modes:

- **Auto**: Prudentia chooses documents, live database data, or a combination
  from the question and the sources visible to you.
- **Documents**: uses only indexed documents in the active Knowledge Space and
  any documents selected with `@` tags.
- **Live DB**: runs generated, validated, read-only SQL against approved
  database scopes. No document scope is used.
- **Hybrid**: combines indexed document evidence with live database results.

Live database sources only appear when a schema catalog is approved for a
Knowledge Space and clearance level you can access.

### Optional GraphRAG Enrichment

GraphRAG is optional. When uploading or reingesting a document, choose the
GraphRAG option only when you want that document included in graph-based themes,
relationships, and corpus-level analysis. Leaving it off runs standard document
ingestion and retrieval without graph extraction.

For opted-in documents, completed ingestion triggers a separate graph enrichment
task. GraphRAG extracts entities and relationships, groups related information
into communities, and prepares summaries for corpus-level questions. Document
indexing can be complete and searchable while graph enrichment is still queued
or running.

## Role Summary

| Role | Main purpose | Typical access |
| --- | --- | --- |
| Platform Admin | Full platform ownership | All pages, all spaces, database connectors, user management, audit, review, RAG evaluation, and Configs |
| System Admin | Global operations without platform config | Query, intake, library, review, audit, user management, and operational recovery |
| User Manager | Account provisioning | Create and manage non-global-admin users inside assigned scopes |
| Space Admin | Knowledge Space and document governance | Query, upload, folder sources, database connectors, library management, ingestion visibility, and space administration |
| Contributor | Document intake and maintenance | Query, upload, document lifecycle actions in writable spaces, and ingestion visibility |
| Reviewer | Extraction quality review | Query, OCR Review Queue, document visibility, and ingestion visibility |
| Auditor | Read-only governance review | System Audit, visible document/space metadata, and ingestion visibility |
| Member | Grounded document use | Query Intelligence and visible document library access |

## Role Details

### Platform Admin

Platform Admins have global control across the workspace. They can:

- Create, update, and delete users, including other Platform Admins.
- Create, edit, and delete Knowledge Spaces.
- Query across visible spaces and switch the active Knowledge Space.
- Upload documents and operate folder ingestion.
- Create and govern database connector profiles and approved schema catalogs.
- Review OCR blocks.
- View audit events.
- Import RAG evaluation datasets and launch evaluation runs.
- Configure inference roles, vLLM resources, ingestion profiles, and worker
  settings.

Use this role sparingly. It can change runtime behavior for the whole system.

### System Admin

System Admins are global operational administrators. They can:

- Manage users except Platform Admin accounts.
- Manage Knowledge Spaces and documents globally.
- Query, upload, reingest, restore, and delete documents.
- Create and govern database connector profiles and approved schema catalogs.
- Review OCR blocks.
- View audit events.
- Recover stale ingestion jobs.

System Admins do not have access to Platform Admin-only configuration pages or
RAG Evaluation.

### User Manager

User Managers provision and maintain users in their assigned scope. They can:

- Open User Management.
- Create users for assignable roles.
- Edit user name, role, active state, and Knowledge Space memberships.
- Delete manageable users.

They cannot query, upload, review OCR, view audit, or change system
configuration.

### Space Admin

Space Admins own one or more Knowledge Spaces. They can:

- Create, edit, and delete allowed Knowledge Spaces.
- Upload, reingest, restore, soft delete, and in scoped cases permanently delete
  documents.
- Upload folder snapshots.
- Create and govern database connector profiles and approved schema catalogs
  for their allowed Knowledge Spaces and clearance.
- Query documents in their spaces.
- View ingestion health and activity for visible content.

Permanent deletion is restricted and should be used only when retention policy
allows it.

### Contributor

Contributors maintain documents in assigned spaces. They can:

- Query visible indexed documents.
- Upload files into writable Knowledge Spaces.
- Track ingestion jobs.
- Reingest, restore, or move writable documents to Trash.

They cannot manage users, spaces, review queues, audit pages, RAG evaluations,
or platform settings.

### Reviewer

Reviewers resolve extraction issues. They can:

- Query visible indexed documents.
- Open the OCR Review Queue.
- Inspect source pages and correction context.
- Approve corrected extraction text or reject a bad block.
- View ingestion status for visible content.

Reviewers normally do not upload or manage documents.

### Auditor

Auditors inspect governance activity. They can:

- Open System Audit.
- Review visible audit events, actors, targets, payload summaries, and creation
  times.
- View visible document and Knowledge Space metadata where the application
  exposes it.
- View ingestion activity and health summaries.

Auditors do not have Query Intelligence, upload, review, user management, or
configuration access.

### Member

Members use the system for grounded answers. They can:

- Ask questions in Query Intelligence.
- Scope queries to a Knowledge Space or individual documents.
- Inspect citations and evidence.
- View documents visible to their role and clearance.
- Open their own Account page and change their password.

Members cannot upload, manage documents, review OCR, audit, manage users, or
change settings.

## Getting Started

1. Open the web app. In the local Compose deployment, the default frontend URL
   is `http://localhost:3000`.
2. Sign in with your email and password.
3. If prompted, open Account Management and change your password.
4. Check the active Knowledge Space selector in the sidebar header.
5. Use the sidebar to open the pages your role allows.

The initial deployment can bootstrap a Platform Admin using the configured
`BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`. After first sign-in,
replace the bootstrap password with a strong deployment-specific password.

## Account Management

Every signed-in user can open **Account Management** from the sidebar footer.
Use it to:

- Confirm your email, Knowledge Spaces, and permission version.
- Change your password. New passwords must be at least 8 characters.
- Sign out.

If your role or Knowledge Space assignment changes, your permission version may
change. Saved chat history and generated artifacts are scoped to the permission
version that created them.

## Query Intelligence

Use **Query Intelligence** to ask questions against indexed documents.

### Ask a Question

1. Select the active Knowledge Space in the sidebar header.
2. Choose **Auto**, **Documents**, **Live DB**, or **Hybrid** in the composer.
3. If using Live DB or Hybrid, optionally select one approved database source.
   Leave the selector on **All visible DB sources** to let Prudentia choose from
   every approved source you can access.
4. Type a question in the composer.
5. Press Enter or click Send. Use Shift+Enter for a new line.
6. Watch the live progress panel as the graph routes the query, retrieves
   evidence, and drafts the answer.
7. Review citations before relying on the answer.

If there are no current indexed documents in the active space, upload or index a
document first.

### Scope a Question to Documents

Type `@` in the composer to search matching documents in the active space. Pick
one or more documents to narrow retrieval. Remove a scoped document from the
chip above the composer.

Document tags apply to Documents, Auto, and Hybrid questions. Live DB mode does
not use tagged document IDs.

### Choose Documents, Live Data, or Both

Use source mode deliberately when the origin of the answer matters:

- Choose **Documents** for policies, manuals, contracts, reports, or any answer
  that must come only from indexed files.
- Choose **Live DB** for current counts, statuses, lists, or other structured
  facts stored in an approved SQL Server or PostgreSQL database.
- Choose **Hybrid** when the answer needs both a live fact and document context,
  such as comparing a current case status with a policy requirement.
- Keep **Auto** when you want Prudentia to infer the best source. Questions that
  clearly ask for counts or structured records favor live data when an approved
  source is visible; document-oriented questions favor the corpus.

If a selected source cannot answer the question, the response may offer
**Search all sources**. Use it to rerun the question in Hybrid mode across the
sources you can access.

### Inspect Evidence

Answers include source chips and inline citation links. Select a citation to
open the evidence inspector. Depending on the source, the viewer can show:

- PDF page highlights.
- DOCX text highlights.
- Image highlights.
- Extracted image evidence from PDFs or DOCX files.
- Live database rows labeled with the approved database scope and generated
  query context.

Warnings such as degraded response, conflicting sources, low faithfulness, or
failed grounding mean you should inspect the cited evidence carefully.

### Ask Corpus-Level Graph Questions

GraphRAG is designed for themes, patterns, relationships, trends, recurring
issues, risks, and executive overviews across documents that were opted in.
Useful prompts include:

- "What are the major themes across all documents in this space?"
- "Which risks or recurring issues appear across the collection?"
- "Give me an executive overview of the main patterns and relationships."

GraphRAG is considered only for corpus-level questions when accessible graph
data exists for documents that were opted in; otherwise standard RAG is used.
GraphRAG still grounds its answer in source document chunks and returns normal
citations. If graph summaries are unavailable, incomplete, or outside your
access scope, Prudentia falls back to standard document retrieval and marks the
response as degraded when appropriate. Exact counts and exhaustive lists use
structured or standard retrieval rather than GraphRAG.

### Chat History

Completed conversations appear in the chat history rail. You can:

- Start a new chat.
- Reopen a saved conversation.
- Load more saved conversations.
- Delete a saved conversation.
- Collapse or expand the history rail.

Chat history is saved for the current user and permission version.

### Upload From Chat

If your role can upload to the active Knowledge Space, use the paperclip in the
composer to upload one PDF, DOCX, JPG, PNG, or JSON file up to 50 MB. The upload
is indexed into the active Knowledge Space and shows document-ingestion and,
when applicable, graph-enrichment progress in the composer.

### Generated Files

When a prompt requests a deliverable such as a DOCX, PDF, or PPTX, Prudentia may
start a document generation job. The job panel shows progress, requested
formats, clarification questions, retry/cancel actions, and download links when
files are ready.

Generated file access follows the user and permission version that created the
job.

## Document Intake

Open **Add Files** to upload documents into the searchable corpus.

### Supported Files

Uploads support:

- PDF
- DOCX
- JPG / JPEG
- PNG
- JSON

Each file must be non-empty and no larger than 50 MB. Each selected file creates
its own ingestion job.

### Upload Documents

1. Open **Document Intake > Add Files**.
2. Select one or more supported files.
3. Choose a writable Knowledge Space.
4. Choose **Fast**, **Balanced**, or **High accuracy** under **Ingestion
   Quality**.
5. Optionally enable **GraphRAG** to include these documents in graph-based
   relationship and corpus analysis. Leave it off for standard RAG only.
6. Optionally set an effective date and expiry date.
7. Optionally add a description.
8. For a single-file upload, optionally enter document IDs in **Supersedes** to
   link the new file as a replacement.
9. Click **Upload documents**.
10. Watch **Recent upload jobs** for per-file document and optional graph
    progress.

Documents inherit the selected Knowledge Space and clearance controls. The
system scans, stores, parses, enriches metadata, chunks, embeds, indexes, and
finalizes each document.

### Cancel Upload Jobs

Users with write access to the document can cancel scheduled, queued, or active
ingestion jobs. Cancelled jobs do not finish indexing.

### Folder Sources

Space Admins and global admins can open **Folder Sources** to upload local
folder snapshots for bulk ingestion.

Choose a folder from the browser to stage a point-in-time snapshot. Supported
PDF, DOCX, JPG, PNG, and JSON files are uploaded with their relative paths, and
unsupported files are recorded as skipped.

Folder snapshots are one-time schedules. To ingest later local edits, choose the
folder again and create a new snapshot. The page lists schedules, runs, and run
items, and supports pausing, resuming, cancelling, and editing schedule timing.

## Database Connectors

Platform Admins, System Admins, and Space Admins can open **Document Intake >
Database Connectors** to prepare governed live database access. The current
connector workflow supports SQL Server and PostgreSQL.

Database connectors do not copy database rows into the document corpus and do
not create recurring record-sync schedules. Those schedules are retired. At
question time, Prudentia generates a read-only SQL query, validates it against
an approved schema catalog, applies result limits and a timeout, and then uses
the returned rows as answer evidence.

### Create and Test a Connection Profile

1. Open **Database Connectors** and click **Add profile**.
2. Choose SQL Server or PostgreSQL.
3. Enter a profile name, server or host, port, database, read-only user, and
   password.
4. For SQL Server, choose ODBC Driver 18, Driver 17, or a deployment-specific
   custom driver. For PostgreSQL, choose the required SSL mode.
5. Click **Save**. Credentials are encrypted at rest and redacted after save.
6. Click **Test** on the saved profile and confirm that the connection succeeds.

Use a database account that has only the minimum read permissions needed for
the approved scope. Editing a profile changes future introspection and Live DB
queries. Replacement user and password fields can be left blank to keep the
stored credentials.

### Capture and Review the Schema

1. Click **Schema** on a tested profile.
2. Review the captured table, column, relationship, index, and estimated-row
   information. Raw schema JSON is available for detailed inspection.
3. Click **AI draft** to create a reviewable schema catalog. A writable
   Knowledge Space is required. Prudentia enriches tables one at a time and
   saves completed work, so the window can be closed while enrichment continues.
4. Open **Review** under **Approved database scopes**.
5. Correct the catalog name, business rules, table and column descriptions, and
   synonyms. Mark tables and columns as allowed or disallowed, and flag
   sensitive fields.
6. Select the Knowledge Space and clearance level that govern who can see this
   source.
7. Save the catalog as draft or reviewed, or click **Approve Scope** when the
   catalog is ready for live queries.

AI-generated descriptions are suggestions only. Live DB retrieval cannot use a
catalog until it is approved. Only approved, non-sensitive tables, columns, and
relationships can be used; wildcard column selection, write statements,
unapproved joins, system schemas, and chained SQL statements are blocked.

### Manage Approved Database Scopes

The connector overview shows saved profiles, approved scope count, test status,
and Live DB readiness. You can edit, retest, re-introspect, review, disable, or
delete profiles and catalogs as permissions allow.

Disabling a catalog removes it from Live DB source selection without deleting
the profile. Deleting a profile should be treated as a governance change because
future live questions can no longer use any catalog tied to that connection.

## Activity and Ingestion Health

### Activity

Open **Document Intake > Activity** to track upload, folder, reingest, and
restore jobs.

Use filters for:

- Search by document, job ID, or space.
- Status.
- Origin.
- Knowledge Space.
- Created date range.

The table shows origin, status, progress, started time, stage details, warnings,
attempt count, and parser provenance. Writable active jobs can be cancelled.

### Ingestion Health

Open **System Overview > Ingestion Health** to monitor:

- Active pipeline count.
- Needs-review count.
- Failed run count.
- Completed run count.
- Stage distribution.
- Folder schedule health.
- Model runtime health, for Platform Admins.
- Worker capacity, for Platform Admins.
- GraphRAG queue, worker, and active-task status.
- Recent failures.

The **GraphRAG activity** panel shows whether graph enrichment is available, how
many opted-in jobs are queued, whether a graph worker is online, and which
document tasks are active. A document can already be indexed while this
separate enrichment step is still queued or running. Documents whose uploader
left GraphRAG off do not enter this queue.

Global admins can also see stale processing runs and requeue recoverable jobs.

## Document Library

The Document Library has four main views:

- **Document Overview**: summary metrics, recommended next step, attention
  items, recent activity, and library by space.
- **Space Explorer / Knowledge Spaces**: folder tree and direct documents in
  selected spaces.
- **Documents**: searchable document table.
- **Trash**: soft-deleted documents.

### Search and Filter Documents

Use document filters to narrow by:

- Text search.
- Lifecycle: current or superseded.
- Ingestion state: indexed, processing, needs review, cancelled, failed, or
  unknown.

Select a document to open the inspector.

### Document Inspector

The inspector can show:

- Title, Knowledge Space, ingestion status, lifecycle, dates, and uploader.
- Description and summary.
- Metadata review flags.
- Topics and LLM topics.
- Entities.
- Cross references.
- Extracted claims.
- Version chain.
- Download link for the original source file.

Available actions depend on your role and scope:

- **Download**: opens or downloads the original file.
- **Reingest**: queues a new ingestion job from the stored source file.
- **Move to Trash**: soft deletes the document and removes indexed vectors.
- **Restore**: restores a Trash document and queues reingestion.
- **Permanently Delete**: removes the source file, image assets, vectors, and
  record where policy and role allow.

### Knowledge Space Management

Space Admins and global admins can create, edit, or delete Knowledge Spaces.
Deleting a Knowledge Space only works when it is empty, has no child spaces, and
has no assigned users.

## OCR Review Queue

Open **Review Queue** to resolve low-confidence extraction blocks before
affected documents continue into the searchable library.

The review workspace includes:

- Pending OCR blocks grouped by document.
- Confidence indicators and quality flags.
- Original page preview with highlighted region when available.
- Original OCR text.
- Editable corrected extraction text.

To review an item:

1. Select a pending block.
2. Compare the OCR text with the document page.
3. Edit **Corrected extraction text**.
4. Click **Approve correction** to save the corrected text, or **Reject block**
   if the block should not continue.

Approval requires non-empty corrected text. When the queue is clear, the page
shows a ready state.

## User Management

Platform Admins, System Admins, and User Managers can open **User Management**.

### Create a User

1. Click **Create user**.
2. Enter email and name.
3. Choose an account type from the roles you are allowed to assign.
4. Copy or regenerate the initial password.
5. Mark the account active or inactive.
6. Select Knowledge Space memberships.
7. Click **Create user**.

Copy the generated password before leaving the dialog. The password is the
handoff credential for the new user.

### Edit a User

Open **Edit** on a user row to update:

- Name.
- Account type.
- Active state.
- Knowledge Space memberships.

If you edit your own account, your session context may refresh after saving.

### Delete a User

User deletion requires typing the target email address to confirm. Deleting a
user removes the account, memberships, chat history, and generated artifacts.
Documents and audit history are retained.

### Assignment Limits

- Platform Admins can assign any role.
- System Admins can assign any role except Platform Admin.
- User Managers cannot assign Platform Admin or System Admin.
- Scoped managers can only assign spaces and clearance levels allowed by their
  own account.

## System Audit

Open **System Audit** to review append-only activity visible to your account.

The audit page shows:

- Visible event count.
- Document event count.
- Event type count.
- Actor count.
- Event type and ID.
- Target type and target ID.
- Actor ID or System.
- Payload summary.
- Created time.

Audit records cover authentication, document mutations, ingestion status, and
other workspace activity.

## RAG Evaluation

RAG Evaluation is Platform Admin-only. Use it to test answer quality with
repeatable datasets.

### Import a Dataset

1. Open **RAG Evaluation**.
2. In **Dataset Import**, enter a dataset name or upload a `.json` / `.jsonl`
   file.
3. Choose auto detect, JSON, or JSONL.
4. Paste or load the dataset content.
5. Click **Import dataset**.

Dataset cases should include a `question` or `query`. Recommended fields include
stable `id` or `case_id`, expected source documents, must-include text,
must-not-include text, citation requirements, faithfulness threshold, and
latency threshold.

### Launch a Run

1. Choose a dataset.
2. Optionally set a Knowledge Space.
3. Optionally provide document IDs.
4. Optionally provide case IDs or a numeric limit. Do not use both.
5. Click **Run evaluation**.

The page shows pass rate, retrieval, reranking, citation, faithfulness,
fallback, and latency metrics. Run inspection shows failure breakdown, case
results, answer text, diagnostics JSON, and node timings.

Active runs can be cancelled. Failed, partial, or cancelled runs can be retried.

## System Configuration

The **Configs** page is Platform Admin-only. It is divided into **Models &
Roles**, **Inference Services**, and **Ingestion Worker Capacity**. The status
strip shows the active stack, whether the draft differs from the active config,
model discovery health, and whether a vLLM restart is pending.

### Models & Roles

Use the guided workflow in order:

1. **Choose stack**: start from **Ollama local** or **vLLM text stack**. The
   resulting configuration becomes Custom when role assignments are mixed.
2. **Check services**: Prudentia discovers models from each selected provider
   and reports the health of the language, vision, and embedding services.
3. **Assign roles**: choose a provider, endpoint, and model for each runtime
   role.
4. **Tune behavior**: set shared budgets, timeouts, model thinking, and query
   planning.
5. **Test and activate**: click **Test draft** before **Save & activate**.

Runtime roles are:

| Role | Purpose |
| --- | --- |
| Answer synthesis | Produces the final grounded response |
| Reasoning | Supports planning, rewrites, dates, and complex retrieval |
| Router | Checks ambiguous routes before retrieval or file generation |
| Faithfulness | Checks whether generated answers are grounded |
| Ingestion metadata | Generates summaries, topics, document types, and claims |
| Vision | Performs image OCR, captions, and optional PDF layout repair |
| Embeddings | Creates dense vectors with FastEmbed, Ollama, or vLLM |
| Reranker | Reorders retrieved evidence before synthesis |

Changing the embedding provider or model requires reindexing existing documents
so stored vectors match the active embedding model.

Runtime behavior includes:

- **JSON/Layout output budget** for planning, composition, and layout contracts.
- **Evidence token budget** for evidence passed into answer synthesis.
- **Chat timeout** and **Embed timeout**.
- **Model thinking**, which applies only to Ollama language roles.
- **Query planner**, which breaks complex retrieval questions into focused
  subqueries. Keep it enabled for multi-part, comparison, and multi-hop
  questions; GraphRAG global routing bypasses the planner automatically.

Testing validates the draft without activating it. Saving validates again and
makes the assignments active without restarting containers.

### Inference Services and vLLM Limits

Use **Inference Services** to check provider availability and manage launch
limits for the vLLM text, embedding, and vision services:

- Max model length.
- GPU memory utilization.
- Max sequences.
- Batched tokens.
- KV cache memory where supported.

Saving limits records a restart requirement. Applying limits restarts only the
selected vLLM service, interrupts requests using that service, and recreates its
container. These controls do not change the active model assignments in
**Models & Roles**.

### Ingestion Profiles and Worker Capacity

Use **Ingestion Worker Capacity** to choose how new documents are parsed and how
many jobs each worker replica can process at once.

The profile on **Add Files** applies to that upload batch. The Configs value is
the workspace default for ingestion requests that do not explicitly choose a
profile.

| Ingestion profile | Behavior | Use when |
| --- | --- | --- |
| Fast | Native text first, no vision, and capped Docling repair | High-volume, text-native documents where throughput matters most |
| Balanced | Native text first with a larger Docling page-repair budget | Mixed collections with some complex layouts |
| High accuracy | Deeper Docling layout repair and preference for full-document repair | Fidelity-sensitive scans, tables, or layout-heavy documents |

Additional controls are:

- **Worker concurrency**: 1-10 per worker replica. One is recommended for the
  default 8 GB Docker environment. The page warns above 2 and requires hazard
  confirmation above 4.
- **OCR review threshold**: 0-100 percent. Blocks below the selected confidence
  pause in Review Queue.
- **Vision layout repair**: asks the assigned vision model to re-read complex
  PDF pages after Docling. Keep it off for faster bulk ingestion; enable it when
  layout fidelity is more important than throughput.

The active-config facts show worker availability, the selected quality profile,
apply status, observed pool size, active jobs, OCR threshold, and vision-repair
state. Quality, OCR, and vision choices apply to new jobs. If no worker is
online, the configuration is saved and capacity applies when a worker starts.

## Common Troubleshooting

### I Cannot See a Page

Your role does not have that route. Ask a Platform Admin, System Admin, or User
Manager to confirm your account type and Knowledge Space memberships.

### I Cannot Query

Check that:

- Your role includes Query Intelligence access.
- The active Knowledge Space has current indexed documents.
- Your clearance level is high enough for the documents.
- The inference runtime is healthy.
- The selected source mode has at least one accessible source.

If **Live DB** shows **No DB sources**, confirm that an approved schema catalog
exists for your active Knowledge Space and clearance. If a selected database
source cannot answer the question, use **Search all sources** when offered.

### My Upload Was Rejected

Check that:

- The file is PDF, DOCX, JPG, JPEG, PNG, or JSON.
- The file is not empty.
- The file is 50 MB or smaller.
- You selected a writable Knowledge Space.
- Virus scanning and storage services are healthy.

### A Document Says Needs Review

Open Review Queue with a Reviewer, System Admin, or Platform Admin account.
Approve corrected OCR text or reject bad blocks so ingestion can continue.

### A Job Looks Stuck

Open Ingestion Health and Activity. Global admins can inspect stale processing
runs and requeue recoverable jobs. For repeated failures, review the job error,
parser provenance, worker health, and runtime model health.

### Graph Enrichment Is Queued or Unavailable

Document indexing and optional GraphRAG enrichment are separate. A completed
document is searchable even when its opted-in graph task is queued or running.
Check **Ingestion Health > GraphRAG activity** for queue depth, worker status,
and active tasks. If GraphRAG was not selected for the document, no graph task
is expected.

If graph status is unavailable, report the document or job ID to operations.
Standard document retrieval remains available; corpus-level graph answers may
fall back or show a degraded warning until enrichment and graph services recover.

### Live Database Queries Fail or Return No Rows

Check that:

- The connection profile test succeeds.
- The schema was re-introspected after database changes.
- The catalog is approved rather than draft, reviewed, or disabled.
- The required tables, columns, and relationships are allowed and not marked
  sensitive.
- The catalog Knowledge Space and clearance are visible to the user.
- The database account still has read access and the query can finish within
  the configured timeout.

Review or disable the catalog instead of broadening access blindly. Live SQL is
restricted to one validated read-only query and bounded results.

### AI Schema Enrichment Is Incomplete

Completed tables are saved as enrichment proceeds. Reopen **Review Schema
Catalog** and click **Continue AI Enrichment** to retry remaining tables. If AI
enrichment continues to fail, administrators can review the raw introspection
metadata, edit descriptions and sensitivity flags manually, and approve only
after a full human review.

### Sources Look Wrong or Missing

Open the citation evidence inspector. If source highlighting is unavailable,
use the original document link and compare page, excerpt, and Knowledge Space.
Low faithfulness, degraded response, or conflict warnings should be treated as
signals to verify the evidence manually.

### RAG Evaluation Failed

Use Run Inspection to identify the primary failure stage:

- Dataset
- Ingestion / indexing
- Retrieval
- Source selection
- Answer content
- Citation
- Faithfulness
- Degradation
- Runtime
- Latency

Fix the relevant dataset, document ingestion, runtime configuration, or prompt
expectations, then retry the run.

## First-Day Checklists

### Platform Admin

1. Sign in with the bootstrap account.
2. Change the bootstrap password.
3. Confirm **Configs** runtime health, role assignments, query planner, and
   ingestion profile.
4. Confirm GraphRAG queue and worker health in Ingestion Health when GraphRAG is
   enabled.
5. Create top-level Knowledge Spaces.
6. Create System Admin, User Manager, Space Admin, Reviewer, Auditor, and
   Member accounts as needed.
7. If live database access is required, test a connector, review its schema,
   and approve only the minimum required database scope.
8. Import or upload pilot documents.
9. Run cited document, Live DB, Hybrid, and corpus-level graph questions as
   applicable.
10. Review System Audit for expected activity.

### System Admin

1. Confirm users and spaces are ready.
2. Upload or schedule documents.
3. Monitor Activity and Ingestion Health.
4. Resolve failed or stale ingestion jobs.
5. Review OCR blocks when needed.
6. Test and review database connector scopes when live data is in use.
7. Check audit events for important document mutations.

### User Manager

1. Open User Management.
2. Search for the target user.
3. Create or edit users inside your allowed scope.
4. Confirm account type, active state, and Knowledge Spaces.
5. Hand off the initial password securely.

### Space Admin

1. Create or confirm Knowledge Spaces.
2. Upload documents or configure folder sources.
3. If live data is required, test a read-only connector and approve a
   least-privilege schema catalog for the correct space and clearance.
4. Monitor ingestion and GraphRAG activity.
5. Reingest or restore documents as needed.
6. Clean Trash only when retention policy allows.

### Contributor

1. Select the correct writable Knowledge Space.
2. Upload source files with dates and description.
3. Track ingestion progress.
4. Ask a smoke query after indexing completes.
5. Reingest or move incorrect documents to Trash if needed.

### Reviewer

1. Open Review Queue.
2. Work from lowest-confidence or oldest blocks.
3. Compare OCR text to source page.
4. Approve corrected text or reject unusable blocks.
5. Refresh the queue and continue until clear.

### Auditor

1. Open System Audit.
2. Review recent document and authentication events.
3. Check target, actor, payload, and created time.
4. Open visible library metadata when more context is needed.
5. Escalate suspicious or missing activity to an admin.

### Member

1. Pick the correct Knowledge Space.
2. Choose Auto, Documents, Live DB, or Hybrid for the question.
3. Ask a focused question.
4. Use `@` to scope to a document when needed.
5. Inspect citations and evidence.
6. Start a new chat when switching topics.
