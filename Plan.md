1️⃣ Final Product Concept

Contextual Web Agent Extension

A browser extension that:

Captures webpage context (text + images)

Sends it to a FastAPI backend

Backend runs an LLM agent with MCP tools

Agent chooses tools to complete tasks

Example:

User on sweater page → asks:

“Find similar sweaters cheaper”

Agent workflow:

Extract sweater image

Generate image embedding

Search for similar products

Query shopping results

Filter cheaper items

Return results

This is real multi-tool agent behavior.

2️⃣ System Architecture
Chrome Extension
│
├── Popup UI (chat)
│
├── Content Script
│   extracts:
│   - page text
│   - images
│   - metadata
│
▼
FastAPI Backend
│
├── Context Store
│
├── Agent Controller
│
├── MCP Tool Server
│
└── Tools
    ├── summarize_page
    ├── image_similarity
    ├── shopping_search
    └── generate_content
3️⃣ Core Features (MVP)

Only implement 4 tools.

Tool 1 — Page Summarization

User prompt:

Summarize this article

Tool input:

page_text

Output:

summary
key points
Tool 2 — Image Similarity Search

User prompt:

Find similar sweaters

Tool input:

image_url

Pipeline:

image → embedding → vector similarity

Output:

similar images/products
Tool 3 — Shopping Search

User prompt:

Find cheaper options

Tool input:

product name

Search:

Amazon

H&M

Zara

Return:

title
price
link
Tool 4 — Content Generator

User prompt:

Turn this article into study notes
Write email summarizing this page

Input:

page_text
task

Output:

generated content
4️⃣ Extension Implementation
Folder
extension/
Structure
extension
│
├── manifest.json
├── popup.html
├── popup.tsx
├── content_script.ts
├── background.ts
Manifest (simplified)
{
  "manifest_version": 3,
  "name": "Web Agent",
  "version": "1.0",
  "permissions": ["activeTab", "scripting"],
  "host_permissions": ["<all_urls>"],
  "action": {
    "default_popup": "popup.html"
  },
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content_script.js"]
    }
  ]
}
5️⃣ Content Script

Extract page context.

function extractPageContext() {
  const text = document.body.innerText;

  const images = [...document.querySelectorAll("img")]
      .map(img => img.src)
      .slice(0,5);

  return {
    url: window.location.href,
    title: document.title,
    text: text.slice(0,10000),
    images
  };
}

Send to extension:

chrome.runtime.sendMessage(context)
6️⃣ Popup Chat UI

Basic UI:

-------------------------
Web Agent

[ chat window ]

> user input

[ send ]
-------------------------

When user submits:

POST /agent/query

Payload:

{
 "prompt": "Find similar sweaters cheaper",
 "context": {...}
}
7️⃣ FastAPI Backend

Folder:

backend/

Structure:

backend
│
├── main.py
├── agent.py
├── context_store.py
│
├── tools
│   ├── summarize.py
│   ├── image_similarity.py
│   ├── shopping_search.py
│   └── generator.py
8️⃣ FastAPI Server
from fastapi import FastAPI
from agent import run_agent

app = FastAPI()

@app.post("/agent/query")
async def query_agent(data: dict):
    prompt = data["prompt"]
    context = data["context"]

    result = await run_agent(prompt, context)

    return {"response": result}
9️⃣ Context Store

Temporary memory.

context_store = {}

def save_context(session_id, context):
    context_store[session_id] = context

def get_context(session_id):
    return context_store.get(session_id)

Hackathon → in-memory is fine.

🔟 Agent Controller

Simple tool-calling agent.

async def run_agent(prompt, context):

    if "summarize" in prompt:
        return summarize(context["text"])

    if "similar" in prompt:
        return image_similarity(context["images"][0])

    if "cheaper" in prompt:
        return shopping_search(context["title"])

    return generate_content(prompt, context["text"])

Later you can replace this with LLM tool calling.

1️⃣1️⃣ Image Similarity Tool

Use CLIP embeddings.

Pipeline:

image → embedding → similarity search

Example:

from PIL import Image
import requests

def image_similarity(image_url):

    img = Image.open(requests.get(image_url, stream=True).raw)

    embedding = model.encode_image(img)

    results = vector_db.search(embedding)

    return results
1️⃣2️⃣ Shopping Search Tool

Simplest hackathon solution:

Use Google Shopping scraping.

def shopping_search(product):

    results = serp_api.search(product)

    return results

Return:

title
price
url
1️⃣3️⃣ Generator Tool
def generate_content(task, text):

    prompt = f"""
    Task: {task}

    Context:
    {text}
    """

    response = llm(prompt)

    return response
1️⃣4️⃣ MCP Tool Definitions

Each tool becomes an MCP function.

Example:

{
 "name": "summarize_page",
 "description": "Summarizes webpage content",
 "parameters": {
   "page_text": "string"
 }
}

Agent receives:

tools
context
user_prompt

Then selects tool.

1️⃣5️⃣ Hackathon Demo Script

This is crucial.

Demo 1

Open blog.

Ask:

Summarize this article

Agent summarizes.

Demo 2

Open clothing item page.

Ask:

Find similar sweaters cheaper

Agent returns alternatives.

Demo 3

Highlight paragraph.

Ask:

Turn this into study notes
1️⃣6️⃣ Timeline
Day 1

Build:

extension UI

content script

FastAPI server

summarization tool

You already have a working project.

Day 2

Add:

image similarity

shopping search

agent orchestration

1️⃣7️⃣ Stretch Features (if time)

These make it very impressive:

🔥 Visual Product Matching
image → embedding → product database
🔥 Highlight + Ask

User selects text → right click:

Ask agent
🔥 Workflow Builder

User says:

Whenever I visit product pages
find cheaper alternatives

Agent saves workflow.
