# POInbox Purchase Order Intake MVP

This repository contains a local MVP for purchase order intake from a shared inbox. It imports sample emails/documents, detects likely purchase orders, extracts header and line data, and presents a review queue where every new PO starts as `Received` and can be marked `Booked`.

## What It Does

- Imports `.txt`, `.eml`, and `.pdf` files from `samples/inbox`
- Stores email metadata, attachments, purchase order headers, PO lines, and processing logs in SQLite
- Detects likely POs from subject/body/attachment text and records confidence/explanation
- Extracts PO fields with a deterministic parser, with optional OpenAI extraction enabled by environment config
- Serves a local review UI for status changes, header edits, line edits, adding lines, and deleting lines
- Includes a Gmail/Outlook connector interface stub for adding real inbox sync after the sample-mode vertical slice is validated

## Run In A Browser With GitHub Codespaces

Use this path if your computer has a browser but cannot install Python or other developer tools.

1. Open [https://github.com/skizitravel/poinbox](https://github.com/skizitravel/poinbox).
2. Click **Code**.
3. Open the **Codespaces** tab.
4. Click **Create codespace on main**.
5. Wait for the setup to finish.
6. In the Codespaces terminal, run:

```bash
python server/app.py
```

Codespaces should prompt you to open forwarded port `8000`. If it does not, open the **Ports** tab, find port `8000`, and click the globe/open-browser icon.

The app will run in a browser tab from the Codespaces URL. Data created there lives inside that Codespace unless you export it or commit code changes.

## Local Quick Start

Install Python 3.11+ and then install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create your local environment file:

```powershell
Copy-Item .env.example .env.local
```

For deterministic local testing, leave `USE_OPENAI_EXTRACTION=0`. To test AI extraction, add your `OPENAI_API_KEY` to `.env.local` and set `USE_OPENAI_EXTRACTION=1`.

Start the app:

```powershell
python server\app.py
```

Then open:

```text
http://127.0.0.1:8000
```

Click **Import Samples** to open the upload dialog. You can drag `.pdf`, `.txt`, or `.eml` files into the dialog, click **Select File**, or use **Import Existing Sample Folder** to process files already in `samples/inbox`.

Use the header switcher to move between **PO Dashboard** and **Admin**. Admin includes configurable order types and a customer part cross-reference CSV upload. Cross-reference CSV files should include customer, customer part number, and internal part number columns.

## Configuration

Copy `.env.example` to `.env.local` and set values as needed. Never commit `.env.local`.

The MVP defaults to deterministic extraction so it runs locally without spending API tokens:

```text
USE_OPENAI_EXTRACTION=0
```

To use the OpenAI extractor, set:

```text
USE_OPENAI_EXTRACTION=1
OPENAI_MODEL=gpt-4.1-mini
```

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
- `public/` - operations review UI
- `samples/inbox/` - fake test fixtures

## MVP Notes

Scanned PDF OCR is represented as a logged fallback path. Text PDFs are supported via `pypdf`. If OCR becomes important after testing real samples, add a local Tesseract or cloud OCR step in `extract_pdf_text()`.
