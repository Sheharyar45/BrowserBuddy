"""
Agent controller for BrowserBuddy.

Routes user prompts to MCP tools using an LLM-based planner.
The LLM receives tool definitions + user prompt + page context and decides
which tools to invoke and with what parameters.  Falls back to keyword
matching if the LLM is unreachable.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Import tool modules → auto-registers them with the global registry
import tools.summarize  # noqa: F401
import tools.shopping_search  # noqa: F401
import tools.image_similarity  # noqa: F401
import tools.generator  # noqa: F401
from tools import get_registry
from llm import llm_json
from candidate_selection import (
    apply_selected_candidate_to_plan,
    build_ambiguity_prompt,
    extract_numeric_choice,
    get_candidate_products,
    get_selected_candidate_index,
    select_candidate_from_prompt,
)

logger = logging.getLogger("browserbuddy.agent")


def _to_plain_text(text: str) -> str:
    """Convert common markdown patterns to readable plain text for popup UI."""
    if not text:
        return ""

    lines = text.splitlines()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Convert markdown table rows like: | Section | What it shows |
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Skip separator rows: |---|---|
            if all(c and set(c) <= {"-", ":"} for c in cells):
                continue
            if len(cells) >= 2:
                out.append(f"- {cells[0]}: {cells[1]}")
            else:
                out.append(f"- {cells[0]}")
            continue

        # Remove markdown headings while keeping text.
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()

        # Replace some markdown emphasis markers.
        stripped = stripped.replace("**", "")
        stripped = stripped.replace("__", "")
        stripped = stripped.replace("`", "")

        out.append(stripped)

    normalized = "\n".join(out)

    # Clean excessive blank lines.
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


# =====================================================================
# LLM relevance guardrail (before tool routing)
# =====================================================================

_RELEVANCE_SYSTEM_PROMPT = """\
You are a strict relevance classifier for a browser-page assistant.

Decide if the user's prompt is relevant to the CURRENT webpage context.

Return ONLY valid JSON:
{
  "is_relevant": true or false,
  "reason": "short reason"
}

Rules:
- Mark false for general knowledge questions unrelated to the page (e.g., "what is the capital of france").
- Mark true for page-focused requests: summary, key points, notes, cheaper alternatives, similar products, or questions about page content.
- If unsure, prefer true.
"""


async def _is_prompt_relevant(prompt: str, context: dict[str, Any]) -> tuple[bool, str]:
    """LLM-based relevance gate with safe fallback."""

    title = context.get("title", "")
    url = context.get("url", "")
    text_preview = (context.get("text", "") or "")[:800]

    messages = [
        {"role": "system", "content": _RELEVANCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Prompt: {prompt}\n\n"
                f"Page title: {title}\n"
                f"Page URL: {url}\n"
                f"Page text preview: {text_preview}"
            ),
        },
    ]

    try:
        result = await llm_json(messages, max_tokens=120, temperature=0.0)
        if isinstance(result, dict) and "is_relevant" in result:
            is_relevant = bool(result.get("is_relevant"))
            reason = str(result.get("reason", ""))
            return is_relevant, reason
    except Exception as exc:
        logger.warning("Relevance guard LLM call failed, defaulting to relevant: %s", exc)

    # Fail-open to avoid blocking useful page tasks if classifier is unavailable.
    return True, "relevance classifier unavailable"


async def _execute_plan(
    registry: Any,
    plan: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    executed_tools: list[str] = []
    tool_results: list[dict[str, Any]] = []

    for step in plan:
        tool_name = step.get("tool", "")
        tool = registry.get(tool_name)
        if tool is None:
            logger.warning("Tool '%s' not in registry — skipping", tool_name)
            continue

        params = step.get("params", {})
        logger.info("Executing tool '%s' with params: %s", tool_name, list(params.keys()))

        try:
            result = await tool.execute(**params)
        except Exception as exc:
            logger.error("Tool '%s' failed: %s", tool_name, exc, exc_info=True)
            result = {"error": f"Tool execution failed: {exc}"}

        executed_tools.append(tool_name)
        tool_results.append(result)

    return executed_tools, tool_results


# =====================================================================
# LLM-based tool routing
# =====================================================================

_ROUTER_SYSTEM_PROMPT = """\
You are the BrowserBuddy tool router.  Given a user prompt and the context of \
the webpage they are viewing, decide which tools to call and provide parameters.

Available tools:

1. summarize_page
   - Use when the user wants a summary, overview, key points, or TL;DR.
   - params: { "page_text": "<the full page text from context>" }

2. shopping_search
   - Use when the user wants to find a product elsewhere, find cheaper \
alternatives, compare prices, buy something, or find where to purchase.
   - params: { "query": "<optimised product search query>", "max_results": 5 }
   - IMPORTANT: The "query" must be a concise product search string suitable for \
a shopping search engine.  Extract the product name/type from the page title and \
text.  Do NOT include the user's full sentence — just the product keywords.  \
Example: if the page is "Oversized Wool Sweater | H&M" and user says "find this \
cheaper", the query should be "oversized wool sweater".

3. image_similarity
   - Use when the user wants to find visually similar items, matching \
products, or "items like this".
   - params: { "image_url": "<first image url from context>", "max_results": 5 }

4. generate_content
   - Use for writing tasks: study notes, emails, rewrites, summaries of a \
different kind, bullet points, or any creative/transformative task.
   - params: { "task": "<what to generate>", "page_text": "<the page text>" }

Rules:
- You may select ONE or MORE tools to handle compound requests.
- For example "find similar sweaters cheaper" → image_similarity + shopping_search.
- For "find this product cheaper" → shopping_search (with a good product query).
- If nothing fits, use generate_content as a catch-all.
- Respond with ONLY valid JSON (no markdown, no explanation).

Response format (a JSON array):
[
  { "tool": "<tool_name>", "params": { ... } }
]
"""


def _build_router_user_message(prompt: str, context: dict[str, Any]) -> str:
    """Build the user message for the LLM router."""

    title = context.get("title", "")
    url = context.get("url", "")
    text_preview = (context.get("text", "") or "")[:4000]
    images = context.get("images", [])
    images_str = ", ".join(images[:3]) if images else "(none)"

    return (
        f"User prompt: {prompt}\n\n"
        f"Page title: {title}\n"
        f"Page URL: {url}\n"
        f"Page text (first 4000 chars): {text_preview}\n"
        f"Page images: {images_str}"
    )


async def _llm_route(prompt: str, context: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Ask the LLM which tools to call. Returns parsed plan or None."""

    messages = [
        {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": _build_router_user_message(prompt, context)},
    ]

    plan = await llm_json(messages, max_tokens=600, temperature=0.1)

    if not isinstance(plan, list) or not plan:
        return None

    # Validate structure
    validated: list[dict[str, Any]] = []
    for item in plan:
        if isinstance(item, dict) and "tool" in item:
            validated.append(item)

    return validated if validated else None


# =====================================================================
# Keyword fallback (used only when LLM routing fails)
# =====================================================================

_SUMMARIZE_KW = {"summarize", "summarise", "summary", "tldr", "tl;dr", "key points", "overview", "recap"}
_SEARCH_KW = {"cheaper", "price", "buy", "shop", "purchase", "find", "search", "alternative", "deal", "discount", "cost", "where to buy", "elsewhere"}
_SIMILAR_KW = {"similar", "like this", "alike", "matching", "looks like", "same style"}
_GENERATE_KW = {"write", "generate", "create", "draft", "notes", "study", "email", "turn this", "rewrite", "rephrase", "bullet"}


def _kw_match(text: str, keywords: set[str]) -> bool:
    return any(kw in text for kw in keywords)


def _keyword_route(prompt: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Keyword-based fallback routing."""

    p = prompt.lower().strip()
    plan: list[dict[str, Any]] = []

    if _kw_match(p, _SUMMARIZE_KW):
        plan.append({"tool": "summarize_page", "params": {"page_text": context.get("text", "")}})

    if _kw_match(p, _SIMILAR_KW):
        images = context.get("images", [])
        plan.append({"tool": "image_similarity", "params": {"image_url": images[0] if images else "", "max_results": 5}})

    if _kw_match(p, _SEARCH_KW):
        title = context.get("title", "")
        plan.append({"tool": "shopping_search", "params": {"query": title or prompt, "max_results": 5}})

    if _kw_match(p, _GENERATE_KW):
        plan.append({"tool": "generate_content", "params": {"task": prompt, "page_text": context.get("text", "")}})

    # Compound: similar → also search
    tool_names = {item["tool"] for item in plan}
    if "image_similarity" in tool_names and "shopping_search" not in tool_names:
        title = context.get("title", "")
        plan.append({"tool": "shopping_search", "params": {"query": title or prompt, "max_results": 5}})

    if not plan:
        plan.append({"tool": "generate_content", "params": {"task": prompt, "page_text": context.get("text", "")}})

    return plan


# =====================================================================
# Response formatter
# =====================================================================


def _format_response(tools_used: list[str], results: list[dict[str, Any]]) -> str:
    """Format structured tool results into a human-readable response string."""

    parts: list[str] = []

    for tool_name, result in zip(tools_used, results):
        if "error" in result:
            parts.append(f"Error ({tool_name}): {result['error']}")
            continue

        if tool_name == "summarize_page":
            summary = result.get("summary", "")
            key_points = result.get("key_points", [])
            method = result.get("method", "extractive")
            text = f"📝 Page Summary ({method})\n\n{summary}"
            if key_points:
                text += "\n\nKey Points:\n" + "\n".join(f"• {kp}" for kp in key_points)
            parts.append(text)

        elif tool_name == "shopping_search":
            query = result.get("query", "")
            items = result.get("results", [])
            note = result.get("note", "")
            text = f'🛒 Shopping Results for "{query}"'
            if not items:
                text += "\n\nNo results found."
            for i, item in enumerate(items, 1):
                title = item.get("title", "Unknown")
                price = item.get("price", "")
                url = item.get("url", "")
                snippet = item.get("snippet", "")
                line = f"\n\n{i}. {title}"
                if price:
                    line += f"  —  {price}"
                if url:
                    line += f"\n   {url}"
                if snippet:
                    line += f"\n   {snippet}"
                text += line
            if note:
                text += f"\n\n({note})"
            parts.append(text)

        elif tool_name == "image_similarity":
            items = result.get("results", [])
            source = result.get("source_image", "")
            text = f"🔍 Similar Items (source: {source})"
            for i, item in enumerate(items, 1):
                title = item.get("title", "Similar item")
                similarity = item.get("similarity", 0)
                price = item.get("price", "")
                url = item.get("url", "")
                sim_str = f"{similarity:.0%}" if isinstance(similarity, (int, float)) else str(similarity)
                line = f"\n\n{i}. {title}  —  {sim_str} match"
                if price:
                    line += f"  —  {price}"
                if url:
                    line += f"\n   {url}"
                text += line
            note = result.get("note", "")
            if note:
                text += f"\n\n({note})"
            parts.append(text)

        elif tool_name == "generate_content":
            content = result.get("content", "")
            method = result.get("method", "template")
            text = f"✍️ Generated Content ({method})\n\n{content}"
            parts.append(text)

        else:
            parts.append(f"Result from {tool_name}: {result}")

    final_text = "\n\n---\n\n".join(parts) if parts else "No results generated."
    return _to_plain_text(final_text)


# =====================================================================
# Main agent entry point
# =====================================================================


async def run_agent(prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Route the user's prompt to the appropriate MCP tool(s), execute them,
    and return a structured response.

    1. Ask the LLM which tools to call (with params).
    2. If LLM fails, fall back to keyword matching.
    3. Execute each tool.
    4. Format and return results.
    """

    registry = get_registry()
    available = registry.list_tool_names()
    logger.info("Available MCP tools: %s", available)

    candidates = get_candidate_products(context)
    pending_selection = context.get("pending_selection")

    # If prior turn asked for a selection and user replied with a number (e.g. "2"),
    # resolve and execute without passing through relevance/routing again.
    if isinstance(pending_selection, dict) and isinstance(pending_selection.get("plan"), list):
        selected_idx = extract_numeric_choice(prompt, len(candidates))
        if selected_idx is not None:
            pending_plan = pending_selection.get("plan") or []
            selected = candidates[selected_idx] if 0 <= selected_idx < len(candidates) else None
            if selected and isinstance(pending_plan, list):
                apply_selected_candidate_to_plan(pending_plan, selected, context, prompt)
                executed_tools, tool_results = await _execute_plan(registry, pending_plan)
                response_text = _format_response(executed_tools, tool_results)
                return {
                    "response": response_text,
                    "tools_used": executed_tools,
                    "tool_results": tool_results,
                    "routing_method": "pending_item_selection",
                    "context_patch": {"pending_selection": None},
                }

    # --- Guardrail: block prompts unrelated to current page ---
    is_relevant, relevance_reason = await _is_prompt_relevant(prompt, context)
    if not is_relevant:
        logger.info("Blocked irrelevant prompt. reason=%s prompt=%s", relevance_reason, prompt)
        return {
            "response": (
                "I can only help with the page you're currently viewing. "
                "Try asking for a summary, notes, similar products, or cheaper alternatives from this page."
            ),
            "tools_used": [],
            "tool_results": [],
            "routing_method": "guardrail_irrelevant",
            "guardrail_reason": relevance_reason,
        }

    # --- 1. Plan: LLM routing (preferred) or keyword fallback ---
    plan = await _llm_route(prompt, context)
    routing_method = "llm"

    if plan is None:
        logger.info("LLM routing failed — using keyword fallback")
        plan = _keyword_route(prompt, context)
        routing_method = "keyword"

    # Pre-execution disambiguation for product/image tools
    needs_product_selection = any(
        step.get("tool") in {"shopping_search", "image_similarity"}
        for step in plan
    )

    if needs_product_selection:
        selected_idx = get_selected_candidate_index(context, candidates)
        selection_reason = "selected via mouse highlight"
        is_ambiguous = False

        if selected_idx is None:
            selected_idx, is_ambiguous, selection_reason = await select_candidate_from_prompt(
                prompt,
                candidates,
                context=context,
            )

        if is_ambiguous and len(candidates) > 1:
            logger.info("Ambiguous product selection. reason=%s", selection_reason)
            return {
                "response": build_ambiguity_prompt(candidates),
                "tools_used": [],
                "tool_results": [],
                "routing_method": "needs_item_selection",
                "context_patch": {"pending_selection": {"plan": plan}},
            }

        if selected_idx is not None and 0 <= selected_idx < len(candidates):
            selected = candidates[selected_idx]
            logger.info("Selected product candidate idx=%s reason=%s", selected_idx, selection_reason)
            apply_selected_candidate_to_plan(plan, selected, context, prompt)

    logger.info(
        "Routing method=%s | Plan: %s",
        routing_method,
        [(p["tool"], list(p.get("params", {}).keys())) for p in plan],
    )

    # --- 2. Execute ---
    executed_tools, tool_results = await _execute_plan(registry, plan)

    # --- 3. Format response ---
    response_text = _format_response(executed_tools, tool_results)

    return {
        "response": response_text,
        "tools_used": executed_tools,
        "tool_results": tool_results,
        "routing_method": routing_method,
        "context_patch": {"pending_selection": None},
    }
