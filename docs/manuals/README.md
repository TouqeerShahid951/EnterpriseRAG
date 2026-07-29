# Prudentia AI Manuals

Last updated: 2026-07-07

This folder contains the standalone manuals for a Prudentia AI deployment. Use
these manuals together when there is no project team available to explain the
system.

## Which Manual To Use

| Manual | Audience | Use it when |
| --- | --- | --- |
| [End User Manual](end-user-manual.md) | Chat Members, Document Contributors, Audit Viewers, and scoped admins | You need to sign in, ask questions, inspect evidence, upload files, resolve Review Queue items, or use the document library. |
| [Administrator Manual](administrator-manual.md) | Platform Admins, System Admins, and Space Admins | You need to create users, manage Knowledge Spaces, govern documents, approve database scopes, configure models, or audit activity. |
| [Operator Manual](operator-manual.md) | The person responsible for running the local deployment | You need to start, stop, update, verify, back up, restore, or troubleshoot the Docker/Ollama runtime. |

## Generated Files

Run the manual builder from the repository root to create DOCX and PDF copies:

```powershell
.\.venv\Scripts\python.exe scripts\build_user_manuals.py
```

The generated files are written to `docs/manuals/generated/`.

## First-Time Reading Order

1. The operator reads the [Operator Manual](operator-manual.md) and starts the
   stack.
2. The first Platform Admin signs in with the bootstrap account and reads the
   [Administrator Manual](administrator-manual.md).
3. Day-to-day users read the [End User Manual](end-user-manual.md).

The Markdown files in this directory are the only manual sources. Regenerate
their DOCX and PDF versions with `scripts/build_user_manuals.py`.
