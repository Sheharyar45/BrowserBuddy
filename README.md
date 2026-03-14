# BrowserBuddy

A contextual web-agent project with:

- A Chrome extension that captures page context (text, images, metadata)
- A FastAPI backend that runs an agent controller
- MCP-style tools for summarization, image similarity, shopping search, and content generation

## MVP Goal

Given the active webpage and a user prompt, route the task to the right tool and return a useful response in the extension chat.

Example: on a sweater product page, user asks **"Find similar sweaters cheaper"** and the system combines image similarity + shopping search.

## Planned Repository Structure

.
├── README.md
├── docs/
│   └── architecture.md
├── extension/
│   ├── manifest.json
│   ├── popup.html
│   ├── popup.tsx
│   ├── content_script.ts
│   └── background.ts
└── backend/
	└── (to be created)

## Current Status

✅ Documentation + extension frontend skeleton created  
🔜 Backend scaffolding and tool wiring

## Extension Flow (Skeleton)

1. `content_script.ts` extracts page context.
2. `popup.tsx` sends prompt + context request.
3. `background.ts` calls backend endpoint: `POST /agent/query`.
4. Popup renders the returned response.

## Notes

- The extension files are currently scaffold files for MVP wiring.
- TypeScript/TSX build setup can be added next (Vite/Plasmo or custom build).

## Next Steps

1. Build FastAPI backend skeleton (`main.py`, `agent.py`, tools)
2. Implement `POST /agent/query`
3. Connect extension fetch flow to live backend
4. Add tool-specific logic and demo data

## Extension Frontend (Run Locally)

From [extension/package.json](extension/package.json):

1. Install deps
2. Build extension scripts
3. Preview popup UI

Preview entry: [extension/popup.html](extension/popup.html)

Generated assets used by manifest:

- [extension/popup.js](extension/popup.js)
- [extension/content_script.js](extension/content_script.js)
- [extension/background.js](extension/background.js)

## Run Popup in Chrome (Exact Steps)

Use this exact flow in VS Code + Chrome.

### 1) Build extension files

From the project root:

1. `cd /Users/sheharyarmeghani/BrowserBuddy/extension`
2. `npm install`
3. `npm run build`

This generates the files Chrome loads:

- [extension/popup.js](extension/popup.js)
- [extension/content_script.js](extension/content_script.js)
- [extension/background.js](extension/background.js)

### 2) Load extension in Chrome

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top-right)
3. Click **Load unpacked**
4. Select folder: [extension](extension)
5. Pin **BrowserBuddy Web Agent** from the extensions menu

### 3) Open popup

1. Visit any website tab (for page context)
2. Click BrowserBuddy icon in Chrome toolbar
3. Popup should open from [extension/popup.html](extension/popup.html)

### 4) Rebuild after code changes

Whenever you change [extension/popup.tsx](extension/popup.tsx), [extension/background.ts](extension/background.ts), or [extension/content_script.ts](extension/content_script.ts):

1. Run `npm run build` again in [extension](extension)
2. Go to `chrome://extensions`
3. Click **Reload** on BrowserBuddy extension card
4. Close and reopen popup

### 5) Backend requirement for live responses

Popup opens without backend, but agent calls require backend on `http://127.0.0.1:8000`.

Start backend with:

`/Users/sheharyarmeghani/BrowserBuddy/.venv/bin/python -m uvicorn --app-dir /Users/sheharyarmeghani/BrowserBuddy/backend main:app --host 127.0.0.1 --port 8000 --reload`
