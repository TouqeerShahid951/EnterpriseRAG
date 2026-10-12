# .NET application integration guide

**Status:** Proposed contract. AgenticRAG does not yet accept external JWTs on its public query or upload routes.

This guide describes the work for the .NET application. The .NET frontend calls the ASP.NET backend. The ASP.NET backend calls AgenticRAG over a private network. AgenticRAG remains a Python service and owns document ingestion, indexing, retrieval, and citations.

~~~text
User → .NET frontend → ASP.NET backend → AgenticRAG API
                              │                 ├─ upload → ingestion workers
                              │                 └─ query → answer + citations
                              └─ app identity, RBAC, and application data
~~~

## Responsibilities

| .NET application | AgenticRAG |
| --- | --- |
| Sign users in and remain the source of truth for app roles. | Own Knowledge Spaces, documents, ingestion jobs, indexes, and retrieval. |
| Decide which RAG spaces each user may read and write. | Verify the signed user context and enforce its read/write scopes. |
| Make server-to-server API calls and display chat, upload status, and citations. | Process uploads and ensure retrieval only returns authorized evidence. |

Do not call RAG from browser code, use its SERVICE_TOKEN for end-user requests, or connect the .NET app directly to RAG's Postgres, Redis, Qdrant, MinIO, or worker queues.

## Knowledge Space administration

The .NET app may provide an administrator screen to list, create, rename, and delete Knowledge Spaces. AgenticRAG stores the canonical space paths and document associations; the .NET app stores which users or roles may read and write each path. Start with the four planned spaces (for example, /space-a through /space-d). A screen to create more spaces is optional if those four will remain fixed.

For an administrator action, the frontend calls ASP.NET. ASP.NET checks its own RBAC and sends a short-lived JWT with a separate `rag:spaces:manage` capability to a private RAG management API. RAG verifies that capability and performs the space change. Existing `/api/v1/admin/groups` routes provide list/create/update/delete semantics, but currently require a local RAG session; bearer support for them is part of the integration work. Keep the space path stable after creation; change its display name when a label needs updating. Before deletion, .NET must clear its user/role assignments and RAG must reject a space that still owns documents or other RAG records.

The .NET app's user-assignment screen records read access, write access, and maximum clearance in its own RBAC database. It does not create RAG user accounts. Each query or upload JWT carries the current assignments. After creating a space, store the canonical path returned by RAG in the .NET mapping; handle a failed second step with a retry or reconciliation rather than assuming the two databases changed together.

Record read and write separately. A user may be allowed to query a space without being allowed to upload into it. Also agree on the maximum clearance each user may query or assign to an upload.

| .NET role or entitlement | RAG read spaces | RAG write spaces | Maximum clearance |
| --- | --- | --- | --- |
| Fill in | Fill in | Fill in | Fill in |

The frontend may let a user choose among their authorized spaces. The backend must check the user's permissions and RAG will check them again. A space name supplied in a request is a requested scope, never proof of permission.

## Identity token

The ASP.NET backend issues a short-lived signed JWT for AgenticRAG after it authenticates the user and checks the user's current RBAC. No OIDC integration is required. The JWT is a server-to-server assertion: it tells RAG which app user made the request and which RAG scopes the app authorized.

The proposed claims are:

~~~json
{
  "iss": "https://<trusted-issuer>",
  "aud": "agenticrag-api",
  "sub": "<immutable-app-user-id>",
  "iat": 1790790000,
  "exp": 1790790300,
  "scope": "rag:query rag:ingest",
  "rag_read_groups": ["/space-a", "/space-b"],
  "rag_write_groups": ["/space-a"],
  "rag_clearance_level": "NATO_CONFIDENTIAL"
}
~~~

This is an example contract, not a live token. Agree the issuer, audience, claim names, clearance vocabulary, token lifetime, and signing-key distribution with the RAG developer before implementing it.

- Create the JWT in the ASP.NET backend only, after authenticating the user's app session and resolving permissions from the app's RBAC. Never let the frontend create or edit permission claims.
- Use asymmetric signing (such as RS256 or ES256). Keep the private key in the .NET backend; give RAG the corresponding trusted public key or a JWKS endpoint. Never share RAG's local JWT_SECRET_KEY.
- Keep the token short-lived (for example, five minutes). The JWT is signed, not encrypted; do not put passwords, secrets, or document contents in it.
- Use a stable sub, not an email address. RAG can identify a principal by the issuer and subject together.
- Include only the exact RAG group paths already created in RAG. Grant `rag:spaces:manage` only after the ASP.NET backend checks the app's space-management permission; do not turn a broad role name into unrestricted RAG access.

The ASP.NET backend sends the token only to RAG:

~~~http
Authorization: Bearer <signed-access-token>
~~~

## Query and chatbot flow

1. The user signs in to the .NET app. The frontend sends a question to an authenticated ASP.NET endpoint.
2. ASP.NET checks the user's current RBAC, determines the allowed RAG scopes, and obtains or creates a valid token.
3. ASP.NET sends the query to RAG's POST /api/v1/query/stream. The JSON body contains the question, a stable RAG session_id for the conversation, and optional query settings such as a requested group_path.
4. RAG verifies the token and confirms the requested group is inside rag_read_groups. If no group is selected, RAG searches only the user's authorized spaces. Clearance and document lifecycle filters still apply.
5. ASP.NET forwards the event stream to the frontend without buffering the full answer. The frontend displays answer tokens as they arrive, then renders citations from source events and the final done or verified response.

The stream can include trace, retrieval_stage, intent, token, source, artifact, artifact_job, warning, done, verified, and error events. Treat done or verified as the final structured answer. Display citations and source metadata supplied by RAG; do not reconstruct them from answer text.

Use ASP.NET request cancellation to cancel the upstream RAG request when the user stops generation or disconnects. Avoid retrying a query after streaming has begun unless using the same client_request_id and the RAG retry semantics have been agreed.

### Chat history and source selection

For a complete chatbot, use the same bearer identity on these endpoints as well:

| Purpose | RAG endpoint |
| --- | --- |
| List a user's saved sessions | GET /api/v1/query/sessions?limit=30&offset=0 |
| Read one session | GET /api/v1/query/sessions/{session_id} |
| Delete one session | DELETE /api/v1/query/sessions/{session_id} |
| List query sources visible in a space | GET /api/v1/query/sources?group_path={space} |

Keep a RAG session ID for each .NET conversation and send it with subsequent queries. RAG must scope the session to the authenticated subject. If the app stores its own transcript as well, agree which system is authoritative so the same conversation is not silently duplicated or allowed to diverge.

Source discovery is optional for a corpus-only chatbot. Use it only if users can query approved live database sources.

## Upload and ingestion flow

1. The user selects a file and target Knowledge Space in the .NET frontend.
2. ASP.NET checks the user's write permission and sends a multipart upload to POST /api/v1/upload with the bearer token, file, group_path, and approved metadata.
3. RAG verifies the target is in rag_write_groups, checks clearance and upload policy, scans and stores the file, creates an ingestion job, and returns HTTP 202 with a job_id.
4. ASP.NET reports queued/processing status and polls GET /api/v1/upload/{job_id}/status with the same user's token. RAG returns the terminal status or a safe failure reason.
5. RAG workers parse, chunk, embed, and index the document with the correct Knowledge Space, clearance, and provenance. The document becomes queryable only through RAG's normal publication lifecycle.

The upload body must not override the user's token permissions. RAG checks that the user can write the requested space and that the requested document clearance is no higher than the token's clearance. For the first release, omit shared-space uploads unless they are specifically required.

The existing RAG upload endpoint currently requires a RAG cookie session and CSRF token. The RAG developer must add the bearer-token path before this flow can be used by .NET.

## Errors and operational behavior

- 401: missing, expired, malformed, or untrusted bearer token. Do not fall back to a shared administrator account.
- 403: user lacks the requested read/write scope or clearance.
- 202 for an accepted upload: retain the returned job ID and show its progress.
- 400/413: invalid upload or file too large; report the returned message safely.
- 503 or stream error event: RAG dependency or model failure; let the user retry explicitly.

Configure the RAG base URL and network credentials on the ASP.NET server. Use TLS between deployments, request timeouts appropriate for long queries, and cancellation propagation. Keep tokens and files out of application logs.

## .NET-side completion checklist

- [ ] Confirm the four initial RAG space paths and whether administrators may create more.
- [ ] If administrators manage spaces, build the .NET admin screen and backend calls for list/create/rename/delete; store user or role read/write assignments in the .NET RBAC database.
- [ ] Provide the RAG developer the issuer, audience, stable user ID claim, permissions, read/write mapping, clearance claim, and trusted signing-key/JWKS details.
- [ ] Add a server-side RAG API client and an ASP.NET chat/query endpoint.
- [ ] Relay streaming events and render final answers, citations, warnings, and errors.
- [ ] Track RAG session IDs per user conversation.
- [ ] Add file upload, ingestion job progress, and failure handling if users will upload from this app.
- [ ] Test a permitted query/upload and a denied cross-space query/upload with separate users.
