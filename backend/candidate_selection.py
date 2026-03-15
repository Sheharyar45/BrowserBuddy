"""
Candidate product selection for BrowserBuddy.

Uses the **text LLM** as the primary selector — it analyses page context,
candidate alt-text, image URLs, and user intent to pick the best match.
**Gemini Vision** is a secondary helper only, called when the text LLM is
ambiguous and downloadable product images are available.
Falls back to deterministic heuristics when both fail.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

from llm import download_image, gemini_vision_json, llm_json

logger = logging.getLogger("browserbuddy.candidate_selection")


# =====================================================================
# Text helpers
# =====================================================================


def normalize_text(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9]{3,}\b", (text or "").lower()))


def _looks_non_product_label(label: str) -> bool:
    cleaned = (label or "").strip().lower()
    if not cleaned:
        return True
    weak_labels = {
        "image", "logo", "icon", "avatar", "profile", "menu", "search",
        "close", "arrow", "banner", "placeholder", "unnamed product",
    }
    return cleaned in weak_labels


# =====================================================================
# Candidate extraction from page context
# =====================================================================


def get_candidate_products(context: dict[str, Any]) -> list[dict[str, str]]:
    raw_candidates = context.get("candidate_products") or []
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        image = str(item.get("image", "")).strip()
        alt_text = str(item.get("alt_text", "")).strip() or "Unnamed product"
        if not image:
            continue
        key = (image, alt_text.lower())
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"image": image, "alt_text": alt_text})

    if not candidates:
        for image in (context.get("images") or [])[:50]:
            if not image:
                continue
            key = (str(image), "unnamed product")
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"image": str(image), "alt_text": "Unnamed product"})

    # Put likely product candidates first.
    def sort_key(item: dict[str, str]) -> tuple[int, int]:
        alt = item.get("alt_text", "")
        weak = 1 if _looks_non_product_label(alt) else 0
        return (weak, -len(alt))

    candidates.sort(key=sort_key)
    return candidates


# =====================================================================
# Deterministic helpers (no API call)
# =====================================================================


def get_selected_candidate_index(
    context: dict[str, Any],
    candidates: list[dict[str, str]],
) -> int | None:
    selected = context.get("selected_candidate")
    if not isinstance(selected, dict):
        return None
    selected_image = str(selected.get("image", "")).strip()
    selected_alt = str(selected.get("alt_text", "")).strip()
    if not selected_image and not selected_alt:
        return None
    for idx, item in enumerate(candidates):
        image_match = selected_image and item.get("image", "").strip() == selected_image
        alt_match = selected_alt and item.get("alt_text", "").strip().lower() == selected_alt.lower()
        if image_match or alt_match:
            return idx
    return None


def _obvious_candidate_from_context(
    context: dict[str, Any],
    candidates: list[dict[str, str]],
) -> tuple[int | None, str]:
    if not candidates:
        return None, "no candidates"
    if len(candidates) == 1:
        return 0, "single candidate"

    explicit_idx = get_selected_candidate_index(context, candidates)
    if explicit_idx is not None:
        return explicit_idx, "selected candidate from UI context"

    title_tokens = normalize_text(str(context.get("title", "")))
    if not title_tokens:
        return None, "no title tokens"

    scored: list[tuple[int, int]] = []
    for idx, item in enumerate(candidates):
        alt_tokens = normalize_text(item.get("alt_text", ""))
        score = len(title_tokens & alt_tokens)
        if score > 0 and not _looks_non_product_label(item.get("alt_text", "")):
            score += 1
        scored.append((score, idx))

    scored.sort(reverse=True)
    best_score, best_idx = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1
    if best_score >= 3 and best_score >= second_score + 2:
        return best_idx, "clear title overlap winner"

    return None, "no obvious deterministic winner"


# =====================================================================
# Gemini Vision helper (secondary — used only when text LLM is unsure)
# =====================================================================

_VISION_SELECTOR_SYSTEM = """\
You are a product selection assistant for a browser extension.
The user is viewing a webpage with multiple product images.
Look at ALL the product images carefully and pick the SINGLE product
that BEST matches the user's request and the page context.

Return ONLY valid JSON (no markdown, no code fences):
{"candidate_index": <0-based number from the list>, "confidence": 0.0-1.0, "reason": "brief reason"}

If you genuinely cannot determine which product, return:
{"candidate_index": null, "ambiguous": true, "confidence": 0.0, "reason": "why"}
"""

_MAX_VISION_CANDIDATES = 8


async def _vision_select_candidate(
    prompt: str,
    candidates: list[dict[str, str]],
    context: dict[str, Any],
) -> tuple[int | None, bool, str]:
    """Use Gemini Vision (multimodal) to pick the best product image.

    Called ONLY when the text LLM was ambiguous / low-confidence.
    """

    top = candidates[:_MAX_VISION_CANDIDATES]

    # Download candidate images concurrently
    tasks = [download_image(c["image"]) for c in top]
    dl_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build image parts & index mapping (vision_pos → original_pos)
    image_parts: list[dict[str, str]] = []
    index_map: dict[int, int] = {}
    desc_lines: list[str] = []

    for orig_idx, dl in enumerate(dl_results):
        if isinstance(dl, BaseException) or dl is None:
            continue
        img_bytes, mime = dl
        vis_pos = len(image_parts)
        image_parts.append({
            "mime_type": mime,
            "data": base64.b64encode(img_bytes).decode(),
        })
        index_map[vis_pos] = orig_idx
        alt = top[orig_idx].get("alt_text", "Unnamed product")
        desc_lines.append(f"Product {vis_pos}: {alt}")

    if not image_parts:
        return None, True, "no candidate images could be downloaded"

    text_prompt = (
        f"User request: {prompt}\n\n"
        f"Page title: {context.get('title', '')}\n"
        f"Page URL: {context.get('url', '')}\n\n"
        f"Below are {len(image_parts)} product images from this page (in order):\n"
        + "\n".join(desc_lines)
        + "\n\nWhich product number (0-based) best matches the user's request?"
    )

    parsed = await gemini_vision_json(
        text_prompt,
        image_parts,
        system_prompt=_VISION_SELECTOR_SYSTEM,
        max_tokens=256,
        temperature=0.1,
    )

    if isinstance(parsed, dict):
        vis_idx = parsed.get("candidate_index")
        confidence = parsed.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        ambiguous = bool(parsed.get("ambiguous", False))
        reason = str(parsed.get("reason", ""))

        if isinstance(vis_idx, int) and vis_idx in index_map:
            orig_idx = index_map[vis_idx]
            if not ambiguous and float(confidence) >= 0.3:
                logger.info(
                    "Gemini Vision selected candidate %d (confidence=%.2f): %s",
                    orig_idx, confidence, reason,
                )
                return orig_idx, False, f"gemini_vision: {reason}"
            return None, True, f"gemini_vision low confidence ({confidence}): {reason}"

    return None, True, "gemini_vision response parsing failed"


# =====================================================================
# Public selection API
# =====================================================================


async def select_candidate_from_prompt(
    prompt: str,
    candidates: list[dict[str, str]],
    context: dict[str, Any] | None = None,
) -> tuple[int | None, bool, str]:
    """Return (index, ambiguous, reason).

    Strategy order:
      1. Deterministic shortcuts (UI selection, single candidate)
      2. User typed a number
      3. **Text LLM** as the primary selector (uses page context + alt text)
      4. Gemini Vision as a helper when text LLM is ambiguous
      5. Token overlap heuristic as final fallback
    Only returns ambiguous=True when confidence is genuinely very low.
    """

    if not candidates:
        return None, False, "no candidates available"

    if len(candidates) == 1:
        return 0, False, "single candidate"

    # 1. Deterministic shortcuts
    obvious_idx, obvious_reason = _obvious_candidate_from_context(context or {}, candidates)
    if obvious_idx is not None:
        return obvious_idx, False, obvious_reason

    # 2. User explicitly typed a number ("2")
    number_match = re.search(r"\b([1-9])\b", prompt)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return idx, False, "user provided candidate index"

    # 3. Token overlap quick-check
    prompt_tokens = normalize_text(prompt)
    scored: list[tuple[int, int]] = []
    for idx, item in enumerate(candidates):
        alt_tokens = normalize_text(item.get("alt_text", ""))
        score = len(prompt_tokens & alt_tokens)
        scored.append((score, idx))

    scored.sort(reverse=True)
    best_score, best_idx = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1
    if best_score >= 2 and best_score > second_score:
        return best_idx, False, "matched candidate alt_text"

    # 4. PRIMARY — text LLM selection
    chooser_prompt = "\n".join(
        [f"{i+1}. {c.get('alt_text', 'Unnamed product')} | {c.get('image', '')}"
         for i, c in enumerate(candidates[:20])]
    )

    page_title = str((context or {}).get("title", ""))
    page_url = str((context or {}).get("url", ""))
    page_text_preview = str((context or {}).get("text", ""))[:1200]
    selected_candidate = (context or {}).get("selected_candidate")

    messages = [
        {
            "role": "system",
            "content": (
                "Select which product candidate the user likely means. "
                "Use the page context to pick the MOST obvious candidate when possible. "
                "Only mark ambiguous=true when confidence is genuinely low. "
                "Use visual clues from image URLs, product title alignment, and selected candidate hint. "
                'Return ONLY JSON: {"candidate_index": <0-based int or null>, '
                '"ambiguous": true|false, "confidence": 0.0-1.0, "reason": "..."}.'
            ),
        },
        {
            "role": "user",
            "content": (
                f"User prompt: {prompt}\n\n"
                f"Page title: {page_title}\n"
                f"Page URL: {page_url}\n"
                f"Page text preview: {page_text_preview}\n"
                f"User-selected candidate from UI (if any): {selected_candidate}\n\n"
                f"Top page image URLs: {(context or {}).get('images', [])[:8]}\n\n"
                f"Candidates:\n{chooser_prompt}"
            ),
        },
    ]

    try:
        llm_choice = await llm_json(messages, max_tokens=1500, temperature=0.0)
        if isinstance(llm_choice, dict):
            idx = llm_choice.get("candidate_index")
            ambiguous = bool(llm_choice.get("ambiguous", False))
            confidence = llm_choice.get("confidence", 0.0)
            if not isinstance(confidence, (int, float)):
                confidence = 0.0
            reason = str(llm_choice.get("reason", ""))
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                if not ambiguous and float(confidence) >= 0.40:
                    return idx, False, reason or "llm selected candidate"
                # Low confidence — try vision as a helper before giving up
                if float(confidence) < 0.40:
                    logger.info("LLM confidence %.2f too low, trying Vision helper", confidence)
                    try:
                        vis_idx, vis_amb, vis_reason = await _vision_select_candidate(
                            prompt, candidates, context or {},
                        )
                        if vis_idx is not None:
                            return vis_idx, False, f"vision_helper: {vis_reason}"
                    except Exception as ve:
                        logger.warning("Vision helper failed: %s", ve)
                    return None, True, reason or "candidate confidence too low"
            # LLM returned null idx or out of range — try vision
            if ambiguous:
                logger.info("LLM ambiguous, trying Vision helper")
                try:
                    vis_idx, vis_amb, vis_reason = await _vision_select_candidate(
                        prompt, candidates, context or {},
                    )
                    if vis_idx is not None:
                        return vis_idx, False, f"vision_helper: {vis_reason}"
                except Exception as ve:
                    logger.warning("Vision helper failed: %s", ve)
            return None, True, reason or "ambiguous candidate selection"
    except Exception as exc:
        logger.warning("Candidate chooser LLM failed: %s", exc)

    # 5. Final fallback — vision standalone (text LLM completely failed)
    try:
        vis_idx, vis_amb, vis_reason = await _vision_select_candidate(
            prompt, candidates, context or {},
        )
        if vis_idx is not None:
            return vis_idx, False, f"vision_fallback: {vis_reason}"
    except Exception as ve:
        logger.warning("Vision fallback also failed: %s", ve)

    return None, True, "could not confidently select candidate"


# =====================================================================
# Ambiguity & plan helpers
# =====================================================================


def build_ambiguity_prompt(
    candidates: list[dict[str, str]], max_items: int = 20,
) -> str:
    lines = [
        "I see multiple products on this page. Which one should I search?",
        "",
    ]
    for i, item in enumerate(candidates[:max_items], start=1):
        label = item.get("alt_text", "Unnamed product")
        lines.append(f"{i}\uFE0F\u20E3 {label}")
    lines.append("")
    lines.append("Reply with a number (for example: 1).")
    return "\n".join(lines)


def extract_numeric_choice(prompt: str, max_candidates: int) -> int | None:
    match = re.search(r"\b([1-9]\d?)\b", (prompt or "").strip())
    if not match:
        return None
    idx = int(match.group(1)) - 1
    if 0 <= idx < max_candidates:
        return idx
    return None


def apply_selected_candidate_to_plan(
    plan: list[dict[str, Any]],
    selected: dict[str, str],
    context: dict[str, Any],
    prompt: str,
) -> None:
    """Inject the selected candidate's image and info into each plan step."""
    for step in plan:
        tool_name = step.get("tool")
        params = step.setdefault("params", {})

        if tool_name == "image_similarity":
            params["image_url"] = selected.get("image", "")

        if tool_name == "shopping_search":
            # Pass image for Gemini Vision product identification
            params["image_url"] = selected.get("image", "")
            params["user_intent"] = prompt
            # Improve text query with product alt_text
            existing_query = str(params.get("query", "")).strip()
            if not existing_query or existing_query.lower() in {
                context.get("title", "").lower(),
                prompt.lower(),
            }:
                params["query"] = selected.get("alt_text", "") or existing_query
