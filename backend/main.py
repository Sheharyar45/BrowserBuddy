import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import run_agent
from context_store import get_context, save_context


logger = logging.getLogger("browserbuddy.backend")


class PageContext(BaseModel):
    url: str
    title: str
    text: str = Field(default="", max_length=20000)
    images: list[str] = Field(default_factory=list)


class AgentQueryRequest(BaseModel):
    prompt: str = Field(min_length=1)
    context: PageContext
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
    has_text = bool(data.context.text.strip())
    has_images = len(data.context.images) > 0

    if not has_text and not has_images:
        raise HTTPException(
            status_code=400,
            detail="Context is empty. Expected page text and/or image URLs.",
        )

    session_id = data.session_id or str(uuid4())
    context_payload = data.context.model_dump()
    try:
        save_context(session_id, context_payload)
        stored_context = get_context(session_id) or {}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info(
        "Stored context for session=%s title=%s text_chars=%s image_count=%s",
        session_id,
        data.context.title,
        len(stored_context.get("text") or ""),
        len(stored_context.get("images") or []),
    )

    result = await run_agent(data.prompt, context_payload)

    return {
        "session_id": session_id,
        "received_context": {
            "url": data.context.url,
            "title": data.context.title,
            "text_chars": len(data.context.text),
            "text_preview": data.context.text[:200],
            "image_count": len(data.context.images),
            "images_preview": data.context.images[:3],
            "first_image": data.context.images[0] if data.context.images else None,
        },
        "stored_context_check": {
            "has_text": bool((stored_context.get("text") or "").strip()),
            "stored_text_chars": len(stored_context.get("text") or ""),
            "has_images": len(stored_context.get("images") or []) > 0,
            "stored_image_count": len(stored_context.get("images") or []),
        },
        "response": result,
    }


@app.get("/context/{session_id}")
async def read_context(session_id: str) -> dict:
    try:
        context = get_context(session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if context is None:
        raise HTTPException(status_code=404, detail="Session context not found")

    logger.info(
        "Fetched context session=%s text_chars=%s image_count=%s",
        session_id,
        len(context.get("text") or ""),
        len(context.get("images") or []),
    )

    return {"session_id": session_id, "context": context}
