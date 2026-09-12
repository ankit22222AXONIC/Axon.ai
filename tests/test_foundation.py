"""AXON foundation tests — one test per pillar."""

import pytest
from axon.core import Axon, AxonStatus
from axon.tools import ToolRegistry
from axon.router import Router
from axon.events import EventBus
from axon.security import SecurityManager, Permission
from axon.tasks import Task, TaskStatus


# --- Pillar 1: Core ---

def test_axon_starts():
    axon = Axon()
    axon.start()
    assert axon.state.status == AxonStatus.READY
    axon.shutdown()
    assert axon.state.status == AxonStatus.STOPPED


# --- Pillar 2: Tool System ---

def test_tool_register_and_get():
    reg = ToolRegistry()
    reg.register("test.echo", lambda msg="": msg, "Echo a message")
    func = reg.get("test.echo")
    assert func(msg="hello") == "hello"


def test_tool_list():
    reg = ToolRegistry()
    reg.register("a.tool", lambda: None, "Tool A")
    reg.register("b.tool", lambda: None, "Tool B")
    tools = reg.list()
    assert "a.tool" in tools
    assert "b.tool" in tools
    assert len(tools) == 2


# --- Pillar 3: Router ---

def test_router_executes_tool():
    reg = ToolRegistry()
    reg.register("math.add", lambda a, b: int(a) + int(b), "Add numbers")
    security = SecurityManager()
    events = EventBus()
    router = Router(reg, security, events)

    result = router.execute("math.add", a=2, b=3)
    assert result["success"] is True
    assert result["result"] == 5


def test_router_unknown_tool():
    reg = ToolRegistry()
    security = SecurityManager()
    events = EventBus()
    router = Router(reg, security, events)

    result = router.execute("nonexistent.tool")
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


# --- Pillar 4: Events ---

def test_events_emitted():
    bus = EventBus()
    received = []
    bus.on("TEST_EVENT", lambda e: received.append(e))

    bus.emit("TEST_EVENT", {"key": "value"})

    assert len(received) == 1
    assert received[0].name == "TEST_EVENT"
    assert received[0].data["key"] == "value"


# --- Pillar 5: Security ---

def test_security_permissions():
    sec = SecurityManager()

    # Default is ALLOWED
    assert sec.check("anything") == Permission.ALLOWED

    sec.set_permission("dangerous.tool", Permission.DENIED)
    assert sec.check("dangerous.tool") == Permission.DENIED

    sec.set_permission("needs.approval", Permission.APPROVAL_REQUIRED)
    assert sec.check("needs.approval") == Permission.APPROVAL_REQUIRED


# --- Pillar 6: Tasks ---

def test_task_transitions():
    task = Task(goal="Test task")
    assert task.status == TaskStatus.CREATED

    task.transition(TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING

    task.transition(TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED

    # Cannot transition from COMPLETED
    with pytest.raises(ValueError):
        task.transition(TaskStatus.RUNNING)


# --- Integration: Router respects security ---

def test_router_denies_blocked_tool():
    reg = ToolRegistry()
    reg.register("blocked.tool", lambda: "should not run", "Blocked")
    security = SecurityManager()
    security.set_permission("blocked.tool", Permission.DENIED)
    events = EventBus()
    router = Router(reg, security, events)

    result = router.execute("blocked.tool")
    assert result["success"] is False
    assert "denied" in result["error"].lower()
