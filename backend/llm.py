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
import re
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
    print("LLM raw response for JSON parsing:", raw[:500] if raw else "None")
    if raw is None:
        return None

    def _strip_code_fences(value: str) -> str:
        text = value.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _extract_first_json_object(value: str) -> str | None:
        start = value.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaping = False
        for idx in range(start, len(value)):
            ch = value[idx]

            if escaping:
                escaping = False
                continue

            if ch == "\\":
                escaping = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return value[start: idx + 1]

        return None

    text = _strip_code_fences(raw)

    # Pass 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Pass 2: try extracting first JSON object from mixed prose output
    extracted = _extract_first_json_object(text)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM response as JSON on first pass — raw: %s", text[:240])

    # Pass 3: single strict retry asking model to output only JSON.
    retry_messages = messages + [
        {
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Return ONLY valid JSON (no markdown, no explanation, no extra text)."
            ),
        }
    ]
    retry_raw = await llm_chat(retry_messages, max_tokens=max_tokens, temperature=0.0)
    if retry_raw is None:
        return None

    retry_text = _strip_code_fences(retry_raw)
    try:
        return json.loads(retry_text)
    except json.JSONDecodeError:
        extracted_retry = _extract_first_json_object(retry_text)
        if extracted_retry:
            try:
                return json.loads(extracted_retry)
            except json.JSONDecodeError:
                pass

    logger.warning("Failed to parse LLM response as JSON after retry — raw: %s", retry_text[:240])
    return None


# ---------------------------------------------------------------------------
# Shared image utilities (used by candidate_selection, shopping_search, etc.)
# ---------------------------------------------------------------------------

_MAX_IMAGE_BYTES = 3 * 1024 * 1024


_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


async def download_image(
    url: str, max_bytes: int = _MAX_IMAGE_BYTES
) -> tuple[bytes, str] | None:
    """Download an image.  Returns ``(raw_bytes, mime_type)`` or *None*."""
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=_DOWNLOAD_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "image/jpeg")
            if not ct.startswith("image/"):
                return None
            body = resp.content
            if len(body) > max_bytes:
                logger.warning("Image too large (%d bytes), skipping", len(body))
                return None
            return body, ct
    except Exception as exc:
        logger.debug("Image download failed %s: %s", url[:100], exc)
        return None


# ---------------------------------------------------------------------------
# Gemini Vision (multimodal) — text + images
# ---------------------------------------------------------------------------


async def gemini_vision(
    text_prompt: str,
    image_parts: list[dict[str, str]],
    system_prompt: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str | None:
    """Call Gemini with text **and** inline images (multimodal).

    *image_parts* is a list of ``{"mime_type": "image/jpeg", "data": "<base64>"}``
    dicts.  Returns the raw text response or *None*.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — cannot call Gemini Vision")
        return None

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    parts: list[dict[str, Any]] = [{"text": text_prompt}]
    for img in image_parts:
        parts.append(
            {"inlineData": {"mimeType": img["mime_type"], "data": img["data"]}}
        )

    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Strip code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        return raw

    except Exception as exc:
        logger.warning("Gemini Vision call failed: %s", exc)
        return None


async def gemini_vision_json(
    text_prompt: str,
    image_parts: list[dict[str, str]],
    system_prompt: str = "",
    max_tokens: int = 512,
    temperature: float = 0.1,
) -> Any | None:
    """Like :func:`gemini_vision` but parses the response as JSON."""
    raw = await gemini_vision(
        text_prompt, image_parts, system_prompt, max_tokens, temperature
    )
    if raw is None:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting a JSON object from mixed prose
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try to recover truncated JSON (Gemini thinking may consume tokens)
    trunc = re.search(r'\{[^{}]*$', raw)
    if trunc:
        fragment = trunc.group()
        # Extract key-value pairs from truncated object
        pairs = re.findall(r'"(\w+)"\s*:\s*"([^"]+)"', fragment)
        if pairs:
            recovered = {k: v for k, v in pairs}
            logger.info("gemini_vision_json: recovered partial JSON: %s", recovered)
            return recovered

    logger.warning("gemini_vision_json: could not parse: %s", raw[:200])
    return None
