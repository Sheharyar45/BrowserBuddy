"""
MCP Tool: summarize_page

Summarises webpage content into a concise summary with key points.

Strategy:
  1. Try GPT-OSS-120B / Gemini via the unified LLM client.
  2. Otherwise → extractive summarisation using TF-IDF-style sentence scoring.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from tools import BaseTool, ToolDefinition, ToolParameter, registry
from llm import llm_json

logger = logging.getLogger("browserbuddy.tools.summarize")

# ---------------------------------------------------------------------------
# Stopwords for extractive summarisation
# ---------------------------------------------------------------------------
STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "but", "and", "or", "if", "while", "that", "this",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "their", "what", "which", "who",
    "whom", "these", "those", "am", "about", "up", "also", "s", "t", "re",
}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (basic regex splitter)."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-z]{3,}\b", text.lower())


# ---------------------------------------------------------------------------
# Extractive summarisation
# ---------------------------------------------------------------------------


def _extractive_summarize(
    text: str,
    num_sentences: int = 5,
    num_key_points: int = 5,
) -> dict[str, Any]:
    """Extractive summarisation using TF-IDF–style sentence scoring."""

    sentences = _split_sentences(text)
    if not sentences:
        return {"summary": text[:500], "key_points": []}

    # Word frequency (non-stopwords)
    words = [w for w in _tokenize(text) if w not in STOP_WORDS]
    word_freq = Counter(words)

    # Document frequency (per sentence)
    num_docs = len(sentences)
    doc_freq: Counter[str] = Counter()
    for sent in sentences:
        for w in set(_tokenize(sent)):
            doc_freq[w] += 1

    # Score each sentence
    scored: list[tuple[float, int, str]] = []
    for idx, sent in enumerate(sentences):
        sent_words = [w for w in _tokenize(sent) if w not in STOP_WORDS]
        if not sent_words:
            continue

        score = 0.0
        for w in sent_words:
            tf = word_freq.get(w, 0)
            idf = math.log((num_docs / (doc_freq.get(w, 1))) + 1)
            score += tf * idf

        score /= len(sent_words)  # normalise by sentence length

        # Position bias: earlier sentences get a slight boost
        position_boost = 1.0 + 0.1 * max(0, 3 - idx)
        score *= position_boost

        scored.append((score, idx, sent))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Pick top sentences in original order for the summary
    top_n = min(num_sentences, len(scored))
    summary_sents = sorted(scored[:top_n], key=lambda x: x[1])
    summary = " ".join(s[2] for s in summary_sents)

    # Key points = top scored unique sentences
    key_points = [s[2] for s in scored[:num_key_points]]

    return {"summary": summary, "key_points": key_points}


# ---------------------------------------------------------------------------
# LLM-based summarisation
# ---------------------------------------------------------------------------


async def _llm_summarize(text: str) -> dict[str, Any] | None:
    """Use the unified LLM client to summarise. Returns None on failure."""

    messages = [
        {
            "role": "system",
            "content": (
                "You are a summarisation assistant. Given webpage text, produce a concise summary "
                "and a list of key points. Respond ONLY with valid JSON:\n"
                '{"summary": "...", "key_points": ["point1", "point2", ...]}'
            ),
        },
        {
            "role": "user",
            "content": f"Summarise the following webpage content:\n\n{text[:6000]}",
        },
    ]

    result = await llm_json(messages, max_tokens=800, temperature=0.3)
    if isinstance(result, dict) and "summary" in result:
        return result
    return None


# ---------------------------------------------------------------------------
# MCP Tool class
# ---------------------------------------------------------------------------


class SummarizePageTool(BaseTool):
    """Summarises webpage content into a concise summary with key points."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="summarize_page",
            description="Summarises webpage content into a concise summary and key points.",
            parameters=[
                ToolParameter(
                    name="page_text",
                    type="string",
                    description="The full text content of the webpage to summarise.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        page_text: str = kwargs.get("page_text", "")
        if not page_text or not page_text.strip():
            return {"error": "No page text provided for summarisation."}

        # Try LLM first, then fall back to extractive
        llm_result = await _llm_summarize(page_text)
        if llm_result:
            return {"tool": "summarize_page", "method": "llm", **llm_result}

        result = _extractive_summarize(page_text)
        return {"tool": "summarize_page", "method": "extractive", **result}


# Auto-register on import
registry.register(SummarizePageTool())
