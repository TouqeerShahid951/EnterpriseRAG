# Prudentia AI Administrator Manual

Last updated: 2026-06-30

This manual explains how to administer Prudentia AI from the web application. It
is written for Platform Admins, System Admins, User Managers, and Space Admins.
For startup, backup, update, and Docker runtime work, use the [Operator Manual](operator-manual.md).

## 1. Administrator Roles

| Role | Main responsibility | Important limits |
| --- | --- | --- |
| Platform Admin | Full platform ownership, Configs, RAG Evaluation, users, spaces, audit, documents, connectors | Use sparingly. This role can change runtime behavior for the whole deployment. |
| System Admin | Global operations, users except Platform Admins, spaces, documents, review, audit, recovery | No Platform Admin-only Configs or RAG Evaluation access. |
| User Manager | Account provisioning within allowed scope | Cannot query, upload, audit, review OCR, or change settings. |
| Space Admin | Knowledge Space and document governance inside assigned scopes | Can manage allowed spaces and documents, but not global platform settings. |

### Account Type Assignment Reference

Use the narrowest role that lets the person do their job.

| Account type | Why it exists | Use it when the person needs to | Do not use it when |
| --- | --- | --- | --- |
| Platform Admin | Full platform ownership | Manage every user and space, change Configs, run evaluations, govern connectors, review audit, and make deployment-wide model choices | The person only needs operational or space-level administration |
| System Admin | Global operations without platform Configs | Manage users except Platform Admins, govern documents, recover ingestion, review audit, review OCR, and manage spaces globally | The person must change model/provider settings or run RAG Evaluation |
| User Manager | Account provisioning | Create users, reset passwords, activate or deactivate accounts, and assign allowed spaces and clearance | The person needs to query documents, upload files, or inspect audit |
| Space Admin | Space-level governance | Own documents, spaces, folder sources, and database scopes inside assigned Knowledge Spaces | The person needs global configuration or user management |
| Contributor | Document intake and maintenance | Upload, track, reingest, restore, or trash writable documents in assigned spaces | The person should only ask questions and inspect evidence |
| Reviewer | OCR quality review | Correct or reject low-confidence extraction blocks and monitor visible ingestion status | The person needs to upload or govern documents |
| Auditor | Governance review | Search, filter, inspect, and export visible audit events without changing system state | The person needs document content access through Query Intelligence |
| Member | Everyday knowledge use | Ask grounded questions, inspect citations, and browse visible document metadata | The person needs to upload, manage, review, audit, or configure anything |

If a page is not visible, the signed-in administrator does not have the role
required for that page.

## 2. First Platform Admin Checklist

After the operator starts the deployment:

1. Open the app URL. Local deployments commonly use `http://localhost:3000`.
2. Sign in with `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`.
3. Open **Account Management** and change the bootstrap password immediately.
4. Open **Configs** and confirm runtime model health.
5. Confirm the active provider stack, role assignments, query planner, and
   ingestion profile.
6. Create the top-level Knowledge Spaces.
7. Create System Admin, User Manager, Space Admin, Reviewer, Auditor,
   Contributor, and Member accounts as needed.
8. Upload a small pilot document and confirm it reaches **Indexed** status.
9. Ask a cited smoke-test question in **Query Intelligence**.
10. If Live DB is required, create and approve the first least-privilege
    database scope.
11. Review **System Audit** for the expected bootstrap, login, user, document,
    and configuration events.

## 3. User Management

Open **Govern > User Management**.

### Create A User

1. Select **Create user**.
2. Enter email and display name.
3. Choose an account type you are allowed to assign.
4. Choose a clearance level. Global admin roles receive the maximum effective
   clearance.
5. Select one or more Knowledge Space memberships.
6. Keep **Active account** selected unless the user should not sign in yet.
7. Copy or regenerate the initial password.
8. Select **Create user**.
9. Hand off the password securely. The user can change it after signing in.

Copy the initial password before closing the dialog. It is the handoff
credential.

### Edit A User

1. Select the edit action on the user row.
2. Update name, account type, clearance, active state, or Knowledge Spaces.
3. Save the user.

If you edit your own account, your session context may refresh after saving.

### Reset A Password

Use this when a user forgets their password or a temporary credential must be
issued.

1. Select the reset-password action on the user row.
2. Copy or regenerate the temporary password.
3. Select **Reset password**.
4. Copy the temporary password before closing the dialog.
5. Give the temporary password to the user through an approved secure channel.

Existing sessions for that user are signed out. The user must change the
temporary password at next sign-in. You cannot reset your own password from User
Management; use **Account Management** for your own password.

### Disable Or Delete A User

Disable an account when access should be blocked but memberships should remain
available for later review. Delete an account only when policy allows removal.

Deleting a user removes the account, memberships, chat history, and generated
artifacts. Documents and audit history are retained. User deletion requires
typing the target email address to confirm.

### Chat Activity

Platform Admins can inspect saved chat activity for managed users when the
action appears in User Management. Use this for governance and investigation
only, according to organizational policy.

## 4. Knowledge Space Management

Knowledge Spaces define document and live-data access boundaries. Space names
use path-like values such as `/finance`, `/legal/contracts`, or `/manuals`.

Space Admins and global admins can create, edit, and delete allowed spaces.
Deleting a Knowledge Space only works when the space is empty, has no child
spaces, and has no assigned users.

Recommended practice:

- Create top-level spaces before onboarding users.
- Assign users only to the spaces they need.
- Use child spaces when access should be narrower than the parent department.
- Keep space names stable because users, documents, folder sources, and
  database scopes depend on them.

## 5. Clearance Levels

Documents and users can carry these clearance levels:

- `NATO_UNCLASSIFIED`
- `NATO_RESTRICTED`
- `NATO_CONFIDENTIAL`
- `NATO_SECRET`
- `COSMIC_TOP_SECRET`

Users can access documents at or below their effective clearance level inside
their allowed Knowledge Spaces. Do not assign higher clearance than the user is
authorized to hold.

## 6. Document Governance

Use **Corpus > Document Library** to inspect and govern documents.

Common actions:

| Action | Effect |
| --- | --- |
| Download | Opens or downloads the original source file. |
| Reingest | Queues a new ingestion job from the stored source file. |
| Move to Trash | Soft deletes the document and removes indexed vectors. |
| Restore | Restores a Trash document and queues reingestion. |
| Permanently Delete | Removes source file, image assets, vectors, and the document record where policy and role allow. |

Use permanent deletion only when retention policy allows it. Prefer Trash when
an item should be hidden from retrieval but retained for review.

When replacing a document, use supersedes metadata so the previous version stays
auditable.

## 7. Folder Sources

Open **Corpus > Document Intake > Folder Sources** to upload local folder
snapshots for bulk ingestion.

Folder snapshots are one-time schedules. They do not continuously watch the
local folder. To ingest later file edits, choose the folder again and create a
new snapshot.

Use run details to review queued, skipped, cancelled, and failed files.
Unsupported files are recorded as skipped.

## 8. Database Connectors

Platform Admins, System Admins, and Space Admins can prepare governed live SQL
access from **Document Intake > Database Connectors**.

Supported source types:

- SQL Server
- PostgreSQL

Database connectors do not copy database rows into the document corpus. At
question time, Prudentia generates a read-only SQL query, validates it against
an approved schema catalog, applies result limits and a timeout, and uses the
returned rows as answer evidence.

### Connector Approval Workflow

1. Add a connection profile with a least-privilege read-only database account.
2. Save the encrypted profile.
3. Test the profile.
4. Capture schema metadata.
5. Create an AI draft catalog.
6. Review table and column descriptions, synonyms, relationships, business
   rules, allowed fields, and sensitivity flags.
7. Assign the correct Knowledge Space and clearance.
8. Save as draft or reviewed until ready.
9. Select **Approve Scope** only after human review is complete.

Only approved, non-sensitive tables, columns, and relationships can be queried.
Write statements, wildcard column selection, unapproved joins, system schemas,
and chained SQL statements are blocked.

## 9. OCR Review Administration

Reviewers, System Admins, and Platform Admins can open **Review Queue**.

If many documents pause in **Needs review**:

1. Review the configured OCR threshold in **Configs**.
2. Confirm the ingestion worker is healthy in **Ingestion Health**.
3. Have reviewers resolve the oldest or lowest-confidence blocks first.
4. Re-check Activity after approvals to confirm ingestion continues.

## 10. RAG Evaluation

RAG Evaluation is Platform Admin-only. Use it to measure answer quality with
repeatable datasets.

Dataset cases should include a `question` or `query`. Recommended fields
include stable IDs, expected source documents, must-include text, must-not-include
text, citation requirements, faithfulness threshold, and latency threshold.

Basic workflow:

1. Open **Evaluate > RAG Evaluation**.
2. Import a JSON or JSONL dataset.
3. Choose the dataset.
4. Optionally set Knowledge Space, document IDs, case IDs, or a numeric limit.
5. Select **Run evaluation**.
6. Review pass rate, retrieval, reranking, citation, faithfulness, fallback, and
   latency metrics.
7. Inspect failed cases and retry after fixing data, ingestion, runtime, or
   expectations.

Active runs can be cancelled. Failed, partial, or cancelled runs can be retried.

## 11. Configs

Configs is Platform Admin-only. It includes **Models & Roles**, **Inference
Services**, and **Ingestion Worker Capacity**.

### Models & Roles

Use the guided flow in order:

1. Choose a starting stack: **Ollama local** or **vLLM text stack**.
2. Check service discovery for language, vision, embedding, and reranker
   providers.
3. Assign runtime roles:

| Runtime role | Purpose |
| --- | --- |
| Answer synthesis | Produces the final grounded response. |
| Reasoning | Supports planning, rewrites, dates, and complex retrieval. |
| Router | Checks ambiguous routes before retrieval or file generation. |
| Faithfulness | Checks whether generated answers are grounded. |
| Ingestion metadata | Generates summaries, topics, document types, and claims. |
| Vision | Performs image OCR, captions, and optional PDF layout repair. |
| Embeddings | Creates dense vectors. |
| Reranker | Reorders retrieved evidence before synthesis. |

4. Tune budgets, timeouts, model thinking, and the query planner.
5. Select **Test draft**.
6. Select **Save & activate** only after validation succeeds.

Changing the embedding provider or embedding model requires reindexing existing
documents so stored vectors match the active embedding model.

### Inference Services

Use **Inference Services** to check provider availability and manage vLLM launch
limits. Applying vLLM limits restarts only the selected vLLM service and
interrupts requests using that service.

Do not switch the active provider to vLLM unless the vLLM services and model
caches are actually available. In the default Windows airgapped rollout, Ollama
is the expected provider until vLLM is deliberately enabled.

### Ingestion Worker Capacity

Use **Ingestion Worker Capacity** to set the default ingestion profile, OCR
review threshold, vision layout repair, and worker concurrency.

One worker-concurrency slot is recommended for the default 8 GB Docker
environment. Increasing concurrency can improve throughput only if CPU, memory,
OCR, model, and storage capacity can support it.

## 12. System Audit

Open **Govern > System Audit** to review append-only activity visible to your
account.

You can filter by:

- Search text.
- Category.
- Event type.
- Actor ID or email.
- Target type.
- Target ID.
- Knowledge Space.
- Date range.

Use **Export CSV** to preserve a filtered audit set. The exported file should be
handled according to your organization's sensitive-data policy.

## 13. Admin Troubleshooting

| Problem | Likely cause | Admin action |
| --- | --- | --- |
| User cannot sign in | Wrong password, inactive account, forced password change | Reset password, confirm active state, ask user to change temporary password. |
| User cannot see a page | Role does not include the route | Confirm account type and assign the correct role only if justified. |
| User cannot see documents | Wrong space, low clearance, lifecycle filter | Check Knowledge Space memberships, clearance, and document lifecycle. |
| Upload stuck in queued | Worker unavailable or capacity saturated | Check Ingestion Health and ask operator to inspect worker logs if needed. |
| Many Needs review jobs | OCR threshold too high or low-quality scans | Assign reviewers or tune threshold after policy review. |
| Live DB source missing | Catalog not approved or outside user's scope | Review connector catalog, Knowledge Space, clearance, and disabled state. |
| Query answers degrade | Runtime provider, retrieval, or source availability issue | Check Configs health, document indexing, and source mode. |
| GraphRAG unavailable | Graph worker or Neo4j unavailable, or docs not opted in | Check Ingestion Health and operator runtime status. |

## 14. Admin Safety Rules

- Use least privilege for roles, Knowledge Spaces, database scopes, and
  clearance.
- Do not approve database catalogs without human review.
- Do not broaden access just to make a query work.
- Do not change model provider or embedding model without a reindex plan.
- Do not permanently delete documents unless retention policy allows it.
- Document operational incidents with timestamps, job IDs, user IDs, document
  IDs, and screenshots where appropriate.
