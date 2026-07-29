# Frontend UX audit

This is the working record for the production-quality frontend review. A page is
complete only after its purpose, primary journey, interaction states,
accessibility, and responsive behavior have been checked together.

## Review standard

- Viewports: 320px, 768px, 1024px, 1440px, and 2400px.
- Input: keyboard, pointer, and touch-sized controls.
- States: loading, empty, populated, error, pending mutation, and success.
- Accessibility: one page heading, landmarks, labels, visible focus, logical tab
  order, named icon controls, status announcements, and non-color state cues.
- Visual system: existing semantic colors, spacing, type, controls, panels, and
  page-width tokens; no page-specific substitute design system.

## Shared audit findings

| Priority | Finding | Resolution |
| --- | --- | --- |
| High | Shared form styles suppressed the global keyboard focus outline. | Removed the overriding `outline: none`; controls now retain the product focus ring. |
| High | Several password, connector review, and shared-space controls relied on nearby text or placeholders instead of an accessible name. | Added explicit accessible names at the owning fields. |
| Medium | Sidebar destinations used button semantics, expanded groups could not collapse, and their control/content relationship was not exposed. | Destinations are links with native URLs; group buttons toggle without navigating and use `aria-controls`; collapsed navigation still opens the first route. |
| Medium | Activity filters wrapped at common scaled desktop widths because the one-row rule started at 1440px. | Aligned the existing rule with the 1280px desktop boundary. |
| Medium | Responsive data tables removed their header row from the accessibility tree on phone layouts. | Replaced `display: none` with visually-hidden table headers while retaining the card presentation. |
| Medium | The mobile workspace drawer trapped keyboard focus but did not expose modal semantics, and the theme switch changed its accessible name with state. | Added mobile dialog semantics and a stable switch name. |
| Medium | Closed mobile navigation controls and the native Knowledge Space option leaked into the accessibility tree. | The closed drawer is now hidden from assistive technology and its inactive backdrop is not rendered. |
| Medium | The retained route-entry transform made viewport-fixed drawers position against the content area instead of the viewport. | Removed the animation fill state so fixed history and evidence layers retain viewport geometry. |
| High | Document rows kept their six-column desktop grid when the available content width was only 768-800px, clipping filters and making row actions unreachable. | Moved the card transition to 1180px, stacked the toolbar at the same boundary, and added inspector-aware collapse below 1680px. |
| High | The document inspector became a visual overlay below 1320px without dialog semantics, a backdrop, focus containment, Escape handling, or focus restoration. | Added responsive modal behavior while preserving the inline extra-large desktop inspector. |
| Medium | Add Files rendered a native fallback “Details” disclosure because its primary form used `<details>` without a summary. | The document-upload form now uses a normal container; only the optional Glossary PDF-import workflow remains collapsible. |
| High | Folder schedule actions and run disclosures were only 20–33px high, and selected filenames collapsed out of view on phones. | Raised operational controls to 44px and switched selected-file rows to a phone grid that preserves filename, path, status, and removal. |
| High | Database connector tables squeezed five or six columns into phone/tablet content widths, producing vertical names, overlapping controls, and off-screen actions. | Added labeled connection/review/access/diagnostic cards below 1180px while retaining accessible headers and the desktop tables. |
| High | Activity’s seven-column job table stayed tabular at 768/1024px, turning titles vertical and placing operational actions beyond the viewport. | Extended its existing accessible job-card layout through the 1180px workbench boundary. |
| Medium | Review Queue evidence, image-selection, and decision controls were only 32–38px high, and its visual tabs lacked keyboard tab behavior and explicit panel relationships. | Raised operational targets to 44px and added arrow/Home/End navigation with labelled tab panels. |
| Medium | RAG Evaluation’s JSON-format help and Query Tracker source modes exposed 25px and 38px targets. | Raised both control families to the 44px product minimum while preserving the compact workbench. |
| High | System Audit kept its six-column table at 768/1024px, crushing identities and targets, while the expanded phone detail inherited a 9rem table-column width. | Switched Audit to labelled cards below 1180px, forced detail rows to span the full card, and raised filters/disclosures/actions to 44px. |
| High | User Management’s seven-column inventory stayed tabular at 768/1024px, reducing names and role descriptions to near-vertical text. | Extended its labelled user-card presentation through the 1180px workbench boundary. |
| Low | Collapsed Runtime Settings workflow steps measured 42px at common tablet/desktop widths. | Added the 44px minimum to every guided Model Routing step header. |
| Medium | Source Viewer’s back link was only 20px high and its image controls were 38px high below the desktop sizing boundary. | Raised the viewer’s base navigation and operational controls to the 44px product minimum. |
| Medium | Authenticated runtime inspection had not been run at every representative viewport. | Completed route-by-route browser inspection with representative governed data and interaction-state checks. |

## Page review status

| Page composition | Primary task | Status |
| --- | --- | --- |
| Sign in | Enter the governed workspace | Complete at 320/768/1440/2400px; focus and service-error states verified |
| Query Intelligence | Ask questions and inspect evidence | Complete at 320/768/1024/1440/2400px; empty, history, populated answer, citation, and evidence states verified |
| Workspace Summary | Understand system state and next actions | Complete at 320/768/1024/1440/2400px; metrics, priority flow, and destination semantics verified |
| Document Overview | Understand corpus readiness | Complete at 320/768/1024/1440/2400px; populated health dashboard and first-run setup journey verified |
| Documents | Find and govern documents | Complete at 320/768/1024/1440/2400px; filters, actions, empty state, and responsive inspector verified |
| Knowledge Spaces | Browse and manage retrieval spaces | Complete at 320/768/1024/1440/2400px; directory, drill-in, no-space state, and actions verified |
| Document Trash | Restore or remove deleted documents | Complete at 320/768/1024/1440/2400px; filters, restore surface, and empty state verified |
| Add Files | Configure and monitor document intake | Complete at 320/768/1024/1440/2400px; empty and selected-file states, removal, governance selection, and responsive guidance verified |
| Abbreviation Glossary | Manage query-expansion terminology | Complete at 320/768/1024/1440/2400px; populated, empty, search, add, delete confirmation, and PDF-import states verified |
| Folder Sources | Configure scheduled folder intake | Complete at 320/768/1024/1440/2400px; validation, selected snapshot, schedule cards/actions, runs, and run items verified |
| Database Connectors | Configure governed live database access | Complete at 320/768/1024/1440/2400px; populated/empty workspaces, all tabs, action menu, setup validation, and access-review modal verified |
| Ingestion Activity | Find and act on intake runs | Complete at 320/768/1024/1440/2400px; summary, filters, populated/empty history, pagination, provenance, statuses, and actions verified |
| Ingestion Health | Diagnose and recover ingestion | Complete at 320/768/1024/1440/2400px; metrics, runtime posture, GraphRAG activity, stale recovery, and recent failures verified |
| Review Queue | Resolve OCR and image review work | Complete at 320/768/1024/1440/2400px; OCR correction, PDF image triage, clear states, touch targets, and keyboard tabs verified |
| RAG Evaluation | Launch, compare, and diagnose evaluations | Complete at 320/768/1024/1440/2400px; all five screens, dataset form, launch validation, tracker controls, run history, and diagnostics verified |
| System Audit | Investigate governed activity | Complete at 320/768/1024/1440/2400px; primary/advanced filters, populated/empty trail, responsive details, payload, links, and pagination verified |
| User Management | Manage accounts and permissions | Complete at 320/768/1024/1440/2400px; populated/empty inventory, create/edit/reset/delete flows, chat activity, confirmation, and responsive cards verified |
| Account Management | Review session access and rotate password | Complete at 320/768/1024/1440/2400px; validation coverage present |
| Runtime Settings | Configure models and operational controls | Complete at 320/768/1024/1440/2400px; routing, discovery, service limits/restarts, ingestion controls, validation, and safety confirmations verified |
| Source Viewer | Inspect cited source regions | Complete at 320/768/1024/1440/2400px; image highlight, zoom controls/shortcuts, incomplete-link recovery, touch targets, and overflow verified |

## Validation evidence

- The full frontend suite passes (44 files, 204 tests), as do TypeScript,
  production build, and dead-code analysis. The package has no separate lint
  script; TypeScript and the production transform are its configured static
  compilation gates.
- Focused sidebar interaction test: `SidebarMenu.test.tsx`.
- Frontend TypeScript check passes after the shared fixes.
- Production build passed after the Activity filter breakpoint fix.
- Browser checks confirm no horizontal overflow on Sign in or Account at their
  representative viewport widths; keyboard focus computes to a 3px product ring.
- Query Intelligence browser checks cover empty and populated conversations,
  mobile history, citation focus, inline mobile evidence, and the desktop
  evidence dialog. The 320px header and composer remain readable with no
  horizontal overflow, and selected mobile evidence opens at its heading.
- Workspace Summary retains a clear primary workflow and bounded reading width
  from phone through extra-large desktop. Its workspace destinations now use
  native links while preserving in-app navigation for ordinary clicks.
- Document Library browser checks cover the overview, active documents,
  Knowledge Space directory and drill-in, Trash, and the inspector. The
  inspector behaves as a focused bottom sheet or modal below 1320px and returns
  focus to its originating document; at large widths it remains an inline pane.
- Add Files browser checks cover the disabled empty form and an actionable
  selected-file state, owner-space selection, removal, mobile touch target, and
  stacked/wide guidance layouts. No audited viewport has horizontal overflow.
- Abbreviation Glossary browser checks cover populated and empty dictionaries,
  responsive table cards, search filtering, direct entry, delete confirmation,
  and the collapsed/expanded governed PDF replacement workflow. Dialog focus and
  all audited widths are clean.
- Folder Sources browser checks cover empty-form validation, mixed supported and
  skipped snapshot files, schedule metadata, pause/resume/cancel targets, and
  nested run/run-item inspection. All operational controls remain in the
  viewport at 44px high across the audited widths.
- Database Connectors browser checks cover populated and empty workspaces, the
  Connections, Schema Reviews, Live Access, and Diagnostics tabs, row actions,
  blank setup validation, and the Database Access Review. Responsive cards keep
  every action in-viewport with 44px controls; both modals contain focus and
  scroll internally without horizontal overflow.
- Ingestion Activity browser checks cover summary metrics, six filters, mixed
  active/indexed/failed runs, progress and parser provenance, pagination,
  operational actions, and a URL-synchronized filtered-empty state. Filters use
  one row at desktop widths; job cards keep all actions reachable below 1180px.
- Ingestion Health browser checks cover pipeline and stage metrics, worker and
  model posture, active GraphRAG tasks, recoverable and exhausted stale runs,
  and recent failure actions. The operational hierarchy remains readable and
  action controls stay reachable at every audited width.
- Review Queue browser checks cover grouped OCR blocks, evidence preview,
  correction context, PDF image batches and candidates, decision controls, and
  queue-clear states. Its workbench collapses cleanly without horizontal
  overflow, operational controls are at least 44px high, and arrow-key tab
  switching updates the labelled tab panel.
- Focused Review Queue tests pass (6 tests), and the frontend TypeScript check
  passes after the interaction and tab-semantics changes.
- RAG Evaluation browser checks cover Overview, Datasets, New Evaluation, Query
  Tracker, and Runs with populated datasets, completed/failed runs, case-level
  diagnostics, and mobile form validation. The JSON help remains in-viewport,
  its compact controls meet 44px, and no screen introduces page overflow.
- Focused evaluation tests pass (11 tests).
- System Audit browser checks cover summary metrics, primary and advanced
  filters, populated and URL-synchronized empty results, pagination, expanded
  actor/target details, resource links, payload fields, and raw JSON. Labelled
  cards replace the compressed table through 1180px; expanded details span the
  card and investigation controls meet the 44px minimum.
- Focused Audit tests pass (7 tests), and the frontend TypeScript check passes.
- User Management browser checks cover populated and search-empty inventory,
  create/edit forms, password reset, exact-email delete confirmation, and saved
  chat activity. User cards remain readable below 1180px; every mobile dialog
  fits without horizontal overflow and exposes 44px controls. The frontend
  TypeScript check passes.
- Runtime Settings browser checks cover Model Routing, vLLM Services, and
  Ingestion Controls with healthy configured data. Guided steps, deployment
  status, launch limits, reset confirmation, per-service restart confirmation,
  thresholds, and hazardous-concurrency confirmation remain readable and gated
  at all audited widths without overflow.
- Focused Runtime Settings tests pass (25 tests), and the frontend TypeScript
  check passes.
- Source Viewer browser checks cover its highlighted image preview at every
  audited width, pointer zoom, keyboard reset/fit shortcuts, and the
  incomplete-citation recovery state. Navigation and viewer actions are at
  least 44px high, highlights render, and no audited width introduces page
  overflow. Focused Source Viewer utility tests pass (10 tests).
- Focused upload validation and authorization tests pass. The full frontend
  TypeScript check passes.
- Repository-wide `git diff --check` is currently noisy because generated PDF
  changes elsewhere in the worktree contain trailing whitespace; frontend-only
  diff checks are clean.

## Validation constraints

- Authenticated browser scenarios used deterministic API fixtures against the
  real Vite application so destructive account, connector, ingestion, and
  settings operations were not sent to a live backend.
- The five-width matrix covers the intended responsive boundaries, but it is
  not a substitute for a separate cross-browser/device-lab pass before a major
  public release.
- The repository contained extensive unrelated staged, unstaged, generated,
  and untracked work before this audit. Those changes were preserved and were
  excluded from the scoped frontend diff validation.
