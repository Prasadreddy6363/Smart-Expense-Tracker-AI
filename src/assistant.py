"""
AI assistant for the Smart Expense Tracker.

Turns natural language into actions using LLM *tool calling* (Ollama, local):

    "I spent 450 on dinner yesterday"        -> add_expense(...)
    "How much did I spend on food this month?" -> get_total(...)

The LLM only decides WHICH tool to call and with WHAT arguments. All maths,
validation and storage are done by normal Python code, so numbers are never
made up by the model.
"""
import json
import os
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx
from pydantic import ValidationError

from .models import ExpenseCreate
from .storage import ExpenseStore

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
MAX_STEPS = 3  # max LLM <-> tool round trips per message

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "Record a new expense the user says they spent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short label, e.g. 'Dinner'"},
                    "amount": {"type": "number", "description": "Amount in rupees, > 0"},
                    "category": {
                        "type": "string",
                        "enum": ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Other"],
                        "description": (
                            "Category of the expense. Use Food for anything edible "
                            "(vegetables, fruits, groceries, meals, coffee). "
                            "Use Transport for travel/fuel. Shopping for clothes/electronics. "
                            "Bills for utilities/rent. Health for medicines/doctor. "
                            "Entertainment for movies/events. Other for everything else."
                        ),
                    },
                    "date": {"type": "string", "description": "YYYY-MM-DD, resolved from today's date"},
                },
                "required": ["title", "amount", "category", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_total",
            "description": "Total spent, optionally filtered by category and/or date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_expenses",
            "description": "List recent expenses, optionally filtered by category and/or date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max rows, default 10"},
                },
            },
        },
    },
]


def system_prompt(today: date) -> str:
    return (
        "You are the assistant of an expense tracker. Currency is Indian rupees (INR).\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}). "
        f"Yesterday is {(today - timedelta(days=1)).isoformat()}. "
        f"'This month' starts on {today.replace(day=1).isoformat()}.\n"
        "Use the tools to add expenses or answer questions about spending. "
        "Never guess totals; call get_total or list_expenses. "
        "If the amount is missing, ask the user instead of calling a tool. "
        "After tool results arrive, reply in one or two short sentences.\n\n"
        "Category rules — pick the BEST match from this list only:\n"
        "  Food       — groceries, vegetables, fruits, dairy, meat, snacks, meals, "
        "restaurants, cafes, coffee, juice, breakfast, lunch, dinner, eating out\n"
        "  Transport  — bus, auto, cab, taxi, Uber, Ola, metro, train, fuel, petrol, "
        "parking, flight, toll\n"
        "  Shopping   — clothes, shoes, electronics, gadgets, appliances, furniture, "
        "online orders, Amazon, Flipkart, gifts\n"
        "  Bills      — electricity, water, gas, internet, phone recharge, rent, EMI, "
        "insurance, subscriptions (Netflix, Spotify)\n"
        "  Health     — medicines, pharmacy, doctor, hospital, clinic, lab tests, gym, "
        "fitness\n"
        "  Entertainment — movies, games, events, concerts, outings, amusement parks\n"
        "  Other      — anything that does not fit the above\n"
        "Examples: 'vegetables' -> Food, 'petrol' -> Transport, 'shirt' -> Shopping, "
        "'electricity bill' -> Bills, 'paracetamol' -> Health."
    )


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"invalid date '{value}', expected YYYY-MM-DD")


def _filter(store: ExpenseStore, args: Dict[str, Any]):
    start, end = _parse_date(args.get("start_date")), _parse_date(args.get("end_date"))
    items = store.list(category=args.get("category") or None)
    if start:
        items = [e for e in items if e.date >= start]
    if end:
        items = [e for e in items if e.date <= end]
    return items


# -- tool implementations (plain Python; they never trust the LLM) -------------
def tool_add_expense(store: ExpenseStore, args: Dict[str, Any]) -> Dict[str, Any]:
    payload = ExpenseCreate(**args)  # Pydantic validates amount > 0, date format, etc.
    expense = store.add(payload)
    return {"added": json.loads(expense.model_dump_json())}


def tool_get_total(store: ExpenseStore, args: Dict[str, Any]) -> Dict[str, Any]:
    items = _filter(store, args)
    return {"total": round(sum(e.amount for e in items), 2), "count": len(items)}


def tool_list_expenses(store: ExpenseStore, args: Dict[str, Any]) -> Dict[str, Any]:
    items = _filter(store, args)
    limit = max(1, min(int(args.get("limit") or 10), 50))
    items = sorted(items, key=lambda e: (e.date, e.id), reverse=True)[:limit]
    return {"expenses": [json.loads(e.model_dump_json()) for e in items]}


TOOL_IMPL: Dict[str, Callable[[ExpenseStore, Dict[str, Any]], Dict[str, Any]]] = {
    "add_expense": tool_add_expense,
    "get_total": tool_get_total,
    "list_expenses": tool_list_expenses,
}


def run_tool(store: ExpenseStore, name: str, args: Any) -> Dict[str, Any]:
    """Execute one tool call safely. Errors are returned to the LLM, not raised."""
    if isinstance(args, str):  # some models send arguments as a JSON string
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {"error": "arguments were not valid JSON"}
    fn = TOOL_IMPL.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(store, args or {})
    except (ValidationError, ValueError, TypeError) as exc:
        return {"error": str(exc)}


# -- LLM call -----------------------------------------------------------------
def call_ollama(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One non-streaming chat request to Ollama. Returns the assistant message."""
    resp = httpx.post(
        f"{OLLAMA_HOST}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages, "tools": TOOLS,
              "stream": False, "options": {"temperature": 0}},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]


def chat(
    store: ExpenseStore,
    user_message: str,
    llm: Callable[[List[Dict[str, Any]]], Dict[str, Any]] = call_ollama,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Run the tool-calling loop. `llm` is injectable so tests need no model."""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt(today or date.today())},
        {"role": "user", "content": user_message},
    ]
    actions: List[Dict[str, Any]] = []

    for _ in range(MAX_STEPS):
        reply = llm(messages)
        calls = reply.get("tool_calls") or []
        if not calls:
            return {"reply": (reply.get("content") or "").strip(), "actions": actions}

        messages.append(reply)
        for call in calls:
            fn = call["function"]
            result = run_tool(store, fn["name"], fn.get("arguments"))
            actions.append({"tool": fn["name"], "args": fn.get("arguments"), "result": result})
            messages.append({"role": "tool", "content": json.dumps(result), "tool_name": fn["name"]})

    return {"reply": "Sorry, I couldn't finish that request. Please try rephrasing.", "actions": actions}
