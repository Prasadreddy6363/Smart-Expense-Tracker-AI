"""
Test suite for the Smart Expense Tracker API — multi-user edition.

Every request carries X-Username: testuser so the server routes it to an
isolated per-user store.  The autouse fixture clears that store before and
after every test so cases remain fully independent.

Run with: pytest
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import app, _get_store  # noqa: E402

TEST_USER = "testuser"
HEADERS = {"X-Username": TEST_USER}


@pytest.fixture(autouse=True)
def reset_store():
    """Ensure every test starts from a clean, empty store for TEST_USER."""
    _get_store(TEST_USER).clear()
    yield
    _get_store(TEST_USER).clear()


client = TestClient(app, headers=HEADERS)


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
        ({"amount": 0},          "amount"),
        ({"amount": -5},         "amount"),
        ({"title": ""},          "title"),
        ({"category": ""},       "category"),
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


# -- Missing / bad header ------------------------------------------------

def test_missing_username_header_returns_422():
    """Requests without X-Username must be rejected."""
    no_header_client = TestClient(app)
    resp = no_header_client.post("/expenses", json=make_expense())
    assert resp.status_code == 422


def test_invalid_username_header_returns_400():
    """Usernames with path-traversal chars must be rejected."""
    bad_client = TestClient(app, headers={"X-Username": "../../etc/passwd"})
    resp = bad_client.get("/expenses")
    assert resp.status_code == 400


# -- User isolation ------------------------------------------------------

def test_users_are_isolated():
    """Expenses added for user A must not appear for user B."""
    client_a = TestClient(app, headers={"X-Username": "isolate-a"})
    client_b = TestClient(app, headers={"X-Username": "isolate-b"})
    _get_store("isolate-a").clear()
    _get_store("isolate-b").clear()

    client_a.post("/expenses", json=make_expense(title="A-only"))
    resp_b = client_b.get("/expenses")
    assert resp_b.status_code == 200
    assert all(e["title"] != "A-only" for e in resp_b.json())

    _get_store("isolate-a").clear()
    _get_store("isolate-b").clear()


# -- Read ----------------------------------------------------------------

def test_list_expenses_empty():
    resp = client.get("/expenses")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_expenses_returns_all():
    client.post("/expenses", json=make_expense(title="Coffee",     category="Food"))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport"))
    resp = client.get("/expenses")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_filter_expenses_by_category():
    client.post("/expenses", json=make_expense(title="Coffee",     category="Food"))
    client.post("/expenses", json=make_expense(title="Lunch",      category="Food"))
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


# -- Totals --------------------------------------------------------------

def test_totals_summary_overall_and_by_category():
    client.post("/expenses", json=make_expense(amount=10, category="Food"))
    client.post("/expenses", json=make_expense(amount=5,  category="Food"))
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


# -- Delete --------------------------------------------------------------

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


# -- Users list ----------------------------------------------------------

def test_list_users_returns_known_users():
    """GET /users should include testuser after an expense has been added."""
    client.post("/expenses", json=make_expense())
    resp = client.get("/users")   # no header needed
    assert resp.status_code == 200
    assert TEST_USER in resp.json()
