"""AXON approval engine tests."""

from axon.tools import ToolRegistry
from axon.router import Router
from axon.events import EventBus
from axon.security import SecurityManager, Permission, ApprovalManager


def _make_router(prompt_fn=None):
    """Helper: create a router with a test tool that requires approval."""
    reg = ToolRegistry()
    reg.register("safe.tool", lambda: "safe_result", "Safe tool")
    reg.register("risky.tool", lambda cmd="": f"ran: {cmd}", "Risky tool")
    reg.register("blocked.tool", lambda: "should never run", "Blocked tool")

    security = SecurityManager()
    security.set_permission("risky.tool", Permission.APPROVAL_REQUIRED)
    security.set_permission("blocked.tool", Permission.DENIED)

    events = EventBus()
    approval = ApprovalManager(events, prompt_fn=prompt_fn)
    router = Router(reg, security, events, approval)
    return router, events


# --- Safe tool executes without approval ---

def test_safe_tool_executes_automatically():
    router, _ = _make_router()
    result = router.execute("safe.tool")
    assert result["success"] is True
    assert result["result"] == "safe_result"


# --- Approval-required tool does NOT execute without prompt ---

def test_approval_required_denied_without_prompt():
    router, _ = _make_router(prompt_fn=None)
    result = router.execute("risky.tool", cmd="test")
    assert result["success"] is False
    assert "denied" in result["error"].lower()


# --- Approval granted → tool executes ---

def test_approval_granted():
    router, _ = _make_router(prompt_fn=lambda name, kwargs: True)
    result = router.execute("risky.tool", cmd="hello")
    assert result["success"] is True
    assert result["result"] == "ran: hello"


# --- Approval denied → tool does not execute ---

def test_approval_denied():
    router, _ = _make_router(prompt_fn=lambda name, kwargs: False)
    result = router.execute("risky.tool", cmd="hello")
    assert result["success"] is False
    assert "denied" in result["error"].lower()


# --- DENIED tools can never execute, even with approval ---

def test_denied_tool_cannot_be_approved():
    router, _ = _make_router(prompt_fn=lambda name, kwargs: True)
    result = router.execute("blocked.tool")
    assert result["success"] is False
    assert "denied" in result["error"].lower()


# --- Approval events are emitted ---

def test_approval_events_emitted():
    events_log = []

    def log_event(event):
        events_log.append(event.name)

    router, events = _make_router(prompt_fn=lambda name, kwargs: True)
    events.on("APPROVAL_REQUESTED", log_event)
    events.on("APPROVAL_GRANTED", log_event)
    events.on("APPROVAL_DENIED", log_event)

    router.execute("risky.tool", cmd="test")
    assert "APPROVAL_REQUESTED" in events_log
    assert "APPROVAL_GRANTED" in events_log

    events_log.clear()
    router2, events2 = _make_router(prompt_fn=lambda name, kwargs: False)
    events2.on("APPROVAL_REQUESTED", log_event)
    events2.on("APPROVAL_DENIED", log_event)

    router2.execute("risky.tool", cmd="test")
    assert "APPROVAL_REQUESTED" in events_log
    assert "APPROVAL_DENIED" in events_log
