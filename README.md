# 💸 Smart Expense Tracker

A personal expense tracking app with a **REST API backend** (Python + FastAPI) and a **dark-theme web UI** — all in one repo, no database required.

---

## 📸 Screenshots

### Web UI
![Smart Expense Tracker Web UI](screenshots/ui.png)

### Swagger API Docs
![Swagger API Docs](screenshots/swagger.png)

---

## ✨ Features

| Feature | Details |
|---|---|
| Add an expense | `title`, `amount`, `category`, `date` — server assigns `id` |
| View all expenses | Sorted by id |
| Filter by category | Case-insensitive, `?category=Food` |
| **Search by title** *(bonus)* | Substring match, `?search=coffee` |
| Totals & per-category breakdown | `GET /expenses/totals/summary` |
| Delete an expense | `DELETE /expenses/{id}` |
| **Swagger / OpenAPI docs** *(bonus)* | Auto-generated at `/docs` |
| **Web UI** *(bonus)* | Single-page app — no build step, served from `/` |
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
    main.py        # FastAPI app + routes
    models.py      # Pydantic request/response models
    storage.py     # In-memory store, mirrored to JSON file
  tests/
    __init__.py
    test_api.py    # pytest test suite (20 tests)
  frontend/
    index.html     # Vanilla HTML/CSS/JS single-page UI
  data/
    expenses.json  # Auto-created at runtime
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
git clone https://github.com/Prasadreddy6363/Smart-Expense-Tracker.git
cd Smart-Expense-Tracker
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
| `http://127.0.0.1:8000` | **Web UI** |
| `http://127.0.0.1:8000/docs` | Swagger / OpenAPI interactive docs |
| `http://127.0.0.1:8000/redoc` | ReDoc docs |

---

## 🧪 Run Tests

```bash
pytest
```

All 20 tests are fully isolated (autouse fixture resets the store between each test).

---

## 🔌 API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/expenses` | Add an expense |
| `GET` | `/expenses` | List all (supports `?category=` and `?search=`) |
| `GET` | `/expenses/{id}` | Get a single expense |
| `DELETE` | `/expenses/{id}` | Delete an expense |
| `GET` | `/expenses/totals/summary` | Overall total + per-category totals |

### Example: add an expense

```bash
curl -X POST http://127.0.0.1:8000/expenses \
  -H "Content-Type: application/json" \
  -d '{"title": "Groceries", "amount": 520.00, "category": "Food", "date": "2026-07-31"}'
```

### Example: filter by category

```bash
curl "http://127.0.0.1:8000/expenses?category=Food"
```

### Example: search by title keyword

```bash
curl "http://127.0.0.1:8000/expenses?search=coffee"
```

### Example: get totals

```bash
curl http://127.0.0.1:8000/expenses/totals/summary
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

**How it works:** `POST /assistant/chat` -> `src/assistant.py` sends the message, tool schemas and today's date to Ollama -> executes returned tool calls -> sends results back -> returns a short reply plus the tools used.

**Safety:** LLM arguments go through the same Pydantic validation as the REST API (amount > 0, ISO date). Totals are never calculated by the model. Unknown tools and bad arguments return an error to the model instead of crashing.

```
ollama pull llama3.2 && ollama serve     # then: uvicorn src.main:app --reload
```
Env vars: `OLLAMA_HOST` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `llama3.2`). Tests use a fake LLM, so `pytest` needs no model.

**Known limitations:** small local models can pick a wrong category or date; single-turn only (no chat memory); no delete tool by design.

---

## 🏗 Design Notes

- **Storage** — in-memory `dict` keyed by id, flushed to `data/expenses.json` on every write. A `threading.Lock` prevents races within a single process.
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
