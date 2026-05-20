# POInbox Purchase Order Intake MVP

This repository contains a local MVP for purchase order intake from a shared inbox. It imports sample emails/documents, detects likely purchase orders, extracts header and line data, and presents a review queue where every new PO starts as `Received` and can be marked `Booked`.

## What It Does

- Imports `.txt`, `.eml`, and `.pdf` files from `samples/inbox`
- Stores email metadata, attachments, purchase order headers, PO lines, and processing logs in SQLite
- Detects likely POs from subject/body/attachment text and records confidence/explanation
- Extracts PO fields with a deterministic parser, with optional OpenAI extraction enabled by environment config
- Serves a local review UI for status changes, header edits, line edits, adding lines, and deleting lines
- Includes a Gmail/Outlook connector interface stub for adding real inbox sync after the sample-mode vertical slice is validated

## Quick Start

Install Python 3.11+ and then install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create your local environment file:

```powershell
Copy-Item .env.example .env.local
```

For deterministic local testing, leave AI extraction off. To test AI extraction, open **Admin > Testing > OpenAI Extraction Configuration**, paste an OpenAI API key, choose a model, and turn on **Use AI extraction**.

Start the app:

```powershell
python server\app.py
```

Then open:

```text
http://127.0.0.1:8000
```

Log in with the seeded local admin unless you changed `.env.local`:

```text
admin@example.com
```

Click **Import Samples** to open the upload dialog. You can drag `.pdf`, `.txt`, or `.eml` files into the dialog, click **Select File**, or use **Import Existing Sample Folder** to process files already in `samples/inbox`.

Use the header switcher to move between **PO Dashboard** and **Admin**. Admin includes configurable order types and a customer part cross-reference CSV upload. Cross-reference CSV files should include customer, customer part number, and internal part number columns.

## Run In A Browser With GitHub Codespaces

Use this path if your computer has a browser but cannot install Python or other developer tools.

1. Open the GitHub repository.
2. Click **Code**.
3. Open the **Codespaces** tab.
4. Click **Create codespace on main**.
5. Wait for setup to finish.
6. In the Codespaces terminal, run:

```bash
python server/app.py
```

Codespaces should prompt you to open forwarded port `8000`. If it does not, open the **Ports** tab, find port `8000`, and click the globe/open-browser icon.

## Configuration

Copy `.env.example` to `.env.local` and set values as needed. Never commit `.env.local`.

The MVP defaults to deterministic extraction so it runs locally without spending API tokens:

```text
USE_OPENAI_EXTRACTION=0
```

You can also use `.env.local` as a developer fallback:

```text
OPENAI_API_KEY=
USE_OPENAI_EXTRACTION=1
OPENAI_MODEL=gpt-4.1-mini
```

The initial admin user is created automatically if the `users` table is empty:

```text
INITIAL_ADMIN_EMAIL=admin@example.com
INITIAL_ADMIN_NAME=Local Admin
```

This is MVP local authentication. It is useful for testing roles and review UX, but should be replaced with proper production auth before real deployment.

## Users And Access

The Admin page is organized into tabs:

- **Users & Access** - invite users, edit user profile fields, and manage access.
- **Master Data** - maintain customer part cross-references and customer profiles.
- **Setup** - maintain order types and departments.
- **Testing** - build a PO test corpus, enter golden answers, run extraction evaluations, and prepare inbox connections.

Admins can open **Admin > Users & Access** to create users by first name, last name, job title, and email. User profiles can be active/inactive, admin/non-admin, allowed into Admin, allowed into the PO Dashboard, and assigned PO Dashboard access:

- `View Only` users can view the queue, details, source text, PDFs, and CSV exports, but cannot edit, delete, import, or change statuses.
- `Edit` users can use the existing PO Dashboard workflow.
- Admin users have all permissions and can manage other users.

To test view-only behavior, invite a user, set PO Dashboard access to `View Only`, log out, and log back in with that user email.

## Master Data

The **Master Data** tab stores customer part cross-references and customer profiles.

Customer profiles currently include:

- customer name
- customer number
- payment terms
- multiple bill-to addresses with structured address fields
- multiple ship-to addresses with structured address fields
- contacts with first name, last name, job title, phone number, and email

Address records use address line 1, address line 2, address line 3, city, state, country, and zip code. Existing freeform addresses are preserved and shown when structured fields are blank.

Contacts are shown as a compact list below the addresses inside the customer profile. Use **Add Contact** or a row **Edit** button to open the contact popup.

Customer master data can be exported from the Customers section as:

- customers only
- customers with addresses, with one row per address
- customer contacts, as a separate contact CSV

Customer CSV uploads can create or update customers and structured addresses. Contact CSV uploads match contacts to existing customers by customer name or customer number.

PO detail now includes a **Master Data Review** section. After a PO is processed, the app compares extracted customer, bill-to address, ship-to address, and contact values against customer master data. Missing matches are advisory review items with actions such as **Add Customer**, **Add Bill-To Address**, **Add Ship-To Address**, and **Add Contact**. These same actions are also surfaced inline near the Customer Company, Customer Contact, Bill-To Address, and Ship-To Address fields when review is needed. These review items do not block booking yet.

PO extraction also stores and displays a best-effort structured version of extracted bill-to and ship-to addresses so future validation can compare against the same address fields used by customer master data. PO detail uses address line 1, address line 2, address line 3, city, state, country, and zip code while keeping the formatted text address for compatibility and exports.

PO line items include customer and internal part revision fields. These are stored separately from the part numbers, can be corrected in the PO detail line editor, are captured by extraction feedback, and are included in the header-plus-lines CSV export.

The **Setup** tab also includes:

- departments, seeded with Sales, Customer Service, Operations, and Accounting
- payment terms, seeded with Net 30, Net 90, and Prepay

Customer profiles can reference the payment terms setup list through a dropdown. The original free-text `payment_terms` value is still preserved for compatibility and CSV export.

## Testing PO Extraction

Use **Admin > Testing** to build a repeatable test set for PO detection and extraction.

### PO Test Corpus

Upload scrubbed `.pdf`, `.txt`, `.eml`, `.csv`, or `.xlsx` samples into the PO Test Corpus. The app stores these under `samples/test-corpus`, which is ignored by Git so real customer documents are not committed.

For each document, set:

- document type, such as `po_pdf`, `po_email_body`, `invoice`, `quote`, or `random_email`
- expected classification: `purchase_order`, `possible_po`, or `not_po`
- notes about the sample

### Golden Answers

Use the **Golden** button on a corpus row to enter the expected PO header and line values. These are the manually verified answers the extractor is measured against. Non-PO documents can be marked as not expected to be a PO.

### Extraction Evaluation

Click **Run Evaluation** to process the corpus without adding records to the main PO Dashboard. Choose an extraction mode before running:

- **Rule Based** - deterministic parser baseline
- **AI Text** - OpenAI text extraction when configured
- **AI With Prior Examples** - OpenAI extraction with reviewed corrections from similar prior POs included as guidance

- true positives, false positives, true negatives, and false negatives
- field match rate
- line match rate
- average confidence
- per-document detection and latency

String comparisons are normalized for case and whitespace. Dates are normalized to `YYYY-MM-DD`, and numeric values are compared with a small tolerance.

This harness is intended to help you grow from a handful of examples to a 30-100 document test set and track extraction quality over time.

### Extraction Learning

The app now records an extraction learning loop:

- every extraction attempt is logged in `document_extraction_runs`
- raw input text, parsed output, extraction method, model name, prompt version, errors, and latency are stored for local testing
- when a user edits a PO header or PO line, changed fields are captured in `extraction_feedback`
- feedback stores the extracted value, corrected value, field confidence, customer, source attachment, and reviewing user when available
- PO detail shows the feedback count and reviewed status
- **Mark Extraction Reviewed** records that a human has finished reviewing the extraction

Admin > Testing includes an **Extraction Learning** dashboard with extraction run counts, failures, most-corrected fields, corrections by customer, and recent feedback rows.

When AI extraction is enabled, the extractor can retrieve recent reviewed/corrected examples and include them in the prompt as layout guidance. Prior examples are not treated as source data: the prompt instructs the model to prefer the current document, never copy PO numbers/prices/dates from examples, and return `null` when a value is missing.

To enable AI extraction from the app, use **Admin > Testing > OpenAI Extraction Configuration**:

- paste the OpenAI API key into the password field
- select the model from the dropdown, such as `gpt-4.1-mini`
- turn **Use AI extraction** on
- save the configuration

The API key is stored locally for this MVP and is never returned to the browser after saving. The panel only shows whether a key is configured. Leave the API key field blank when saving if you want to keep the existing key.

`.env.local` still works as a fallback for developers:

```text
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
USE_OPENAI_EXTRACTION=1
```

Recommended workflow for your first 35 PDFs:

1. Upload the PDFs to **Admin > Testing > PO Test Corpus**.
2. Enter golden answers for a representative subset first, such as 5-10 documents.
3. Run **Rule Based** evaluation to establish a baseline.
4. Enable AI extraction and run **AI Text** evaluation.
5. Import/process the same kinds of POs into the dashboard.
6. Correct extracted fields and line items in PO detail.
7. Click **Mark Extraction Reviewed** after each corrected PO.
8. Run **AI With Prior Examples** evaluation and compare the accuracy trend.
9. Expand the golden-answer set until the corpus reflects the real customer mix.

Scanned/image-only PDFs still need OCR or vision extraction. If PDF text extraction returns little or no text, the test harness marks the document as needing OCR instead of crashing. The placeholder `extract_pdf_with_vision_or_ocr()` is intentionally not wired to a production OCR provider yet.

AI extraction behavior:

- normal PO processing uses rule-based extraction when **Use AI extraction** is off
- normal PO processing uses OpenAI extraction when **Use AI extraction** is on and a key is configured
- if AI is enabled but no key is configured, the app falls back to rule-based extraction and records a note
- **AI Text** evaluation uses the saved OpenAI configuration
- **AI With Prior Examples** evaluation also includes reviewed corrections from the feedback loop as guidance
- production deployments should replace local SQLite/API-key storage with encrypted managed secret storage

## Gmail Inbox Testing

The app now has an inbox connection foundation in **Admin > Testing > Inbox Connections**.

Current Gmail MVP status:

- inbox account records are stored in SQLite
- Gmail OAuth configuration can be entered in **Admin > Testing > Gmail OAuth App Configuration**
- `GET /api/gmail-oauth-config` never returns the raw client secret
- `Connect Gmail` redirects to Google OAuth when client ID/secret are configured
- the Gmail OAuth callback exchanges the code for tokens and stores the connected account
- `Sync Inbox Now` refreshes tokens, fetches recent Gmail messages, downloads supported attachments, deduplicates messages, and reuses the PO detection/extraction pipeline
- inbox connections can be activated/deactivated without deleting them
- each Gmail connection has a **Configure** modal for labels, attachment filtering, and schedule settings
- Outlook is stubbed for a later Microsoft Graph implementation

Gmail folders are labels. After a Gmail account connects, the app fetches labels from Gmail and caches them per inbox connection. Use **Configure > Refresh Labels** to refresh the cached labels manually. Labels are also refreshed when the account connects and when a sync runs. New labels are selected by default except `TRASH` and `SPAM`; existing selections are preserved on refresh.

In the Configure modal, choose which labels should be monitored. Sync checks the selected labels, merges duplicate message IDs across labels, and then processes each unique message once.

The **Evaluate emails without attachments** setting is off by default. When it is off, Gmail sync skips body-only emails or emails without supported attachments and records them in inbox detection metrics as `skipped_no_supported_attachment`. Turn it on when you want the app to evaluate email-body purchase orders too.

Use **Sync Now** on a Gmail inbox connection to run a manual date/time-range sync. The modal asks for a start and end datetime, then scans configured Gmail labels for messages received in that range. Gmail's search date operators are coarse by day, so the app also filters exact received datetime after fetching each message.

Per-inbox schedule settings are stored for future automation:

- `Sync every ___ hours`
- `Starting at ___`
- `Next scheduled sync`

Manual **Sync Inbox Now** remains available for active inbox connections regardless of the stored schedule. This MVP stores schedule settings but does not run a background scheduler yet.

Add these values to `.env.local` when you are ready to configure Gmail:

```text
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REDIRECT_URI=http://127.0.0.1:8000/api/oauth/gmail/callback
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.readonly
```

Manual sync comes first. Gmail Pub/Sub push notifications are intentionally not part of this MVP because they require more Google Cloud setup. Token storage in SQLite is MVP-only and should be replaced with encrypted/managed secret storage before production.

To configure Google Cloud:

1. Create or open a Google Cloud project.
2. Enable the Gmail API.
3. Configure the OAuth consent screen and add your Gmail as a test user while the app is in testing mode.
4. Create OAuth credentials with application type **Web application**.
5. Add this authorized redirect URI:

```text
http://127.0.0.1:8000/api/oauth/gmail/callback
```

6. Copy the client ID and a newly created client secret into the local Gmail OAuth config panel.

If a client secret was pasted into chat, committed, or otherwise exposed, rotate it in Google Cloud before using it.

## Real Inbox Next Step

The app currently ships with a connector interface and local sample connector. Add Gmail or Outlook by implementing `InboxConnector.fetch_recent()` in `server/connectors.py`.

Recommended Gmail path:

- Create a Google Cloud OAuth client
- Request Gmail readonly scope
- Fetch recent messages and attachments
- Map them into the `IncomingEmail` and `IncomingAttachment` structures

Recommended Outlook path:

- Register an Azure app
- Use Microsoft Graph Mail.Read
- Fetch recent shared mailbox messages and attachments
- Map them into the same connector structures

The rest of the pipeline should not need to change.

## Project Layout

- `server/app.py` - local HTTP server and API routes
- `server/db.py` - SQLite schema and data access
- `server/processing.py` - sample import and PO processing pipeline
- `server/extraction.py` - PO detection and structured extraction
- `server/connectors.py` - inbox connector interface and sample file connector
- `samples/test-corpus/` - ignored local folder for extraction evaluation samples
- `public/` - operations review UI
- `samples/inbox/` - fake test fixtures

## MVP Notes

Scanned PDF OCR is represented as a logged fallback path. Text PDFs are supported via `pypdf`. If OCR becomes important after testing real samples, add a local Tesseract or cloud OCR step in `extract_pdf_text()`.
