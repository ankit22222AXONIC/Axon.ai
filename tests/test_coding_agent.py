"""Comprehensive test suite for AXON v0.5 — Coding Agent."""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from axon.core import Axon
from axon.core.config import Config
from axon.ai.router import Intent, IntentRouter
from axon.ai.client import OpenRouterClient
from axon.coding.agent import CodingAgent, CODING_SYSTEM_PROMPT
from axon.coding.context import WorkspaceContext, CodingChangeReport
from axon.coding.tools import (
    coding_list_files,
    coding_read_file,
    coding_search_code,
    coding_create_file,
    coding_edit_file,
    coding_run_tests,
)
from axon.security.policy import SecurityPolicyEngine, PermissionLevel
from axon.security.terminal_security import inspect_terminal_command
from axon.security.path_security import is_within_workspace, check_path_security
from axon.tools.filesystem import filesystem_set_workspace
from axon.tasks.tasks import Task, TaskStatus, StepStatus
from axon.agent.planner import Plan, PlannedStep


# ==============================================================================
# 1. MODEL & INTENT ROUTING TESTS
# ==============================================================================

def test_intent_router_general_queries():
    router = IntentRouter()
    queries = [
        "What's the capital of France?",
        "Explain recursion.",
        "What is recursion?",
        "Explain what an API is.",
        "What is my CPU usage?",
        "Open calculator",
        "Hello AXON, how are you today?",
    ]
    for q in queries:
        intent, reason = router.route(q)
        assert intent == Intent.GENERAL, f"Expected GENERAL for '{q}', got {intent} ({reason})"


def test_intent_router_coding_queries():
    router = IntentRouter()
    queries = [
        "Read main.py and explain the bug.",
        "Fix the login bug in my project.",
        "Create a React component for the dashboard.",
        "Add a function called add that returns the sum of two numbers, then run the tests.",
        "Run pytest to check if tests pass",
        "npm test",
        "Find the bug in this project and fix it.",
        "Inspect project files in this repo",
        "Edit utils.py to handle null values",
        "git status",
        "git diff",
    ]
    for q in queries:
        intent, reason = router.route(q)
        assert intent == Intent.CODING, f"Expected CODING for '{q}', got {intent} ({reason})"


def test_intent_router_safe_fallback():
    router = IntentRouter()
    # Ambiguous or empty input defaults to GENERAL
    assert router.route("")[0] == Intent.GENERAL
    assert router.route("   ")[0] == Intent.GENERAL
    assert router.route("Tell me a story about a dragon")[0] == Intent.GENERAL


# ==============================================================================
# 2. CONFIGURATION & DUAL MODEL TESTS
# ==============================================================================

def test_config_dual_models_defaults():
    cfg = Config()
    assert cfg.get("GENERAL_MODEL") in ("openai/gpt-4o-mini", os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
    assert cfg.get("CODING_MODEL") == os.environ.get("CODING_MODEL", "qwen/qwen-2.5-coder-32b-instruct")


def test_runtime_initializes_dual_clients():
    axon = Axon()
    assert axon.ai_client.model == axon.config.get("GENERAL_MODEL")
    assert axon.coding_client.model == axon.config.get("CODING_MODEL")
    assert axon.coding_agent is not None
    assert axon.intent_router is not None
    assert axon.brain.coding_agent is axon.coding_agent


# ==============================================================================
# 3. WORKSPACE-LOCKED CODING TOOLS TESTS
# ==============================================================================

@pytest.fixture
def test_workspace(tmp_path):
    """Set up an isolated workspace with sample files."""
    old_ws = Path.cwd()
    filesystem_set_workspace(str(tmp_path))

    # Create project layout
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "calc.py").write_text("def add(a, b):\n    return a - b  # bug!\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Test Project\nSample codebase\n", encoding="utf-8")
    
    # Create ignored directories
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "calc.cpython-312.pyc").write_text("bytecode", encoding="utf-8")

    yield tmp_path
    filesystem_set_workspace(str(old_ws))


def test_coding_list_files(test_workspace):
    res = coding_list_files(path=".", recursive=True)
    assert "files" in res
    paths = [f["path"] for f in res["files"]]
    # Normal files should be included
    assert any("calc.py" in p for p in paths)
    assert any("README.md" in p for p in paths)
    # Ignored directory files should NOT be included
    assert not any("__pycache__" in p for p in paths)


def test_coding_read_file_and_lines(test_workspace):
    # Full read
    res = coding_read_file("src/calc.py")
    assert "def add(a, b):" in res["content"]
    assert res["total_lines"] == 2

    # Specific line range
    res_lines = coding_read_file("src/calc.py", start_line=1, end_line=1)
    assert "def add(a, b):" in res_lines["content"]
    assert "return a - b" not in res_lines["content"]


def test_coding_search_code(test_workspace):
    res = coding_search_code(query="def add", path=".")
    assert res["matches_count"] >= 1
    assert any("calc.py" in m["file"] for m in res["matches"])


def test_coding_create_and_edit_file(test_workspace):
    # Create new file
    create_res = coding_create_file("src/helpers.py", "def helper(): pass\n")
    assert create_res["status"] == "success"
    assert (test_workspace / "src" / "helpers.py").exists()

    # Edit file surgically
    edit_res = coding_edit_file("src/calc.py", target="return a - b", replacement="return a + b")
    assert edit_res["status"] == "success"
    assert "return a + b" in (test_workspace / "src" / "calc.py").read_text()


# ==============================================================================
# 4. SECURITY & WORKSPACE BOUNDARY TESTS
# ==============================================================================

def test_workspace_boundary_enforcement(test_workspace):
    # File inside workspace
    inside_path = test_workspace / "src" / "calc.py"
    assert is_within_workspace(inside_path, test_workspace) is True

    # File outside workspace (e.g. system file or parent directory)
    outside_path = test_workspace.parent / "outside_secret.txt"
    assert is_within_workspace(outside_path, test_workspace) is False

    is_safe, reason, _ = check_path_security(
        str(outside_path),
        operation="read",
        workspace_root=test_workspace,
        enforce_workspace=True,
    )
    assert is_safe is False
    assert "escapes workspace" in reason


def test_axon_source_and_env_protection(test_workspace):
    # Attempting to edit .env or axon internal code via policy
    policy = SecurityPolicyEngine(workspace_root=test_workspace)

    dec_env = policy.evaluate("coding.edit_file", {"path": ".env", "target": "a", "replacement": "b"})
    assert dec_env.level == PermissionLevel.BLOCKED

    dec_axon = policy.evaluate("coding.edit_file", {"path": "axon/ai/brain.py", "target": "a", "replacement": "b"})
    assert dec_axon.level == PermissionLevel.BLOCKED


def test_git_destructive_commands_blocked():
    blocked_commands = [
        "git reset --hard",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git clean -f",
        "git push origin main --force",
        "git push -f origin main",
        "git checkout -- .",
        "git branch -D feature",
    ]
    for cmd in blocked_commands:
        is_allowed, reason, _ = inspect_terminal_command(cmd)
        assert is_allowed is False, f"Expected '{cmd}' to be blocked, but was allowed"
        assert "blocked" in reason.lower()

    # Safe read-only Git commands should be allowed
    safe_commands = [
        "git status",
        "git diff",
        "git log -n 5",
        "git branch",
    ]
    for cmd in safe_commands:
        is_allowed, reason, _ = inspect_terminal_command(cmd)
        assert is_allowed is True, f"Expected '{cmd}' to be allowed, but was: {reason}"


# ==============================================================================
# 5. APPROVAL MANAGEMENT TESTS
# ==============================================================================

def test_file_modification_requires_approval(test_workspace):
    axon = Axon()
    axon.start()

    # Attempting to edit an existing file without approval prompt resolving
    calc_path = test_workspace / "src" / "calc.py"
    res = axon.router.execute("coding.edit_file", path=str(calc_path), target="return a - b", replacement="return a + b")

    # Since no approval prompt is set, it defaults to approval required / denied
    assert res["success"] is False
    assert "denied" in res["error"].lower()


def test_approval_granted_modifies_file(test_workspace):
    axon = Axon()
    # Configure auto-approval prompt
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    calc_path = test_workspace / "src" / "calc.py"
    res = axon.router.execute("coding.edit_file", path=str(calc_path), target="return a - b", replacement="return a + b")

    assert res["success"] is True
    assert "return a + b" in calc_path.read_text(encoding="utf-8")


def test_approval_denied_halts_modification(test_workspace):
    axon = Axon()
    # Configure prompt that denies
    axon.approval.set_prompt(lambda tool, kwargs: False)
    axon.start()

    calc_path = test_workspace / "src" / "calc.py"
    original_text = calc_path.read_text(encoding="utf-8")
    res = axon.router.execute("coding.edit_file", path=str(calc_path), target="return a - b", replacement="return a + b")

    assert res["success"] is False
    assert "denied" in res["error"].lower()
    # File content must remain unchanged
    assert calc_path.read_text(encoding="utf-8") == original_text


# ==============================================================================
# 6. AGENT LOOP, VERIFICATION & CHANGE REPORT
# ==============================================================================

def test_coding_change_report_formatting():
    report = CodingChangeReport(
        files_changed=["src/calc.py", "tests/test_calc.py"],
        changes=["Fixed addition bug in add()", "Added test_add() assertion"],
        tests_run=["✓ pytest tests/test_calc.py (2 passed)"],
        final_status="completed",
    )
    summary = report.format_summary()

    assert "Files changed:" in summary
    assert "- src/calc.py" in summary
    assert "Changes:" in summary
    assert "- Fixed addition bug in add()" in summary
    assert "Tests:" in summary
    assert "✓ pytest tests/test_calc.py (2 passed)" in summary
    assert "Status: Completed" in summary


def test_coding_agent_end_to_end_flow(test_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    # Write a test file in the workspace
    test_file = test_workspace / "test_calc.py"
    test_file.write_text(
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # Coding request routed through Brain
    # Using mock on coding_client to avoid live API call during unit tests
    import json
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "goal": "Fix the bug in src/calc.py and run the tests",
                    "steps": [
                        {"description": "Inspect calc.py", "tool": "coding.read_file", "tool_args": {"path": "src/calc.py"}},
                        {"description": "Fix bug in calc.py", "tool": "coding.edit_file", "tool_args": {"path": "src/calc.py", "target": "return a - b", "replacement": "return a + b"}},
                        {"description": "Run tests", "tool": "coding.run_tests", "tool_args": {"command": "python -m pytest test_calc.py"}},
                    ]
                })
            }
        }]
    }

    with patch.object(axon.coding_client, "chat", return_value=mock_response):
        result = axon.brain.process("Fix the bug in src/calc.py and run the tests")

    assert "Coding Task Summary" in result
    assert "src/calc.py" in result
    assert "return a + b" in (test_workspace / "src" / "calc.py").read_text(encoding="utf-8")
