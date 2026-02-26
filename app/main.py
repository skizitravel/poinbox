"""FastAPI application entry point for PO Inbox Monitor."""

from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import create_db_and_tables, get_session
from app.mailbox.mock_adapter import MockMailboxAdapter
from app.services.worklist_service import sync_inbox
from app.storage import get_worklist, count_by_status

app = FastAPI(title="PO Inbox Monitor")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Track last sync result in memory (good enough for first draft)
_last_sync_result: Optional[dict] = None


@app.on_event("startup")
def on_startup() -> None:
    """Create database tables on application startup."""
    create_db_and_tables()


def _get_adapter():
    """Return the configured mailbox adapter."""
    mode = settings.MAILBOX_MODE.lower()
    if mode == "mock":
        return MockMailboxAdapter(csv_path=settings.MOCK_CSV_PATH)
    # TODO: add graph mode instantiation here in next phase
    raise ValueError(f"Unsupported MAILBOX_MODE: {mode!r}")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    status: Optional[str] = None,
    likely_po: Optional[str] = None,
):
    """Render the main worklist page."""
    likely_po_filter: Optional[bool] = None
    if likely_po == "yes":
        likely_po_filter = True
    elif likely_po == "no":
        likely_po_filter = False

    with get_session() as session:
        records = get_worklist(session, status_filter=status or None, likely_po_filter=likely_po_filter)
        counts = count_by_status(session)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "records": records,
            "counts": counts,
            "status_filter": status or "",
            "likely_po_filter": likely_po or "",
            "last_sync": _last_sync_result,
        },
    )


@app.post("/sync", response_class=RedirectResponse)
def sync(request: Request):
    """Trigger a manual inbox sync and redirect back to the worklist."""
    global _last_sync_result
    adapter = _get_adapter()
    with get_session() as session:
        result = sync_inbox(adapter, session)
    _last_sync_result = result.dict()
    return RedirectResponse(url="/", status_code=303)
