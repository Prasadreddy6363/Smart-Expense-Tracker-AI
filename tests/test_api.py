"""
Test suite for the Smart Expense Tracker API.

Run with: pytest
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import app, store  # noqa: E402


@pytest.fixture(autouse=True)
def reset_store():
    """Ensure every test starts from a clean, empty store."""
    store.clear()
    yield
    store.clear()


client = TestClient(app)


def make_expense(title="Coffee", amount=4.5, category="Food", date="2026-07-01"):
    return {"title": title, "amount": amount, "category": category, "date": date}


# -- Create --------------------------------------------------------------

def test_add_expense_returns_201_and_assigns_id():
    resp = client.post("/expenses", json=make_expense())
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 1
    assert body["title"] == "Coffee"
    assert body["amount"] == 4.5
    assert body["category"] == "Food"
    assert body["date"] == "2026-07-01"


def test_add_expense_ids_increment():
    r1 = client.post("/expenses", json=make_expense(title="A"))
    r2 = client.post("/expenses", json=make_expense(title="B"))
    assert r1.json()["id"] == 1
    assert r2.json()["id"] == 2


@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"amount": 0}, "amount"),
        ({"amount": -5}, "amount"),
        ({"title": ""}, "title"),
        ({"category": ""}, "category"),
        ({"date": "not-a-date"}, "date"),
    ],
)
def test_add_expense_validation_errors(overrides, field):
    payload = make_expense()
    payload.update(overrides)
    resp = client.post("/expenses", json=payload)
    assert resp.status_code == 422


def test_add_expense_missing_field_returns_422():
    payload = make_expense()
    del payload["title"]
    resp = client.post("/expenses", json=payload)
    assert resp.status_code == 422


# -- Read ------------------------------------------------------------------

def test_list_expenses_empty():
    resp = client.get("/expenses")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_expenses_returns_all():
    client.post("/expenses", json=make_expense(title="Coffee", category="Food"))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport"))
    resp = client.get("/expenses")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_filter_expenses_by_category():
    client.post("/expenses", json=make_expense(title="Coffee", category="Food"))
    client.post("/expenses", json=make_expense(title="Lunch", category="Food"))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport"))

    resp = client.get("/expenses", params={"category": "Food"})
    assert resp.status_code == 200
    titles = {e["title"] for e in resp.json()}
    assert titles == {"Coffee", "Lunch"}


def test_filter_expenses_by_category_case_insensitive():
    client.post("/expenses", json=make_expense(category="Food"))
    resp = client.get("/expenses", params={"category": "food"})
    assert len(resp.json()) == 1


def test_filter_by_unknown_category_returns_empty_list():
    client.post("/expenses", json=make_expense(category="Food"))
    resp = client.get("/expenses", params={"category": "Nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_single_expense():
    created = client.post("/expenses", json=make_expense()).json()
    resp = client.get(f"/expenses/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_single_expense_not_found():
    resp = client.get("/expenses/9999")
    assert resp.status_code == 404


# -- Totals ------------------------------------------------------------------

def test_totals_summary_overall_and_by_category():
    client.post("/expenses", json=make_expense(amount=10, category="Food"))
    client.post("/expenses", json=make_expense(amount=5, category="Food"))
    client.post("/expenses", json=make_expense(amount=20, category="Transport"))

    resp = client.get("/expenses/totals/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_total"] == 35
    assert body["by_category"] == {"Food": 15, "Transport": 20}


def test_totals_summary_empty_store():
    resp = client.get("/expenses/totals/summary")
    assert resp.status_code == 200
    assert resp.json() == {"overall_total": 0, "by_category": {}}


# -- Delete ------------------------------------------------------------------

def test_delete_expense():
    created = client.post("/expenses", json=make_expense()).json()
    resp = client.delete(f"/expenses/{created['id']}")
    assert resp.status_code == 204

    resp2 = client.get(f"/expenses/{created['id']}")
    assert resp2.status_code == 404


def test_delete_expense_not_found():
    resp = client.delete("/expenses/9999")
    assert resp.status_code == 404


def test_delete_then_totals_updates():
    created = client.post("/expenses", json=make_expense(amount=10, category="Food")).json()
    client.post("/expenses", json=make_expense(amount=5, category="Food"))

    client.delete(f"/expenses/{created['id']}")

    resp = client.get("/expenses/totals/summary")
    assert resp.json()["overall_total"] == 5
