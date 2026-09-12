"""AXON approval — asks for user consent before executing restricted tools."""


class ApprovalManager:
    def __init__(self, event_bus, prompt_fn=None):
        self.event_bus = event_bus
        # prompt_fn(tool_name, kwargs) -> bool
        # If None, approval-required tools are denied by default
        self._prompt_fn = prompt_fn

    def set_prompt(self, prompt_fn):
        """Set the function that asks the user for approval."""
        self._prompt_fn = prompt_fn

    def set_auto_approve(self, auto_approve: bool = True):
        """Convenience method to auto-grant or auto-deny approvals."""
        self._prompt_fn = (lambda tool, kwargs: bool(auto_approve)) if auto_approve is not None else None

    def request(self, tool_name: str, kwargs: dict) -> bool:
        """Ask for approval. Returns True if granted, False if denied."""
        self.event_bus.emit("APPROVAL_REQUESTED", {"tool": tool_name, "args": kwargs})

        if self._prompt_fn is None:
            self.event_bus.emit("APPROVAL_DENIED", {"tool": tool_name})
            return False

        granted = self._prompt_fn(tool_name, kwargs)

        if granted:
            self.event_bus.emit("APPROVAL_GRANTED", {"tool": tool_name, "args": kwargs})
        else:
            self.event_bus.emit("APPROVAL_DENIED", {"tool": tool_name})

        return granted
