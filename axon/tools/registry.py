"""AXON tool registry."""


class ToolRegistry:
    def __init__(self):
        self._tools = {}  # name -> {func, description}

    def register(self, name: str, func, description: str = ""):
        self._tools[name] = {"func": func, "description": description}

    def get(self, name: str):
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool["func"]

    def list(self) -> dict:
        return {name: info["description"] for name, info in self._tools.items()}

    def exists(self, name: str) -> bool:
        return name in self._tools

    def has(self, name: str) -> bool:
        return self.exists(name)
