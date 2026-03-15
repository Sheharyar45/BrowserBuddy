"""Quick integration test for BrowserBuddy backend."""

import asyncio
import json
import urllib.request


BASE = "http://127.0.0.1:8000"

SAMPLE_CONTEXT = {
    "url": "https://example.com/article",
    "title": "The Future of AI Agents",
    "text": (
        "Artificial intelligence agents are rapidly transforming how we interact "
        "with technology. These agents can understand natural language, process "
        "complex information, and take actions on behalf of users. The development "
        "of large language models has enabled a new generation of AI assistants "
        "that can reason about tasks. Companies are investing billions in developing "
        "more capable AI systems. Browser-based agents are particularly interesting "
        "because they can interact with the web on behalf of users. They can read "
        "pages, extract information, and complete tasks like shopping or research. "
        "The integration of tool-calling capabilities allows agents to use specialized "
        "functions. For example an agent might use a summarization tool to condense a "
        "long article. Or it might use a search tool to find related products. The "
        "future of AI agents is closely tied to advances in reasoning and planning. "
        "Multi-step task completion remains one of the hardest challenges in AI."
    ),
    "images": ["https://example.com/ai-agents.jpg"],
}


def post_query(prompt: str, *, session_id: str | None = None, include_context: bool = True) -> dict:
    body: dict = {"prompt": prompt}
    if session_id:
        body["session_id"] = session_id
    if include_context:
        body["context"] = SAMPLE_CONTEXT

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}/agent/query",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def get_json(path: str) -> dict:
    resp = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(resp.read())


def separator(label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")


def main() -> None:
    # 1. Health
    separator("Health Check")
    print(json.dumps(get_json("/health"), indent=2))

    # 2. List tools
    separator("Registered MCP Tools")
    tools = get_json("/tools")
    for t in tools["tools"]:
        print(f"  - {t['name']}: {t['description']}")
    print(f"  Total: {tools['count']}")

    # 3. Test: summarize
    separator("Test: Summarize")
    result = post_query("Summarize this article")
    print(f"  Routing: {result.get('routing_method')}")
    print(f"  Tools used: {result.get('tools_used')}")
    print(f"  Response preview: {result['response'][:300]}...")

    # 3b. Test: session reuse without resending context
    separator("Test: Reuse session_id (no context)")
    session_id = result.get("session_id")
    if not session_id:
        raise RuntimeError("Expected session_id from backend")
    result2 = post_query("Summarize again in one sentence", session_id=session_id, include_context=False)
    print(f"  Session: {result2.get('session_id')}")
    print(f"  Context source: {result2.get('context_source')}")
    print(f"  Response preview: {result2['response'][:200]}...")

    # 4. Test: shopping search
    separator("Test: Find cheaper alternatives")
    result = post_query("Find cheaper alternatives")
    print(f"  Routing: {result.get('routing_method')}")
    print(f"  Tools used: {result.get('tools_used')}")
    print(f"  Response preview: {result['response'][:300]}...")

    # 5. Test: similar images
    separator("Test: Find similar items")
    result = post_query("Find similar items like this")
    print(f"  Routing: {result.get('routing_method')}")
    print(f"  Tools used: {result.get('tools_used')}")
    print(f"  Response preview: {result['response'][:300]}...")

    # 6. Test: compound query (similar + cheaper)
    separator("Test: Find similar sweaters cheaper (multi-tool)")
    result = post_query("Find similar sweaters cheaper")
    print(f"  Routing: {result.get('routing_method')}")
    print(f"  Tools used: {result.get('tools_used')}")
    print(f"  Response preview: {result['response'][:500]}...")

    # 7. Test: generate content
    separator("Test: Turn into study notes")
    result = post_query("Turn this into study notes")
    print(f"  Routing: {result.get('routing_method')}")
    print(f"  Tools used: {result.get('tools_used')}")
    print(f"  Response preview: {result['response'][:300]}...")

    # 8. Test: default (generate_content fallback)
    separator("Test: Default fallback")
    result = post_query("What can you tell me about this?")
    print(f"  Routing: {result.get('routing_method')}")
    print(f"  Tools used: {result.get('tools_used')}")
    print(f"  Response preview: {result['response'][:300]}...")

    # 9. Verify context storage
    separator("Context Storage Check")
    if session_id:
        ctx = get_json(f"/context/{session_id}")
        print(f"  Session: {ctx['session_id']}")
        print(f"  Stored text chars: {len(ctx['context'].get('text', ''))}")
        print(f"  Stored images: {len(ctx['context'].get('images', []))}")

    print(f"\n{'=' * 60}")
    print("  ALL TESTS PASSED")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
