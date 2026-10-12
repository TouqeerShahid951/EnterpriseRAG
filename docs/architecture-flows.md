# Ingestion and Query Flows

These flowcharts show what happens after a user uploads a document and after a
user sends a question. The system keeps permissions, provenance, and review
status attached to the data throughout both flows.

## Document ingestion

![Document ingestion flow](diagrams/ingestion-flow.svg)

[PNG export](diagrams/ingestion-flow.png) · [SVG export](diagrams/ingestion-flow.svg)

```mermaid
flowchart TD
    User["User uploads a file<br/>chooses Knowledge Space, clearance,<br/>and optional analysis"]
    Validate["API validates file, access,<br/>and upload metadata"]
    Source["Store original file<br/>in object storage"]
    Job["Create document record<br/>and ingestion job"]
    Queue["Place job on<br/>ingestion queue"]
    Worker["Document-pipeline worker<br/>reads the file and reports progress"]
    Extract["Extract text, layout, tables,<br/>slides, images, and spreadsheet structure"]
    Review{"Human review needed?"}
    Hold["Pause as Needs review<br/>in the Review Queue"]
    Resume["Approved items resume<br/>without reparsing the original"]
    Enrich["Generate metadata<br/>and enrich table details"]
    Prepare["Create logical chunks,<br/>claims, and provenance"]
    Embed["Create dense and sparse<br/>embeddings"]
    Stage["Stage a replacement<br/>index generation"]
    Verify["Verify counts, hashes,<br/>and vector dimensions"]
    Activate["Atomically activate the<br/>verified current generation"]
    Ready["Document is indexed<br/>and searchable"]
    Graph{"GraphRAG enabled<br/>for this document?"}
    GraphJob["Queue optional graph enrichment:<br/>entities, relationships, communities"]
    Searchable["Ready for document search<br/>and optional graph-based questions"]
    Retry["Retry transient failures<br/>with backoff"]
    Failed["Show Failed or Cancelled<br/>job status"]

    User --> Validate
    Validate --> Source
    Validate --> Job
    Job --> Queue
    Source --> Worker
    Queue --> Worker
    Worker --> Extract
    Extract --> Review
    Review -->|yes| Hold
    Hold --> Resume
    Resume --> Enrich
    Review -->|no| Enrich
    Enrich --> Prepare --> Embed --> Stage --> Verify --> Activate --> Ready
    Ready --> Graph
    Graph -->|yes| GraphJob --> Searchable
    Graph -->|no| Searchable
    Worker -. transient error .-> Retry -. redeliver .-> Worker
    Worker -. permanent error or cancellation .-> Failed
```

The original file is retained for provenance. Only the verified active index
generation is used for normal retrieval; older generations can remain available
for lifecycle and audit operations until they are retired.

## Question and answer retrieval

![Question and answer retrieval flow](diagrams/query-flow.svg)

[PNG export](diagrams/query-flow.png) · [SVG export](diagrams/query-flow.svg)

```mermaid
flowchart TD
    User["User sends a question<br/>with source mode, Knowledge Space,<br/>and optional document tags"]
    API["Query API authenticates<br/>and starts the query trace"]
    Artifact{"Is this an artifact request?"}
    ArtifactJob["Queue a separate artifact job<br/>and return its status"]
    Memory["Load conversation memory"]
    Context["Resolve follow-up context,<br/>explicit document scope, and dates"]
    Sources["Discover authorized sources:<br/>indexed documents, approved databases,<br/>and optional GraphRAG"]
    DatabaseChoice{"More than one database<br/>is plausible?"}
    Clarify["Ask the user to choose a database<br/>when more than one is plausible"]
    Route["Route the intent and plan<br/>the evidence needs"]
    Access["Apply Knowledge Space, clearance,<br/>lifecycle, and current-version filters"]
    Retrieve["Retrieve permitted evidence"]
    Documents["Indexed search:<br/>dense, sparse, and table-row vectors"]
    Database["Approved live source:<br/>one validated read-only SQL query"]
    Graph["Optional GraphRAG:<br/>authorized relationships and communities"]
    Merge["Merge evidence while preserving<br/>provenance and source identity"]
    Rank["Deduplicate and rerank<br/>while preserving required coverage"]
    Sufficient{"Evidence sufficient?"}
    Repair["Rewrite or expand the route<br/>once when correction is allowed"]
    Partial["Prepare a partial answer<br/>or abstain when support is missing"]
    Temporal["Resolve effective dates<br/>and temporal context"]
    Evidence["Build evidence windows<br/>and citations"]
    Conflict{"Conflicting sources?"}
    Flag["Keep the conflict visible<br/>as an answer warning"]
    Synthesize["Synthesize a grounded answer"]
    Check["Check citation support<br/>and responsiveness"]
    Response["Return answer, citations,<br/>warnings, and trace to the user"]

    User --> API --> Artifact
    Artifact -->|yes| ArtifactJob
    Artifact -->|no| Memory --> Context --> Sources --> DatabaseChoice
    DatabaseChoice -->|yes| Clarify -->|user selects a source| Route
    DatabaseChoice -->|no| Route
    Route --> Access --> Retrieve
    Retrieve --> Documents --> Merge
    Retrieve --> Database --> Merge
    Retrieve --> Graph --> Merge
    Merge --> Rank --> Sufficient
    Sufficient -->|no, correction available| Repair --> Route
    Sufficient -->|no| Partial --> Synthesize
    Sufficient -->|yes| Temporal --> Evidence --> Conflict
    Conflict -->|yes| Flag --> Synthesize
    Conflict -->|no| Synthesize
    Synthesize --> Check --> Response --> User
```

The answer is streamed to the browser when streaming is enabled. Citations and
warnings let the user inspect the evidence, see conflicts, and recognize when
Prudentia could not support a complete answer.
