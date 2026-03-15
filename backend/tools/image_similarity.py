"""
MCP Tool: image_similarity

Finds visually similar images/products given an image URL.

MVP implementation uses a mock similarity engine.  When CLIP + a vector DB
are available the mock can be swapped out transparently because the MCP
interface stays the same.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from tools import BaseTool, ToolDefinition, ToolParameter, registry

logger = logging.getLogger("browserbuddy.tools.image_similarity")


# ---------------------------------------------------------------------------
# Mock similarity engine (MVP)
# ---------------------------------------------------------------------------


def _mock_similar_images(image_url: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Return deterministic mock results seeded by the image URL.

    In production this would:
      1. Download the image
      2. Generate a CLIP embedding
      3. Search a vector database for nearest neighbours
    """

    # Use hash of URL to create varied but deterministic demo results
    url_hash = hashlib.md5(image_url.encode()).hexdigest()
    seed = int(url_hash[:8], 16)

    mock_products = [
        {
            "title": "Classic Knit Pullover",
            "url": "https://example.com/product/knit-pullover",
            "image_url": "https://picsum.photos/seed/prod1/300/300",
            "similarity": 0.94,
            "price": "$32.00",
        },
        {
            "title": "Ribbed Cotton Sweater",
            "url": "https://example.com/product/ribbed-sweater",
            "image_url": "https://picsum.photos/seed/prod2/300/300",
            "similarity": 0.89,
            "price": "$27.50",
        },
        {
            "title": "Oversized Wool Cardigan",
            "url": "https://example.com/product/wool-cardigan",
            "image_url": "https://picsum.photos/seed/prod3/300/300",
            "similarity": 0.85,
            "price": "$45.00",
        },
        {
            "title": "Cashmere Blend V-Neck",
            "url": "https://example.com/product/cashmere-vneck",
            "image_url": "https://picsum.photos/seed/prod4/300/300",
            "similarity": 0.82,
            "price": "$55.00",
        },
        {
            "title": "Lightweight Crew Neck",
            "url": "https://example.com/product/crew-neck",
            "image_url": "https://picsum.photos/seed/prod5/300/300",
            "similarity": 0.78,
            "price": "$22.99",
        },
    ]

    # Rotate results based on seed for variety
    offset = seed % len(mock_products)
    rotated = mock_products[offset:] + mock_products[:offset]
    return rotated[:max_results]


# ---------------------------------------------------------------------------
# MCP Tool class
# ---------------------------------------------------------------------------


class ImageSimilarityTool(BaseTool):
    """Finds visually similar products/images given a source image URL."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="image_similarity",
            description="Finds visually similar images or products given a source image URL.",
            parameters=[
                ToolParameter(
                    name="image_url",
                    type="string",
                    description="URL of the source image to find similar matches for.",
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
        max_results: int = kwargs.get("max_results", 5)

        if not image_url or not image_url.strip():
            return {"error": "No image URL provided."}

        results = _mock_similar_images(image_url, max_results)

        return {
            "tool": "image_similarity",
            "source_image": image_url,
            "results": results,
            "count": len(results),
            "note": "Using mock similarity engine (MVP). Swap in CLIP + vector DB for production.",
        }


# Auto-register on import
registry.register(ImageSimilarityTool())
