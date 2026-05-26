# Safe Build Prompt Framework

Use this framework when asking Codex to add, improve, or modify features in the MountainGoat / PO Intake MVP without breaking existing functionality.

## Purpose

This prompt structure keeps future development focused, additive, and safe. It helps Codex understand what to preserve, what to change, what not to touch, and how to verify that existing functionality still works.

Use it for:

- New features
- Enhancements
- UX changes
- Backend additions
- Database migrations
- Integration improvements
- Bug fixes where surrounding behavior must be protected

## Prompt Template

```text
Add the following focused features to the existing MountainGoat PO intake MVP without breaking current functionality.

Important:
Preserve all current behavior:
- Local login/logout
- User-based permissions
- PO Dashboard/Admin access rules
- Existing Admin tabs
- Existing PO Dashboard workflows
- Existing PO detail editing
- Existing status changes
- Existing ingestion workflows
- Existing extraction workflows
- Existing Exceptions Queue behavior
- Existing master data workflows
- Existing CSV upload/download/export behavior
- Existing Gmail/Outlook/OpenAI configuration behavior
- SQLite persistence
- Local/Codespaces run support

Do not remove existing frontend tables, panels, modals, buttons, tabs, forms, or configuration sections without explicit permission. If a UI surface appears obsolete, hidden, duplicated, or misplaced, first verify whether existing backend routes, event handlers, or workflows still depend on it. Prefer relocating, reconnecting, or refactoring existing UI over deleting it.

When changing backend API response shapes, permission models, route names, or frontend data-loading assumptions, preserve compatibility with the currently running/local backend until the app is restarted and verified. Frontend code must include safe fallback behavior for existing response fields and legacy permissions during migrations.

Do not let one failed optional or newly added API endpoint prevent unrelated existing UI sections from rendering. Admin tabs, dashboard panels, and master data tables should load independently where practical. If one endpoint fails or returns 404, show a local message or empty state for that section only, and continue rendering the rest of the tab.

When adding granular permissions, treat broader existing permissions as implied access unless intentionally changed. For example, `users:manage` must imply user-table view access, Full Admin must imply all Admin tab access, and legacy `admin:view` / `can_access_admin` users must not lose access because a new permission field is missing.

Do not rewrite the app.
Make focused additive changes only. Do not modify unrelated features, routes, schema, UI, or workflows unless required for the requested change.

Goal:
[Describe the business goal in plain English.]

Current behavior:
[Describe what the app currently does.]

Requested changes:

Feature 1: [Feature Name]
[Describe the exact new behavior.]

Requirements:
- [Requirement 1]
- [Requirement 2]
- [Requirement 3]

Backend requirements:
- [New routes, if needed]
- [Existing routes to update]
- [Permission requirements]
- [Validation rules]
- [Error handling]

Frontend requirements:
- [Where the UI appears]
- [What buttons/fields/tables/modals are needed]
- [Loading/success/error states]
- [View-only behavior]

Database requirements:
- Use additive migrations only
- Use CREATE TABLE IF NOT EXISTS
- Use ensure_column
- Do not drop, rename, or destructively modify existing columns/tables

Suggested schema changes:
- [table_name.column_name]
- [new_table_name]

Non-goals:
Do not implement these in this pass:
- Unrelated refactors
- New frontend framework
- Native ERP write-back
- Production auth redesign
- Large schema rewrites
- Any changes not required for the requested feature

Architecture constraints:
Keep the current architecture:
- Python standard library HTTP server
- SQLite database
- Vanilla JavaScript frontend
- Minimal dependencies
- Existing helper patterns
- Existing modal/table/button styles
- Existing permission model

Prefer small helper functions over duplicated logic.

Security requirements:
- Do not commit .env.local
- Do not commit local databases
- Do not commit API keys, OAuth tokens, downloaded emails, or real customer documents
- Never return raw secrets to the frontend
- Backend permissions must enforce access; hidden buttons are not enough

Compatibility requirements:
The change must not break:
- Existing sample upload/import
- Existing Gmail sync
- Existing Outlook sync
- Existing PO extraction
- Existing PO editing
- Existing master data CRUD
- Existing CSV exports
- Existing analytics/reporting
- Existing view-only permissions
- Existing runtime compatibility between frontend and backend API shapes during local restarts or migrations

Implementation guidance:
Before editing:
1. Inspect the relevant code with rg.
2. Identify existing patterns.
3. Reuse existing helpers and UI conventions.
4. Make the smallest coherent change.
5. Before deleting any frontend table, panel, modal, or tab, search for its ID, event handlers, API routes, and related documentation. Do not delete it unless the user explicitly requested removal.

During implementation:
1. Keep routes stable where possible.
2. Add new helper functions instead of large rewrites.
3. Add database changes with additive migrations.
4. Keep UI compact and operational.
5. Avoid touching unrelated files.
6. After changing permissions or API contracts, inspect the live `/api/me` response and at least one affected list endpoint before finalizing. Confirm the frontend handles both the new response shape and the existing/legacy response shape if the running server may be out of date.
7. For Admin changes, do not use a single all-or-nothing `Promise.all` load path for unrelated tables unless every endpoint is required for the same surface. Use isolated loads or safe fallbacks so Users, Master Data, Setup, Testing, and Analytics can render independently.

After implementation:
1. Run Python compile checks.
2. Run frontend JavaScript syntax check.
3. Restart the app if needed.
4. Smoke test the changed feature and nearby workflows.

Acceptance criteria:
The feature is complete when:
- New behavior works as requested
- Existing related workflows still work
- View-only users cannot perform restricted actions
- Errors are clear and actionable
- Data persists in SQLite
- UI refreshes after save/update actions
- No unrelated behavior changed

Smoke tests:
- App loads
- Login works
- Dashboard loads
- Admin tabs load
- Admin is not blank after switching from Dashboard
- Each Admin tab with existing data shows rows or a clear empty state
- Users & Access renders for Full Admin and legacy `users:manage` users
- Master Data renders even if optional Setup, Testing, Analytics, or Export endpoint calls fail
- PO detail opens
- Existing sample import still works
- Existing Gmail/Outlook sync routes still load
- Existing PO edit/save still works
- Existing master data workflows still work
- New feature works
- View-only restrictions still work
- Browser/runtime console has no uncaught errors during Admin load
- If backend files changed, restart the server and retest against the restarted server, not only static syntax checks
- Python compile passes
- Frontend JS syntax check passes

Final response requirements:
When finished, summarize:
- What changed
- What files were updated
- What was verified
- What was not fully tested
- Any follow-up risks or recommended next steps
```

## Recommended Preserve List By Area

Use the relevant items below in the prompt instead of blindly pasting everything every time. For broad changes, include the full list.

### Authentication And Access

- Local login/logout
- User-based permissions
- PO Dashboard/Admin access rules
- View-only vs edit behavior
- Admin user management
- Backend permission checks

### PO Dashboard

- PO list/search/status filters
- PO detail editing
- Header fields
- Line fields
- Status changes
- Calculated line totals and PO totals
- Field confidence highlighting
- View PO/PDF behavior
- Confirmed Order View
- Acknowledgment draft
- PO delete/export features

### Ingestion

- Sample upload/import
- Gmail OAuth/connect/sync
- Outlook/Microsoft Graph OAuth/connect/sync
- Gmail label configuration
- Outlook folder configuration
- Manual date/time sync
- Inbox activate/deactivate behavior
- Inbox detection metrics
- Inbox retry/reprocess behavior

### Extraction

- Rule-based extraction
- OpenAI extraction configuration
- Model dropdown
- Extraction feedback and learning loop
- Extraction evaluation modes
- Source evidence capture
- System-controlled date_received behavior
- Requested date extraction on PO lines

### Master Data

- Customer CRUD
- Structured customer addresses
- Customer address popup
- Customer contact popup
- Customer CSV upload/download
- Customer part cross-reference upload/download/list/edit/delete
- Item Master CRUD and CSV upload/download
- Product/item matching
- Order types/departments/payment terms
- Master-data review resolution for customer/address/contact

### Exceptions And Review

- Exceptions Queue
- Review tasks
- Resolve/ignore actions
- Bulk actions
- Open Next Exception
- Exception count badges
- PO detail Exceptions section
- Duplicate candidate workflow
- Audit trail

### Reporting And Output

- Analytics tab
- Operations Metrics
- Summary CSV
- Exceptions CSV
- Corrections CSV
- Existing PO CSV exports
- Existing export behavior

## Good Prompt Example

```text
Add the following focused feature to the existing MountainGoat PO intake MVP without breaking current functionality.

Important:
Preserve all current behavior:
- Local login/logout
- User-based permissions
- PO Dashboard/Admin access rules
- Existing PO detail editing
- Existing Exceptions Queue behavior
- Existing Item Master CRUD and CSV upload/download
- Existing customer part cross-reference matching
- Existing CSV exports
- SQLite persistence
- Local/Codespaces run support

Do not rewrite the app. Make focused additive changes only.

Goal:
Allow users to resolve unmatched item exceptions faster by creating a customer part cross-reference directly from the PO line exception.

Current behavior:
Unmatched or weak item matches create exceptions, but users must manually go to Admin > Master Data to add the cross-reference.

Feature 1: Add Cross-Reference From PO Line Exception

Requirements:
- In PO detail, show an Add Xref action for unmatched item exceptions.
- Prefill customer, customer part number, customer part revision, internal part number, and internal part revision when available.
- Save through the existing customer part cross-reference backend logic.
- After save, rerun item matching for that PO and resolve the related exception if matched.
- View-only users can see the exception but cannot add the xref.

Backend requirements:
- Reuse existing xref create/update logic where possible.
- Enforce admin/master-data permission server-side.
- Regenerate review tasks after saving.

Frontend requirements:
- Use existing modal/table styling.
- Show success/error feedback.
- Refresh PO detail after save.

Non-goals:
- Do not redesign Item Master.
- Do not change Gmail/Outlook sync.
- Do not alter extraction prompts.

Smoke tests:
- Existing PO detail loads.
- Existing xref table still works.
- Add Xref from exception creates xref.
- Related exception resolves after match.
- View-only user cannot add xref.
- Python compile passes.
- Frontend JS syntax check passes.
```

## Useful Verification Commands

Run from:

```text
C:\Users\mhadd\OneDrive\Documents\MountainGoat
```

Python compile:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m py_compile server\app.py server\db.py server\processing.py server\extraction.py
```

Frontend syntax check:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check public\app.js
```

Run app:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -u server\app.py
```

Open:

```text
http://127.0.0.1:8000/
```

If frontend changes do not appear, try:

```text
Ctrl + Shift + R
```

## Why This Framework Works

A safe build prompt should always tell Codex:

1. What must be preserved
2. What exact business goal is being solved
3. What the current behavior is
4. What new behavior is expected
5. What is explicitly out of scope
6. What technical constraints must be followed
7. How the work should be verified

The most important sentence is:

```text
Do not rewrite the app. Make focused additive changes only. Do not modify unrelated features, routes, schema, UI, or workflows unless required for the requested change.
```
