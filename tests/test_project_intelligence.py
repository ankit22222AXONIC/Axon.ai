"""Comprehensive test suite for AXON v0.6 — Project Intelligence."""

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from axon.core import Axon
from axon.coding.project import (
    ProjectInfo,
    ProjectIntelligence,
    MAX_PROJECT_FILES,
    MAX_CONTEXT_FILES,
    MAX_FILE_SIZE,
    MAX_CONTEXT_CHARS,
)
from axon.coding.context import WorkspaceContext
from axon.coding.agent import CodingAgent
from axon.tools.filesystem import filesystem_set_workspace


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def temp_workspace(tmp_path):
    """Provide an isolated workspace for project testing."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    filesystem_set_workspace(str(ws))
    yield ws
    filesystem_set_workspace(str(Path.cwd()))


# ==============================================================================
# 1. PROJECT TYPE DETECTION TESTS
# ==============================================================================

def test_detect_python_project(temp_workspace):
    (temp_workspace / "requirements.txt").write_text("flask>=2.0\npytest\n", encoding="utf-8")
    (temp_workspace / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    assert "Python" in info.languages
    assert "Flask" in info.frameworks
    assert info.package_manager == "pip"
    assert info.test_framework == "pytest"
    assert "app.py" in info.entry_points
    assert "requirements.txt" in info.important_files


def test_detect_node_project(temp_workspace):
    pkg = {
        "name": "my-node-app",
        "version": "1.0.0",
        "main": "server.js",
        "dependencies": {"express": "^4.18.0"},
        "devDependencies": {"jest": "^29.0.0"}
    }
    (temp_workspace / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (temp_workspace / "package-lock.json").write_text("{}", encoding="utf-8")
    (temp_workspace / "server.js").write_text("const express = require('express');\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    assert "JavaScript" in info.languages
    assert info.package_manager == "npm"
    assert info.test_framework == "Jest"
    assert "server.js" in info.entry_points
    assert "package.json" in info.important_files


def test_detect_react_vite_typescript_project(temp_workspace):
    pkg = {
        "name": "react-vite-app",
        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
        "devDependencies": {"vite": "^5.0.0", "vitest": "^1.0.0", "typescript": "^5.0.0"}
    }
    (temp_workspace / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (temp_workspace / "pnpm-lock.yaml").write_text("lockfileVersion: 5.4\n", encoding="utf-8")
    (temp_workspace / "tsconfig.json").write_text("{}", encoding="utf-8")
    (temp_workspace / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")

    src = temp_workspace / "src"
    src.mkdir()
    (src / "main.tsx").write_text("import React from 'react';\n", encoding="utf-8")
    (src / "App.tsx").write_text("export const App = () => <h1>Hello</h1>;\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    assert "TypeScript" in info.languages
    assert "React" in info.frameworks
    assert info.build_system == "Vite"
    assert info.package_manager == "pnpm"
    assert info.test_framework == "Vitest"
    assert "src/main.tsx" in info.entry_points
    assert "vite.config.ts" in info.important_files


def test_detect_nextjs_project(temp_workspace):
    pkg = {
        "name": "nextjs-app",
        "dependencies": {"next": "^14.0.0", "react": "^18.2.0"}
    }
    (temp_workspace / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (temp_workspace / "yarn.lock").write_text("", encoding="utf-8")
    (temp_workspace / "next.config.js").write_text("module.exports = {};\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    assert "Next.js" in info.frameworks
    assert "React" in info.frameworks
    assert info.package_manager == "yarn"
    assert info.build_system == "Next.js"


def test_detect_unknown_project(temp_workspace):
    (temp_workspace / "notes.txt").write_text("Just some notes.", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    assert info.languages == []
    assert info.frameworks == []
    assert info.package_manager is None
    assert info.test_framework is None
    assert info.entry_points == []


# ==============================================================================
# 2. LANGUAGE DETECTION & IGNORED DIRECTORIES
# ==============================================================================

def test_language_detection_ignores_vendor_and_cache(temp_workspace):
    src = temp_workspace / "src"
    src.mkdir()
    (src / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")

    # Create ignored folders containing other languages
    node_modules = temp_workspace / "node_modules" / "some_pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("console.log('vendor');\n", encoding="utf-8")

    pycache = temp_workspace / "__pycache__"
    pycache.mkdir()
    (pycache / "calc.cpython-312.pyc").write_text("binary", encoding="utf-8")

    git_dir = temp_workspace / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    assert info.languages == ["Python"]
    assert "JavaScript" not in info.languages
    assert "Shell" not in info.languages


def test_mixed_language_detection(temp_workspace):
    (temp_workspace / "main.py").write_text("print('hello')", encoding="utf-8")
    (temp_workspace / "script.js").write_text("console.log('hi')", encoding="utf-8")
    (temp_workspace / "types.ts").write_text("type ID = string;", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    langs = intel.analyze().languages

    assert "Python" in langs
    assert "JavaScript" in langs
    assert "TypeScript" in langs


# ==============================================================================
# 3. PACKAGE MANAGER DETECTION
# ==============================================================================

def test_package_manager_precedence(temp_workspace):
    intel = ProjectIntelligence(temp_workspace)

    # 1. pnpm
    (temp_workspace / "package.json").write_text("{}", encoding="utf-8")
    (temp_workspace / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert intel.analyze(refresh=True).package_manager == "pnpm"

    # 2. yarn
    (temp_workspace / "pnpm-lock.yaml").unlink()
    (temp_workspace / "yarn.lock").write_text("", encoding="utf-8")
    assert intel.analyze(refresh=True).package_manager == "yarn"

    # 3. npm lockfile
    (temp_workspace / "yarn.lock").unlink()
    (temp_workspace / "package-lock.json").write_text("{}", encoding="utf-8")
    assert intel.analyze(refresh=True).package_manager == "npm"

    # 4. poetry
    (temp_workspace / "package.json").unlink()
    (temp_workspace / "package-lock.json").unlink()
    (temp_workspace / "poetry.lock").write_text("", encoding="utf-8")
    assert intel.analyze(refresh=True).package_manager == "poetry"

    # 5. pip via requirements.txt
    (temp_workspace / "poetry.lock").unlink()
    (temp_workspace / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert intel.analyze(refresh=True).package_manager == "pip"


# ==============================================================================
# 4. STRUCTURE MAPPING TESTS
# ==============================================================================

def test_structure_map_bounded_depth_and_filtering(temp_workspace):
    # Create multi-level hierarchy
    deep_path = temp_workspace / "level1" / "level2" / "level3" / "level4"
    deep_path.mkdir(parents=True)
    (deep_path / "deep.txt").write_text("too deep", encoding="utf-8")

    src = temp_workspace / "src"
    src.mkdir()
    (src / "app.py").write_text("# app", encoding="utf-8")
    (temp_workspace / "README.md").write_text("# Project", encoding="utf-8")

    # Ignored directories
    (temp_workspace / ".git").mkdir()
    (temp_workspace / ".git" / "config").write_text("git config", encoding="utf-8")
    (temp_workspace / "node_modules").mkdir()
    (temp_workspace / "node_modules" / "dummy.js").write_text("dummy", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    struct = intel.build_structure_map(max_depth=3)

    assert "src/" in struct
    assert "app.py" in struct
    assert "README.md" in struct
    # Ignored directories must not be present
    assert "node_modules" not in struct
    assert ".git" not in struct
    # Depth 4 file should not be reached
    assert "deep.txt" not in struct


# ==============================================================================
# 5. DEPENDENCY AWARENESS TESTS
# ==============================================================================

def test_dependency_extraction(temp_workspace):
    # Test requirements.txt with complex version specs
    reqs = (
        "# Comments should be ignored\n"
        "Flask>=2.0.1\n"
        "requests~=2.28.0\n"
        "pytest>=7.0.0; python_version > '3.8'\n"
        "celery\n"
    )
    (temp_workspace / "requirements.txt").write_text(reqs, encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    deps = intel.analyze().dependencies

    assert "flask" in deps
    assert "requests" in deps
    assert "pytest" in deps
    assert "celery" in deps


# ==============================================================================
# 6. SMART CONTEXT & RELEVANCE SCORING TESTS
# ==============================================================================

def test_smart_context_relevant_files_scoring(temp_workspace):
    src = temp_workspace / "src"
    src.mkdir()
    auth_file = src / "auth.py"
    auth_file.write_text("def login(): pass\ndef authenticate_user(): pass\n", encoding="utf-8")
    db_file = src / "database.py"
    db_file.write_text("def get_db(): pass\n", encoding="utf-8")
    ui_file = src / "components.jsx"
    ui_file.write_text("export const Card = () => null;\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)

    # Query targeting authentication
    relevant = intel.find_relevant_files("Fix the authentication login issue", max_files=5)
    assert "src/auth.py" in relevant
    # database and components should rank lower than auth.py
    assert relevant[0] == "src/auth.py"

    # Query targeting database
    relevant_db = intel.find_relevant_files("Update database connection logic", max_files=5)
    assert "src/database.py" in relevant_db


def test_context_budget_limits_respected(temp_workspace):
    # Create large file (> MAX_FILE_SIZE)
    large_file = temp_workspace / "large_data.py"
    large_content = "# Data definition\n" + ("x = 1\n" * 10_000)  # ~60KB
    large_file.write_text(large_content, encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    context_str = intel.format_model_context("Inspect large_data.py")

    # Entire formatted context must not exceed MAX_CONTEXT_CHARS
    assert len(context_str) <= MAX_CONTEXT_CHARS
    assert "PROJECT:" in context_str
    assert "RELEVANT FILES:" in context_str
    assert "large_data.py" in context_str


# ==============================================================================
# 7. SECURITY & WORKSPACE CONFINEMENT TESTS
# ==============================================================================

def test_security_protects_env_and_secrets(temp_workspace):
    # Create sensitive files in workspace
    (temp_workspace / ".env").write_text("SECRET_KEY=verysecret123\nAPI_KEY=token999\n", encoding="utf-8")
    (temp_workspace / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----", encoding="utf-8")
    (temp_workspace / "main.py").write_text("print('safe')\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    info = intel.analyze()

    # Sensitive files must never appear in important files or entry points
    assert ".env" not in info.important_files
    assert "id_rsa" not in info.important_files
    assert ".env" not in info.structure_map
    assert "id_rsa" not in info.structure_map

    # Model context must never leak .env contents
    context = intel.format_model_context("Check environment variables")
    assert "SECRET_KEY" not in context
    assert "verysecret123" not in context


def test_security_cannot_scan_outside_workspace(temp_workspace, tmp_path):
    # Outside directory
    outside_dir = tmp_path / "outside_project"
    outside_dir.mkdir()
    (outside_dir / "secret_doc.txt").write_text("top secret", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)
    relevant = intel.find_relevant_files(f"Read {outside_dir}/secret_doc.txt")

    # File outside workspace must not be included
    for r in relevant:
        assert not Path(r).is_absolute()
        assert not (temp_workspace / r).resolve().is_relative_to(outside_dir.resolve())


# ==============================================================================
# 8. IN-MEMORY CACHING TESTS
# ==============================================================================

def test_in_memory_cache_and_invalidation(temp_workspace):
    (temp_workspace / "main.py").write_text("print('v1')", encoding="utf-8")
    intel = ProjectIntelligence(temp_workspace)

    info1 = intel.analyze()
    info2 = intel.analyze()
    assert info1 is info2  # Same object returned from cache

    # Invalidate cache
    intel.invalidate_cache()
    info3 = intel.analyze()
    assert info3 is not info1
    assert info3.languages == ["Python"]


# ==============================================================================
# 9. WORKSPACE CONTEXT & CODING AGENT INTEGRATION
# ==============================================================================

def test_workspace_context_backward_compatibility(temp_workspace):
    (temp_workspace / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
    (temp_workspace / "calc.py").write_text("def multiply(a, b): return a * b\n", encoding="utf-8")

    ctx = WorkspaceContext(temp_workspace)
    proj_type = ctx.detect_project_type()

    assert proj_type["is_python"] is True
    assert proj_type["is_node"] is False
    assert proj_type["default_test_cmd"] == "python -m pytest"
    assert "Python" in proj_type["languages"]


def test_coding_agent_uses_project_intelligence(temp_workspace):
    axon = Axon()
    axon.approval.set_prompt(lambda tool, kwargs: True)
    axon.start()
    filesystem_set_workspace(str(temp_workspace))

    # Set up Python project
    (temp_workspace / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (temp_workspace / "math_utils.py").write_text("def subtract(a, b): return a - b\n", encoding="utf-8")
    (temp_workspace / "test_math.py").write_text(
        "from math_utils import subtract\ndef test_sub(): assert subtract(5, 2) == 3\n",
        encoding="utf-8",
    )

    # Track emitted events
    events_received = []
    axon.events.on("PROJECT_ANALYZED", lambda e: events_received.append(e.data))

    mock_plan = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "goal": "Fix subtraction in math_utils.py and test",
                    "steps": [
                        {"description": "Inspect math_utils.py", "tool": "coding.read_file", "tool_args": {"path": "math_utils.py"}},
                        {"description": "Run tests", "tool": "coding.run_tests", "tool_args": {"command": "python -m pytest test_math.py"}},
                    ]
                })
            }
        }]
    }

    with patch.object(axon.coding_client, "chat", return_value=mock_plan):
        result = axon.coding_agent.handle("Fix subtraction in math_utils.py and run the tests")

    # Verify PROJECT_ANALYZED event was emitted with project metadata
    assert len(events_received) >= 1
    assert "Python" in events_received[0]["languages"]
    assert events_received[0]["test_framework"] == "pytest"
    assert "math_utils.py" in result


# ==============================================================================
# 10. REAL INTEGRATION TEST (SPEC SECTION 21)
# ==============================================================================

def test_real_project_inspection_and_context(temp_workspace):
    """Real integration test verifying project detection, relevant file discovery, and task execution."""
    # Build sample test project
    pkg = {
        "name": "sample-app",
        "version": "1.0.0",
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"vitest": "^1.0.0"}
    }
    (temp_workspace / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    (temp_workspace / "package-lock.json").write_text("{}", encoding="utf-8")

    src = temp_workspace / "src"
    src.mkdir()
    (src / "App.jsx").write_text("import React from 'react';\nexport function App() { return <div>Hello</div>; }\n", encoding="utf-8")
    (src / "utils.js").write_text("export function formatName(name) { return name.trim(); }\n", encoding="utf-8")

    tests_dir = temp_workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "utils.test.js").write_text("import { formatName } from '../src/utils';\n", encoding="utf-8")

    intel = ProjectIntelligence(temp_workspace)

    # 1. Verify project analysis
    info = intel.analyze()
    assert "JavaScript" in info.languages
    assert "React" in info.frameworks
    assert info.package_manager == "npm"
    assert info.test_framework == "Vitest"
    assert "src/App.jsx" in info.entry_points
    assert "package.json" in info.important_files

    # 2. Verify relevant files for App component without scanning irrelevant parts
    relevant_app = intel.find_relevant_files("Find the relevant files for the App component")
    assert "src/App.jsx" in relevant_app
    assert relevant_app[0] == "src/App.jsx"

    # 3. Verify relevant files for utils
    relevant_utils = intel.find_relevant_files("Add a simple function to utils.js and run the tests")
    assert "src/utils.js" in relevant_utils
