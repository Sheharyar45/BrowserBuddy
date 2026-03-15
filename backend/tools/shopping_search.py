"""
MCP Tool: shopping_search

Searches the web for product/shopping results using DuckDuckGo via the
``ddgs`` package (free, no API key required).
Falls back to curated demo results if the library is unavailable or fails.
"""

from __future__ import annotations

import logging
from typing import Any

from tools import BaseTool, ToolDefinition, ToolParameter, registry

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
    logger.warning("ddgs package not installed — shopping search will use demo results")

# ---------------------------------------------------------------------------
# Demo / fallback data
# ---------------------------------------------------------------------------
DEMO_RESULTS: list[dict[str, str]] = [
    {
        "title": "Similar Wool Sweater — H&M",
        "price": "$29.99",
        "url": "https://www.hm.com/sweater-example",
        "snippet": "Soft-knit wool-blend sweater in a relaxed fit.",
        "source": "demo",
    },
    {
        "title": "Cable Knit Sweater — Zara",
        "price": "$35.90",
        "url": "https://www.zara.com/sweater-example",
        "snippet": "Cable-knit sweater with round neckline and long sleeves.",
        "source": "demo",
    },
    {
        "title": "Cozy Knit Pullover — Amazon",
        "price": "$24.99",
        "url": "https://www.amazon.com/sweater-example",
        "snippet": "Women's oversized knit pullover sweater, multiple colours.",
        "source": "demo",
    },
    {
        "title": "Merino Wool Crew Neck — Uniqlo",
        "price": "$39.90",
        "url": "https://www.uniqlo.com/sweater-example",
        "snippet": "Extra fine merino crew neck sweater, machine washable.",
        "source": "demo",
    },
]


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
        # Search with "buy" suffix to bias towards shopping results
        search_query = f"{query} buy"
        logger.info("DuckDuckGo search query: %s", search_query)
        raw_results = ddgs.text(
            search_query,
            max_results=max_results + 3,
        )

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
    """Searches the web for product listings and shopping results."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shopping_search",
            description="Searches the web for product listings and shopping results based on a query.",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Product name or search query for shopping.",
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
        max_results: int = kwargs.get("max_results", 10)

        if not query or not query.strip():
            return {"error": "No search query provided."}

        results = _search_duckduckgo(query, max_results)

        if results:
            return {
                "tool": "shopping_search",
                "query": query,
                "results": results,
                "count": len(results),
            }

        # Fallback to demo data
        logger.info("Using demo results for query: %s", query)
        return {
            "tool": "shopping_search",
            "query": query,
            "results": DEMO_RESULTS[:max_results],
            "count": len(DEMO_RESULTS[:max_results]),
            "note": "Using demo results. Install 'duckduckgo-search' for live results.",
        }


# Auto-register on import
registry.register(ShoppingSearchTool())
