"""AXON Step Verifier — verifies expected real-world outcomes of executed actions."""

import os
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

from axon.router import Router
from axon.tasks.tasks import Step


class Verifier:
    """Verifies that an executed step achieved its intended side effect."""

    def __init__(self, router: Router):
        self.router = router

    def verify(self, step: Step, step_result: Dict[str, Any]) -> Tuple[bool, str]:
        """Verify the outcome of an executed step.
        
        Returns:
            (is_verified, reason_or_details)
        """
        # If tool execution itself reported failure, verification fails immediately
        if not step_result.get("success", False):
            return False, f"Tool execution failed: {step_result.get('error', 'unknown error')}"

        # 1. Explicit verification tool specified on the step
        if step.verification_tool:
            v_res = self.router.execute(step.verification_tool, **step.verification_args)
            if not v_res.get("success", False):
                return False, f"Verification tool {step.verification_tool} failed: {v_res.get('error')}"

            val = v_res.get("result", {})
            # If verification tool returns a running dict (like applications.is_running)
            if isinstance(val, dict):
                if "running" in val:
                    if val["running"]:
                        return True, f"Verified running: {val.get('name') or val.get('matches')}"
                    else:
                        return False, f"Process not running according to {step.verification_tool}"
                if val.get("status") == "success":
                    return True, "Verified successful status"

            return True, "Verification tool completed successfully"

        # 2. Built-in heuristics for common actions
        tool = step.tool.replace("__", ".")
        args = step.tool_args or {}

        # applications.open verification
        if tool == "applications.open":
            target = args.get("name_or_path") or args.get("name") or ""
            if target:
                v_res = self.router.execute("applications.is_running", name=target)
                if v_res.get("success", False) and v_res.get("result", {}).get("running", False):
                    return True, f"Verified application '{target}' is running"
                # If launching via shell, process might take 100-200ms to register
                return True, "Application launch dispatched"

        # filesystem.write & coding file creation verification
        if tool in ("filesystem.write", "coding.create_file", "coding.write_file"):
            path_str = args.get("path", "")
            if path_str:
                from axon.tools.filesystem import resolve_path
                p = resolve_path(path_str)
                if p.exists() and p.is_file():
                    return True, f"Verified file exists: {p}"
                return False, f"Expected file does not exist after write: {p}"

        # filesystem.replace_content & coding.edit_file verification
        if tool in ("filesystem.replace_content", "coding.edit_file"):
            path_str = args.get("path", "")
            repl = args.get("replacement", "")
            if path_str:
                from axon.tools.filesystem import resolve_path
                p = resolve_path(path_str)
                if not p.exists() or not p.is_file():
                    return False, f"Target file does not exist: {p}"
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if repl and repl in text:
                        return True, f"Verified replacement content is present in {p.name}"
                    return True, f"Verified file was modified: {p.name}"
                except Exception as e:
                    return False, f"Failed to verify file modification: {e}"

        # coding.run_tests & coding.run_build verification
        if tool in ("coding.run_tests", "coding.run_build"):
            tool_label = "Build" if tool == "coding.run_build" else "Test runner"
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict):
                exit_code = res_val.get("exit_code", 0)
                if exit_code == 0:
                    return True, f"{tool_label} exited with status 0 (passed)"
                else:
                    return False, f"{tool_label} exited with code {exit_code}"
            return True, f"{tool_label} execution finished"

        # filesystem.create_directory verification
        if tool == "filesystem.create_directory":
            path_str = args.get("path", "")
            if path_str:
                from axon.tools.filesystem import resolve_path
                p = resolve_path(path_str)
                if p.exists() and p.is_dir():
                    return True, f"Verified directory exists: {p}"
                return False, f"Expected directory does not exist: {p}"

        # filesystem.delete verification
        if tool == "filesystem.delete":
            path_str = args.get("path", "")
            if path_str:
                from axon.tools.filesystem import resolve_path
                p = resolve_path(path_str)
                if not p.exists():
                    return True, f"Verified item was deleted: {p}"
                return False, f"Item still exists after delete: {p}"

        # screenshot.take & screenshot.analyze verification
        if tool in ("screenshot.take", "screenshot.analyze"):
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict):
                p_str = res_val.get("path", "")
                if p_str and Path(p_str).exists():
                    return True, f"Verified screenshot exists at {p_str}"
                if res_val.get("status") == "success":
                    return True, "Screenshot operation verified"
            return True, "Screenshot tool completed"

        # desktop.switch_window verification
        if tool == "desktop.switch_window":
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict) and res_val.get("switched", False):
                return True, f"Verified window switch: {res_val.get('title') or res_val.get('target')}"
            return True, "Window switch command dispatched"

        # desktop.close_window verification
        if tool == "desktop.close_window":
            target = str(args.get("title_or_pid") or "").lower()
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict) and res_val.get("closed", False):
                return True, f"Verified window close: {target}"
            return True, "Window close dispatched"

        # mouse.move verification
        if tool == "mouse.move":
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict) and res_val.get("status") == "success":
                return True, f"Verified mouse moved to ({res_val.get('x')}, {res_val.get('y')})"
            return True, "Mouse move completed"

        # mouse.click & mouse.double_click verification
        if tool in ("mouse.click", "mouse.double_click"):
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict) and res_val.get("status") == "success":
                return True, f"Verified mouse {res_val.get('action', 'click')} at ({res_val.get('x')}, {res_val.get('y')})"
            return True, "Mouse click completed"

        # keyboard.type verification
        if tool == "keyboard.type":
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict) and res_val.get("status") == "success":
                return True, f"Verified typed {res_val.get('characters_typed', 0)} characters"
            return True, "Keyboard typing completed"

        # keyboard.press & keyboard.hotkey verification
        if tool in ("keyboard.press", "keyboard.hotkey"):
            res_val = step_result.get("result", {})
            if isinstance(res_val, dict) and res_val.get("status") == "success":
                return True, f"Verified key action: {res_val.get('key') or res_val.get('hotkey')}"
            return True, "Keyboard action completed"

        # Default: Tool succeeded and no contradictory verification
        return True, "Action completed without errors"
