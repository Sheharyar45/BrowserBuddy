from typing import Any


async def run_agent(prompt: str, context: dict[str, Any]) -> str:
    text_chars = len(context.get("text", ""))
    image_count = len(context.get("images", []))

    return (
        f"Received prompt: {prompt}. "
        f"Context loaded: {text_chars} text characters and {image_count} image URLs."
    )
