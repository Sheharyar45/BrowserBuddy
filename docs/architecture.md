# BrowserBuddy Architecture (MVP)

## 1) Product Concept

Browser extension + backend agent system that uses webpage context to complete user tasks with multiple tools.

### Core user loop

1. User opens any webpage.
2. Extension captures context (text, images, metadata).
3. User asks a task in popup chat.
4. Backend agent selects the right tool(s).
5. Response returns to popup.

---

## 2) High-Level System

Chrome Extension
├── Popup UI (chat)
├── Content Script (page extraction)
└── Background Worker (API bridge)

FastAPI Backend
├── `/agent/query` endpoint
├── Agent Controller
├── Context Store (in-memory for hackathon)
└── Tool modules
   ├── summarize_page
   ├── image_similarity
   ├── shopping_search
   └── generate_content

---

## 3) Request Flow

1. Popup asks content script for current page context.
2. Popup sends `{ prompt, context }` to background.
3. Background posts payload to backend `/agent/query`.
4. Backend runs `run_agent(prompt, context)`.
5. Agent routes to one or more tools.
6. Tool result is returned to popup.

---

## 4) Context Contract (MVP)

```json
{
  "url": "https://example.com/page",
  "title": "Page Title",
  "text": "trimmed page text",
  "images": ["https://.../img1.jpg", "https://.../img2.jpg"]
}
```

---

## 5) Tool Definitions (MVP)

### Tool: `summarize_page`
- Input: `page_text`
- Output: `summary`, `key_points`

### Tool: `image_similarity`
- Input: `image_url`
- Output: similar products/images

### Tool: `shopping_search`
- Input: product/query text
- Output: `title`, `price`, `url`

### Tool: `generate_content`
- Input: `task`, `page_text`
- Output: generated text

---

## 6) Agent Routing Logic (initial)

- If prompt contains summarize intent → `summarize_page`
- If prompt contains similar/find alike intent → `image_similarity`
- If prompt contains cheaper/price intent → `shopping_search`
- Else → `generate_content`

This can later be replaced with true LLM tool-calling.

---

## 7) Non-Goals for MVP

- Persistent database
- Full auth/user accounts
- Production-scale crawling/indexing
- Complex workflow automation UI

---

## 8) Next Build Phase

1. Add backend folder + FastAPI app
2. Implement `/agent/query` + placeholder tools
3. Connect extension background fetch
4. Test end-to-end with two demo scenarios
