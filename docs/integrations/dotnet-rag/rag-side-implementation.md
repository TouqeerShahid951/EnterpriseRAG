# AgenticRAG integration implementation guide

**Status:** Implementation plan; external .NET bearer-token authentication is not implemented.

## Goal

Allow the .NET app to use its own login and RBAC while AgenticRAG retains ownership of Knowledge Space records, ingestion pipeline, document ACLs, retrieval, citations, and chat execution. Start with the four planned spaces; the .NET app may offer administrators a screen to manage them. Do not mirror full user accounts or passwords into RAG.

The .NET backend sends a short-lived signed JWT for the authenticated user. RAG validates it, converts verified claims into a request-scoped principal, and enforces read/write permissions at every relevant route and inside retrieval.

## Current RAG behavior

- Public query routes (POST /api/v1/query and POST /api/v1/query/stream) depend on require_current_user, which reads RAG's access cookie and looks up a local UserRecord. Query POST also requires CSRF.
- Public upload (POST /api/v1/upload) and upload status (GET /api/v1/upload/{job_id}/status) also require a local RAG user. Upload permissions are checked using that user.
- Session history and source-list routes likewise use RAG cookie authentication.
- Space administration already has list/create/update/delete routes at `/api/v1/admin/groups`, but these use local RAG account permissions and cookie/CSRF authentication.
- RAG's local token helper signs HS256 tokens with JWT_SECRET_KEY; it checks signature, token type, and expiry. It is not an external OIDC/JWT validator and currently does not check issuer or audience.
- SERVICE_TOKEN is for internal worker-facing endpoints. Do not use it as end-user query or upload authentication.
- The API and query-api containers run the same FastAPI application/image. Upload routes enqueue work for Celery ingestion workers. The .NET app should call the API; it should never call workers or data stores directly.

## Agreed authorization model

RAG stores the canonical Knowledge Space paths. Authorized administrators may create or manage them from the .NET app through the RAG API. The .NET app remains authoritative for which signed-in user may read or write each space, storing user or role assignments in its own database. RAG enforces the signed scopes against its documents, live sources, and retrieval filters.

Use a proposed claim contract like:

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

Treat this as a proposal until issuer, audience, exact group paths, token lifetime, and key distribution are agreed. If the app supports an authorization revision claim, agree whether it is needed for permission-change invalidation. Do not grant global-admin rights from a generic app role.

## JWT validation

Add an external bearer-token authentication path for only the public integration routes. Keep the existing cookie/session flow for the RAG UI.

1. Read the bearer token from the Authorization header.
2. Verify the signature using a configured trusted public key or trusted JWKS. Prefer asymmetric signing (RS256 or ES256) so the .NET backend keeps the private key and RAG only has verification material.
3. Allowlist the expected algorithm. Select keys only from configured trust material; never fetch a key URL supplied by the token.
4. Require exact issuer and audience matches. Validate signature, expiry, not-before when present, issued-at, and a short maximum token lifetime with small clock skew.
5. Validate claim types and bounds: stable non-empty subject; bounded arrays of normalized known group paths; valid clearance; and the required rag:query or rag:ingest capability.
6. Return 401 for an invalid or missing token. Return 403 for a valid identity without the requested capability or scope.

Use an established JWT validation library after checking the locked backend dependencies. Do not extend the custom HS256 helper into a general external-token verifier or share JWT_SECRET_KEY with .NET. Tokens are signed, not encrypted; log neither token contents nor signing material. Support key rotation through kid and configured JWKS/public-key updates.

Trust only the agreed .NET backend issuer and RAG API audience. This integration uses a JWT assertion signed by the .NET backend; it does not depend on OIDC.

## Request-scoped principal and enforcement

Do not create fake UserRecord rows or dummy passwords for external users. Add the smallest auth principal/contract needed to represent verified identity, capabilities, read groups, write groups, clearance, and an audit identity such as iss|sub. Adapt the route authorization boundary to accept both the current local user and this external principal while retaining existing browser behavior.

The current query authorization helpers take UserRecord and consult the local identity repository. Update that boundary so external claims become a trusted UserContext/principal and preserve existing permission checks:

- Query requires rag:query. If group_path is supplied, it must be a known RAG space and appear in rag_read_groups. Without a selected group, retrieval receives only the claim's read groups.
- Any document ID, database source, session, or history access must remain within the authenticated subject's readable scopes. Continue applying group, clearance, lifecycle, and current-version filters before evidence leaves vector storage.
- Upload requires rag:ingest. The requested owner group must be in rag_write_groups; clearance cannot exceed rag_clearance_level; every shared group (if enabled) must also be writable.
- Space administration requires a separate `rag:spaces:manage` capability from the trusted .NET issuer. RAG checks the capability before listing or changing canonical spaces. It must not infer space-management rights from a generic app role name.
- Never derive permissions from the query/upload JSON body, a caller-selected group_path, an email address, or an unsigned header.
- Scope chat sessions and analytics to issuer plus subject. If authorization changes must invalidate active sessions immediately, add a trusted authorization-version claim or introspection; otherwise keep token lifetime short and re-evaluate scopes on each new request.

Refactor the ingestion application boundary to accept the authenticated actor contract instead of requiring a database-backed UserRecord. Preserve uploader attribution using the external subject. Do not weaken file scanning, upload-size checks, provenance, or durable job creation.

## Routes to support

Bearer auth must cover the complete features the .NET app uses—not only the streaming query.

| Capability | Existing public endpoint | Required external checks |
| --- | --- | --- |
| Streaming query | POST /api/v1/query/stream | rag:query, read groups, clearance |
| Non-streaming query | POST /api/v1/query | Same as streaming query |
| Session list/read/delete | /api/v1/query/sessions and /api/v1/query/sessions/{session_id} | Subject ownership and current readable evidence |
| Source discovery | GET /api/v1/query/sources | Only sources visible in allowed groups/clearance |
| Upload | POST /api/v1/upload | rag:ingest, write group, clearance |
| Upload job status | GET /api/v1/upload/{job_id}/status | Job/document visibility for that subject |
| Space administration, if enabled | GET/POST/PUT/DELETE /api/v1/admin/groups | `rag:spaces:manage`; retain existing group validation and empty-space deletion rules |

Add ingestion-job listing or cancellation only if the .NET app needs those user experiences. Keep /internal worker APIs on service-token auth; do not expose them as shortcuts.

For space deletion, .NET first removes its user/role assignments. RAG must reject deletion while RAG-owned documents or other dependent records remain; check that the existing database constraint failure is returned as a safe client error. Neither side can assume the other's database update is atomic with its own.

For bearer-authenticated requests, CSRF validation is unnecessary because the browser does not automatically attach the bearer token. Preserve CSRF validation for cookie-authenticated browser mutations.

## Ingestion behavior

The upload API should continue returning HTTP 202 with a job ID. Existing RAG workers own scanning, parsing/OCR, chunking, metadata, embeddings, indexing, retries, publication, and job status. The .NET app polls the public upload status endpoint with the same user token.

On acceptance, RAG must persist a durable job before queueing it. Apply the verified group and clearance labels to document metadata and Qdrant ACL payloads. Failed validation or permission checks must not create a job or publish content.

## Chat behavior

Keep the existing stream event and response contract so the .NET client can relay it: trace, retrieval_stage, intent, token, source, artifact, artifact_job, warning, done, verified, and error. Preserve citations and safe error codes. Continue cancelling query work when the downstream stream disconnects.

The authenticated subject must own saved sessions. A stable RAG session ID is reused only by that subject. Source visibility and historical evidence must be rechecked against current permissions before returning it.

## Configuration and deployment

Add typed configuration for the trusted external issuer, audience, key/JWKS source, allowed algorithm, and any required maximum token age. Keep credentials out of tracked files; update .env.example with placeholders only. Do not make key retrieval a request-time dependency if the deployment is air-gapped; support a pinned public key or locally hosted JWKS.

Deploy the RAG API and its existing queue workers/data services as the RAG-owned stack. Allow the .NET backend to reach the public API on a private network. No browser CORS change is required for server-to-server calls.

## Required tests

- Valid external token accepted; bad signature, untrusted key, wrong issuer/audience, expired/not-yet-valid token, wrong algorithm, malformed claims, and missing capability rejected.
- Query allowed in an assigned read space; denied in an unassigned/unknown space; a client-supplied group cannot broaden signed scopes.
- Upload allowed in an assigned write space; denied in a read-only/unassigned space or above the user's clearance; shared groups cannot exceed write scopes.
- Space management accepts only a trusted admin capability; ordinary query/ingest tokens cannot create, rename, or delete spaces. New spaces become queryable only for users whom .NET subsequently assigns.
- Session list/read/delete and upload-job status are isolated by iss|sub and respect current document visibility.
- Streaming returns source/final events and cancellation still works.
- Existing cookie-authenticated RAG UI behavior, CSRF, public API contracts, service-token internal routes, and ingestion durable-job behavior remain unchanged.

## Inputs needed before implementation

1. The four initial Knowledge Space paths, and whether .NET administrators may create more spaces.
2. .NET role/entitlement to read/write-space and clearance mapping.
3. Identity issuer, audience, immutable subject claim, trusted JWKS/public key, signing algorithm, and token lifetime.
4. Whether the .NET app needs source selection, saved chat history, upload progress, ingestion-job listing/cancellation, or artifact generation in its first release.
