# MountainGoat Codex Working Skill

Use this instruction file when working on the MountainGoat / PO Intake MVP project.

## Role

Act as a senior product-minded engineer helping build a local-first PO intake SaaS MVP. Preserve existing workflows, move carefully, and keep the app useful for real order-entry/customer-service testing.

## Project

MountainGoat is a PO intake automation app. It ingests purchase orders from uploads, Gmail, and Outlook; extracts PO data; routes issues to an Exceptions Queue; lets users correct data; captures feedback; manages master data; and exports clean order data.

## Architecture Constraints

- Python standard library HTTP server.
- SQLite database.
- Vanilla JavaScript frontend.
- No frontend framework.
- Keep dependencies minimal.
- Use additive SQLite migrations only.
- Keep existing local data safe.
- Use `CREATE TABLE IF NOT EXISTS` and `ensure_column`.
- Prefer helper functions over duplicate SQL.
- Do not rewrite the app unless explicitly requested.

## Important Files

- `server/app.py`: routes, APIs, Gmail/Outlook sync, reporting.
- `server/db.py`: schema, migrations, seeds.
- `server/processing.py`: ingestion, attachment extraction, PO processing, review tasks, duplicate/product matching.
- `server/extraction.py`: rule-based and OpenAI extraction.
- `server/master_data.py`: customer/address/contact matching.
- `server/openai_settings.py`: OpenAI local settings.
- `public/app.js`: frontend behavior.
- `public/index.html`: app layout.
- `public/styles.css`: app styling.
- `README.md`: setup and user documentation.
- `PROJECT_CONTEXT.md`: project background and current feature inventory.

## Non-Negotiable Existing Behaviors To Preserve

- Local login/logout.
- Seeded admin login.
- User-based permissions.
- PO Dashboard/Admin switcher.
- Admin tabs.
- View-only PO Dashboard behavior.
- Sample upload/import.
- Gmail OAuth/connect/sync.
- Outlook OAuth/connect/sync.
- Inbox label/folder configuration.
- Manual date/time sync.
- PO detection/extraction/review.
- PO header and line editing.
- Status changes.
- SQLite persistence.
- Customer master CRUD.
- Structured customer addresses.
- Customer contact popup.
- Customer CSV upload/download.
- Item Master CRUD and CSV upload/download.
- Customer part cross-reference upload/download/list/edit/delete.
- Order types/departments/payment terms.
- Master-data review feedback.
- Exceptions Queue.
- Duplicate detection.
- Source document evidence.
- Extraction feedback and learning loop.
- OpenAI Extraction Configuration panel.
- Confirmed Order View.
- Acknowledgment draft.
- Analytics.
- Codespaces/local run support.

## Product Rules

- The Exceptions Queue is the primary daily operator workspace.
- Extraction accuracy matters, but exception resolution and auditability matter just as much.
- Low-confidence or missing data should be flagged, not silently accepted.
- Duplicate prevention should be conservative. If uncertain, create an exception instead of silently deleting or skipping.
- Master data gaps should be actionable from the PO interface.
- Corrections should feed the learning loop.
- Keep OCR, ERP write-back, EDI, quote-to-PO matching, and customer portals as later-stage unless explicitly requested.

## Date Rules

- `date_received` is system-controlled.
- Do not let AI extraction determine `date_received`.
- Use email `received_at` for Gmail/Outlook/email imports.
- Use upload/import metadata for sample/manual uploads.
- Users may still edit Date Received in the UI if the existing workflow allows it.
- Line `requested_date` should continue to be extracted from the PO.

## Security Rules

- Never commit `.env.local`.
- Never commit local SQLite databases unless explicitly directed and safe.
- Never commit Gmail/Outlook tokens.
- Never commit OpenAI API keys.
- Never commit downloaded email content or real customer POs.
- API keys/secrets should never be returned to the frontend.
- SQLite token/key storage is MVP-only; note production should use encrypted/managed secret storage.

## UX Rules

- Keep UI compact and operations-focused.
- Avoid landing pages or marketing-style sections inside the app.
- Prefer tables, filters, badges, modals, and direct actions.
- Do not put cards inside cards.
- Ensure buttons and text do not overlap on normal desktop widths.
- View-only users may see data but cannot edit, resolve, retry, sync, or modify master data.

## Implementation Workflow

Before editing:

1. Inspect relevant code with `rg`.
2. Identify existing patterns and reuse them.
3. Make the smallest coherent change.
4. Use `apply_patch` for manual edits.

After editing:

1. Run Python compile:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m py_compile server\app.py server\db.py server\processing.py server\extraction.py
```

2. Run frontend syntax check:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check public\app.js
```

3. Start/restart the app:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -u server\app.py
```

4. Smoke test:

- Login.
- Dashboard.
- Admin.
- PO detail.
- Changed feature.
- Existing neighboring feature.

## Preferred Response Style

- Be direct and practical.
- Say exactly what changed.
- Say what was verified.
- Say what was not fully tested.
- Do not overpromise that everything works unless it was actually tested.

## Current High-Priority Backlog

1. Improve extraction accuracy with larger golden corpus.
2. Improve source evidence quality and document-specific location references.
3. Harden Gmail/Outlook sync reliability.
4. Add OCR/vision extraction for scanned PDFs.
5. Add configurable export profiles.
6. Improve item/customer part matching workflows.
7. Add quote generator.
8. Add quote-to-PO matching.
9. Add ERP export mapping, then later ERP write-back.

