# MountainGoat New Chat Handoff

Use this file when starting a fresh Codex/chat session for the MountainGoat project. It captures the practical handoff details that are easy to lose when a long thread cannot be moved into the project folder.

## Start Here

Before making changes, read these files in this order:

1. `NEW_CHAT_HANDOFF.md`
2. `PROJECT_CONTEXT.md`
3. `MOUNTAINGOAT_CODEX_SKILL.md`
4. `README.md`
5. `Brand Files\Branding.md` when working on UI, UX, branding, visual design, copy, or product positioning

## Canonical Workspace

The active local project folder is:

```text
C:\Users\mhadd\OneDrive\Documents\MountainGoat
```

Use this folder for future edits, local runs, commits, and pushes.

Do not use the older Codex workspace unless explicitly asked:

```text
C:\Users\mhadd\Documents\Codex\2026-05-16\look-at-the-poinbox-github-repository
```

That old folder may still exist and may contain stale copies of files.

## GitHub Repo

Remote repository:

```text
https://github.com/skizitravel/poinbox.git
```

Branch:

```text
main
```

The MountainGoat folder has been initialized as the intended local repo and pushed to GitHub. Future git work should happen from the MountainGoat folder.

## Local Run Command

Preferred local Python runtime in this Codex environment:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -u server\app.py
```

Open:

```text
http://127.0.0.1:8000/
```

Default local admin login:

```text
admin@example.com
```

## Verification Commands

Run these after meaningful code changes:

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m py_compile server\app.py server\db.py server\processing.py server\extraction.py
```

```powershell
& "C:\Users\mhadd\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check public\app.js
```

Smoke test at minimum:

- App loads at `http://127.0.0.1:8000/`
- Login works with `admin@example.com`
- Dashboard loads
- Admin tabs load
- PO detail opens
- The changed feature works
- Neighboring existing behavior still works

## Browser Cache Gotcha

If frontend UI changes do not appear at `http://127.0.0.1:8000/`, first try:

```text
Ctrl + Shift + R
```

The app currently loads `/app.js` and `/styles.css` without cache-busting, so the browser may keep older frontend files after a restart. If this becomes annoying, add version query strings in `public/index.html`, for example:

```html
<link rel="stylesheet" href="/styles.css?v=20260524" />
<script src="/app.js?v=20260524"></script>
```

## Component System

The app does not use React, Vue, Tailwind, shadcn, Bootstrap, or an external component library.

Current UI system:

- static HTML in `public/index.html`
- vanilla JavaScript rendering/helpers in `public/app.js`
- shared CSS in `public/styles.css`

Reuse existing render helpers, modal patterns, tables, buttons, badges, and forms before adding new structure.

## Architecture Snapshot

The app is intentionally simple and local-first:

- Python standard library HTTP server
- SQLite database
- Vanilla JavaScript frontend
- Minimal dependencies
- Additive schema migrations only
- Optional OpenAI extraction configured through Admin > Testing
- Gmail and Outlook OAuth/manual sync through existing inbox connection architecture

Important files:

- `server/app.py`: routes, API handlers, Gmail/Outlook sync, reporting
- `server/db.py`: SQLite schema, migrations, seed data
- `server/processing.py`: ingestion, attachment extraction, PO processing, duplicate/product/review task generation
- `server/extraction.py`: rule-based and OpenAI extraction
- `server/master_data.py`: customer/address/contact matching and review logic
- `server/openai_settings.py`: local OpenAI extraction settings
- `public/app.js`: frontend state, rendering, modals, API calls
- `public/index.html`: app layout
- `public/styles.css`: app styles

## Product Direction

MountainGoat is becoming a workflow automation SaaS for operations teams. The first app focuses on purchase order intake:

1. Ingest emailed/uploaded POs
2. Extract PO header and line data
3. Match customer and item master data
4. Route issues to an Exceptions Queue
5. Let users correct and review data
6. Export or acknowledge clean orders
7. Capture feedback so extraction improves over time

The ideal early customer is a small to mid-sized B2B manufacturer, distributor, contract manufacturer, or industrial supplier with customer service/order-entry teams manually processing emailed POs.

## Current High-Priority Product Priorities

1. Exceptions Queue usability
2. Accurate line-item extraction
3. Item/customer part matching
4. Source document review UX
5. Audit trail
6. Gmail/Outlook ingestion reliability
7. Duplicate detection
8. Master data feedback loop
9. ERP-ready CSV/export workflows
10. Basic reporting and ROI metrics

Later priorities:

- OCR/vision for scanned PDFs
- configurable export profiles
- quote generator
- quote-to-PO matching
- ERP booking/write-back
- production OAuth/token encryption
- production scheduler/job queue
- EDI
- customer portal/supplier network

## Recently Important Decisions

### Date Received

`date_received` is system-controlled only.

- AI extraction must not determine `date_received`.
- Email imports should use Gmail/Outlook/email `received_at`.
- Sample/manual uploads should use upload/import metadata.
- If AI still returns `date_received`, backend processing should ignore/discard it.
- PO line `requested_date` still comes from the PO document.

### UX Button Placement

The `View PO` button was moved near the top of PO detail, under/near the status, because it was hidden on some screen sizes when placed in lower line actions.

`Confirmed Order View` was moved near Extraction Notes. `Draft Acknowledgment` remains in the action area.

### Branding

Brand guidance lives at:

```text
Brand Files\Branding.md
```

Use it before UI/visual/copy changes.

Brand should feel:

- clear
- practical
- trustworthy
- operationally competent
- friendly but polished
- modern
- slightly warm

Avoid:

- childish mascot usage
- goofy goat jokes
- generic SaaS hype
- luxury/snobby styling
- heavy marketing pages inside the operational app

Note: `Branding.md` may contain some text encoding artifacts such as curly quotes rendered as `â€™`. Clean those if editing brand docs.

## Security And Local Config

Never commit:

- `.env.local`
- SQLite runtime databases
- Gmail/Outlook tokens
- OpenAI API keys
- downloaded email content
- uploaded customer files
- real POs/customer documents

The app may store OAuth tokens and OpenAI settings locally in SQLite for MVP testing. Production should use encrypted managed secret storage.

If a Gmail, Outlook, or OpenAI secret was pasted into chat or committed, assume it is exposed and rotate it before use.

Local secrets and OAuth settings may need to be re-entered after cloning on another machine.

## Known Documentation Caveat

If the README says Gmail/Outlook sync is only a stub, verify against the code before trusting that sentence. Later README sections describe real Gmail/Outlook OAuth and manual sync, and the app has had real connector work added. Prefer code verification with `rg` when documentation and behavior disagree.

## Working Style For Future Codex Chats

When asked to change the app:

1. Work from `C:\Users\mhadd\OneDrive\Documents\MountainGoat`.
2. Inspect relevant files first with `rg`.
3. Preserve existing behavior.
4. Make focused additive changes.
5. Use additive migrations with `CREATE TABLE IF NOT EXISTS` and `ensure_column`.
6. Keep backend permissions authoritative.
7. Avoid large rewrites.
8. Run Python compile and JS syntax checks.
9. Restart the app when needed.
10. Tell the user what changed, what was verified, and what was not fully tested.

## New Chat Starter Prompt

Copy/paste this into a new project chat if needed:

```text
You are working on MountainGoat, a local-first PO intake MVP in C:\Users\mhadd\OneDrive\Documents\MountainGoat. Read NEW_CHAT_HANDOFF.md, PROJECT_CONTEXT.md, MOUNTAINGOAT_CODEX_SKILL.md, README.md, and Brand Files\Branding.md before making changes. Preserve existing behavior, use additive SQLite migrations, keep the Python stdlib + SQLite + vanilla JS architecture, do not commit secrets/local databases/tokens/real POs, and work from the MountainGoat folder only.
```
