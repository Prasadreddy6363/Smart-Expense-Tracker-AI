# 💸 Smart Expense Tracker

A personal expense tracking app with a **REST API backend** (Python + FastAPI) and a **dark-theme web UI** — all in one repo, no database required.

**Multi-user:** each user gets a fully isolated expense store. Just enter a username on the login screen — no password needed for local use.

---

## 📸 Screenshots

### Login Screen
![Login Screen](screenshots/login.png)

### Web UI
![Smart Expense Tracker Web UI](screenshots/ui.png)

### Swagger API Docs
![Swagger API Docs](screenshots/swagger.png)

---

## ✨ Features

| Feature | Details |
|---|---|
| **Multi-user support** | Each username gets an isolated store — `data/expenses_<username>.json` |
| Add an expense | `title`, `amount`, `category`, `date` — server assigns `id` |
| View all expenses | Sorted by id |
| Filter by category | Case-insensitive, `?category=Food` |
| **Search by title** | Substring match, `?search=coffee` |
| Totals & per-category breakdown | `GET /expenses/totals/summary` |
| Delete an expense | `DELETE /expenses/{id}` |
| **List all users** | `GET /users` — shows who has data on disk |
| **Swagger / OpenAPI docs** | Auto-generated at `/docs` |
| **Web UI** | Single-page app — no build step, served from `/` |
| **Indian Rupee (₹) formatting** | All amounts displayed in INR with Indian number grouping |

---

## 🗂 Project Structure

```
Smart-Expense-Tracker/
  README.md
  AI_NOTES.md
  requirements.txt
  src/
    __init__.py
    main.py        # FastAPI app + routes (multi-user via X-Username header)
    models.py      # Pydantic request/response models
    storage.py     # Per-user in-memory store, mirrored to JSON file
  tests/
    __init__.py
    test_api.py    # pytest test suite (31 tests)
    test_assistant.py
  frontend/
    index.html     # Vanilla HTML/CSS/JS single-page UI with login screen
  data/
    expenses_<username>.json  # Auto-created per user at runtime
  screenshots/
    ui.png
    swagger.png
```

---

## ⚙️ Requirements

- **Python 3.10+**

---

## 🚀 Install & Run

### 1. Clone the repo

```bash
git clone https://github.com/Prasadreddy6363/Smart-Expense-Tracker-AI.git
cd Smart-Expense-Tracker-AI
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Start the server

```bash
uvicorn src.main:app --reload
```

| URL | Description |
|---|---|
| `http://127.0.0.1:8000` | **Web UI** (login screen → your expenses) |
| `http://127.0.0.1:8000/docs` | Swagger / OpenAPI interactive docs |
| `http://127.0.0.1:8000/redoc` | ReDoc docs |

---

## 👤 Multi-User Usage

### Web UI
Open `http://127.0.0.1:8000`, enter any username (e.g. `alice`), and start tracking. Each user's data is completely isolated. Sign out and enter a different username to switch users.

### API / curl
Pass the `X-Username` header on every request:

```bash
# Add an expense for alice
curl -X POST http://127.0.0.1:8000/expenses \
  -H "Content-Type: application/json" \
  -H "X-Username: alice" \
  -d '{"title": "Groceries", "amount": 520.00, "category": "Food", "date": "2026-10-01"}'

# List alice's expenses
curl -H "X-Username: alice" http://127.0.0.1:8000/expenses

# List all users who have data
curl http://127.0.0.1:8000/users
```

Username rules: 1–32 characters, letters / digits / `_` / `-` only. Case-insensitive (`Alice` and `alice` are the same user).

---

## 🧪 Run Tests

```bash
pytest
```

31 tests, all fully isolated (autouse fixture resets the per-user store between each test). No Ollama model required.

---

## 🔌 API Reference

| Method | Path | Header | Description |
|---|---|---|---|
| `GET` | `/users` | — | List all usernames with data |
| `POST` | `/expenses` | `X-Username` | Add an expense |
| `GET` | `/expenses` | `X-Username` | List all (supports `?category=` and `?search=`) |
| `GET` | `/expenses/{id}` | `X-Username` | Get a single expense |
| `DELETE` | `/expenses/{id}` | `X-Username` | Delete an expense |
| `GET` | `/expenses/totals/summary` | `X-Username` | Overall total + per-category totals |
| `POST` | `/assistant/chat` | `X-Username` | AI assistant (natural language) |

### Example: add an expense

```bash
curl -X POST http://127.0.0.1:8000/expenses \
  -H "Content-Type: application/json" \
  -H "X-Username: prasad" \
  -d '{"title": "Groceries", "amount": 520.00, "category": "Food", "date": "2026-07-31"}'
```

### Example: filter by category

```bash
curl -H "X-Username: prasad" "http://127.0.0.1:8000/expenses?category=Food"
```

### Example: get totals

```bash
curl -H "X-Username: prasad" http://127.0.0.1:8000/expenses/totals/summary
# {"overall_total": 720.50, "by_category": {"Food": 520.0, "Transport": 200.5}}
```

---

## 🤖 AI Assistant (LLM tool calling)

Type expenses in plain English and ask questions about your spending. A local LLM (Ollama, `llama3.2`) picks a **tool** and its arguments; normal Python code validates and runs it.

| You type | Tool called | Result |
| --- | --- | --- |
| `I spent 450 on dinner yesterday` | `add_expense` | Saved as Food, dated yesterday |
| `How much did I spend on food this month?` | `get_total` | Sum computed in code |
| `Show my last 5 transport expenses` | `list_expenses` | Filtered list |

```bash
ollama pull llama3.2 && ollama serve     # then: uvicorn src.main:app --reload
```

Env vars: `OLLAMA_HOST` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `llama3.2`). Tests use a fake LLM, so `pytest` needs no model.

---

## 🏗 Design Notes

- **Multi-user isolation** — `X-Username` header on every request. Each username maps to a separate `ExpenseStore` instance backed by `data/expenses_<username>.json`. Username is validated (alphanumeric + `_-`, max 32 chars) to prevent path-traversal attacks.
- **Storage** — in-memory `dict` keyed by id, flushed to JSON on every write. Each store has its own `threading.Lock`.
- **Category filter & search** are both case-insensitive.
- **Route ordering** — `/expenses/totals/summary` is declared before `/expenses/{id}` so FastAPI doesn't misparse `"totals"` as an integer id.
- **Validation** — Pydantic: amount > 0, title/category non-blank, date is valid ISO 8601.
- **Frontend** — pure vanilla HTML/CSS/JS, served by FastAPI itself. No npm, no build step.

---

## 📝 AI Notes

See [`AI_NOTES.md`](AI_NOTES.md) for a full breakdown of what was AI-generated, what was manually written/validated, and which AI suggestions were rejected and why.

---

## 📄 License

MIT
