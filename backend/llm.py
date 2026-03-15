"""
Unified LLM client for BrowserBuddy.

Uses GPT-OSS-120B via a HuggingFace Inference Endpoint (OpenAI-compatible API).
Falls back to Gemini API, then to no-LLM mode.

All tools and the agent router use this single entry point so there is
exactly one place to configure the model.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

# Load .env from the backend directory (works regardless of cwd)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(_env_path)

logger = logging.getLogger("browserbuddy.llm")

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

# Primary: GPT-OSS-120B on HuggingFace (free, OpenAI-compatible)
HF_ENDPOINT = os.environ.get(
    "HF_ENDPOINT",
    "https://qyt7893blb71b5d3.us-east-2.aws.endpoints.huggingface.cloud/v1",
)
HF_MODEL = os.environ.get("HF_MODEL", "openai/gpt-oss-120b")
HF_API_KEY = os.environ.get("HF_API_KEY", "")  # empty = no auth needed for this endpoint

# Fallback: Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Timeout for LLM calls (seconds)
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _call_hf_openai(
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> str | None:
    """Call the HuggingFace OpenAI-compatible chat endpoint."""

    url = f"{HF_ENDPOINT}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if HF_API_KEY:
        headers["Authorization"] = f"Bearer {HF_API_KEY}"

    payload = {
        "model": HF_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]
        # GPT-OSS-120B is a reasoning model: content may be populated,
        # or it may be in the reasoning field when max_tokens is too low.
        content = choice.get("content") or ""
        if not content and choice.get("reasoning"):
            content = choice["reasoning"]
        return content.strip() if content else None

    except Exception as exc:
        logger.warning("HF endpoint call failed: %s", exc)
        return None


async def _call_gemini(
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> str | None:
    """Call Google Gemini REST API as fallback."""

    if not GEMINI_API_KEY:
        return None

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    # Convert OpenAI-style messages to Gemini format
    contents: list[dict[str, Any]] = []
    system_text = ""
    for msg in messages:
        if msg["role"] == "system":
            system_text = msg["content"]
        else:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload: dict[str, Any] = {"contents": contents}
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}
    payload["generationConfig"] = {
        "maxOutputTokens": max_tokens,
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    except Exception as exc:
        logger.warning("Gemini call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def llm_chat(
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> str | None:
    """
    Send a chat-completion request to the best available LLM.

    Priority: GPT-OSS-120B (HF) → Gemini → None

    Returns the assistant's text content, or None if all providers fail.
    """

    # 1. Try GPT-OSS-120B
    result = await _call_hf_openai(messages, max_tokens, temperature)
    if result:
        logger.info("LLM response from HF endpoint (%d chars)", len(result))
        return result

    # 2. Try Gemini
    result = await _call_gemini(messages, max_tokens, temperature)
    if result:
        logger.info("LLM response from Gemini (%d chars)", len(result))
        return result

    logger.warning("All LLM providers failed — returning None")
    return None


async def llm_json(
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.1,
) -> Any | None:
    """
    Like llm_chat but parses the response as JSON.

    Strips markdown code fences if the model wraps the JSON.
    Returns the parsed object, or None on failure.
    """

    raw = await llm_chat(messages, max_tokens, temperature)
    if raw is None:
        return None

    # Strip code fences
    text = raw.strip()
    if text.startswith("```"):
        # Remove opening ```json or ``` and closing ```
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM response as JSON: %s — raw: %s", exc, text[:200])
        return None
