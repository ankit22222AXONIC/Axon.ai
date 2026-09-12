"""Tests for AXON's code inspection, search, surgical editing, and workspace management tools."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from axon.core import Axon
from axon.tools.filesystem import (
    filesystem_view_lines,
    filesystem_find_in_files,
    filesystem_replace_content,
    filesystem_set_workspace,
    filesystem_get_workspace,
    resolve_path,
)
from axon.security import PermissionLevel
from axon.agent.verifier import Verifier
from axon.tasks.tasks import Step


@pytest.fixture
def workspace_dir():
    d = tempfile.mkdtemp(prefix="axon_code_ws_")
    orig_ws = filesystem_get_workspace()["workspace"]
    filesystem_set_workspace(d)
    yield Path(d)
    filesystem_set_workspace(orig_ws)
    shutil.rmtree(d, ignore_errors=True)


class TestCodeTools:
    def test_view_lines(self, workspace_dir):
        test_file = workspace_dir / "sample.py"
        test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

        res = filesystem_view_lines("sample.py", start_line=2, end_line=4)
        assert res.get("status") == "success"
        assert res.get("total_lines") == 5
        assert res.get("start_line") == 2
        assert res.get("end_line") == 4
        lines_str = res.get("lines", "")
        assert "2: line 2" in lines_str
        assert "3: line 3" in lines_str
        assert "4: line 4" in lines_str
        assert "1: line 1" not in lines_str
        assert "5: line 5" not in lines_str

    def test_view_lines_nonexistent(self):
        res = filesystem_view_lines("nonexistent_file_999.py")
        assert "error" in res

    def test_find_in_files(self, workspace_dir):
        # Create dummy project structure
        src = workspace_dir / "src"
        src.mkdir()
        (src / "main.py").write_text("def calculate_total(price, tax):\n    return price + tax\n", encoding="utf-8")
        (src / "helper.py").write_text("def print_greeting():\n    print('Hello World')\n", encoding="utf-8")
        
        # Ignored dir
        git_dir = workspace_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("calculate_total inside git", encoding="utf-8")

        # Search for calculate_total
        res = filesystem_find_in_files(query="calculate_total", path=str(workspace_dir))
        assert res.get("status") == "success"
        assert res.get("match_count") == 1
        assert res["matches"][0]["file"] == str(Path("src") / "main.py")
        assert res["matches"][0]["line_number"] == 1
        assert "def calculate_total" in res["matches"][0]["line_content"]

    def test_replace_content_single(self, workspace_dir):
        code_file = workspace_dir / "app.py"
        code_file.write_text(
            "def greet(name):\n"
            "    print('Hello ' + name)\n"
            "    return True\n",
            encoding="utf-8",
        )

        res = filesystem_replace_content(
            path="app.py",
            target="print('Hello ' + name)",
            replacement="print(f'Hello, {name}!')",
        )
        assert res.get("status") == "success"
        assert res.get("replacements_made") == 1

        updated = code_file.read_text(encoding="utf-8")
        assert "print(f'Hello, {name}!')" in updated
        assert "print('Hello ' + name)" not in updated

    def test_replace_content_target_not_found(self, workspace_dir):
        code_file = workspace_dir / "app.py"
        code_file.write_text("val = 42\n", encoding="utf-8")

        res = filesystem_replace_content(
            path="app.py",
            target="missing_code()",
            replacement="new_code()",
        )
        assert "error" in res
        assert "not found" in res["error"].lower()

    def test_replace_content_ambiguous(self, workspace_dir):
        code_file = workspace_dir / "duplicate.py"
        code_file.write_text("x = 1\nx = 1\n", encoding="utf-8")

        # Default allow_multiple=False should reject ambiguous replacement
        res = filesystem_replace_content(path="duplicate.py", target="x = 1", replacement="x = 2")
        assert "error" in res
        assert "found 2 times" in res["error"].lower()

        # With allow_multiple=True it succeeds
        res2 = filesystem_replace_content(path="duplicate.py", target="x = 1", replacement="x = 2", allow_multiple=True)
        assert res2.get("status") == "success"
        assert res2.get("replacements_made") == 2
        assert code_file.read_text(encoding="utf-8") == "x = 2\nx = 2\n"

    def test_workspace_management(self, workspace_dir):
        sub = workspace_dir / "sub_project"
        sub.mkdir()

        res = filesystem_set_workspace(str(sub))
        assert res.get("status") == "success"
        assert res.get("workspace") == str(sub.resolve())

        res_get = filesystem_get_workspace()
        assert res_get.get("workspace") == str(sub.resolve())

        # Relative path resolution should now resolve inside sub_project
        p = resolve_path("myfile.txt")
        assert p == (sub / "myfile.txt").resolve()


class TestCodeToolsRouterAndSecurity:
    def test_router_execution(self, workspace_dir):
        axon = Axon()
        axon.start()

        # Create a test file
        f = workspace_dir / "test_route.py"
        f.write_text("def test(): pass\n", encoding="utf-8")

        # view_lines is safe and executes directly through Router
        view_res = axon.router.execute("filesystem.view_lines", path=str(f), start_line=1, end_line=5)
        assert view_res.get("success") is True
        assert "1: def test(): pass" in view_res["result"]["lines"]

        # find_in_files is safe and executes directly
        find_res = axon.router.execute("filesystem.find_in_files", query="test()", path=str(workspace_dir))
        assert find_res.get("success") is True
        assert find_res["result"]["match_count"] >= 1

        axon.shutdown()

    def test_replace_content_requires_approval(self, workspace_dir):
        axon = Axon()
        axon.start()

        f = workspace_dir / "protected_edit.py"
        f.write_text("secret = 'old'\n", encoding="utf-8")

        # Without approval callback, modifying existing file is blocked/requires approval
        res = axon.router.execute(
            "filesystem.replace_content",
            path=str(f),
            target="secret = 'old'",
            replacement="secret = 'new'",
        )
        assert res.get("success") is False
        assert "approval" in res.get("error", "").lower()

        # With approval granted
        axon.approval.set_prompt(lambda tool, args: True)
        res_approved = axon.router.execute(
            "filesystem.replace_content",
            path=str(f),
            target="secret = 'old'",
            replacement="secret = 'new'",
        )
        assert res_approved.get("success") is True
        assert "secret = 'new'" in f.read_text(encoding="utf-8")

        axon.shutdown()

    def test_verifier_replace_content(self, workspace_dir):
        axon = Axon()
        axon.start()

        f = workspace_dir / "verify_edit.py"
        f.write_text("result = 100\n", encoding="utf-8")

        verifier = Verifier(axon.router)
        step = Step(
            id="s1",
            description="Update result to 200",
            tool="filesystem.replace_content",
            tool_args={"path": str(f), "target": "result = 100", "replacement": "result = 200"},
        )

        f.write_text("result = 200\n", encoding="utf-8")
        is_v, reason = verifier.verify(step, {"success": True})
        assert is_v is True
        assert "replacement content is present" in reason

        axon.shutdown()
