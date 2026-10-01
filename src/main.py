"""
Smart Expense Tracker API.

Endpoints:
    POST   /expenses               Add an expense
    GET    /expenses               List all expenses (optional ?category=, ?search=)
    GET    /expenses/{id}          Get a single expense
    DELETE /expenses/{id}          Delete an expense
    GET    /expenses/totals/summary  Overall total + breakdown by category
    GET    /expenses/search        Search expenses by title keyword (bonus)
"""
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

import httpx
from pydantic import BaseModel, Field

from . import assistant
from .models import Expense, ExpenseCreate
from .storage import ExpenseStore

app = FastAPI(
    title="Smart Expense Tracker API",
    description="A small REST API for tracking personal expenses.",
    version="1.0.0",
)

# Allow requests from the frontend (any origin in dev; lock down in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ExpenseStore()

# Serve the frontend static files
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/", tags=["health"], include_in_schema=False)
def root():
    """Serve the frontend index page."""
    frontend_index = os.path.join(_frontend_dir, "index.html")
    if os.path.isfile(frontend_index):
        return FileResponse(frontend_index)
    return {"status": "ok", "docs": "/docs"}


@app.post("/expenses", response_model=Expense, status_code=201, tags=["expenses"])
def add_expense(payload: ExpenseCreate):
    """Add a new expense. The server assigns the id."""
    return store.add(payload)


@app.get("/expenses", response_model=List[Expense], tags=["expenses"])
def list_expenses(
    category: Optional[str] = Query(None, description="Filter by category (case-insensitive)"),
    search: Optional[str] = Query(None, description="Search by title keyword (case-insensitive)"),
):
    """List all expenses, optionally filtered by category and/or searched by title keyword."""
    return store.list(category=category, search=search)


@app.get("/expenses/totals/summary", tags=["expenses"])
def totals_summary():
    """Overall total and a breakdown of totals per category.

    Note: this route is registered before /expenses/{expense_id} so that
    'totals' isn't mistaken for an expense id.
    """
    return {
        "overall_total": store.total(),
        "by_category": store.total_by_category(),
    }


@app.get("/expenses/{expense_id}", response_model=Expense, tags=["expenses"])
def get_expense(expense_id: int):
    expense = store.get(expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    return expense


@app.delete("/expenses/{expense_id}", status_code=204, tags=["expenses"])
def delete_expense(expense_id: int):
    deleted = store.delete(expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    return JSONResponse(status_code=204, content=None)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)


@app.post("/assistant/chat", tags=["assistant"])
def assistant_chat(payload: ChatRequest):
    """Natural-language assistant: add expenses or ask about spending (LLM tool calling)."""
    try:
        return assistant.chat(store, payload.message.strip())
    except (httpx.ConnectError, httpx.TimeoutException):
        raise HTTPException(
            status_code=503,
            detail="LLM not reachable. Start Ollama (`ollama serve`) and run `ollama pull llama3.2`.",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc.response.status_code}")
