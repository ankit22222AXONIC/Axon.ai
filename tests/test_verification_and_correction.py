"""Comprehensive test suite for AXON v0.7 — Verification & Self-Correction."""

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from axon.core import Axon
from axon.core.runtime import AxonStatus
from axon.agent.planner import Plan, PlannedStep
from axon.tasks.tasks import Task, TaskStatus, StepStatus
from axon.coding.project import ProjectInfo, ProjectIntelligence
from axon.coding.verification import (
    VerificationResult,
    WorkspaceRollback,
    ErrorAnalyzer,
    BuildTestVerifier,
)
from axon.coding.tools import coding_run_build
from axon.security.policy import PermissionLevel
from axon.tools.filesystem import filesystem_set_workspace


@pytest.fixture
def test_workspace(tmp_path):
    """Fixture to provide a clean temporary workspace for coding verification tests."""
    ws = tmp_path / "test_project"
    ws.mkdir(parents=True, exist_ok=True)
    filesystem_set_workspace(str(ws))

    # Add pytest.ini to ensure workspace root is on pythonpath for subtests
    (ws / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    # Create dummy source and test structure
    src_dir = ws / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    calc_file = src_dir / "calc.py"
    calc_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    yield ws
    filesystem_set_workspace(None)


# ==============================================================================
# 1. COMMAND DETECTION (TEST & BUILD)
# ==============================================================================

def test_detect_python_test_command(test_workspace):
    router = MagicMock()
    verifier = BuildTestVerifier(router)
    proj_info = ProjectInfo(
        root=str(test_workspace),
        name="demo",
        languages=["python"],
        test_framework="pytest",
    )
    cmd = verifier.detect_test_command(proj_info, test_workspace)
    assert cmd == "python -m pytest"


def test_detect_npm_test_and_build(test_workspace):
    pkg_json = test_workspace / "package.json"
    pkg_json.write_text(json.dumps({
        "name": "demo-app",
        "scripts": {
            "test": "jest",
            "build": "vite build"
        }
    }), encoding="utf-8")

    router = MagicMock()
    verifier = BuildTestVerifier(router)
    proj_info = ProjectInfo(
        root=str(test_workspace),
        name="demo-app",
        languages=["javascript"],
        package_manager="npm",
        build_system="Vite",
        test_framework="jest",
    )

    test_cmd = verifier.detect_test_command(proj_info, test_workspace)
    build_cmd = verifier.detect_build_command(proj_info, test_workspace)

    assert test_cmd == "npm test"
    assert build_cmd == "npm run build"


def test_detect_cargo_test_and_build(test_workspace):
    cargo_toml = test_workspace / "Cargo.toml"
    cargo_toml.write_text('[package]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")

    router = MagicMock()
    verifier = BuildTestVerifier(router)
    proj_info = ProjectInfo(root=str(test_workspace), name="demo", languages=["rust"])

    assert verifier.detect_test_command(proj_info, test_workspace) == "cargo test"
    assert verifier.detect_build_command(proj_info, test_workspace) == "cargo build"


# ==============================================================================
# 2. ERROR ANALYZER
# ==============================================================================

def test_error_analyzer_python_traceback(test_workspace):
    tb_output = """
Traceback (most recent call last):
  File "src/calc.py", line 2, in add
    return a + c
NameError: name 'c' is not defined
"""
    analysis = ErrorAnalyzer.analyze(tb_output, test_workspace)
    assert "src/calc.py" in analysis["affected_files"]
    assert len(analysis["errors"]) >= 1
    err = analysis["errors"][0]
    assert err["file"] == "src/calc.py"
    assert err["line"] == 2
    assert "NameError" in err["type"]


def test_error_analyzer_pytest_failure(test_workspace):
    pytest_output = """
============================= test session starts =============================
FAILED tests/test_calc.py::test_add - AssertionError: assert -1 == 5
============================== 1 failed in 0.05s ==============================
"""
    analysis = ErrorAnalyzer.analyze(pytest_output, test_workspace)
    assert "tests/test_calc.py" in analysis["affected_files"]
    assert "tests/test_calc.py" in analysis["summary"]


def test_error_analyzer_typescript_error(test_workspace):
    ts_output = "src/index.ts:15:7 - error TS2322: Type 'string' is not assignable to type 'number'."
    analysis = ErrorAnalyzer.analyze(ts_output, test_workspace)
    assert "src/index.ts" in analysis["affected_files"]
    assert analysis["errors"][0]["line"] == 15
    assert "TS2322" in analysis["errors"][0]["type"]


# ==============================================================================
# 3. WORKSPACE ROLLBACK
# ==============================================================================

def test_workspace_rollback_restores_modified_file(test_workspace):
    calc_path = test_workspace / "src" / "calc.py"
    original_code = calc_path.read_text(encoding="utf-8")

    rollback = WorkspaceRollback(test_workspace)
    # Snapshot before modification
    assert rollback.snapshot("src/calc.py") is True
    assert rollback.has_snapshots() is True

    # Modify file
    calc_path.write_text("BROKEN CODE CORRUPTING EVERYTHING", encoding="utf-8")
    assert calc_path.read_text(encoding="utf-8") == "BROKEN CODE CORRUPTING EVERYTHING"

    # Rollback
    result = rollback.rollback()
    assert result["success"] is True
    assert "src/calc.py" in result["restored"]
    assert calc_path.read_text(encoding="utf-8") == original_code
    assert rollback.has_snapshots() is False


def test_workspace_rollback_deletes_newly_created_file(test_workspace):
    rollback = WorkspaceRollback(test_workspace)
    new_file_rel = "src/temp_broken.py"
    new_file_path = test_workspace / "src" / "temp_broken.py"

    # Snapshot non-existent file
    rollback.snapshot(new_file_rel)
    new_file_path.write_text("def broken(): pass", encoding="utf-8")
    assert new_file_path.exists() is True

    # Rollback removes created file
    result = rollback.rollback()
    assert result["success"] is True
    assert new_file_rel in result["deleted"]
    assert new_file_path.exists() is False


def test_workspace_rollback_respects_boundary_and_secrets(test_workspace):
    rollback = WorkspaceRollback(test_workspace)

    # Outside workspace path
    outside_file = str(Path(tempfile.gettempdir()).resolve() / "outside_test.txt")
    assert rollback.snapshot(outside_file) is False

    # Sensitive credential file
    env_file = test_workspace / ".env"
    env_file.write_text("SECRET=12345", encoding="utf-8")
    assert rollback.snapshot(".env") is False


# ==============================================================================
# 4. CODING_RUN_BUILD TOOL & PERMISSIONS
# ==============================================================================

def test_coding_run_build_execution(test_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    # Run benign build command
    res = axon.router.execute("coding.run_build", command="python -c \"print('Build successful')\"")
    assert res["success"] is True
    assert res["result"]["exit_code"] == 0
    assert "Build successful" in res["result"]["output"]


def test_coding_run_build_blocks_dangerous_commands(test_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    res = axon.router.execute("coding.run_build", command="git reset --hard")
    assert res["success"] is False
    assert "blocked" in res["error"].lower()


# ==============================================================================
# 5. CODING AGENT VERIFICATION & SELF-CORRECTION E2E
# ==============================================================================

def test_verification_success_clean_flow(test_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    test_file = test_workspace / "test_calc.py"
    test_file.write_text(
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "goal": "Fix addition in src/calc.py",
                    "steps": [
                        {"description": "Inspect calc.py", "tool": "coding.read_file", "tool_args": {"path": "src/calc.py"}},
                        {"description": "Fix bug in calc.py", "tool": "coding.edit_file", "tool_args": {"path": "src/calc.py", "target": "return a - b", "replacement": "return a + b"}},
                    ]
                })
            }
        }]
    }

    with patch.object(axon.coding_client, "chat", return_value=mock_response):
        result = axon.coding_agent.handle("Fix addition in src/calc.py")

    assert "Coding Task Summary" in result
    assert "src/calc.py" in result
    assert "return a + b" in (test_workspace / "src" / "calc.py").read_text(encoding="utf-8")


def test_self_correction_fixes_bug_on_retry(test_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    test_file = test_workspace / "test_calc.py"
    test_file.write_text(
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # Plan 1: faulty edit (changes return a - b to return a * b)
    plan1_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "goal": "Fix addition bug",
                    "steps": [
                        {"description": "Edit calc.py with wrong logic", "tool": "coding.edit_file", "tool_args": {"path": "src/calc.py", "target": "return a - b", "replacement": "return a * b"}},
                    ]
                })
            }
        }]
    }

    # Plan 2 (correction attempt 1): fixes logic to return a + b
    plan2_correction_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "goal": "Fix verification failure in src/calc.py",
                    "steps": [
                        {"description": "Fix multiplication to addition", "tool": "coding.edit_file", "tool_args": {"path": "src/calc.py", "target": "return a * b", "replacement": "return a + b"}},
                    ]
                })
            }
        }]
    }

    call_count = 0
    def mock_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return plan1_response
        return plan2_correction_response

    with patch.object(axon.coding_client, "chat", side_effect=mock_chat):
        result = axon.coding_agent.handle("Fix addition bug in src/calc.py")

    assert "Coding Task Summary" in result
    assert "self-correction" in result.lower()
    assert "return a + b" in (test_workspace / "src" / "calc.py").read_text(encoding="utf-8")


def test_self_correction_fails_stops_at_3_and_rolls_back(test_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()

    calc_path = test_workspace / "src" / "calc.py"
    original_content = calc_path.read_text(encoding="utf-8")

    test_file = test_workspace / "test_calc.py"
    test_file.write_text(
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    # Every response tries bad code that will never satisfy the test
    persistent_bad_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "goal": "Attempt fix",
                    "steps": [
                        {"description": "Corrupt calc.py", "tool": "coding.edit_file", "tool_args": {"path": "src/calc.py", "target": "return a - b", "replacement": "return 'syntax_error'"}},
                    ]
                })
            }
        }]
    }

    attempts_recorded = []
    def on_attempt(event):
        attempts_recorded.append(event.data.get("attempt"))

    axon.events.on("SELF_CORRECTION_ATTEMPT", on_attempt)

    with patch.object(axon.coding_client, "chat", return_value=persistent_bad_response):
        result = axon.coding_agent.handle("Fix src/calc.py")

    # Must have attempted up to 3 times
    assert len(attempts_recorded) == 3
    assert attempts_recorded == [1, 2, 3]

    # Verification failed and rollback restored original content!
    assert calc_path.read_text(encoding="utf-8") == original_content
    assert "Rollback" in result or "rolled back" in result.lower()
    assert "Verification failed after 3 self-correction attempt" in result
