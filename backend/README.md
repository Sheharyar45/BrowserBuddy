# Backend (FastAPI)

This backend now supports the first MVP requirement: reliably receiving and storing active tab context (text + images) from the extension.

## Implemented

- `POST /agent/query`
  - Accepts: `prompt`, `context`
  - `context` includes: `url`, `title`, `text`, `images`
  - Validates context is not empty
  - Stores context in memory by `session_id`
  - Returns context receipt summary (`text_chars`, `image_count`, `first_image`)

- `GET /context/{session_id}`
  - Returns saved context for inspection/debugging

- `GET /health`
  - Basic health check

## Files

- `main.py` — API models + endpoints
- `context_store.py` — in-memory session context store
- `agent.py` — temporary agent stub
- `requirements.txt` — backend dependencies

## Run Server in VS Code Terminal

Use these steps from a VS Code integrated terminal.

### 1) Open backend folder

- In terminal, go to the backend directory:
  - `cd /Users/sheharyarmeghani/BrowserBuddy/backend`

### 2) Create and activate virtual environment

- Create local venv (from backend folder):
  - `python3 -m venv /Users/sheharyarmeghani/BrowserBuddy/.venv`
- Activate it (macOS/Linux):
  - `source /Users/sheharyarmeghani/BrowserBuddy/.venv/bin/activate`

### 3) Install dependencies

- Install from requirements:
  - `python -m pip install -r requirements.txt`

### 4) Start Redis (required)

This backend stores context in Redis (not in memory).

Option A — Docker:

- `docker run --rm -p 6379:6379 redis:7-alpine`

Option B — Homebrew (macOS):

- `brew install redis`
- `brew services start redis`

Environment variables (optional):

- `REDIS_URL` (default: `redis://localhost:6379/0`)
- `CONTEXT_TTL_SECONDS` (default: `3600`, set to `0` for no TTL)

### 5) Start FastAPI server

- Recommended command (works reliably from any current directory):
  - `/Users/sheharyarmeghani/BrowserBuddy/.venv/bin/python -m uvicorn --app-dir /Users/sheharyarmeghani/BrowserBuddy/backend main:app --host 127.0.0.1 --port 8000 --reload`

Server should show:

- `Uvicorn running on http://127.0.0.1:8000`

### 6) Quick verify

- Health check: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

### Common issue

- If you see `Could not import module "main"`, use the same command above with `--app-dir` and make sure path points to the `backend` folder.

## Expected Request Body

```json
{
  "prompt": "Find similar sweaters cheaper",
  "context": {
    "url": "https://shop.example.com/sweater/123",
    "title": "Wool Knit Sweater",
    "text": "Product details and description...",
    "images": ["https://.../image1.jpg", "https://.../image2.jpg"]
  }
}
```
