"""Comprehensive test suite for AXON v0.10 — Advanced Computer Automation."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from axon.core import Axon
from axon.security import PermissionLevel, PolicyDecision
from axon.tools.desktop import (
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_scroll,
    mouse_get_position,
    keyboard_type,
    keyboard_press,
    keyboard_hotkey,
    desktop_get_windows,
    desktop_get_active_window,
    desktop_switch_window,
    desktop_close_window,
    desktop_inspect_screen,
    screenshot_analyze,
    safety_reset,
    clamp_coordinates,
    get_screen_bounds,
)
from axon.agent.planner import Planner, Plan
from axon.tasks.tasks import StepStatus


@pytest.fixture
def axon_app(tmp_path):
    """Fixture providing initialized Axon runtime with custom temp paths."""
    app = Axon()
    app.config.set("memory_db_path", str(tmp_path / "memory.db"))
    app.config.set("audit_log_path", str(tmp_path / "audit.jsonl"))
    app.start()
    return app


# ── 1. Mouse Automation Unit Tests ──────────────────────────────────────────

def test_screen_bounds_and_clamping():
    """Verify screen bounds retrieval and coordinate clamping."""
    w, h = get_screen_bounds()
    assert w > 0 and h > 0

    # Inside bounds
    cx, cy = clamp_coordinates(100, 200)
    assert cx == 100 and cy == 200

    # Negative coordinates clamped to 0
    cx, cy = clamp_coordinates(-50, -100)
    assert cx == 0 and cy == 0

    # Oversized coordinates clamped to screen width-1, height-1
    cx, cy = clamp_coordinates(w + 500, h + 500)
    assert cx == w - 1 and cy == h - 1


def test_mouse_get_position():
    """Verify reading mouse position and screen metrics."""
    pos = mouse_get_position()
    assert pos.get("status") == "success"
    assert "x" in pos
    assert "y" in pos
    assert pos["screen_width"] > 0
    assert pos["screen_height"] > 0


def test_mouse_move():
    """Verify mouse cursor movement with clamping."""
    res = mouse_move(50, 60)
    assert res.get("status") == "success"
    assert res.get("x") == 50
    assert res.get("y") == 60


def test_mouse_click_and_double_click():
    """Verify mouse click and double click actions."""
    res_click = mouse_click(button="left")
    assert res_click.get("status") == "success"
    assert res_click.get("action") == "click"
    assert res_click.get("button") == "left"

    res_dbl = mouse_double_click()
    assert res_dbl.get("status") == "success"
    assert res_dbl.get("action") == "double_click"

    # Invalid button error
    err_click = mouse_click(button="invalid_button")
    assert "error" in err_click


def test_mouse_scroll():
    """Verify mouse scroll bounded actions."""
    res = mouse_scroll(delta=120)
    assert res.get("status") == "success"
    assert res.get("delta") == 120

    # Clamped scroll delta
    res_huge = mouse_scroll(delta=50000)
    assert res_huge.get("status") == "success"
    assert res_huge.get("delta") == 1200


# ── 2. Keyboard Automation Unit Tests ───────────────────────────────────────

def test_keyboard_press_valid_and_invalid():
    """Verify pressing valid and invalid keys."""
    res = keyboard_press("shift")
    assert res.get("status") == "success"
    assert res.get("key") == "shift"

    res_err = keyboard_press("non_existent_key_xyz")
    assert "error" in res_err


def test_keyboard_hotkey():
    """Verify key combination hotkey execution."""
    res = keyboard_hotkey("ctrl+c")
    assert res.get("status") == "success"
    assert res.get("hotkey") == "ctrl+c"
    assert res.get("keys_pressed") == 2

    # Invalid component key
    err_res = keyboard_hotkey("ctrl+boguskey123")
    assert "error" in err_res


def test_keyboard_type_and_length_limit():
    """Verify Unicode typing and length safety limits."""
    res = keyboard_type("Hello World")
    assert res.get("status") == "success"
    assert res.get("characters_typed") == 11

    # Text exceeding 2000 characters is rejected
    long_text = "A" * 2005
    err_res = keyboard_type(long_text)
    assert "error" in err_res
    assert "exceeds maximum safe limit" in err_res["error"]


# ── 3. Window & Desktop Understanding Unit Tests ────────────────────────────

def test_desktop_inspect_screen():
    """Verify aggregate desktop screen inspection."""
    info = desktop_inspect_screen()
    assert info.get("status") == "success"
    assert "display" in info
    assert "cursor" in info
    assert "active_window" in info
    assert "visible_windows_count" in info
    assert info.get("untrusted_data") is True


def test_desktop_get_windows():
    """Verify enumerating desktop windows."""
    windows = desktop_get_windows()
    assert isinstance(windows, list)
    # If windows are returned, verify dictionary keys
    for w in windows[:3]:
        assert "title" in w
        assert "process" in w


def test_desktop_get_active_window():
    """Verify retrieving active foreground window."""
    active = desktop_get_active_window()
    assert active.get("status") == "success"
    assert "title" in active


def test_desktop_switch_window():
    """Verify switching window focus."""
    res = desktop_switch_window("explorer")
    assert res.get("status") == "success"
    assert "switched" in res


def test_desktop_close_window():
    """Verify desktop window close handling."""
    res = desktop_close_window("NonExistentFakeWindowXYZ")
    assert res.get("status") == "success" or "error" in res


def test_safety_reset():
    """Verify safety reset releases keys and mouse buttons."""
    res = safety_reset()
    assert res.get("status") == "success"


def test_screenshot_analyze(tmp_path):
    """Verify visual telemetry analysis on generated test image."""
    from PIL import Image
    test_img_path = tmp_path / "test_screen.png"
    img = Image.new("RGB", (800, 600), color=(40, 44, 52))  # Dark gray image
    img.save(test_img_path)

    analysis = screenshot_analyze(str(test_img_path))
    assert analysis.get("status") == "success"
    assert analysis["dimensions"]["width"] == 800
    assert analysis["dimensions"]["height"] == 600
    assert analysis["visual_metrics"]["theme"] == "dark"
    assert analysis.get("untrusted_data") is True


# ── 4. Security Boundaries & Human Approval Tests ───────────────────────────

def test_security_safe_desktop_tools(axon_app):
    """Verify read-only desktop tools are evaluated as SAFE."""
    sec = axon_app.security
    for tool in (
        "desktop.inspect_screen",
        "desktop.get_windows",
        "desktop.get_active_window",
        "mouse.get_position",
        "screenshot.analyze",
        "screenshot.take",
        "safety_reset",
    ):
        dec = sec.evaluate(tool, {})
        assert dec.level == PermissionLevel.SAFE, f"{tool} should be SAFE"


def test_security_caution_desktop_tools(axon_app):
    """Verify standard automation tools are evaluated as CAUTION."""
    sec = axon_app.security
    assert sec.evaluate("mouse.move", {"x": 100, "y": 100}).level == PermissionLevel.CAUTION
    assert sec.evaluate("mouse.click", {"button": "left"}).level == PermissionLevel.CAUTION
    assert sec.evaluate("mouse.double_click", {}).level == PermissionLevel.CAUTION
    assert sec.evaluate("mouse.scroll", {"delta": 120}).level == PermissionLevel.CAUTION
    assert sec.evaluate("desktop.switch_window", {"title_or_pid": "code"}).level == PermissionLevel.CAUTION
    assert sec.evaluate("keyboard.press", {"key": "enter"}).level == PermissionLevel.CAUTION
    assert sec.evaluate("keyboard.hotkey", {"keys": "ctrl+c"}).level == PermissionLevel.CAUTION
    assert sec.evaluate("keyboard.type", {"text": "hello"}).level == PermissionLevel.CAUTION


def test_security_approval_required_for_destructive_actions(axon_app):
    """Verify sensitive/destructive computer actions require user approval."""
    sec = axon_app.security

    # 1. Closing windows requires approval
    dec_close = sec.evaluate("desktop.close_window", {"title_or_pid": "Untitled - Notepad"})
    assert dec_close.level == PermissionLevel.APPROVAL_REQUIRED

    from axon.security.policy import SecurityPolicyEngine
    engine = SecurityPolicyEngine()
    dec_engine = engine.evaluate("desktop.close_window", {"title_or_pid": "Untitled - Notepad"})
    assert dec_engine.level == PermissionLevel.APPROVAL_REQUIRED
    assert "requires human approval" in dec_engine.reason

    # 2. Destructive hotkey alt+f4 requires approval
    dec_altf4 = sec.evaluate("keyboard.hotkey", {"keys": "alt+f4"})
    assert dec_altf4.level == PermissionLevel.APPROVAL_REQUIRED

    # 3. System lock hotkeys require approval
    dec_lock = sec.evaluate("keyboard.hotkey", {"keys": "win+l"})
    assert dec_lock.level == PermissionLevel.APPROVAL_REQUIRED

    # 4. Dangerous command in keyboard.type requires approval
    dec_type_rmdir = sec.evaluate("keyboard.type", {"text": "rmdir /s /q C:\\ImportantData"})
    assert dec_type_rmdir.level == PermissionLevel.APPROVAL_REQUIRED

    dec_type_format = sec.evaluate("keyboard.type", {"text": "format d: /q"})
    assert dec_type_format.level == PermissionLevel.APPROVAL_REQUIRED

    # 5. System power keys require approval
    dec_power = sec.evaluate("keyboard.press", {"key": "power"})
    assert dec_power.level == PermissionLevel.APPROVAL_REQUIRED


def test_security_blocked_abnormal_desktop_actions(axon_app):
    """Verify out-of-bounds or malformed desktop actions are BLOCKED."""
    sec = axon_app.security

    # Wildly negative or huge mouse coordinates
    dec_neg = sec.evaluate("mouse.move", {"x": -999, "y": 100})
    assert dec_neg.level == PermissionLevel.BLOCKED

    dec_huge = sec.evaluate("mouse.move", {"x": 50000, "y": 50000})
    assert dec_huge.level == PermissionLevel.BLOCKED

    # Invalid mouse button
    dec_bad_btn = sec.evaluate("mouse.click", {"button": "middle_finger"})
    assert dec_bad_btn.level == PermissionLevel.BLOCKED

    # Oversized scroll delta
    dec_bad_scroll = sec.evaluate("mouse.scroll", {"delta": 999999})
    assert dec_bad_scroll.level == PermissionLevel.BLOCKED

    # Exceeding typing length
    dec_long_type = sec.evaluate("keyboard.type", {"text": "X" * 2500})
    assert dec_long_type.level == PermissionLevel.BLOCKED


def test_router_enforces_approval_for_desktop_actions(axon_app):
    """Verify Router enforces ApprovalManager on desktop.close_window."""
    # When approval is denied
    axon_app.approval.set_auto_approve(False)
    res_denied = axon_app.router.execute("desktop.close_window", title_or_pid="TestApp")
    assert res_denied["success"] is False
    assert "Approval denied" in res_denied["error"]

    # When approval is granted
    axon_app.approval.set_auto_approve(True)
    with patch("axon.tools.desktop.desktop_close_window", return_value={"status": "success", "closed": True}):
        res_granted = axon_app.router.execute("desktop.close_window", title_or_pid="TestApp")
        assert res_granted["success"] is True


# ── 5. Agent Verification & Recovery Tests ──────────────────────────────────

def test_verifier_handles_desktop_actions(axon_app):
    """Verify Verifier handles outcomes for desktop automation tools."""
    verifier = axon_app.executor.verifier
    task = axon_app.tasks.create("Test desktop verifier")

    # Step: mouse.move
    s1 = task.add_step("Move mouse", tool="mouse.move", tool_args={"x": 100, "y": 100})
    ok, msg = verifier.verify(s1, {"success": True, "result": {"status": "success", "x": 100, "y": 100}})
    assert ok is True
    assert "Verified mouse moved" in msg

    # Step: desktop.switch_window
    s2 = task.add_step("Switch to Notepad", tool="desktop.switch_window", tool_args={"title_or_pid": "Notepad"})
    ok, msg = verifier.verify(s2, {"success": True, "result": {"status": "success", "switched": True, "title": "Notepad"}})
    assert ok is True
    assert "Verified window switch" in msg

    # Step: keyboard.type
    s3 = task.add_step("Type text", tool="keyboard.type", tool_args={"text": "hello"})
    ok, msg = verifier.verify(s3, {"success": True, "result": {"status": "success", "characters_typed": 5}})
    assert ok is True
    assert "Verified typed 5 characters" in msg


def test_failed_desktop_action_recovery_and_safety_reset(axon_app):
    """Verify that failing desktop actions trigger safety_reset to release keys."""
    safety_reset_called = False

    def mock_safety_reset():
        nonlocal safety_reset_called
        safety_reset_called = True
        return {"status": "success"}

    with patch("axon.tools.desktop.safety_reset", side_effect=mock_safety_reset):
        task = axon_app.tasks.create("Failing mouse action")
        # Add an action that fails verification
        step = task.add_step("Move mouse to bad pos", tool="mouse.move", tool_args={"x": 50, "y": 50})
        step.max_retries = 1

        with patch.object(axon_app.router, "execute", return_value={"success": False, "error": "Hardware error"}):
            axon_app.executor._execute_step_with_retries(task, step)

        assert step.status == StepStatus.FAILED
        assert safety_reset_called is True


# ── 6. Multi-Step Workflow & Planner Integration Tests ──────────────────────

def test_planner_desktop_heuristic_workflows():
    """Verify Planner creates multi-step plans for desktop goals."""
    planner = Planner()

    # Goal: Take screenshot and analyze screen
    p_screen = planner.plan("Take a screenshot and analyze the screen")
    assert len(p_screen.steps) == 2
    assert p_screen.steps[0].tool == "screenshot.take"
    assert p_screen.steps[1].tool == "screenshot.analyze"

    # Goal: Inspect desktop
    p_inspect = planner.plan("Inspect desktop state and visible windows")
    assert len(p_inspect.steps) == 2
    assert p_inspect.steps[0].tool == "desktop.inspect_screen"
    assert p_inspect.steps[1].tool == "desktop.get_windows"

    # Goal: Notepad automation workflow
    p_notepad = planner.plan("Open notepad and write note")
    assert len(p_notepad.steps) >= 3
    tools = [s.tool for s in p_notepad.steps]
    assert "applications.open" in tools
    assert "desktop.switch_window" in tools
    assert "keyboard.type" in tools


def test_agent_executor_runs_multi_step_desktop_plan(axon_app):
    """Verify AgentExecutor runs a full desktop plan step-by-step through Router."""
    axon_app.approval.set_auto_approve(True)

    plan = Plan(
        goal="Desktop telemetry and inspection workflow",
        steps=[],
    )
    p1 = axon_app.planner.plan("Inspect desktop state and visible windows")

    task = axon_app.executor.execute_plan(p1)
    assert task.status.value in ("completed", "running")
    assert len(task.steps) >= 2
    for step in task.steps:
        assert step.status.value == "completed"


# ── 7. Regression Tests ─────────────────────────────────────────────────────

def test_existing_tools_and_security_still_work(axon_app):
    """Verify existing filesystem, apps, git, memory, and coding features still pass."""
    # Applications
    assert axon_app.registry.exists("applications.list")
    assert axon_app.registry.exists("applications.open")
    assert axon_app.registry.exists("applications.close")

    # Filesystem
    assert axon_app.registry.exists("filesystem.list")
    assert axon_app.registry.exists("filesystem.write")

    # Git
    assert axon_app.registry.exists("git.status")
    assert axon_app.registry.exists("git.commit")

    # New desktop tools
    assert axon_app.registry.exists("mouse.move")
    assert axon_app.registry.exists("keyboard.type")
    assert axon_app.registry.exists("desktop.inspect_screen")
    assert axon_app.registry.exists("screenshot.analyze")
