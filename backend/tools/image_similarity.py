"""
MCP Tool: image_similarity

Finds visually similar images, products, or places given an image URL.

Strategy (waterfall — first success wins):
  1. **SerpApi Google Lens** (optional) — direct visual-match results.
     Requires ``SERPAPI_KEY`` in ``.env``.  Free tier: 100 searches / month.
  2. **Gemini Vision** — download the image, send to Gemini via the shared
     multimodal helper, ask it to describe the image & produce a search
     query, then find matches with DuckDuckGo.
  3. **Text-inference fallback** — use the page title / text and the LLM
     to *guess* what the image contains, then search DuckDuckGo.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from tools import BaseTool, ToolDefinition, ToolParameter, registry
from llm import (
    llm_json,
    llm_chat,
    download_image,
    gemini_vision_json,
    GEMINI_API_KEY,
    LLM_TIMEOUT,
)

_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_env_path)

logger = logging.getLogger("browserbuddy.tools.image_similarity")

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")


# =====================================================================
# Strategy 1 — SerpApi Google Lens
# =====================================================================


async def _serpapi_lens(
    image_url: str,
    max_results: int = 5,
) -> list[dict[str, Any]] | None:
    """Call SerpApi Google Lens.  Returns a list of visual matches or None."""

    if not SERPAPI_KEY:
        return None

    params: dict[str, Any] = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": SERPAPI_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            resp.raise_for_status()
            data = resp.json()

        visual_matches = data.get("visual_matches", [])
        results: list[dict[str, Any]] = []
        for match in visual_matches[:max_results]:
            results.append({
                "title": match.get("title", "Visual match"),
                "url": match.get("link", ""),
                "image_url": match.get("thumbnail", ""),
                "snippet": match.get("snippet", match.get("source", "")),
                "price": (
                    match.get("price", {}).get("extracted_value", "")
                    if isinstance(match.get("price"), dict)
                    else str(match.get("price", ""))
                ),
                "source": "google_lens",
            })

        if results:
            logger.info("SerpApi Google Lens returned %d visual matches", len(results))
            return results

    except Exception as exc:
        logger.warning("SerpApi Google Lens failed: %s", exc)

    return None


# =====================================================================
# Strategy 2 — Gemini Vision (describe → DDG search)
# =====================================================================

_VISION_PROMPT = """\
Look at this image carefully.  Return ONLY a JSON object (no markdown, no explanation):
{
  "item": "<what the image shows — e.g. avocado toast, red sneakers>",
  "description": "<1-sentence visual description>",
  "search_query": "<web search query to find this exact item for sale or on a menu — use the item name, not a generic category>"
}
Important: the search_query should focus on the PRIMARY item name (e.g. "avocado toast" not "soft-boiled egg"), and be suitable for a shopping or restaurant search engine.
"""


async def _ddg_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Run a DuckDuckGo web search and return simplified results."""
    try:
        from ddgs import DDGS  # type: ignore[import-untyped]
        ddgs = DDGS()
        raw = ddgs.text(query, max_results=max_results + 2)
        results: list[dict[str, Any]] = []
        for r in raw:
            title = r.get("title", "")
            if not title:
                continue
            results.append({
                "title": title,
                "url": r.get("href", r.get("link", "")),
                "snippet": r.get("body", r.get("snippet", "")),
                "source": "duckduckgo",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as exc:
        logger.warning("DDG search failed: %s", exc)
        return []


async def _gemini_vision_pipeline(
    image_url: str,
    user_query: str,
    max_results: int = 5,
) -> tuple[list[dict[str, Any]], str] | None:
    """Gemini Vision → DDG pipeline.  Returns (results, identified_item) or None."""

    downloaded = await download_image(image_url)
    if downloaded is None:
        return None

    image_bytes, mime = downloaded
    image_parts = [{
        "mime_type": mime,
        "data": base64.b64encode(image_bytes).decode(),
    }]

    description = await gemini_vision_json(
        _VISION_PROMPT,
        image_parts,
        max_tokens=2048,
        temperature=0.1,
    )
    if description is None or not isinstance(description, dict):
        return None

    item = description.get("item", "")
    logger.info("Gemini Vision identified: %s", item)

    # Build search query from user intent + identified item
    lower_q = user_query.lower()
    if "near me" in lower_q or "nearby" in lower_q:
        search_query = f"{item} restaurant near me"
    elif "near" in lower_q:
        search_query = f"{item} near me"
    elif "cheap" in lower_q or "price" in lower_q or "buy" in lower_q:
        search_query = f"{item} buy price"
    elif "similar" in lower_q or "like this" in lower_q:
        search_query = f"{item} similar alternatives"
    else:
        search_query = description.get("search_query", item)

    logger.info("Vision pipeline: item=%r, search_query=%r", item, search_query)
    results = await _ddg_search(search_query, max_results)
    return (results, item) if results else None


# =====================================================================
# Strategy 3 — Text-inference fallback (page context → LLM → DDG)
# =====================================================================

_INFER_PROMPT = """\
You are a helpful assistant.  The user is viewing a webpage and looking
at an image on that page.  Based on the page title and text, infer what
the image most likely depicts.

You MUST reply with ONLY a raw JSON object — no explanation, no markdown:
{"item": "<what the image shows>", "search_query": "<web search query to find this item>"}
"""


async def _text_inference_pipeline(
    image_url: str,
    user_query: str,
    page_text: str,
    page_title: str,
    max_results: int = 5,
) -> tuple[list[dict[str, Any]], str] | None:
    """Use the LLM (text-only) to guess what the image is, then DDG search."""

    messages = [
        {"role": "system", "content": _INFER_PROMPT},
        {
            "role": "user",
            "content": (
                f"User's request: {user_query}\n"
                f"Page title: {page_title}\n"
                f"Image URL: {image_url}\n"
                f"Page text (first 1500 chars): {page_text[:1500]}"
            ),
        },
    ]

    import re as _re

    parsed = await llm_json(messages, max_tokens=200, temperature=0.1)

    if not isinstance(parsed, dict) or "item" not in parsed:
        raw = await llm_chat(messages, max_tokens=300, temperature=0.1)
        if raw:
            json_match = _re.search(r"\{[^}]+\}", raw)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except json.JSONDecodeError:
                    parsed = None

        if not isinstance(parsed, dict) or "item" not in parsed:
            if page_title or page_text:
                item_guess = page_title or page_text[:100]
                parsed = {"item": item_guess, "search_query": f"{item_guess} buy"}
                logger.info("Text inference fell back to page title: %s", item_guess)
            else:
                return None

    item = parsed.get("item", "")
    search_query = parsed.get("search_query", item)

    lower_q = user_query.lower()
    if "near me" in lower_q or "nearby" in lower_q:
        search_query = f"{item} restaurant near me"
    elif "near" in lower_q:
        search_query = f"{item} near me"
    elif "cheap" in lower_q or "price" in lower_q or "buy" in lower_q:
        search_query = f"{item} buy price"

    results = await _ddg_search(search_query, max_results)
    return (results, item) if results else None


# =====================================================================
# MCP Tool class
# =====================================================================


class ImageSimilarityTool(BaseTool):
    """Finds visually similar images, products, or nearby places."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="image_similarity",
            description=(
                "Finds visually similar images, products, or places given a "
                "source image URL.  Supports queries like 'find places selling "
                "this near me' or 'find similar items'."
            ),
            parameters=[
                ToolParameter(
                    name="image_url",
                    type="string",
                    description="URL of the source image to find similar matches for.",
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description=(
                        "The user's intent in natural language "
                        "(e.g. 'find places selling this near me')."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="page_text",
                    type="string",
                    description="Text from the webpage for context (used as fallback).",
                    required=False,
                ),
                ToolParameter(
                    name="page_title",
                    type="string",
                    description="Title of the webpage (used as fallback).",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of similar results to return (default 5).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        image_url: str = kwargs.get("image_url", "")
        user_query: str = kwargs.get("query", "find similar items")
        page_text: str = kwargs.get("page_text", "")
        page_title: str = kwargs.get("page_title", "")
        max_results: int = kwargs.get("max_results", 5)

        if not image_url or not image_url.strip():
            return {"error": "No image URL provided."}

        # --- Strategy 1: SerpApi Google Lens ---
        lens_results = await _serpapi_lens(image_url, max_results)
        if lens_results:
            return {
                "tool": "image_similarity",
                "source_image": image_url,
                "results": lens_results,
                "count": len(lens_results),
                "method": "google_lens",
                "identified_item": "(visual match via Google Lens)",
            }

        # --- Strategy 2: Gemini Vision → DDG ---
        vision_result = await _gemini_vision_pipeline(
            image_url, user_query, max_results,
        )
        if vision_result is not None:
            results, item = vision_result
            return {
                "tool": "image_similarity",
                "source_image": image_url,
                "identified_item": item,
                "results": results,
                "count": len(results),
                "method": "gemini_vision",
            }

        # --- Strategy 3: Text inference → DDG ---
        text_result = await _text_inference_pipeline(
            image_url, user_query, page_text, page_title, max_results,
        )
        if text_result is not None:
            results, item = text_result
            return {
                "tool": "image_similarity",
                "source_image": image_url,
                "identified_item": item,
                "results": results,
                "count": len(results),
                "method": "text_inference",
                "note": (
                    "Image could not be analysed directly.  Results are based "
                    "on the page context."
                ),
            }

        # --- All strategies failed ---
        return {
            "tool": "image_similarity",
            "source_image": image_url,
            "results": [],
            "count": 0,
            "method": "none",
            "error": (
                "Could not analyse the image.  Make sure the image URL is "
                "publicly accessible and try again."
            ),
        }


# Auto-register on import
registry.register(ImageSimilarityTool())
