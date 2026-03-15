import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import run_agent
from context_store import get_context, save_context
from tools import get_registry


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("browserbuddy.backend")


def _apply_context_patch(base: dict, patch: dict) -> dict:
    updated = dict(base)
    for key, value in patch.items():
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = value
    return updated


class PageContext(BaseModel):
    url: str
    title: str
    text: str = Field(default="", max_length=20000)
    images: list[str] = Field(default_factory=list)
    candidate_products: list[dict[str, str]] = Field(default_factory=list)
    selected_candidate: dict[str, str] | None = None


class AgentQueryRequest(BaseModel):
    prompt: str = Field(min_length=1)
    context: PageContext | None = None
    session_id: str | None = None


app = FastAPI(title="BrowserBuddy Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/query")
async def query_agent(data: AgentQueryRequest) -> dict:
    context_payload: dict | None = None
    context_source = "stored"

    if data.context is not None:
        has_text = bool(data.context.text.strip())
        has_images = len(data.context.images) > 0

        if has_text or has_images:
            session_id = data.session_id or str(uuid4())
            context_payload = data.context.model_dump()
            save_context(session_id, context_payload)
            context_source = "request"
        else:
            # Treat an empty context object as if no context was provided.
            session_id = data.session_id
    else:
        session_id = data.session_id

    if context_payload is None:
        if not session_id:
            raise HTTPException(
                status_code=400,
                detail="Missing context. Provide page context on the first request, or provide session_id to reuse stored context.",
            )

        stored_context = get_context(session_id)
        if stored_context is None:
            raise HTTPException(status_code=404, detail="Session context not found")
        context_payload = stored_context
    else:
        stored_context = get_context(session_id) or {}

    logger.info(
        "Context ready for session=%s source=%s title=%s text_chars=%s image_count=%s",
        session_id,
        context_source,
        context_payload.get("title"),
        len(stored_context.get("text") or ""),
        len(stored_context.get("images") or []),
    )

    agent_result = await run_agent(data.prompt, context_payload)

    context_patch = agent_result.get("context_patch")
    if isinstance(context_patch, dict):
        context_payload = _apply_context_patch(context_payload, context_patch)
        save_context(session_id, context_payload)
        stored_context = context_payload

    return {
        "session_id": session_id,
        "response": agent_result.get("response", ""),
        "tools_used": agent_result.get("tools_used", []),
        "tool_results": agent_result.get("tool_results", []),
        "routing_method": agent_result.get("routing_method", "unknown"),
        "context_source": context_source,
        "received_context": {
            "url": context_payload.get("url"),
            "title": context_payload.get("title"),
            "text_chars": len(context_payload.get("text") or ""),
            "text_preview": (context_payload.get("text") or "")[:200],
            "image_count": len(context_payload.get("images") or []),
            "images_preview": (context_payload.get("images") or [])[:3],
            "first_image": (context_payload.get("images") or [None])[0],
            "candidate_product_count": len(context_payload.get("candidate_products") or []),
            "selected_candidate": context_payload.get("selected_candidate"),
        },
        "stored_context_check": {
            "has_text": bool((stored_context.get("text") or "").strip()),
            "stored_text_chars": len(stored_context.get("text") or ""),
            "has_images": len(stored_context.get("images") or []) > 0,
            "stored_image_count": len(stored_context.get("images") or []),
            "stored_candidate_product_count": len(stored_context.get("candidate_products") or []),
        },
    }


@app.get("/context/{session_id}")
async def read_context(session_id: str) -> dict:
    context = get_context(session_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Session context not found")

    logger.info(
        "Fetched context session=%s text_chars=%s image_count=%s",
        session_id,
        len(context.get("text") or ""),
        len(context.get("images") or []),
    )

    return {"session_id": session_id, "context": context}


@app.get("/tools")
async def list_tools() -> dict:
    """List all registered MCP tools and their definitions."""
    reg = get_registry()
    return {
        "tools": [t.to_dict() for t in reg.list_tools()],
        "count": len(reg.list_tools()),
    }
