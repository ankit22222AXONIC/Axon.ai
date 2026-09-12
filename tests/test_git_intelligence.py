"""Comprehensive test suite for AXON v0.8 — Git Intelligence.

Verifies:
1. Git repository and GitHub remote detection
2. Status, diff, and log operations with structured output
3. Branch listing, creation, and deletion blocking
4. Safe checkout and switch operations
5. Pre-commit secret scanning & .env blocking
6. Changed files preview before commit
7. Mandatory approval requirements for git.commit and git.push
8. Destructive command blocking (force-push, reset --hard, clean -f, branch -D)
9. Pull safety preventing overwrite of uncommitted changes
10. Safe rollback via Git
11. Clean error handling when directory is not a Git repo
"""

import os
import subprocess
import pytest
from pathlib import Path

from axon.core import Axon
from axon.ai.router import IntentRouter, Intent
from axon.security.policy import SecurityPolicyEngine, PermissionLevel
from axon.security import Permission
from axon.tools.filesystem import filesystem_set_workspace
from axon.tools.git import (
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_branch,
    git_checkout,
    git_switch,
    git_pull,
    git_push,
    git_info,
    git_safe_rollback,
)


def _init_test_git_repo(repo_dir: Path) -> Path:
    """Initialize a clean Git repository with test user config for commit tests."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "AxonTester"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@axon.ai"], cwd=str(repo_dir), capture_output=True, check=True)
    return repo_dir


@pytest.fixture
def git_workspace(tmp_path):
    """Fixture providing an active Git workspace."""
    repo_dir = tmp_path / "git_project"
    _init_test_git_repo(repo_dir)
    filesystem_set_workspace(str(repo_dir))
    yield repo_dir
    filesystem_set_workspace(None)


# ==============================================================================
# 1. TOOL REGISTRATION & SECURITY APPROVAL
# ==============================================================================

def test_git_tools_registered_in_axon():
    axon = Axon()
    axon.start()

    expected_tools = [
        "git.status",
        "git.diff",
        "git.log",
        "git.commit",
        "git.branch",
        "git.checkout",
        "git.switch",
        "git.pull",
        "git.push",
        "git.info",
        "git.rollback",
    ]
    for tool_name in expected_tools:
        assert axon.registry.has(tool_name), f"Tool '{tool_name}' should be registered"

    # Verify security permission requirements
    assert axon.security.get_permission("git.commit") == Permission.APPROVAL_REQUIRED
    assert axon.security.get_permission("git.push") == Permission.APPROVAL_REQUIRED
    assert axon.security.get_permission("git.rollback") == Permission.APPROVAL_REQUIRED


def test_git_security_policy_evaluation():
    engine = SecurityPolicyEngine()

    # Read-only operations are SAFE
    assert engine.evaluate("git.status").level == PermissionLevel.SAFE
    assert engine.evaluate("git.diff").level == PermissionLevel.SAFE
    assert engine.evaluate("git.log").level == PermissionLevel.SAFE
    assert engine.evaluate("git.info").level == PermissionLevel.SAFE
    assert engine.evaluate("git.branch").level == PermissionLevel.SAFE

    # Branch creation is CAUTION
    assert engine.evaluate("git.branch", {"name": "feature-x"}).level == PermissionLevel.CAUTION

    # Checkout / switch are CAUTION
    assert engine.evaluate("git.checkout", {"target": "main"}).level == PermissionLevel.CAUTION
    assert engine.evaluate("git.switch", {"branch": "main"}).level == PermissionLevel.CAUTION

    # Pull is CAUTION
    assert engine.evaluate("git.pull").level == PermissionLevel.CAUTION

    # Commit requires approval
    assert engine.evaluate("git.commit", {"message": "feat: test"}).level == PermissionLevel.APPROVAL_REQUIRED

    # Push ALWAYS requires approval
    assert engine.evaluate("git.push", {"remote": "origin", "branch": "main"}).level == PermissionLevel.APPROVAL_REQUIRED

    # Rollback requires approval
    assert engine.evaluate("git.rollback", {"file_path": "main.py"}).level == PermissionLevel.APPROVAL_REQUIRED


# ==============================================================================
# 2. DESTRUCTIVE COMMAND BLOCKING & PUSH SAFETY
# ==============================================================================

def test_git_push_blocks_force_flag():
    engine = SecurityPolicyEngine()

    # Direct force flag
    decision1 = engine.evaluate("git.push", {"force": True})
    assert decision1.level == PermissionLevel.BLOCKED
    assert "force" in decision1.reason.lower()

    # --force in remote or branch argument
    decision2 = engine.evaluate("git.push", {"remote": "origin", "branch": "main --force"})
    assert decision2.level == PermissionLevel.BLOCKED

    decision3 = engine.evaluate("git.push", {"remote": "origin", "branch": "-f"})
    assert decision3.level == PermissionLevel.BLOCKED

    # Refspec with force '+'
    decision4 = engine.evaluate("git.push", {"remote": "origin", "branch": "+main:main"})
    assert decision4.level == PermissionLevel.BLOCKED


def test_git_push_blocks_force_in_tool(git_workspace):
    res = git_push(remote="origin", branch="main", force=True)
    assert res["success"] is False
    assert "BLOCKED" in res["error"]

    res2 = git_push(remote="origin", branch="main --force")
    assert res2["success"] is False
    assert "BLOCKED" in res2["error"]


def test_git_branch_blocks_deletion():
    engine = SecurityPolicyEngine()
    decision = engine.evaluate("git.branch", {"delete": "main"})
    assert decision.level == PermissionLevel.BLOCKED

    decision2 = engine.evaluate("git.branch", {"name": "-D main"})
    assert decision2.level == PermissionLevel.BLOCKED

    res = git_branch(delete="some-branch")
    assert res["success"] is False
    assert "BLOCKED" in res["error"]


def test_git_checkout_blocks_wipe_and_hard_flags():
    engine = SecurityPolicyEngine()
    decision = engine.evaluate("git.checkout", {"target": "-- ."})
    assert decision.level == PermissionLevel.BLOCKED

    decision2 = engine.evaluate("git.checkout", {"target": "."})
    assert decision2.level == PermissionLevel.BLOCKED

    res = git_checkout(target="-- .")
    assert res["success"] is False
    assert "BLOCKED" in res["error"]


# ==============================================================================
# 3. NON-GIT DIRECTORY ERROR HANDLING
# ==============================================================================

def test_git_operations_handle_non_git_repo(tmp_path):
    non_git_dir = tmp_path / "regular_folder"
    non_git_dir.mkdir()
    filesystem_set_workspace(str(non_git_dir))

    st = git_status()
    assert st["success"] is False
    assert st["is_git_repo"] is False
    assert "not a git repository" in st["error"].lower()

    diff = git_diff()
    assert diff["success"] is False

    log = git_log()
    assert log["success"] is False

    info = git_info()
    assert info["success"] is False
    assert info["is_git_repo"] is False


# ==============================================================================
# 4. STATUS, DIFF, COMMIT, AND LOG OPERATIONS
# ==============================================================================

def test_git_status_and_commit_flow(git_workspace):
    # Check initial clean status
    st = git_status()
    assert st["success"] is True
    assert st["is_clean"] is True
    assert st["untracked"] == []

    # Create a new file
    test_file = git_workspace / "app.py"
    test_file.write_text("print('hello axon')", encoding="utf-8")

    st = git_status()
    assert st["success"] is True
    assert st["is_clean"] is False
    assert "app.py" in st["untracked"]

    # Commit the file
    res = git_commit(message="Initial commit", files=["app.py"])
    assert res["success"] is True
    assert "commit_hash" in res
    assert res["files_count"] == 1
    assert res["changed_files"][0]["path"] == "app.py"

    # Status should now be clean
    st = git_status()
    assert st["is_clean"] is True

    # Make a change and test diff
    test_file.write_text("print('hello axon v0.8')", encoding="utf-8")
    diff_res = git_diff()
    assert diff_res["success"] is True
    assert diff_res["has_changes"] is True
    assert "+print('hello axon v0.8')" in diff_res["diff"]

    # Check git log
    log_res = git_log(limit=5)
    assert log_res["success"] is True
    assert len(log_res["commits"]) >= 1
    assert log_res["commits"][0]["subject"] == "Initial commit"
    assert log_res["commits"][0]["author"] == "AxonTester"


def test_git_commit_requires_staged_changes(git_workspace):
    res = git_commit(message="Empty commit")
    assert res["success"] is False
    assert "no changes staged" in res["error"].lower()


# ==============================================================================
# 5. SECRET PROTECTION & SENSITIVE FILE BLOCKING
# ==============================================================================

def test_git_commit_blocks_env_file(git_workspace):
    env_file = git_workspace / ".env"
    env_file.write_text("SECRET_KEY=supersecret", encoding="utf-8")

    # Staging via files argument
    res = git_commit(message="Add env", files=[".env"])
    assert res["success"] is False
    assert "BLOCKED" in res["error"]
    assert "sensitive credential" in res["error"].lower()


def test_git_commit_blocks_staged_env_file_with_stage_all(git_workspace):
    env_file = git_workspace / ".env.local"
    env_file.write_text("DATABASE_URL=postgres://localhost", encoding="utf-8")

    res = git_commit(message="Add all", stage_all=True)
    assert res["success"] is False
    assert "BLOCKED" in res["error"]
    assert ".env.local" in res["error"]


def test_git_commit_blocks_hardcoded_credentials_in_diff(git_workspace):
    code_file = git_workspace / "config.py"
    code_file.write_text(
        'OPENAI_API_KEY = "sk-1234567890abcdef1234567890abcdef"\n',
        encoding="utf-8",
    )

    res = git_commit(message="Add secret key", files=["config.py"])
    assert res["success"] is False
    assert "BLOCKED" in res["error"]
    assert "credentials" in res["error"].lower()


# ==============================================================================
# 6. BRANCH & SWITCH OPERATIONS
# ==============================================================================

def test_git_branch_and_switch(git_workspace):
    # Initial commit needed so branch exists
    (git_workspace / "init.txt").write_text("init", encoding="utf-8")
    git_commit(message="Initial commit", stage_all=True)

    # Create new branch
    b_res = git_branch(name="feature/v08")
    assert b_res["success"] is True

    # List branches
    list_res = git_branch()
    assert list_res["success"] is True
    assert "feature/v08" in list_res["branches"]

    # Switch branch
    sw_res = git_switch(branch="feature/v08")
    assert sw_res["success"] is True
    assert sw_res["branch"] == "feature/v08"

    # Verify active branch
    st = git_status()
    assert st["branch"] == "feature/v08"


# ==============================================================================
# 7. PULL SAFETY — BLOCK WHEN UNCOMMITTED CHANGES EXIST
# ==============================================================================

def test_git_pull_refuses_when_uncommitted_changes_exist(git_workspace):
    tracked = git_workspace / "tracked.txt"
    tracked.write_text("v1", encoding="utf-8")
    git_commit(message="v1", stage_all=True)

    # Modify tracked file without committing
    tracked.write_text("v2 uncommitted", encoding="utf-8")

    pull_res = git_pull(remote="origin", branch="main")
    assert pull_res["success"] is False
    assert "uncommitted local changes" in pull_res["error"]


# ==============================================================================
# 8. GITHUB REMOTE / REPOSITORY DETECTION
# ==============================================================================

def test_github_remote_detection_https(git_workspace):
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/deepmind/axon-core.git"],
        cwd=str(git_workspace),
        capture_output=True,
        check=True,
    )

    info = git_info()
    assert info["success"] is True
    assert info["is_github"] is True
    assert info["github"]["owner"] == "deepmind"
    assert info["github"]["repo"] == "axon-core"
    assert info["github"]["url"] == "https://github.com/deepmind/axon-core"


def test_github_remote_detection_ssh(git_workspace):
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:octocat/Hello-World.git"],
        cwd=str(git_workspace),
        capture_output=True,
        check=True,
    )

    info = git_info()
    assert info["success"] is True
    assert info["is_github"] is True
    assert info["github"]["owner"] == "octocat"
    assert info["github"]["repo"] == "Hello-World"


# ==============================================================================
# 9. SAFE ROLLBACK USING GIT
# ==============================================================================

def test_git_safe_rollback_single_file(git_workspace):
    target = git_workspace / "code.py"
    target.write_text("stable code", encoding="utf-8")
    git_commit(message="stable code", stage_all=True)

    # Make broken edit
    target.write_text("broken code", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "broken code"

    # Revert specific file
    res = git_safe_rollback(file_path="code.py")
    assert res["success"] is True
    assert res["action"] == "reverted_file"
    assert target.read_text(encoding="utf-8") == "stable code"


def test_git_safe_rollback_blocks_workspace_wipe(git_workspace):
    res = git_safe_rollback(file_path=".")
    assert res["success"] is False
    assert "BLOCKED" in res["error"]


def test_git_safe_rollback_revert_commit(git_workspace):
    f1 = git_workspace / "f1.txt"
    f1.write_text("f1", encoding="utf-8")
    git_commit(message="add f1", stage_all=True)

    f2 = git_workspace / "f2.txt"
    f2.write_text("f2", encoding="utf-8")
    c2 = git_commit(message="add f2", stage_all=True)
    c2_hash = c2["commit_hash"]

    # Safely revert c2
    res = git_safe_rollback(commit=c2_hash)
    assert res["success"] is True
    assert res["action"] == "revert_commit"
    assert not f2.exists()
    assert f1.exists()


# ==============================================================================
# 10. INTENT ROUTER CLASSIFICATION
# ==============================================================================

def test_intent_router_classifies_git_queries():
    router = IntentRouter()

    queries = [
        "git status",
        "check git diff",
        "show git log",
        "git branch",
        "commit changes to git",
        "push to github remote",
        "check github remote",
        "show changed files",
    ]
    for q in queries:
        intent, _ = router.route(q)
        assert intent == Intent.CODING, f"Query '{q}' should be classified as CODING"
