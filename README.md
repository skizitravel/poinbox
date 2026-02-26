# PO Inbox Monitor

A small Python web app that monitors an Outlook/Exchange inbox (or simulates one in **mock mode**), identifies which emails likely contain purchase orders, and generates a live worklist.

---

## What it does

- Reads inbox messages from a local CSV file (mock mode) or from Microsoft Graph (stub — ready for next phase)
- Classifies each email as a **likely PO** based on file extension and keyword rules
- Persists PO records in a local SQLite database
- Displays a filterable, sortable worklist in the browser
- Provides a **Sync Inbox** button to pull new messages on demand
- Deduplicates: re-syncing never creates duplicate rows

## What it does NOT do yet

- PDF / OCR parsing
- ERP or Salesforce integration
- CSV export
- Microsoft Graph / Outlook auth (stub only — see `app/mailbox/graph_adapter.py`)
- Webhooks or background polling
- User authentication

---

## Setup

### Prerequisites

- Python 3.11+

### Install

```bash
git clone <repo-url>
cd poinbox

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### Configure

Copy the example env file and adjust as needed:

```bash
cp .env.example .env
```

The defaults work out of the box for mock mode:

```
APP_ENV=dev
DATABASE_URL=sqlite:///./po_inbox_monitor.db
MAILBOX_MODE=mock
MOCK_CSV_PATH=data/sample_inbox_messages.csv
```

### Run

```bash
uvicorn app.main:app --reload
```

Open your browser at **http://127.0.0.1:8000**.

Click **Sync Inbox** to import records from the sample CSV.

---

## How mock mode works

In mock mode (`MAILBOX_MODE=mock`) the app reads from `data/sample_inbox_messages.csv`.  
Each row represents one email with one attachment.  
Edit that file to add your own test data.

The CSV columns are:

| Column | Description |
|---|---|
| `email_id` | Unique ID for the email |
| `received_at` | ISO 8601 datetime |
| `sender` | Sender email address |
| `subject` | Email subject |
| `attachment_id` | Unique ID for the attachment |
| `attachment_name` | Attachment filename (extension matters) |
| `attachment_hash` | Optional content hash |

---

## How to change the PO keyword rules

Edit **`app/services/po_classifier.py`**:

```python
PO_KEYWORDS: List[str] = ["PURCHASE ORDER", "PO", "REV", "ORDER"]
PO_EXTENSIONS: List[str] = [".pdf", ".xlsx", ".xls"]
```

- Add or remove keywords from `PO_KEYWORDS` (matching is case-insensitive)
- Add or remove file extensions from `PO_EXTENSIONS`

---

## How to add real Outlook / Microsoft Graph integration

1. Register an app in Azure Active Directory with `Mail.Read` permission (application scope)
2. Fill in the Graph variables in your `.env`:

   ```
   MAILBOX_MODE=graph
   GRAPH_TENANT_ID=<your-tenant-id>
   GRAPH_CLIENT_ID=<your-client-id>
   GRAPH_CLIENT_SECRET=<your-client-secret>
   GRAPH_MAILBOX_USER=mailbox@yourdomain.com
   GRAPH_FOLDER_NAME=Inbox
   ```

3. Implement `_get_access_token()` and `fetch_messages()` in **`app/mailbox/graph_adapter.py`** using the [MSAL](https://github.com/AzureAD/microsoft-authentication-library-for-python) library
4. Update `_get_adapter()` in `app/main.py` to return `GraphMailboxAdapter` when `MAILBOX_MODE=graph`

---

## Run tests

```bash
pytest tests/ -v
```

---

## Project structure

```
poinbox/
├── README.md
├── requirements.txt
├── .env.example
├── data/
│   └── sample_inbox_messages.csv
├── app/
│   ├── main.py              ← FastAPI app + routes
│   ├── config.py            ← Settings from environment
│   ├── database.py          ← SQLite engine + session
│   ├── models.py            ← SQLModel ORM model (po_worklist table)
│   ├── schemas.py           ← Pydantic schemas (InboxMessage, SyncResult)
│   ├── storage.py           ← DB insert / query helpers
│   ├── mailbox/
│   │   ├── base.py          ← MailboxAdapter abstract base
│   │   ├── mock_adapter.py  ← CSV-based mock adapter
│   │   └── graph_adapter.py ← Microsoft Graph stub
│   ├── services/
│   │   ├── po_classifier.py     ← PO classification logic
│   │   └── worklist_service.py  ← Sync orchestration
│   ├── templates/
│   │   └── index.html       ← Jinja2 HTML UI
│   └── static/
│       └── styles.css
└── tests/
    ├── test_classifier.py
    ├── test_storage.py
    └── test_worklist_service.py
```