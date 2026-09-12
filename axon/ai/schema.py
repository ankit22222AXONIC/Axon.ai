"""Tool schema converter — converts ToolRegistry tools to OpenAI/OpenRouter function calling schemas."""

import inspect
from typing import List, Dict, Any
from axon.tools import ToolRegistry


def to_api_tool_name(name: str) -> str:
    """Convert a dotted AXON tool name (e.g. 'filesystem.list') to an API-valid name ('filesystem__list')."""
    return name.replace(".", "__")


def resolve_tool_name(api_name: str, registry: ToolRegistry) -> str:
    """Resolve an API tool name back to the internal AXON tool name."""
    if registry.exists(api_name):
        return api_name
    candidate = api_name.replace("__", ".")
    if registry.exists(candidate):
        return candidate
    candidate_single = api_name.replace("_", ".")
    if registry.exists(candidate_single):
        return candidate_single
    return api_name


def tool_registry_to_schemas(registry: ToolRegistry) -> List[Dict[str, Any]]:
    """Convert registered tools in ToolRegistry to OpenAI/OpenRouter tool definitions."""
    schemas = []
    for name, info in registry._tools.items():
        func = info["func"]
        desc = info.get("description", "")
        api_name = to_api_tool_name(name)
        schema = _function_to_tool_schema(api_name, func, desc)
        schemas.append(schema)
    return schemas


def _function_to_tool_schema(name: str, func, description: str) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: List[str] = []

    try:
        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue

            ann = param.annotation
            param_type = "string"
            if ann is int:
                param_type = "integer"
            elif ann is float:
                param_type = "number"
            elif ann is bool:
                param_type = "boolean"
            elif ann is list:
                param_type = "array"
            elif ann is dict:
                param_type = "object"

            prop: Dict[str, Any] = {
                "type": param_type,
                "description": f"Argument '{param_name}'",
            }
            if param.default is not inspect.Parameter.empty and param.default is not None:
                prop["default"] = param.default

            properties[param_name] = prop

            if param.default is inspect.Parameter.empty:
                required.append(param_name)
    except Exception:
        pass

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or f"Execute {name}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
