# BrowserBuddy

BrowserBuddy is a Chrome extension + FastAPI backend that turns any webpage into a contextual assistant.

You can ask questions like:
- "Summarize this page"
- "Turn this into notes"
- "Find this product cheaper"
- "Find visually similar products"

The extension captures page context (text, images, candidate products, selected/highlighted product hints) and sends it to the backend agent, which routes to tool modules.

---

## Features

- Chrome extension popup chat UI
- Page context capture via content script
- Session-based context reuse (no need to resend full text every turn)
- Agent routing with guardrails for irrelevant prompts
- Product candidate disambiguation workflow
- MCP-style tool modules:
	- `summarize_page`
	- `shopping_search`
	- `image_similarity`
	- `generate_content`

---

## Repository Structure

```text
BrowserBuddy/
├── README.md
├── docs/
│   └── architecture.md
├── extension/
│   ├── manifest.json
│   ├── popup.html
│   ├── popup.tsx
│   ├── background.ts
│   ├── content_script.ts
│   ├── selection_utils.ts
│   └── package.json
└── backend/
		├── main.py
		├── agent.py
		├── candidate_selection.py
		├── context_store.py
		├── llm.py
		├── requirements.txt
		└── tools/
```

---

## Architecture Overview

1. `content_script.ts` extracts active tab context.
2. `popup.tsx` sends prompt (+ session ID and optionally context).
3. `background.ts` forwards requests to backend `POST /agent/query`.
4. `backend/main.py` resolves/stores context and calls `run_agent(...)`.
5. `backend/agent.py` applies guardrails, routes to tools, and returns a response.
6. Popup displays tool output.

Detailed design: `docs/architecture.md`.

---

## Prerequisites

- macOS/Linux (commands below are macOS-friendly)
- Python 3.11+
- Node.js 18+
- Chrome
- (Optional) Redis for persistent session context

---

## Quick Start (End-to-End)

### 1) Clone and enter project

```bash
git clone <your-repo-url>
cd BrowserBuddy
```

### 2) Backend setup

```bash
cd backend
python3 -m venv ../.venv
source ../.venv/bin/activate
python -m pip install -r requirements.txt
```

### 3) (Optional) Start Redis

BrowserBuddy automatically falls back to in-memory storage if Redis is unavailable.

Docker option:
```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

### 4) Start backend API

From project root:
```bash
/Users/sheharyarmeghani/BrowserBuddy/.venv/bin/python -m uvicorn --app-dir /Users/sheharyarmeghani/BrowserBuddy/backend main:app --host 127.0.0.1 --port 8000 --reload
```

Health check:
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/docs

### 5) Extension setup

In a new terminal:
```bash
cd extension
npm install
npm run build
```

### 6) Load extension in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `extension/` folder
5. Pin BrowserBuddy extension

### 7) Use it

1. Open any product/article page
2. Click extension icon
3. Ask a question in popup
4. For shopping/similarity queries, you can select or highlight product text/image before asking

---

## Frontend (Extension) Development

Commands (from `extension/`):

- Build once:
	```bash
	npm run build
	```
- Watch mode:
	```bash
	npm run watch
	```

After changes:
1. Rebuild (or keep watch running)
2. Reload extension in `chrome://extensions`
3. Reopen popup

---

## Backend Configuration

`backend/llm.py` reads env vars from `backend/.env` if present.

Common variables:

- `HF_ENDPOINT` (default set in code)
- `HF_MODEL` (default: `openai/gpt-oss-120b`)
- `HF_API_KEY` (optional)
- `GEMINI_API_KEY` (optional fallback)
- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `LLM_TIMEOUT` (default: `60`)
- `REDIS_URL` (default: `redis://localhost:6379/0`)
- `CONTEXT_TTL_SECONDS` (default: `3600`, set `0` for no TTL)

Example `backend/.env`:

```env
HF_API_KEY=
GEMINI_API_KEY=
LLM_TIMEOUT=60
REDIS_URL=redis://localhost:6379/0
CONTEXT_TTL_SECONDS=3600
```

---

## API Contract (Core)

### `POST /agent/query`

Supports two modes:

1. First request with full context
2. Follow-up requests with `session_id` only

Example (first request):

```json
{
	"prompt": "find this product cheaper",
	"context": {
		"url": "https://example.com/product",
		"title": "Product title",
		"text": "page text...",
		"images": ["https://..."],
		"candidate_products": [{ "image": "https://...", "alt_text": "Product image" }],
		"selected_candidate": { "image": "https://...", "alt_text": "Product image" }
	}
}
```

Example (follow-up):

```json
{
	"prompt": "2",
	"session_id": "<session-id>"
}
```

### `GET /context/{session_id}`

Returns stored context for debugging.

### `GET /tools`

Lists registered tool definitions.

---

## Candidate Selection Behavior

For shopping/similarity flows, backend attempts candidate auto-selection using:

- Explicit selected candidate from extension
- Prompt/candidate matching heuristics
- LLM candidate chooser using page context

If confidence is low, agent asks user to pick from a numbered list.

---

## Troubleshooting

### Extension popup opens but answers fail

- Ensure backend is running at `http://127.0.0.1:8000`
- Check backend terminal for errors

### `Could not import module "main"`

- Use `--app-dir /Users/sheharyarmeghani/BrowserBuddy/backend` in uvicorn command

### Changes not reflected in extension

- Run `npm run build`
- Reload extension in `chrome://extensions`

### Redis not running

- App still works with in-memory context (temporary)
- Start Redis for durable/session-shared context

### LLM returns non-JSON where JSON is expected

- Check backend logs from `browserbuddy.llm`
- Verify model endpoint behavior and token limits
- Use stricter prompts / fallback logic in `llm_json`

---

## Current Status

- Extension + backend integration is live
- Context/session flow implemented
- Tool routing and multi-tool support implemented
- Candidate-selection and disambiguation flow implemented

---

## License

Internal / project-specific unless otherwise specified.
