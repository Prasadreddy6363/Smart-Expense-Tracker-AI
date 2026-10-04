"""
AI assistant for the Smart Expense Tracker.

Supports two LLM backends — auto-selected based on environment variables:

  1. Groq  (cloud, free)  — set GROQ_API_KEY env var.  Used on Render.
     Model: llama-3.3-70b-versatile (default) or GROQ_MODEL env var.

  2. Ollama (local)       — fallback when GROQ_API_KEY is not set.
     Requires `ollama serve` + `ollama pull llama3.2` running locally.

The LLM only decides WHICH tool to call and WHAT arguments to pass.
All maths, validation, and storage are done by normal Python code.
"""
import json
import os
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx
from pydantic import ValidationError

from .models import ExpenseCreate
from .storage import ExpenseStore

# -- LLM config ---------------------------------------------------------------
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL    = os.getenv("GROQ_MODEL", "llama3-8b-8192")
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"

OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3.2")

MAX_STEPS = 3  # max LLM <-> tool round trips per message

# -- Tool schemas -------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_expense",
            "description": "Record a new expense the user says they spent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title":    {"type": "string", "description": "Short label, e.g. 'Dinner'"},
                    "amount":   {"type": "number", "description": "Amount in rupees, > 0"},
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
                    "category":   {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    "end_date":   {"type": "string", "description": "YYYY-MM-DD inclusive"},
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
                    "category":   {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date":   {"type": "string"},
                    "limit":      {"type": "integer", "description": "Max rows, default 10"},
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
        "  Health     — medicines, pharmacy, doctor, hospital, clinic, lab tests, gym, fitness\n"
        "  Entertainment — movies, games, events, concerts, outings, amusement parks\n"
        "  Other      — anything that does not fit the above\n"
        "Examples: 'vegetables' -> Food, 'petrol' -> Transport, 'shirt' -> Shopping, "
        "'electricity bill' -> Bills, 'paracetamol' -> Health."
    )


# -- Tool helpers -------------------------------------------------------------
def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"invalid date '{value}', expected YYYY-MM-DD")


def _filter(store: ExpenseStore, args: Dict[str, Any]):
    start = _parse_date(args.get("start_date"))
    end   = _parse_date(args.get("end_date"))
    items = store.list(category=args.get("category") or None)
    if start:
        items = [e for e in items if e.date >= start]
    if end:
        items = [e for e in items if e.date <= end]
    return items


# -- Tool implementations -----------------------------------------------------
def tool_add_expense(store: ExpenseStore, args: Dict[str, Any]) -> Dict[str, Any]:
    payload = ExpenseCreate(**args)
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
    "add_expense":   tool_add_expense,
    "get_total":     tool_get_total,
    "list_expenses": tool_list_expenses,
}


def run_tool(store: ExpenseStore, name: str, args: Any) -> Dict[str, Any]:
    """Execute one tool call safely. Errors are returned to the LLM, not raised."""
    if isinstance(args, str):
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


# -- LLM backends -------------------------------------------------------------
def _normalize_openai_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert an OpenAI-format tool_calls response to the same shape
    we use internally (matching Ollama's format) so the chat loop
    works with both backends unchanged.
    """
    tool_calls = msg.get("tool_calls")
    if not tool_calls:
        return msg
    normalized = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        # OpenAI sends arguments as a JSON string; parse it
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass
        normalized.append({"function": {"name": fn.get("name"), "arguments": args}})
    return {**msg, "tool_calls": normalized}


def call_groq(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One non-streaming chat request to Groq (OpenAI-compatible API)."""
    # Groq does not accept the 'tool_name' key in tool result messages
    clean_messages = []
    for m in messages:
        if m.get("role") == "tool":
            clean_messages.append({"role": "tool", "content": m["content"],
                                   "tool_call_id": m.get("tool_call_id", "call_0")})
        else:
            clean_messages.append({k: v for k, v in m.items() if k != "tool_name"})

    resp = httpx.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": clean_messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0,
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]
    return _normalize_openai_message(raw)


def call_ollama(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One non-streaming chat request to Ollama."""
    resp = httpx.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "tools": TOOLS,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]


def _default_llm() -> Callable[[List[Dict[str, Any]]], Dict[str, Any]]:
    """Pick Groq if API key is set, otherwise fall back to Ollama."""
    if GROQ_API_KEY:
        return call_groq
    return call_ollama


# -- Main chat loop -----------------------------------------------------------
def chat(
    store: ExpenseStore,
    user_message: str,
    llm: Callable[[List[Dict[str, Any]]], Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Run the tool-calling loop. `llm` is injectable so tests need no model."""
    if llm is None:
        llm = _default_llm()

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt(today or date.today())},
        {"role": "user",   "content": user_message},
    ]
    actions: List[Dict[str, Any]] = []

    for _ in range(MAX_STEPS):
        reply = llm(messages)
        calls = reply.get("tool_calls") or []
        if not calls:
            return {"reply": (reply.get("content") or "").strip(), "actions": actions}

        messages.append(reply)
        for call in calls:
            fn     = call["function"]
            result = run_tool(store, fn["name"], fn.get("arguments"))
            actions.append({"tool": fn["name"], "args": fn.get("arguments"), "result": result})
            messages.append({
                "role":        "tool",
                "content":     json.dumps(result),
                "tool_name":   fn["name"],
                "tool_call_id": "call_0",
            })

    return {"reply": "Sorry, I couldn't finish that. Please try rephrasing.", "actions": actions}
