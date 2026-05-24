# MountainGoat / PO Intake MVP Project Context

## Product Summary

MountainGoat is a local-first purchase order intake MVP. The app ingests purchase orders from sample uploads, Gmail, and Outlook/Microsoft Graph, extracts PO header and line data, routes uncertain or incomplete records into an exceptions workflow, and helps operators review, correct, export, and acknowledge orders.

The product direction is to become an order-entry automation platform for manufacturers, distributors, and B2B suppliers who receive customer POs by email and need to convert them into clean order data with human review before ERP booking.

## Current Ideal Customer

The best early customer is a small to mid-sized B2B manufacturer, distributor, contract manufacturer, or industrial supplier with:

- Customer service or order-entry staff manually reading emailed POs.
- Many customer-specific PO formats.
- Repetitive line-item entry into an ERP or order system.
- A need to reduce duplicate order entry, missed POs, and manual rekeying.
- Enough PO volume to justify automation, but not enough process standardization for EDI-only workflows.

## MVP Scope

Current MVP goals:

- Ingest POs from uploads, sample folder import, Gmail, and Outlook.
- Extract PO headers and line items using deterministic parsing plus optional OpenAI extraction.
- Route questionable records to an operator-focused Exceptions Queue.
- Let users correct extracted data and capture correction feedback.
- Match customers, addresses, contacts, customer part numbers, and internal item master data.
- Export clean PO data as CSV.
- Provide basic operations metrics and testing/evaluation tools.

Explicitly deferred:

- Native ERP write-back.
- Full quote-to-PO matching.
- EDI ingestion.
- Customer portal or supplier network.
- Mobile app.
- Production-grade OAuth/token encryption.
- Production job runner.
- Full OCR/vision extraction for scanned PDFs.

## Technical Architecture

The app intentionally uses a simple local architecture:

- Python standard library HTTP server.
- SQLite persistence.
- Vanilla JavaScript frontend.
- Dependency-light frontend, no framework.
- Optional Python packages for PDF/Office parsing.
- Optional OpenAI API configuration through Admin > Testing.

Core files:

- `server/app.py`: HTTP routes, API handlers, Gmail/Outlook OAuth and sync, reporting, UI data routes.
- `server/db.py`: SQLite schema, additive migrations, seed data.
- `server/processing.py`: sample import, attachment text extraction, PO processing, duplicate/product/review task generation.
- `server/extraction.py`: PO classification and extraction, rule-based parser, optional OpenAI extraction prompt/schema.
- `server/master_data.py`: customer/address/contact matching and master-data review logic.
- `server/openai_settings.py`: local OpenAI extraction configuration.
- `server/connectors.py`: shared incoming message/attachment structures and sample connector.
- `public/app.js`: frontend state, rendering, modals, API calls.
- `public/index.html`: app structure.
- `public/styles.css`: UI styling.
- `README.md`: user-facing setup and feature notes.

## Run Commands

From the project root:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -u server\app.py
```

Open:

```text
http://127.0.0.1:8000/
```

Default local admin:

```text
admin@example.com
```

Useful verification:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m py_compile server\app.py server\db.py server\processing.py server\extraction.py
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check public\app.js
```

## Current Feature Inventory

### Authentication And Permissions

- Local email login.
- Seeded local admin.
- User management under Admin > Users & Access.
- Admin/PO Dashboard access control.
- PO Dashboard view-only vs edit access.
- Backend route permission checks.

### PO Dashboard

- PO list with status/search filters.
- PO detail review panel.
- Editable PO header fields.
- Editable PO line fields.
- Status changes.
- Date inputs.
- Calculated line totals and PO totals.
- Field confidence highlighting.
- PDF View PO button.
- Confirmed Order View.
- Draft Acknowledgment action.
- PO delete with confirmation.
- CSV export for headers and header + lines.
- Source attribute for records.

### Extraction

- Rule-based PO detection/extraction.
- Optional OpenAI extraction.
- OpenAI config panel in Admin > Testing.
- Model dropdown.
- Extraction feedback capture when users correct fields.
- Extraction reviewed status.
- Extraction learning dashboard.
- Evaluation harness with test corpus and golden answers.
- Prior-correction retrieval for AI prompt guidance.
- `date_received` is system-controlled only. AI must not determine it.

Important date behavior:

- `date_received` comes from email received timestamp or upload/import metadata.
- AI extraction ignores/discards `date_received`.
- PO line `requested_date` remains extracted from the PO.

### Email/Ingestion

- Gmail OAuth configuration, connect, token storage, token refresh.
- Outlook/Microsoft Graph OAuth configuration, connect, token storage, token refresh.
- Gmail label discovery/configuration.
- Outlook folder discovery/configuration.
- Manual inbox sync date/time range.
- Per-inbox active/inactive state.
- Evaluate emails without attachments setting.
- Inbox sync run metrics.
- Inbox detection results.
- Basic retry/reprocess hooks.
- Optional local background scheduler via `ENABLE_BACKGROUND_SYNC=1`.

### Attachments

Supported extraction:

- PDF text.
- TXT.
- EML-like text.
- XLSX.
- DOCX.

Unsupported or limited:

- `.xls` and `.doc` are logged unsupported.
- Scanned/image PDFs still need OCR/vision extraction.

### Master Data

- Customers.
- Structured customer addresses.
- Customer contacts with popup.
- Payment terms list.
- Departments.
- Order types.
- Customer part cross-reference with revisions.
- Item Master CRUD and CSV upload/download.
- Customer CSV upload/download.
- Customer contact CSV download/upload support.

### Matching And Feedback

- Customer/address/contact master-data review.
- Add customer/address/contact from PO review.
- Customer part cross-reference matching.
- Item Master exact and fuzzy matching.
- Line-level product match status, score, and reason.
- Missing/weak matches create exceptions.

### Exceptions Queue

- Review task data model.
- Exceptions Queue.
- Open exceptions in PO detail.
- Resolve/ignore actions.
- Assignment, priority, age, filtering, sorting, bulk actions.
- Open Next Exception.
- Exception count badges on PO rows.
- Duplicate candidate exceptions.

### Duplicate Detection

- Provider message ID dedupe.
- PO number + revision dedupe.
- Deleted PO can be recreated by reprocessing retained email/attachments.
- Attachment SHA-256 hash.
- Duplicate candidate table.
- Duplicate candidate review actions:
  - Mark Duplicate.
  - Keep Both.
  - Link Revision.
  - Ignore.

### Analytics

- Admin > Analytics tab.
- Operations Metrics.
- POs by status.
- Open exceptions and exception rate.
- Average extraction confidence.
- Manual correction count.
- POs received/booked by day.
- Top customers.
- Top exception reasons.
- Inbox reliability by account.
- Summary, exceptions, and corrections CSV downloads.

## Product Priorities

Highest priority:

1. Exceptions Queue usability.
2. Accurate line-item extraction.
3. Item/customer part matching.
4. Source document review UX.
5. Audit trail.
6. Gmail/Outlook ingestion reliability.
7. Duplicate detection.
8. Master data feedback loop.
9. ERP-ready CSV export.
10. Basic reporting.

Later:

1. Configurable export profiles.
2. Background sync hardening.
3. OCR/scanned PDF support.
4. Quote generator.
5. Quote-to-PO matching.
6. ERP booking integration.

## Design Principles

- Do not rewrite the app unless explicitly directed.
- Make focused additive changes.
- Preserve current local SQLite data.
- Use additive migrations with `CREATE TABLE IF NOT EXISTS` and `ensure_column`.
- Keep frontend dependency-free.
- Keep operations UI compact and work-focused.
- Prefer tables, filters, modals, and direct actions over marketing-style pages.
- Backend permissions are authoritative; do not rely only on hidden buttons.
- Keep route guards centralized.
- Add helper functions instead of duplicating SQL.
- Never commit or expose secrets, tokens, downloaded emails, local databases, real customer POs, or `.env.local`.

## Common Smoke Tests

After changes, verify:

- App loads.
- Login with `admin@example.com` works.
- Dashboard loads.
- Admin tabs load.
- PO detail loads.
- Existing sample upload/import works.
- Existing PO edit/save/status changes work.
- View-only user cannot edit.
- Customer master data still works.
- Item Master still works.
- Customer part xref still works.
- Exceptions Queue loads.
- Analytics loads and Refresh Metrics works.
- CSV exports download.
- Gmail/Outlook config routes still load.
- OpenAI config route still loads.
- Python compile passes.
- Frontend JS syntax check passes.

## Useful Prompts

Preferred implementation style:

```text
Add the following focused features to the existing PO intake MVP without breaking current functionality.

Important:
Preserve all current behavior:
- [list relevant behaviors]

Do not rewrite the app. Make focused additive changes.

Implementation notes:
- Keep Python stdlib + SQLite + vanilla JS architecture.
- Use additive schema migrations.
- Keep backend permission checks authoritative.
- Do not commit secrets, databases, tokens, downloaded email, or real POs.

Smoke tests:
- [specific tests]
```

