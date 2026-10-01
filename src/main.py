"""
Smart Expense Tracker API — multi-user edition.

Every expense endpoint requires an X-Username header.  Each user gets their
own isolated in-memory store backed by data/expenses_<username>.json.

Endpoints:
    GET    /users                            List all known usernames
    POST   /expenses                Add an expense          (X-Username required)
    GET    /expenses                List / filter expenses  (X-Username required)
    GET    /expenses/{id}           Get a single expense    (X-Username required)
    DELETE /expenses/{id}           Delete an expense       (X-Username required)
    GET    /expenses/totals/summary Overall + per-category  (X-Username required)
    POST   /assistant/chat          AI assistant            (X-Username required)
"""
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import threading

import httpx
from pydantic import BaseModel, Field

from . import assistant
from .models import Expense, ExpenseCreate
from .storage import DATA_DIR, ExpenseStore, sanitize_username

app = FastAPI(
    title="Smart Expense Tracker API",
    description="Multi-user expense tracker — pass X-Username header on every request.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*", "X-Username"],
    expose_headers=["X-Username"],
)

# ---------------------------------------------------------------------------
# Per-user store registry
# ---------------------------------------------------------------------------
_stores: Dict[str, ExpenseStore] = {}
_registry_lock = threading.Lock()


def _get_store(username: str) -> ExpenseStore:
    """Return (creating if needed) the ExpenseStore for *username*."""
    if username not in _stores:
        with _registry_lock:
            if username not in _stores:          # double-checked locking
                path = os.path.join(DATA_DIR, f"expenses_{username}.json")
                _stores[username] = ExpenseStore(data_file=path)
    return _stores[username]


def get_user_store(x_username: str = Header(..., alias="X-Username")) -> ExpenseStore:
    """FastAPI dependency — validates the header and returns the user's store."""
    try:
        username = sanitize_username(x_username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _get_store(username)


# kept for tests that import it directly
store = _get_store("default")

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/", tags=["health"], include_in_schema=False)
def root():
    frontend_index = os.path.join(_frontend_dir, "index.html")
    if os.path.isfile(frontend_index):
        return FileResponse(frontend_index)
    return {"status": "ok", "docs": "/docs"}


# ---------------------------------------------------------------------------
# User list (no auth required — just shows who has data)
# ---------------------------------------------------------------------------
@app.get("/users", tags=["users"])
def list_users():
    """Return all usernames that have at least one expense file on disk."""
    users = []
    try:
        for fname in os.listdir(DATA_DIR):
            if fname.startswith("expenses_") and fname.endswith(".json"):
                users.append(fname[len("expenses_"):-len(".json")])
    except FileNotFoundError:
        pass
    return sorted(users)


# ---------------------------------------------------------------------------
# Expense routes  (all require X-Username header)
# ---------------------------------------------------------------------------
@app.post("/expenses", response_model=Expense, status_code=201, tags=["expenses"])
def add_expense(
    payload: ExpenseCreate,
    store: ExpenseStore = Depends(get_user_store),
):
    """Add a new expense for the authenticated user."""
    return store.add(payload)


@app.get("/expenses", response_model=List[Expense], tags=["expenses"])
def list_expenses(
    category: Optional[str] = Query(None, description="Filter by category (case-insensitive)"),
    search: Optional[str] = Query(None, description="Search by title keyword (case-insensitive)"),
    store: ExpenseStore = Depends(get_user_store),
):
    """List all expenses for the authenticated user."""
    return store.list(category=category, search=search)


@app.get("/expenses/totals/summary", tags=["expenses"])
def totals_summary(store: ExpenseStore = Depends(get_user_store)):
    """Overall total and per-category breakdown for the authenticated user.

    Registered before /expenses/{expense_id} so FastAPI doesn't treat
    the literal 'totals' as an integer id.
    """
    return {
        "overall_total": store.total(),
        "by_category": store.total_by_category(),
    }


@app.get("/expenses/{expense_id}", response_model=Expense, tags=["expenses"])
def get_expense(
    expense_id: int,
    store: ExpenseStore = Depends(get_user_store),
):
    expense = store.get(expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    return expense


@app.delete("/expenses/{expense_id}", status_code=204, tags=["expenses"])
def delete_expense(
    expense_id: int,
    store: ExpenseStore = Depends(get_user_store),
):
    deleted = store.delete(expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    return JSONResponse(status_code=204, content=None)


# ---------------------------------------------------------------------------
# AI assistant
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)


@app.post("/assistant/chat", tags=["assistant"])
def assistant_chat(
    payload: ChatRequest,
    store: ExpenseStore = Depends(get_user_store),
):
    """Natural-language assistant for the authenticated user (LLM tool calling)."""
    try:
        return assistant.chat(store, payload.message.strip())
    except (httpx.ConnectError, httpx.TimeoutException):
        raise HTTPException(
            status_code=503,
            detail="LLM not reachable. Start Ollama (`ollama serve`) and run `ollama pull llama3.2`.",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc.response.status_code}")
