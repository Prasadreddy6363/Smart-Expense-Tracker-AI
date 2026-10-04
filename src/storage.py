"""
Simple JSON-file-backed storage for expenses.

Data lives in memory (a dict keyed by id) while the process runs, and is
flushed to a JSON file on every write so the data survives restarts.
No external database is used, per the assignment requirements.

Multi-user: each user gets their own ExpenseStore instance with its own
JSON file (data/expenses_<username>.json) and its own threading lock.
"""
import json
import os
import re
import threading
from datetime import date
from typing import Dict, List, Optional

from .models import Expense, ExpenseCreate

# On Render the persistent disk is mounted at /data.
# Locally it falls back to the repo's own data/ folder.
_RENDER_DATA = "/data"
DATA_DIR = _RENDER_DATA if os.path.isdir(_RENDER_DATA) else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
DATA_FILE = os.path.join(DATA_DIR, "expenses.json")

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def sanitize_username(username: str) -> str:
    """
    Validate and normalise a username.

    Rules:
    - 1-32 characters, letters / digits / underscore / hyphen only
    - Stored lower-case so 'Alice' and 'alice' are the same user
    - Prevents path-traversal (no dots, slashes, etc.)

    Raises ValueError for invalid usernames.
    """
    username = username.strip().lower()
    if not _USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 1-32 characters and contain only "
            "letters, digits, underscores, or hyphens."
        )
    return username


class ExpenseStore:
    """In-memory store of expenses for a single user, mirrored to a JSON file."""

    def __init__(self, data_file: str = DATA_FILE):
        self.data_file = data_file
        self._expenses: Dict[int, Expense] = {}
        self._next_id = 1
        self._lock = threading.Lock()   # per-instance lock; not shared across users
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if not os.path.exists(self.data_file):
            self._expenses = {}
            self._next_id = 1
            return

        with open(self.data_file, "r", encoding="utf-8") as f:
            try:
                raw = json.load(f)
            except json.JSONDecodeError:
                raw = []

        self._expenses = {}
        for item in raw:
            expense = Expense(**item)
            self._expenses[expense.id] = expense
        self._next_id = (max(self._expenses.keys()) + 1) if self._expenses else 1

    def _flush(self) -> None:
        serializable = [json.loads(e.model_dump_json()) for e in self._expenses.values()]
        tmp_path = self.data_file + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, default=str)
        os.replace(tmp_path, self.data_file)

    # -- CRUD --------------------------------------------------------------
    def add(self, payload: ExpenseCreate) -> Expense:
        with self._lock:
            expense = Expense(id=self._next_id, **payload.model_dump())
            self._expenses[expense.id] = expense
            self._next_id += 1
            self._flush()
            return expense

    def list(self, category: Optional[str] = None, search: Optional[str] = None) -> List[Expense]:
        items = list(self._expenses.values())
        if category is not None:
            items = [e for e in items if e.category.lower() == category.lower()]
        if search is not None:
            items = [e for e in items if search.lower() in e.title.lower()]
        return sorted(items, key=lambda e: e.id)

    def get(self, expense_id: int) -> Optional[Expense]:
        return self._expenses.get(expense_id)

    def delete(self, expense_id: int) -> bool:
        with self._lock:
            if expense_id not in self._expenses:
                return False
            del self._expenses[expense_id]
            self._flush()
            return True

    def total(self, category: Optional[str] = None) -> float:
        items = self.list(category=category)
        return round(sum(e.amount for e in items), 2)

    def total_by_category(self) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for e in self._expenses.values():
            totals[e.category] = round(totals.get(e.category, 0.0) + e.amount, 2)
        return totals

    def clear(self) -> None:
        """Used only by tests to reset state between test cases."""
        with self._lock:
            self._expenses = {}
            self._next_id = 1
            self._flush()
