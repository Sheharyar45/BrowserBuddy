from __future__ import annotations

import logging
import re
from typing import Any

from llm import llm_json

logger = logging.getLogger("browserbuddy.candidate_selection")


def normalize_text(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9]{3,}\b", (text or "").lower()))


def get_candidate_products(context: dict[str, Any]) -> list[dict[str, str]]:
    raw_candidates = context.get("candidate_products") or []
    candidates: list[dict[str, str]] = []

    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        image = str(item.get("image", "")).strip()
        alt_text = str(item.get("alt_text", "")).strip() or "Unnamed product"
        if not image:
            continue
        candidates.append({"image": image, "alt_text": alt_text})

    if not candidates:
        for image in (context.get("images") or [])[:50]:
            if not image:
                continue
            candidates.append({"image": str(image), "alt_text": "Unnamed product"})

    return candidates


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


async def select_candidate_from_prompt(
    prompt: str,
    candidates: list[dict[str, str]],
) -> tuple[int | None, bool, str]:
    """Return (index, ambiguous, reason)."""

    if not candidates:
        return None, False, "no candidates available"

    if len(candidates) == 1:
        return 0, False, "single candidate"

    number_match = re.search(r"\b([1-9])\b", prompt)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return idx, False, "user provided candidate index"

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

    chooser_prompt = "\n".join(
        [f"{i+1}. {c.get('alt_text', 'Unnamed product')} | {c.get('image', '')}" for i, c in enumerate(candidates[:20])]
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Select which product candidate the user likely means. "
                "Return ONLY JSON: {\"candidate_index\": <0-based int or null>, \"ambiguous\": true|false, \"reason\": \"...\"}."
            ),
        },
        {
            "role": "user",
            "content": f"User prompt: {prompt}\n\nCandidates:\n{chooser_prompt}",
        },
    ]

    try:
        llm_choice = await llm_json(messages, max_tokens=140, temperature=0.0)
        if isinstance(llm_choice, dict):
            idx = llm_choice.get("candidate_index")
            ambiguous = bool(llm_choice.get("ambiguous", False))
            reason = str(llm_choice.get("reason", ""))
            if isinstance(idx, int) and 0 <= idx < len(candidates) and not ambiguous:
                return idx, False, reason or "llm selected candidate"
            return None, True, reason or "ambiguous candidate selection"
    except Exception as exc:
        logger.warning("Candidate chooser LLM failed: %s", exc)

    return None, True, "could not confidently select candidate"


def build_ambiguity_prompt(candidates: list[dict[str, str]], max_items: int = 20) -> str:
    lines = [
        "I see multiple products on this page. Which one should I search?",
        "",
    ]
    for i, item in enumerate(candidates[:max_items], start=1):
        label = item.get("alt_text", "Unnamed product")
        lines.append(f"{i}️⃣ {label}")
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
    for step in plan:
        tool_name = step.get("tool")
        params = step.setdefault("params", {})
        if tool_name == "image_similarity":
            params["image_url"] = selected.get("image", "")
        if tool_name == "shopping_search":
            existing_query = str(params.get("query", "")).strip()
            if not existing_query or existing_query.lower() in {context.get("title", "").lower(), prompt.lower()}:
                params["query"] = selected.get("alt_text", "") or existing_query
