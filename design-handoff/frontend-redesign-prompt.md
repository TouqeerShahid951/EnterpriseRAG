# ChatGPT Prompt: Redesign Prudentia AI Frontend

You are a senior product designer and frontend engineer. I am giving you screenshots of the current Prudentia AI / AgenticRAG frontend. Redesign it for a more polished, trustworthy, enterprise-grade UX/UI while preserving the product's current workflows and information density.

## Product Context

Prudentia AI is a local enterprise RAG workspace for controlled document intake, retrieval-augmented Q&A, evidence inspection, OCR review, auditability, answer evaluation, and grounded artifact generation. It is used in deployments where data locality, role-aware access, clearance boundaries, and offline model execution matter.

Primary users include platform admins, system admins, space admins, Document Contributors, Chat Members, and Audit Viewers. The interface must feel calm, secure, operational, and efficient. It should not feel like a marketing site or generic AI dashboard.

## Current Stack And Constraints

- Frontend: Vite, React, TypeScript.
- Routing is custom in `frontend/src/App.tsx` and `frontend/src/routes.ts`.
- Styling lives mainly in `frontend/src/styles.css`, `frontend/src/Prudentia-ui.css`, and route-specific CSS files.
- Icons use `lucide-react`.
- Preserve role-aware navigation, document clearance concepts, Knowledge Spaces, source provenance, auditability, and offline/local deployment posture.
- Do not require backend API changes unless absolutely necessary. Prefer frontend structure, component, layout, and styling improvements first.
- Keep product UI conventions familiar: sidebar navigation, tables, filters, forms, tabs, status badges, empty states, loading states, and clear actions.

## Screenshots Provided

Use the attached 1920 x 1200 desktop screenshots as the current-state baseline. `00-contact-sheet-highres.png` is a quick overview, but use the individual PNG files for detailed critique:

1. `01-login.png`: Secure login screen.
2. `02-chat-query-intelligence.png`: Main chat / Query Intelligence workspace with conversations, scoped documents, and evidence-grounded prompt area.
3. `03-system-overview.png`: Workspace summary / system overview.
4. `04-document-overview.png`: Document overview with intake status, attention areas, recent activity, and library by space.
5. `05-documents-library.png`: Documents table/library.
6. `06-upload-add-files.png`: Add files / source package upload workflow.
7. `07-folder-sources.png`: Folder source scheduling and intake.
8. `08-ingestion-activity.png`: Ingestion activity history.
9. `09-ingestion-health.png`: Ingestion health, runtime posture, stale runs, and failures.
10. `10-review-queue.png`: OCR review empty/queue state.
11. `11-rag-evaluations.png`: RAG evaluation datasets and run history.
12. `12-system-audit.png`: System audit log and filters.
13. `13-user-management.png`: User management and access controls.
14. `14-configs-settings.png`: Runtime/configuration settings.
15. `15-chat-light-theme.png`: Query Intelligence in the current light theme.

Additional updated implementation screenshots are available in `design-handoff/champagne-stone-screenshots/`. These show the revised shared shell, navigation, cards, buttons, forms, tables, and Champagne Stone accent direction applied to the main authenticated screens.

## Redesign Goals

Improve the UX/UI so the app feels more polished and easier to operate:

- Stronger visual hierarchy across dense operational screens.
- More consistent spacing, typography, buttons, cards, tables, badges, form controls, and page headers.
- More ergonomic navigation between chat, document intake, library, review, audit, settings, and user management.
- Better empty, loading, error, and disabled states.
- Cleaner distinction between primary actions, secondary actions, destructive actions, and passive metadata.
- Better table scanning, filtering, row density, and status visibility.
- More refined dark and light theme tokens.
- Better responsive behavior for laptop and desktop; mobile can be supported, but the product is primarily an enterprise desktop workspace.
- Preserve trust: avoid decorative AI gimmicks, excessive gradients, glassmorphism, animated hero sections, huge marketing-style cards, or low-density landing-page patterns.

## Design Direction

Use a restrained product interface:

- System or Inter-like sans typography.
- Tinted graphite neutrals with Champagne Stone `#B8A77A` as the disciplined premium product accent. Use a deeper Champagne Stone shade only where light-theme text contrast requires it.
- Keep semantic colors separate: green for success, amber for warning/review, red for destructive/error, and blue only for informational states when necessary.
- Dense but breathable layouts.
- Predictable side navigation and page structure.
- Tables and panels optimized for repeated use.
- Helpful microcopy where it reduces ambiguity.
- Motion only for state change, feedback, or progressive reveal.

## What I Want From You

Please produce a practical redesign proposal with these sections:

1. Current UX audit: screen-by-screen issues and opportunities based on the screenshots.
2. New visual system: color tokens, typography scale, spacing scale, elevation/borders, status badge styles, and form/table/button rules.
3. Information architecture improvements: navigation grouping, page header pattern, breadcrumbs/tabs if useful, and action placement.
4. Component redesign specs: sidebar, page header, stat panels, tables, filters, forms, upload panel, chat composer, chat history, document cards/rows, audit filters, user rows, settings panels, empty states, loading skeletons, modals/dialogs, toasts.
5. Screen-by-screen redesign notes for every screenshot listed above.
6. Implementation plan mapped to the existing React/CSS files, with a safe order of changes.
7. Accessibility and responsive requirements.
8. A short final checklist I can use to verify the redesign before shipping.

Be specific enough that a frontend engineer can implement the redesign directly. Avoid generic advice like "make it cleaner." Recommend exact layout changes, spacing, component behavior, typography roles, and interaction states.

If you suggest code, assume the implementation should remain in the current Vite React app and should reuse existing data contracts and route structure.
