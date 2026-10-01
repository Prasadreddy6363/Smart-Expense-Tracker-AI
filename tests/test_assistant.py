"""Assistant tests. The LLM is replaced by a scripted fake, so no model is needed."""
import os
import sys
from datetime import date

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import assistant  # noqa: E402
from src.main import app, store  # noqa: E402

TODAY = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def reset_store():
    store.clear()
    yield
    store.clear()


def tool_call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def scripted(*replies):
    """Fake LLM that returns the given replies in order."""
    it = iter(replies)
    return lambda messages: next(it)


def test_add_expense_from_sentence():
    llm = scripted(
        tool_call("add_expense", title="Dinner", amount=450, category="Food", date="2026-09-30"),
        {"role": "assistant", "content": "Added Dinner for 450."},
    )
    out = assistant.chat(store, "I spent 450 on dinner yesterday", llm=llm, today=TODAY)
    assert out["reply"] == "Added Dinner for 450."
    assert out["actions"][0]["result"]["added"]["date"] == "2026-09-30"
    assert len(store.list()) == 1


def test_total_is_computed_by_code_not_llm():
    for amt, d in [(100, "2026-10-01"), (50, "2026-10-01"), (999, "2026-08-01")]:
        store.add(assistant.ExpenseCreate(title="x", amount=amt, category="Food", date=d))
    llm = scripted(
        tool_call("get_total", category="food", start_date="2026-10-01", end_date="2026-10-31"),
        {"role": "assistant", "content": "You spent 150 on food this month."},
    )
    out = assistant.chat(store, "food this month?", llm=llm, today=TODAY)
    assert out["actions"][0]["result"] == {"total": 150.0, "count": 2}


def test_invalid_llm_arguments_are_rejected_not_stored():
    llm = scripted(
        tool_call("add_expense", title="Bad", amount=-5, category="Food", date="2026-10-01"),
        {"role": "assistant", "content": "That amount looks invalid."},
    )
    out = assistant.chat(store, "spent -5", llm=llm, today=TODAY)
    assert "error" in out["actions"][0]["result"]
    assert store.list() == []


def test_unknown_tool_and_bad_date_return_errors():
    assert "error" in assistant.run_tool(store, "drop_database", {})
    assert "error" in assistant.run_tool(store, "get_total", {"start_date": "yesterday"})


def test_plain_reply_without_tools():
    out = assistant.chat(store, "hi", llm=scripted({"role": "assistant", "content": "Hello!"}), today=TODAY)
    assert out == {"reply": "Hello!", "actions": []}


def test_endpoint_returns_503_when_llm_down(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(assistant, "chat", boom)
    r = TestClient(app).post("/assistant/chat", json={"message": "hi"})
    assert r.status_code == 503
