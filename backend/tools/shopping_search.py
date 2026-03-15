"""
MCP Tool: shopping_search

Searches the web for product/shopping results.  When a product image is
available, uses **Gemini Vision (multimodal)** to generate a precise product
description for better search results.
Uses DuckDuckGo via the ``ddgs`` package for the actual search.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from tools import BaseTool, ToolDefinition, ToolParameter, registry
from llm import download_image, gemini_vision_json

logger = logging.getLogger("browserbuddy.tools.shopping_search")

# ---------------------------------------------------------------------------
# ddgs import
# ---------------------------------------------------------------------------
HAS_DDGS = False
_DDGS_CLASS = None

try:
    from ddgs import DDGS as _DDGS  # type: ignore[import-untyped]
    _DDGS_CLASS = _DDGS
    HAS_DDGS = True
    logger.info("ddgs package loaded successfully")
except ImportError:
    logger.warning("ddgs not installed — shopping search will return no results")


# ---------------------------------------------------------------------------
# Gemini Vision product description
# ---------------------------------------------------------------------------

_PRODUCT_VISION_SYSTEM = """\
You are a product identification assistant for a shopping search engine.
Look at the product image carefully and describe it precisely.
Consider the user's intent when crafting the search query.

Return ONLY valid JSON (no markdown, no code fences):
{"product_name": "<specific product name including brand if visible>", \
"search_query": "<optimised shopping search query tailored to user intent>"}
"""


async def _describe_product_for_search(
    image_url: str,
    user_intent: str,
    current_query: str,
) -> str | None:
    """Use Gemini Vision to see the product and build an optimised search query."""

    downloaded = await download_image(image_url)
    if downloaded is None:
        return None

    img_bytes, mime = downloaded
    image_parts = [{
        "mime_type": mime,
        "data": base64.b64encode(img_bytes).decode(),
    }]

    # Tailor instructions to user intent
    lower = user_intent.lower()
    if any(kw in lower for kw in ("cheap", "cheaper", "price", "lowest", "deal", "discount")):
        intent_instruction = (
            "The user wants to find this product at the CHEAPEST possible price. "
            "Make the search query focus on finding deals, discounts, and low prices."
        )
    elif any(kw in lower for kw in ("alternative", "similar", "like this")):
        intent_instruction = (
            "The user wants SIMILAR alternatives to this product. "
            "Make the search query broad enough to find comparable items."
        )
    elif any(kw in lower for kw in ("buy", "purchase", "order", "get")):
        intent_instruction = (
            "The user wants to BUY this exact product. "
            "Include the product name, brand, and model in the search query."
        )
    else:
        intent_instruction = f"User's request: {user_intent}"

    text_prompt = (
        f"{intent_instruction}\n\n"
        f"Current text-based query for reference: {current_query}\n\n"
        "Look at this product image and provide a precise, optimised shopping search query."
    )

    parsed = await gemini_vision_json(
        text_prompt,
        image_parts,
        system_prompt=_PRODUCT_VISION_SYSTEM,
        max_tokens=1024,
        temperature=0.1,
    )

    if isinstance(parsed, dict):
        query = parsed.get("search_query") or parsed.get("product_name")
        if query:
            logger.info("Vision product description: %s", query)
            return str(query)

    return None


# ---------------------------------------------------------------------------
# DuckDuckGo search helper
# ---------------------------------------------------------------------------


def _search_duckduckgo(query: str, max_results: int = 10) -> list[dict[str, str]]:
    """Run a DuckDuckGo text search for shopping-oriented results."""

    if not HAS_DDGS or _DDGS_CLASS is None:
        logger.warning("ddgs not available (HAS_DDGS=%s)", HAS_DDGS)
        return []

    try:
        ddgs = _DDGS_CLASS()
        search_query = f"{query} buy"
        logger.info("DuckDuckGo search query: %s", search_query)
        raw_results = ddgs.text(search_query, max_results=max_results + 3)

        results: list[dict[str, str]] = []
        for r in raw_results:
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

        logger.info("DuckDuckGo returned %d results for '%s'", len(results), query)
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# MCP Tool class
# ---------------------------------------------------------------------------


class ShoppingSearchTool(BaseTool):
    """Searches the web for product listings using vision-enhanced search."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shopping_search",
            description=(
                "Searches the web for product listings and shopping results. "
                "When a product image is provided, uses Gemini Vision to identify "
                "the product precisely for better search results."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Product name or search query for shopping.",
                ),
                ToolParameter(
                    name="image_url",
                    type="string",
                    description="URL of the selected product image for vision-enhanced search.",
                    required=False,
                ),
                ToolParameter(
                    name="user_intent",
                    type="string",
                    description="The user's original request to tailor search strategy.",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of results to return (default 10).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs.get("query", "")
        image_url: str = kwargs.get("image_url", "")
        user_intent: str = kwargs.get("user_intent", "")
        max_results: int = kwargs.get("max_results", 10)

        if not query or not query.strip():
            return {"error": "No search query provided."}

        # ---- Vision-enhanced search ----
        vision_query: str | None = None
        if image_url:
            vision_query = await _describe_product_for_search(
                image_url, user_intent or query, query,
            )
            if vision_query:
                logger.info(
                    "Vision-enhanced query: '%s' (original: '%s')",
                    vision_query, query,
                )

        if vision_query:
            effective_query = vision_query + query
        else:
            effective_query = vision_query or query
            
        results = _search_duckduckgo(effective_query, max_results)

        if results:
            return {
                "tool": "shopping_search",
                "query": effective_query,
                "original_query": query,
                "results": results,
                "count": len(results),
                "vision_enhanced": bool(vision_query),
            }

        # Retry with the original text query if vision query returned nothing
        if vision_query and vision_query != query:
            results = _search_duckduckgo(query, max_results)
            if results:
                return {
                    "tool": "shopping_search",
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "vision_enhanced": False,
                    "note": "Vision search returned no results; used text query.",
                }

        # No results at all
        return {
            "tool": "shopping_search",
            "query": query,
            "results": [],
            "count": 0,
            "note": "No shopping results found. Try a different query.",
        }


# Auto-register on import
registry.register(ShoppingSearchTool())
