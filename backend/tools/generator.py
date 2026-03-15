"""
MCP Tool: generate_content

Generates new content (study notes, emails, rewrites, etc.) from page
context and a user task description.

Strategy:
  1. Try GPT-OSS-120B / Gemini via the unified LLM client.
  2. Otherwise → template-based generation with extractive techniques.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from tools import BaseTool, ToolDefinition, ToolParameter, registry
from llm import llm_chat

logger = logging.getLogger("browserbuddy.tools.generator")


# ---------------------------------------------------------------------------
# Stopwords (shared with summarize, but duplicated here for independence)
# ---------------------------------------------------------------------------
_STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "but", "and", "or", "if", "while",
    "that", "this", "it", "its", "i", "me", "my", "we", "our", "you",
    "your", "he", "him", "his", "she", "her", "they", "them", "their",
}


# ---------------------------------------------------------------------------
# Template-based generation (no LLM needed)
# ---------------------------------------------------------------------------


def _extract_key_phrases(text: str, top_n: int = 8) -> list[str]:
    """Extract the most frequent meaningful phrases from text."""
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    meaningful = [w for w in words if w not in _STOP_WORDS]
    return [word for word, _ in Counter(meaningful).most_common(top_n)]


def _extract_sentences(text: str, max_sentences: int = 10) -> list[str]:
    """Pull top sentences from text."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20][:max_sentences]


def _template_generate(task: str, page_text: str) -> str:
    """Generate content using templates when no LLM is available."""

    task_lower = task.lower()
    key_phrases = _extract_key_phrases(page_text)
    sentences = _extract_sentences(page_text)

    if any(kw in task_lower for kw in ("study notes", "notes", "study")):
        header = "Study Notes"
        body_parts = [f"Topic keywords: {', '.join(key_phrases)}.", ""]
        body_parts.append("Key concepts:")
        for i, sent in enumerate(sentences[:7], 1):
            body_parts.append(f"  {i}. {sent}")
        body_parts.append("")
        body_parts.append("Review these points and test your understanding of each concept.")
        return f"{header}\n\n" + "\n".join(body_parts)

    if any(kw in task_lower for kw in ("email", "mail")):
        subject_hint = ", ".join(key_phrases[:3])
        body_sentences = sentences[:5]
        lines = [
            f"Subject: Regarding {subject_hint}",
            "",
            "Hi,",
            "",
            "I wanted to share some key points from the page I was reading:",
            "",
        ]
        for sent in body_sentences:
            lines.append(f"- {sent}")
        lines += ["", "Let me know your thoughts.", "", "Best regards"]
        return "\n".join(lines)

    if any(kw in task_lower for kw in ("rewrite", "rephrase", "paraphrase")):
        # Simple rewrite: reverse sentence order to show transformation
        return "Rewritten content:\n\n" + " ".join(reversed(sentences[:8]))

    if any(kw in task_lower for kw in ("bullet", "list", "points")):
        lines = ["Key points:"]
        for sent in sentences[:10]:
            lines.append(f"• {sent}")
        return "\n".join(lines)

    # Generic: extract and reorganise
    lines = [
        f"Generated content for: {task}",
        "",
        f"Main topics: {', '.join(key_phrases)}",
        "",
        "Content:",
        "",
    ]
    for sent in sentences[:8]:
        lines.append(f"  {sent}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM-based generation
# ---------------------------------------------------------------------------


async def _llm_generate(task: str, page_text: str) -> str | None:
    """Use the unified LLM client to generate content. Returns None on failure."""

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful writing assistant. The user will give you a task "
                "and some webpage content. Complete the task using the content as context."
            ),
        },
        {
            "role": "user",
            "content": f"Task: {task}\n\nWebpage content:\n{page_text[:6000]}",
        },
    ]

    return await llm_chat(messages, max_tokens=1024, temperature=0.5)


# ---------------------------------------------------------------------------
# MCP Tool class
# ---------------------------------------------------------------------------


class GenerateContentTool(BaseTool):
    """Generates new content (notes, emails, rewrites) from page context."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="generate_content",
            description="Generates new content (study notes, emails, rewrites, etc.) based on a task and page content.",
            parameters=[
                ToolParameter(
                    name="task",
                    type="string",
                    description="The generation task or instruction (e.g., 'Turn this into study notes').",
                ),
                ToolParameter(
                    name="page_text",
                    type="string",
                    description="The webpage text to use as source material.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        task: str = kwargs.get("task", "")
        page_text: str = kwargs.get("page_text", "")

        if not task or not task.strip():
            return {"error": "No task description provided."}
        if not page_text or not page_text.strip():
            return {"error": "No page text provided for content generation."}

        # Try LLM first
        llm_content = await _llm_generate(task, page_text)
        if llm_content:
            return {
                "tool": "generate_content",
                "method": "llm",
                "task": task,
                "content": llm_content,
            }

        # Template-based fallback
        content = _template_generate(task, page_text)
        return {
            "tool": "generate_content",
            "method": "template",
            "task": task,
            "content": content,
        }


# Auto-register on import
registry.register(GenerateContentTool())
