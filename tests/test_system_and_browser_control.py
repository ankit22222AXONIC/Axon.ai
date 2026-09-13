"""Tests for AXONIC System & Browser Control expansion.

Verifies:
- browser.close_tab (SAFE, no approval required, dispatches Ctrl+W)
- browser.close_window (APPROVAL_REQUIRED, graceful window close)
- applications.close (APPROVAL_REQUIRED, graceful WM_CLOSE, no force kill by default, aliases)
- system.shutdown (APPROVAL_REQUIRED, explicit user approval, mocked shutdown.exe /s)
- system.restart (APPROVAL_REQUIRED, explicit user approval, mocked shutdown.exe /r)
- factory-reset rejection (blocks systemreset commands and rejects factory reset prompts)
- duplicate-action prevention (blocks concurrent pending power actions)
- invalid arguments & security policy enforcement
"""

import os
import subprocess
from unittest.mock import patch, MagicMock
import pytest

from axon.core import Axon
from axon.security import SecurityPolicyEngine, PermissionLevel
from axon.security.terminal_security import inspect_terminal_command
from axon.tools.browser import browser_close_tab, browser_close_window
from axon.tools.applications import applications_close
from axon.tools.system import (
    system_shutdown,
    system_restart,
    system_cancel_shutdown,
)
import axon.tools.system as system_mod


@pytest.fixture(autouse=True)
def reset_system_pending_state():
    """Ensure clean pending system state before and after each test."""
    system_mod._PENDING_SYSTEM_ACTION = None
    yield
    system_mod._PENDING_SYSTEM_ACTION = None


# ── 1. Browser Tab & Window Control Tests ────────────────────────────────────

def test_browser_close_tab_policy_does_not_require_approval():
    """Closing an individual browser tab is SAFE and does not require approval."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("browser.close_tab", {"tab_title": "YouTube"})
    assert dec.level == PermissionLevel.SAFE
    assert dec.requires_approval is False
    assert dec.is_allowed is True


def test_browser_close_window_policy_requires_approval():
    """Closing an entire browser window strictly requires user approval."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("browser.close_window", {"browser_name": "chrome"})
    assert dec.level == PermissionLevel.APPROVAL_REQUIRED
    assert dec.requires_approval is True
    assert "prevent loss of unsaved work" in dec.reason.lower()


@patch("axon.tools.desktop.keyboard_hotkey")
@patch("axon.tools.browser._focus_browser_window", return_value=True)
def test_browser_close_tab_execution(mock_focus, mock_hotkey):
    """browser.close_tab focuses window and dispatches Ctrl+W hotkey."""
    mock_hotkey.return_value = {"status": "success", "hotkey": "ctrl+w"}

    res = browser_close_tab()
    assert res["status"] == "success"
    assert res["action"] == "closed_tab"
    assert res["method"] == "ctrl_w"
    mock_hotkey.assert_called_once_with("ctrl+w")


@patch("axon.tools.desktop.desktop_close_window")
def test_browser_close_window_execution(mock_close_win):
    """browser.close_window delegates to graceful window close."""
    mock_close_win.return_value = {"status": "success", "closed": True, "method": "wm_close"}

    res = browser_close_window(browser_name="chrome")
    assert res["status"] == "success"
    assert res["action"] == "closed_window"
    assert res["browser"] == "chrome"
    mock_close_win.assert_called_once_with("chrome")


def test_browser_close_window_router_approval_flow():
    """Router enforces approval for browser.close_window."""
    axon = Axon()
    axon.start()

    # Without approval: denied
    res_denied = axon.router.execute("browser.close_window", browser_name="edge")
    assert res_denied["success"] is False
    assert "approval denied" in res_denied["error"].lower()

    # With approval: allowed
    axon.approval.set_prompt(lambda tool, kwargs: True)
    with patch("axon.tools.desktop.desktop_close_window", return_value={"status": "success", "closed": True}):
        res_approved = axon.router.execute("browser.close_window", browser_name="edge")
        assert res_approved["success"] is True

    axon.shutdown()


# ── 2. Application Closing & Safety Tests ────────────────────────────────────

def test_applications_close_requires_approval():
    """Closing applications requires approval to protect unsaved work."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("applications.close", {"name_or_pid": "notepad"})
    assert dec.level == PermissionLevel.APPROVAL_REQUIRED


def test_applications_close_blocks_critical_processes():
    """Attempting to close critical OS processes or AXON itself is blocked."""
    engine = SecurityPolicyEngine()

    # Critical system process
    dec_csrss = engine.evaluate("applications.close", {"name_or_pid": "csrss.exe"})
    assert dec_csrss.level == PermissionLevel.BLOCKED

    # AXON own PID
    dec_self = engine.evaluate("applications.close", {"name_or_pid": str(os.getpid())})
    assert dec_self.level == PermissionLevel.BLOCKED

    # System PID 0
    dec_pid0 = engine.evaluate("applications.close", {"name_or_pid": "0"})
    assert dec_pid0.level == PermissionLevel.BLOCKED


def test_applications_close_empty_name_fails_closed():
    """Calling applications_close with empty or whitespace argument fails closed."""
    res_empty = applications_close("")
    assert "error" in res_empty
    assert "No application name or PID provided" in res_empty["error"]

    res_none = applications_close(None)
    assert "error" in res_none


@patch("subprocess.run")
def test_applications_close_graceful_taskkill_never_forces_by_default(mock_subproc):
    """applications.close runs taskkill without /F by default."""
    mock_subproc.return_value = MagicMock(returncode=0, stdout="SUCCESS: Sent termination signal", stderr="")

    # Mock EnumWindows to not find matching window so it falls back to graceful taskkill
    with patch("ctypes.windll.user32.EnumWindows", return_value=True):
        res = applications_close("notepad")

    assert res["status"] == "success"
    assert res["method"] == "graceful_taskkill"
    call_args = mock_subproc.call_args[0][0]
    assert "/F" not in call_args
    assert "notepad.exe" in call_args


@patch("subprocess.run")
def test_applications_close_force_flag_only_when_explicit(mock_subproc):
    """applications.close only passes /F when force=True is explicitly specified."""
    mock_subproc.return_value = MagicMock(returncode=0, stdout="SUCCESS: Process terminated", stderr="")

    with patch("ctypes.windll.user32.EnumWindows", return_value=True):
        res = applications_close("calc", force=True)

    assert res["status"] == "success"
    assert res["method"] == "force_taskkill"
    call_args = mock_subproc.call_args[0][0]
    assert "/F" in call_args


def test_applications_close_file_explorer_safe_handling():
    """applications.close for File Explorer closes windows without killing explorer.exe process."""
    with patch("ctypes.windll.user32.EnumWindows", return_value=True):
        res = applications_close("File Explorer")
        assert res["status"] == "success"
        assert res["closed"] is False
        assert "No open File Explorer windows found" in res["message"]


# ── 3. System Shutdown & Restart Tests ────────────────────────────────────────

def test_system_shutdown_policy_requires_approval():
    """system.shutdown strictly requires explicit user approval."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("system.shutdown", {"delay_seconds": 30})
    assert dec.level == PermissionLevel.APPROVAL_REQUIRED
    assert dec.requires_approval is True
    assert "shutdown" in dec.reason.lower()
    assert "Continue?" in dec.metadata.get("prompt", "")


def test_system_restart_policy_requires_approval():
    """system.restart strictly requires explicit user approval."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("system.restart", {"delay_seconds": 30})
    assert dec.level == PermissionLevel.APPROVAL_REQUIRED
    assert dec.requires_approval is True
    assert "restart" in dec.reason.lower()
    assert "interrupt running applications" in dec.metadata.get("prompt", "")


def test_system_cancel_shutdown_policy_is_caution():
    """system.cancel_shutdown is safe and does not require approval."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("system.cancel_shutdown")
    assert dec.level == PermissionLevel.CAUTION
    assert dec.requires_approval is False


@patch("subprocess.run")
def test_system_shutdown_execution_mocked(mock_subproc):
    """system_shutdown invokes shutdown.exe /s with sanitized message."""
    mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

    res = system_shutdown(delay_seconds=45, message="Testing shutdown")
    assert res["status"] == "success"
    assert res["action"] == "shutdown"
    assert res["delay_seconds"] == 45

    cmd = mock_subproc.call_args[0][0]
    assert "shutdown.exe" in cmd
    assert "/s" in cmd
    assert "/t" in cmd
    assert "45" in cmd


@patch("subprocess.run")
def test_system_restart_execution_mocked(mock_subproc):
    """system_restart invokes shutdown.exe /r with sanitized message."""
    mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

    res = system_restart(delay_seconds=30, message="Testing restart")
    assert res["status"] == "success"
    assert res["action"] == "restart"
    assert res["delay_seconds"] == 30

    cmd = mock_subproc.call_args[0][0]
    assert "shutdown.exe" in cmd
    assert "/r" in cmd
    assert "/t" in cmd
    assert "30" in cmd


def test_system_shutdown_invalid_delay_arguments():
    """system_shutdown rejects negative, out of bounds, or non-numeric delays."""
    res_neg = system_shutdown(delay_seconds=-10)
    assert "error" in res_neg
    assert "between 0 and 3600" in res_neg["error"]

    res_huge = system_shutdown(delay_seconds=10000)
    assert "error" in res_huge
    assert "between 0 and 3600" in res_huge["error"]

    res_invalid = system_shutdown(delay_seconds="invalid_number")
    assert "error" in res_invalid
    assert "numeric integer" in res_invalid["error"]


@patch("subprocess.run")
def test_duplicate_system_action_prevention(mock_subproc):
    """Duplicate shutdown or restart calls while an action is pending are blocked."""
    mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

    # First shutdown succeeds
    res1 = system_shutdown(delay_seconds=60)
    assert res1["status"] == "success"

    # Second shutdown is blocked as duplicate
    res2 = system_shutdown(delay_seconds=60)
    assert "error" in res2
    assert "already pending" in res2["error"]

    # Restart is also blocked while shutdown is pending
    res3 = system_restart(delay_seconds=60)
    assert "error" in res3
    assert "already pending" in res3["error"]

    # Cancelling pending action allows subsequent actions
    res_cancel = system_cancel_shutdown()
    assert res_cancel["status"] == "success"

    res4 = system_restart(delay_seconds=30)
    assert res4["status"] == "success"


def test_shutdown_router_approval_enforcement():
    """Axon router strictly denies system.shutdown when approval is not granted."""
    axon = Axon()
    axon.start()

    # Default approval prompt is None (denied)
    res_denied = axon.router.execute("system.shutdown", delay_seconds=60)
    assert res_denied["success"] is False
    assert "approval denied" in res_denied["error"].lower()

    # When user grants approval
    axon.approval.set_prompt(lambda tool, kwargs: True)
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        res_approved = axon.router.execute("system.shutdown", delay_seconds=60)
        assert res_approved["success"] is True

    axon.shutdown()


# ── 4. Factory Reset & Terminal Security Tests ───────────────────────────────

def test_terminal_security_blocks_systemreset_and_reagentc():
    """Terminal security strictly blocks Windows factory reset tools."""
    is_allowed1, reason1, _ = inspect_terminal_command("systemreset")
    assert is_allowed1 is False
    assert "factory reset" in reason1.lower()

    is_allowed2, reason2, _ = inspect_terminal_command("systemreset.exe -cleanpc")
    assert is_allowed2 is False

    is_allowed3, reason3, _ = inspect_terminal_command("reagentc /disable")
    assert is_allowed3 is False
    assert "recovery environment" in reason3.lower()


def test_brain_rejects_factory_reset_request():
    """Brain process explicitly rejects requests for destructive factory reset."""
    axon = Axon()
    axon.start()

    resp = axon.brain.process("Perform a factory reset on my PC")
    assert "does not support destructive windows factory reset" in resp.lower()
    assert "safe restart" in resp.lower()

    resp2 = axon.brain.process("Factory reset my computer")
    assert "does not support destructive windows factory reset" in resp2.lower()

    axon.shutdown()


def test_brain_clarifies_reset_computer_vs_factory_reset():
    """Brain process handles 'Reset my PC' by clarifying safe restart vs factory reset."""
    axon = Axon()
    axon.start()

    resp = axon.brain.process("Reset my PC")
    assert "safe restart" in resp.lower()
    assert "factory reset" in resp.lower()

    axon.shutdown()


# ── 5. Security Policy Bypass Prevention ─────────────────────────────────────

def test_security_subsystems_cannot_be_called_or_bypassed_by_ai():
    """AI cannot call tools with 'security' or 'permission' in their name."""
    engine = SecurityPolicyEngine()
    dec = engine.evaluate("security.override_all", {})
    assert dec.level == PermissionLevel.BLOCKED
    assert "cannot directly call or modify security" in dec.reason.lower()
