"""
MCP-style tool registry for BrowserBuddy.

Each tool follows the Model Context Protocol pattern:
- Has a name, description, and parameter schema
- Implements an async execute() method
- Auto-registers with the global ToolRegistry on import
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class ToolDefinition:
    """MCP-style tool definition with name, description, and parameters."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                p.name: {"type": p.type, "description": p.description, "required": p.required}
                for p in self.parameters
            },
        }


class BaseTool(abc.ABC):
    """Base class for all MCP-style tools."""

    @property
    @abc.abstractmethod
    def definition(self) -> ToolDefinition:
        """Return the MCP tool definition."""
        ...

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool with the given parameters and return structured results."""
        ...


class ToolRegistry:
    """Central registry that holds all available MCP tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance by its definition name."""
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Return definitions for all registered tools."""
        return [t.definition for t in self._tools.values()]

    def list_tool_names(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._tools.keys())

    @property
    def tools(self) -> dict[str, BaseTool]:
        return dict(self._tools)


# ---------------------------------------------------------------------------
# Global singleton registry
# ---------------------------------------------------------------------------
registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Return the global tool registry (importing tool modules auto-registers them)."""
    return registry
