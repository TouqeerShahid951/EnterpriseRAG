# Faham AI User Guide

Last updated: 2026-06-18

This guide explains how to use the Faham AI / AgenticRAG workspace from the
web application. It covers every account type and the main workflows users see
in the sidebar.

For offline Windows deployment and runtime setup, see
[Windows Airgapped Runtime Runbook](windows-airgap-runbook.md) and
[Airgap Runtime Mode](airgap-runtime.md).

## What This System Does

Faham AI is an enterprise RAG workspace for uploading controlled documents,
indexing them into Knowledge Spaces, asking grounded questions, reviewing
low-confidence OCR, auditing activity, and evaluating answer quality.

The application is organized around these areas:

- **Operate**: workspace summary, ingestion health, and Query Intelligence.
- **Corpus**: document intake, folder sources, activity, document library, and
  Knowledge Spaces.
- **Evaluate**: OCR review and RAG evaluation.
- **Govern**: audit trail, user management, and platform configuration.

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

## Role Summary

| Role | Main purpose | Typical access |
| --- | --- | --- |
| Platform Admin | Full platform ownership | All pages, all spaces, user management, audit, review, RAG evaluation, and system configuration |
| System Admin | Global operations without platform config | Query, intake, library, review, audit, user management, and operational recovery |
| User Manager | Account provisioning | Create and manage non-global-admin users inside assigned scopes |
| Space Admin | Knowledge Space and document governance | Query, upload, folder sources, library management, ingestion visibility, and space administration |
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
- Review OCR blocks.
- View audit events.
- Import RAG evaluation datasets and launch evaluation runs.
- Configure inference runtime, vLLM resources, and ingestion worker settings.

Use this role sparingly. It can change runtime behavior for the whole system.

### System Admin

System Admins are global operational administrators. They can:

- Manage users except Platform Admin accounts.
- Manage Knowledge Spaces and documents globally.
- Query, upload, reingest, restore, and delete documents.
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
- Schedule folder sources.
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
2. Type a question in the composer.
3. Press Enter or click Send. Use Shift+Enter for a new line.
4. Watch the live progress panel as the graph routes the query, retrieves
   evidence, and drafts the answer.
5. Review citations before relying on the answer.

If there are no current indexed documents in the active space, upload or index a
document first.

### Scope a Question to Documents

Type `@` in the composer to search matching documents in the active space. Pick
one or more documents to narrow retrieval. Remove a scoped document from the
chip above the composer.

### Inspect Evidence

Answers include source chips and inline citation links. Select a citation to
open the evidence inspector. Depending on the source, the viewer can show:

- PDF page highlights.
- DOCX text highlights.
- Image highlights.
- Extracted image evidence from PDFs or DOCX files.

Warnings such as degraded response, conflicting sources, low faithfulness, or
failed grounding mean you should inspect the cited evidence carefully.

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
composer to upload one PDF, DOCX, JPG, or PNG file up to 50 MB. The upload is
indexed into the active Knowledge Space and shows progress in the composer.

### Generated Files

When a prompt requests a deliverable such as a DOCX, PDF, or PPTX, Faham may
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

Each file must be non-empty and no larger than 50 MB. Each selected file creates
its own ingestion job.

### Upload Documents

1. Open **Document Intake > Add Files**.
2. Select one or more supported files.
3. Choose a writable Knowledge Space.
4. Optionally set an effective date and expiry date.
5. Optionally add a description.
6. For a single-file upload, optionally enter document IDs in **Supersedes** to
   link the new file as a replacement.
7. Click **Upload documents**.
8. Watch **Recent upload jobs** for per-file progress.

Documents inherit the selected Knowledge Space and clearance controls. The
system scans, stores, parses, enriches metadata, chunks, embeds, indexes, and
finalizes each document.

### Cancel Upload Jobs

Users with write access to the document can cancel scheduled, queued, or active
ingestion jobs. Cancelled jobs do not finish indexing.

### Folder Sources

Space Admins and global admins can open **Folder Sources** to schedule bulk
ingestion.

Two source modes are available:

- **Browser snapshot**: choose a local folder in the browser and submit a
  snapshot of files.
- **S3/MinIO prefix**: enter a bucket and prefix. Credentials remain on the
  backend; the schedule stores only bucket, prefix, schedule, and metadata.

Schedules can be one-time or recurring. Recurring schedules include days of
week and a time window. The page lists schedules, runs, and run items, and
supports pausing, resuming, cancelling, and editing schedule timing.

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
- Recent failures.

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

System Configuration is Platform Admin-only.

### Inference Runtime

Use **Inference Runtime** to choose the active provider and model roles.

Supported providers:

- Ollama
- vLLM

The panel configures:

- Local or network inference location.
- Chat, embedding, reasoning, routing, faithfulness, and ingestion endpoints.
- Answer synthesis model.
- Embedding model.
- Reranker model.
- Optional reasoning, routing, faithfulness, ingestion, and vision/OCR models.
- Model thinking for Ollama.
- JSON/Layout budget.
- Evidence retrieval token budget.
- Chat and embedding timeouts.

Click **Test draft** to validate a draft without activating it. Click
**Save & activate** to validate and make the runtime active.

### vLLM Container Resources

Use this panel to save or apply vLLM resource limits:

- Max model length.
- GPU memory utilization.
- Max sequences.
- Batched tokens.
- KV cache memory where supported.

Applying these limits recreates vLLM containers and interrupts active
generation. These settings do not choose the active inference provider.

### Ingestion Worker Capacity

Use this panel to configure:

- Worker concurrency, from 1 to 10.
- OCR review threshold, from 0 to 100 percent.

OCR blocks below the configured confidence threshold pause for review. High
concurrency can exhaust memory when Docling parses multiple documents; the UI
warns above 2 and requires confirmation above 4.

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

### My Upload Was Rejected

Check that:

- The file is PDF, DOCX, JPG, JPEG, or PNG.
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
3. Confirm System Configuration runtime health.
4. Create top-level Knowledge Spaces.
5. Create System Admin, User Manager, Space Admin, Reviewer, Auditor, and
   Member accounts as needed.
6. Import or upload pilot documents.
7. Run a smoke query and inspect citations.
8. Review System Audit for expected activity.

### System Admin

1. Confirm users and spaces are ready.
2. Upload or schedule documents.
3. Monitor Activity and Ingestion Health.
4. Resolve failed or stale ingestion jobs.
5. Review OCR blocks when needed.
6. Check audit events for important document mutations.

### User Manager

1. Open User Management.
2. Search for the target user.
3. Create or edit users inside your allowed scope.
4. Confirm account type, active state, and Knowledge Spaces.
5. Hand off the initial password securely.

### Space Admin

1. Create or confirm Knowledge Spaces.
2. Upload documents or configure folder sources.
3. Monitor ingestion jobs.
4. Reingest or restore documents as needed.
5. Clean Trash only when retention policy allows.

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
2. Ask a focused question.
3. Use `@` to scope to a document when needed.
4. Inspect citations and evidence.
5. Start a new chat when switching topics.
