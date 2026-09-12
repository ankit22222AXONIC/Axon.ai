"""Tests for AXON's expanded Windows computer control tools."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from axon.core import Axon
from axon.security import Permission
from axon.tools.filesystem import (
    resolve_path,
    filesystem_list,
    filesystem_list_detailed,
    filesystem_read,
    filesystem_write,
    filesystem_create_directory,
    filesystem_copy,
    filesystem_move,
    filesystem_delete,
)
from axon.tools.applications import (
    applications_list,
    applications_is_running,
    applications_open,
    applications_close,
)
from axon.tools.screenshot import screenshot_take
from axon.tools.browser import browser_open, browser_search
from axon.tools.system import system_resources, processes_find


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="axon_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


class TestFilesystemTools:
    def test_resolve_path(self, tmp_dir):
        # Current directory
        assert resolve_path(".").is_dir()
        # Home expansion
        assert resolve_path("~").exists()
        # Custom shortcuts
        assert resolve_path("Desktop") == Path.home() / "Desktop"
        # Subpath in tmp_dir
        sub = tmp_dir / "test.txt"
        assert resolve_path(str(sub)) == sub.resolve()

    def test_write_and_read(self, tmp_dir):
        file_path = str(tmp_dir / "hello.txt")
        res = filesystem_write(file_path, "Hello AXON!")
        assert res["status"] == "success"
        assert res["bytes_written"] == 11
        assert res["mode"] == "overwrite"

        content = filesystem_read(file_path)
        assert content == "Hello AXON!"

        # Append
        res_app = filesystem_write(file_path, " More content", append=True)
        assert res_app["status"] == "success"
        assert res_app["mode"] == "append"
        assert filesystem_read(file_path) == "Hello AXON! More content"

    def test_create_directory_and_list_detailed(self, tmp_dir):
        sub_dir = str(tmp_dir / "nested" / "folder")
        res = filesystem_create_directory(sub_dir)
        assert res["status"] == "success"
        assert Path(sub_dir).is_dir()

        # Write file inside
        filesystem_write(str(Path(sub_dir) / "doc.txt"), "Testing detailed list")

        detailed = filesystem_list_detailed(sub_dir)
        assert len(detailed) == 1
        assert detailed[0]["name"] == "doc.txt"
        assert detailed[0]["is_dir"] is False
        assert detailed[0]["size_bytes"] > 0
        assert "modified" in detailed[0]

    def test_copy_and_move(self, tmp_dir):
        src_file = str(tmp_dir / "original.txt")
        filesystem_write(src_file, "Original text")

        # Copy
        copy_file = str(tmp_dir / "copy.txt")
        copy_res = filesystem_copy(src_file, copy_file)
        assert copy_res["status"] == "success"
        assert Path(copy_file).exists()
        assert Path(src_file).exists()

        # Move
        move_file = str(tmp_dir / "moved.txt")
        move_res = filesystem_move(copy_file, move_file)
        assert move_res["status"] == "success"
        assert Path(move_file).exists()
        assert not Path(copy_file).exists()

    def test_delete(self, tmp_dir):
        test_file = str(tmp_dir / "to_delete.txt")
        filesystem_write(test_file, "goodbye")
        del_file_res = filesystem_delete(test_file)
        assert del_file_res["status"] == "success"
        assert del_file_res["type"] == "file"
        assert not Path(test_file).exists()

        # Delete directory
        test_dir = str(tmp_dir / "to_delete_dir")
        filesystem_create_directory(test_dir)
        filesystem_write(str(Path(test_dir) / "nested.txt"), "inside")
        del_dir_res = filesystem_delete(test_dir)
        assert del_dir_res["status"] == "success"
        assert del_dir_res["type"] == "directory"
        assert not Path(test_dir).exists()


class TestApplicationTools:
    def test_applications_list_returns_list(self):
        apps = applications_list()
        assert isinstance(apps, list)
        assert len(apps) > 0

    def test_applications_list_includes_known_aliases(self):
        """Aliases for apps that exist on the system should appear in the list."""
        apps_lower = [a.lower() for a in applications_list()]
        # calc.exe is always present on Windows, so "Calculator" alias should appear
        assert "calculator" in apps_lower

    def test_applications_is_running(self):
        # 'python' is currently running pytest
        res = applications_is_running("python")
        assert "running" in res
        assert res["running"] is True
        assert res["instances_count"] > 0

    def test_applications_is_running_nonexistent(self):
        res = applications_is_running("axon_fake_process_xyz_999")
        assert res["running"] is False
        assert res["instances_count"] == 0

    # ── applications_open tests (mocked) ────────────────────────────────────

    @patch("axon.tools.applications.subprocess.Popen")
    @patch("axon.tools.applications.shutil.which", return_value="C:\\Windows\\system32\\calc.EXE")
    def test_open_calculator_alias(self, mock_which, mock_popen):
        """'Calculator' should resolve via alias to 'calc' and launch."""
        res = applications_open("Calculator")
        assert res["status"] == "success"
        assert res.get("alias") == "Calculator"
        mock_popen.assert_called_once()

    @patch("axon.tools.applications.subprocess.Popen")
    @patch("axon.tools.applications.shutil.which", return_value="C:\\Windows\\system32\\notepad.EXE")
    def test_open_notepad_alias(self, mock_which, mock_popen):
        """'Notepad' should resolve via alias."""
        res = applications_open("Notepad")
        assert res["status"] == "success"
        assert res.get("alias") == "Notepad"

    @patch("axon.tools.applications.os.startfile", create=True)
    def test_open_settings_uri(self, mock_startfile):
        """'Settings' should launch via ms-settings: URI scheme."""
        res = applications_open("Settings")
        assert res["status"] == "success"
        assert res["method"] == "uri_scheme"
        mock_startfile.assert_called_with("ms-settings:")

    @patch("axon.tools.applications.subprocess.Popen")
    @patch("axon.tools.applications.shutil.which", return_value="C:\\Windows\\system32\\mspaint.EXE")
    def test_open_paint_alias(self, mock_which, mock_popen):
        """'Paint' should resolve to mspaint."""
        res = applications_open("Paint")
        assert res["status"] == "success"
        assert res.get("alias") == "Paint"

    def test_open_unknown_app(self):
        """An app that doesn't exist should return a useful error."""
        res = applications_open("axon_nonexistent_app_zzz_12345")
        assert "error" in res
        assert "axon_nonexistent_app_zzz_12345" in res["error"]
        # The error should NOT say 'missing' generically — it should describe what failed
        assert "not found" in res["error"].lower() or "failed" in res["error"].lower()

    def test_open_empty_name(self):
        res = applications_open("")
        assert "error" in res

    @patch("subprocess.run")
    def test_applications_close(self, mock_subproc):
        mock_subproc.return_value = MagicMock(returncode=0, stdout="SUCCESS: Sent termination signal", stderr="")
        res = applications_close("notepad")
        assert res["status"] == "success"
        assert res["target"] == "notepad"



class TestScreenshotTool:
    def test_screenshot_take(self, tmp_dir):
        res = screenshot_take(save_dir=str(tmp_dir))
        assert res["status"] == "success"
        assert Path(res["path"]).exists()
        assert res["width"] > 0
        assert res["height"] > 0
        assert res["size_bytes"] > 0


class TestBrowserTools:
    @patch("webbrowser.open")
    def test_browser_open(self, mock_webbrowser):
        mock_webbrowser.return_value = True
        res = browser_open("github.com")
        assert res["status"] == "success"
        assert res["url"] == "https://github.com"
        mock_webbrowser.assert_called_with("https://github.com")

    @patch("webbrowser.open")
    def test_browser_search(self, mock_webbrowser):
        mock_webbrowser.return_value = True
        res = browser_search("AI agent windows", engine="google")
        assert res["status"] == "success"
        assert "google.com/search?q=AI+agent+windows" in res["url"]

        res_ddg = browser_search("privacy search", engine="duckduckgo")
        assert "duckduckgo.com/?q=privacy+search" in res_ddg["url"]


class TestSystemTelemetry:
    def test_system_resources(self):
        res = system_resources()
        assert "cpu_count" in res
        assert res["cpu_count"] > 0
        assert "disk" in res
        assert "total_gb" in res["disk"]
        assert "ram" in res
        assert "total_gb" in res["ram"]
        assert "uptime" in res
        assert "formatted" in res["uptime"]

    def test_processes_find(self):
        matches = processes_find("python")
        assert isinstance(matches, list)
        assert len(matches) > 0
        assert "pid" in matches[0]


class TestRuntimeWiringAndSecurity:
    def test_runtime_tools_and_permissions(self):
        axon = Axon()
        axon.start()

        # Verify all tools registered
        expected_tools = [
            "filesystem.list",
            "filesystem.list_detailed",
            "filesystem.search",
            "filesystem.read",
            "filesystem.write",
            "filesystem.create_directory",
            "filesystem.delete",
            "filesystem.copy",
            "filesystem.move",
            "applications.list",
            "applications.open",
            "applications.is_running",
            "applications.close",
            "screenshot.take",
            "browser.open",
            "browser.search",
            "system.info",
            "system.resources",
            "processes.list",
            "processes.find",
            "terminal.run",
            "memory.store",
            "memory.forget",
            "task.create",
        ]
        for tool_name in expected_tools:
            assert axon.registry.exists(tool_name), f"Tool {tool_name} not registered"

        # Verify security permissions
        # APPROVAL_REQUIRED
        assert axon.security.check("terminal.run") == Permission.APPROVAL_REQUIRED
        assert axon.security.check("filesystem.delete") == Permission.APPROVAL_REQUIRED
        assert axon.security.check("applications.close") == Permission.APPROVAL_REQUIRED
        assert axon.security.check("memory.forget") == Permission.APPROVAL_REQUIRED

        # ALLOWED
        assert axon.security.check("filesystem.write") == Permission.ALLOWED
        assert axon.security.check("filesystem.create_directory") == Permission.ALLOWED
        assert axon.security.check("screenshot.take") == Permission.ALLOWED
        assert axon.security.check("browser.open") == Permission.ALLOWED
        assert axon.security.check("system.resources") == Permission.ALLOWED

        axon.shutdown()
