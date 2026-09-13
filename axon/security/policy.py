"""AXON Security Policy Engine — defines permission levels, policy decisions, and rules."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any

from axon.security.path_security import check_path_security, normalize_path
from axon.security.terminal_security import inspect_terminal_command
from axon.security.process_security import is_protected_process


class PermissionLevel(Enum):
    SAFE = "safe"
    CAUTION = "caution"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"

    @property
    def is_allowed_without_approval(self) -> bool:
        return self in (PermissionLevel.SAFE, PermissionLevel.CAUTION)

    @property
    def requires_approval(self) -> bool:
        return self == PermissionLevel.APPROVAL_REQUIRED

    @property
    def is_blocked(self) -> bool:
        return self == PermissionLevel.BLOCKED


@dataclass
class PolicyDecision:
    level: PermissionLevel
    reason: str
    tool_name: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.level.is_allowed_without_approval

    @property
    def requires_approval(self) -> bool:
        return self.level.requires_approval

    @property
    def is_blocked(self) -> bool:
        return self.level.is_blocked


class SecurityPolicyEngine:
    """Evaluates requested tool calls against security policies and determines permission level."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or Path.cwd()
        # Explicit overrides (tool_name -> PermissionLevel)
        self._overrides: Dict[str, PermissionLevel] = {}

    def set_override(self, tool_name: str, level: PermissionLevel):
        self._overrides[tool_name] = level

    def evaluate(self, tool_name: str, kwargs: Optional[Dict[str, Any]] = None) -> PolicyDecision:
        """Contextually evaluate whether a tool call is SAFE, CAUTION, APPROVAL_REQUIRED, or BLOCKED."""
        args = kwargs or {}
        canonical_name = tool_name.replace("__", ".")

        # 1. Check if tool is an attempt to alter security policy or approval directly
        if "security" in canonical_name or "permission" in canonical_name:
            return PolicyDecision(
                level=PermissionLevel.BLOCKED,
                reason="AI cannot directly call or modify security subsystems",
                tool_name=canonical_name,
            )

        # 2. Check explicit programmatic override
        if canonical_name in self._overrides:
            override_level = self._overrides[canonical_name]
            if canonical_name in ("terminal.run", "coding.run_tests", "coding.run_build"):
                cmd = args.get("command", "")
                if cmd:
                    is_allowed, reason, meta = inspect_terminal_command(cmd)
                    if not is_allowed:
                        return PolicyDecision(
                            level=PermissionLevel.BLOCKED,
                            reason=reason,
                            tool_name=canonical_name,
                            metadata=meta,
                        )
            if canonical_name.startswith("git."):
                destructive_decision = self._check_git_destructive(canonical_name, args)
                if destructive_decision:
                    return destructive_decision
                # git.push ALWAYS requires human approval even if overridden
                if canonical_name == "git.push" and override_level in (PermissionLevel.SAFE, PermissionLevel.CAUTION):
                    override_level = PermissionLevel.APPROVAL_REQUIRED

            return PolicyDecision(
                level=override_level,
                reason=f"Programmatic policy override set for {canonical_name}",
                tool_name=canonical_name,
            )

        # 3. Contextual evaluation by tool domain
        if canonical_name == "terminal.run":
            return self._evaluate_terminal(args)

        if canonical_name.startswith("git."):
            return self._evaluate_git(canonical_name, args)

        if canonical_name.startswith("filesystem."):
            return self._evaluate_filesystem(canonical_name, args)

        if canonical_name.startswith("coding."):
            return self._evaluate_coding(canonical_name, args)

        if canonical_name.startswith("applications."):
            return self._evaluate_applications(canonical_name, args)

        if canonical_name.startswith("memory."):
            return self._evaluate_memory(canonical_name, args)

        if canonical_name.startswith("browser."):
            return self._evaluate_browser(canonical_name, args)

        if canonical_name.startswith("desktop."):
            return self._evaluate_desktop(canonical_name, args)

        if canonical_name.startswith("mouse."):
            return self._evaluate_mouse(canonical_name, args)

        if canonical_name.startswith("keyboard."):
            return self._evaluate_keyboard(canonical_name, args)

        if canonical_name in ("screenshot.take", "screenshot.analyze"):
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Capturing or analyzing desktop screenshot visual state is safe read-only inspection",
                tool_name=canonical_name,
            )

        if canonical_name == "safety_reset":
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Safety reset to release stuck keys and buttons is always safe",
                tool_name=canonical_name,
            )

        if canonical_name.startswith("system."):
            return self._evaluate_system(canonical_name, args)

        if canonical_name in ("processes.list", "processes.find"):
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Read-only system inspection telemetry",
                tool_name=canonical_name,
            )

        if canonical_name.startswith("task."):
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Internal task management",
                tool_name=canonical_name,
            )

        if canonical_name.startswith("osiris."):
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="OSIRIS 3D globe and real-time world intelligence telemetry",
                tool_name=canonical_name,
            )

        # Default fallback
        return PolicyDecision(
            level=PermissionLevel.CAUTION,
            reason=f"Uncategorized tool '{canonical_name}' defaults to CAUTION",
            tool_name=canonical_name,
        )

    def _evaluate_terminal(self, args: dict) -> PolicyDecision:
        command = args.get("command", "")
        is_allowed, reason, meta = inspect_terminal_command(command)
        if not is_allowed:
            return PolicyDecision(
                level=PermissionLevel.BLOCKED,
                reason=reason,
                tool_name="terminal.run",
                metadata=meta,
            )

        # All non-blocked terminal commands strictly require user approval
        return PolicyDecision(
            level=PermissionLevel.APPROVAL_REQUIRED,
            reason=f"Terminal command requires user approval: {reason}",
            tool_name="terminal.run",
            metadata=meta,
        )

    def _evaluate_filesystem(self, tool_name: str, args: dict) -> PolicyDecision:
        op_map = {
            "filesystem.read": "read",
            "filesystem.view_lines": "read",
            "filesystem.write": "write",
            "filesystem.replace_content": "write",
            "filesystem.delete": "delete",
            "filesystem.move": "move",
            "filesystem.copy": "write",
            "filesystem.create_directory": "write",
            "filesystem.list": "list",
            "filesystem.list_detailed": "list",
            "filesystem.search": "list",
            "filesystem.find_in_files": "list",
            "filesystem.set_workspace": "read",
            "filesystem.get_workspace": "read",
        }
        op = op_map.get(tool_name, "read")
        path_str = args.get("path") or args.get("source") or "."

        # Check primary path
        is_safe, reason, norm_path = check_path_security(path_str, operation=op, workspace_root=self.workspace_root)
        if not is_safe:
            return PolicyDecision(
                level=PermissionLevel.BLOCKED,
                reason=reason,
                tool_name=tool_name,
                metadata={"path": str(norm_path)},
            )

        # For copy/move, also check destination path
        if tool_name in ("filesystem.copy", "filesystem.move"):
            dst_str = args.get("destination", "")
            if dst_str:
                dst_safe, dst_reason, dst_norm = check_path_security(dst_str, operation="write", workspace_root=self.workspace_root)
                if not dst_safe:
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason=dst_reason,
                        tool_name=tool_name,
                        metadata={"destination": str(dst_norm)},
                    )

        # Operation permission levels
        if tool_name == "filesystem.delete":
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason=f"File or directory deletion requires user approval: {norm_path}",
                tool_name=tool_name,
                metadata={"path": str(norm_path)},
            )

        if tool_name in ("filesystem.write", "filesystem.replace_content"):
            # If target file exists, overwriting or modifying requires approval
            if norm_path.exists() and norm_path.is_file():
                return PolicyDecision(
                    level=PermissionLevel.APPROVAL_REQUIRED,
                    reason=f"Modifying existing file requires user approval: {norm_path}",
                    tool_name=tool_name,
                    metadata={"path": str(norm_path), "overwrite": True},
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Creating new file: {norm_path}",
                tool_name=tool_name,
                metadata={"path": str(norm_path), "overwrite": False},
            )

        if tool_name in ("filesystem.move", "filesystem.copy"):
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Moving or copying files in user area",
                tool_name=tool_name,
                metadata={"path": str(norm_path)},
            )

        if tool_name == "filesystem.create_directory":
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Creating directory: {norm_path}",
                tool_name=tool_name,
                metadata={"path": str(norm_path)},
            )

        # Read / list operations
        return PolicyDecision(
            level=PermissionLevel.SAFE,
            reason="Read-only filesystem access in allowed location",
            tool_name=tool_name,
            metadata={"path": str(norm_path)},
        )

    def _evaluate_applications(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name == "applications.close":
            target = args.get("name_or_pid") or args.get("name") or args.get("target") or ""
            is_prot, reason = is_protected_process(target)
            if is_prot:
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason=reason,
                    tool_name=tool_name,
                    metadata={"target": target},
                )
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason=f"Closing application '{target}' requires user approval",
                tool_name=tool_name,
                metadata={"target": target},
            )

        if tool_name == "applications.open":
            name = args.get("name_or_path") or args.get("name") or ""
            # Prevent launching destructive system commands through applications.open
            clean_name = str(name).lower()
            if any(blocked in clean_name for blocked in ("format", "diskpart", "bcdedit")):
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason="Launching disk or boot modification tools is blocked",
                    tool_name=tool_name,
                    metadata={"name": name},
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Launching application '{name}'",
                tool_name=tool_name,
                metadata={"name": name},
            )

        # applications.list, applications.is_running
        return PolicyDecision(
            level=PermissionLevel.SAFE,
            reason="Application status inspection",
            tool_name=tool_name,
        )

    def _evaluate_memory(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name == "memory.forget":
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason="Deleting long-term memories requires user approval",
                tool_name=tool_name,
                metadata=args,
            )
        return PolicyDecision(
            level=PermissionLevel.SAFE,
            reason="Memory store, search, or retrieval",
            tool_name=tool_name,
            metadata=args,
        )

    def _evaluate_coding(self, tool_name: str, args: dict) -> PolicyDecision:
        """Evaluate permissions for coding-specific tools operating within a workspace."""
        if tool_name in ("coding.run_tests", "coding.run_build"):
            default_cmd = "python -m pytest" if tool_name == "coding.run_tests" else "build"
            cmd = args.get("command") or default_cmd
            is_allowed, reason, meta = inspect_terminal_command(cmd)
            if not is_allowed:
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason=reason,
                    tool_name=tool_name,
                    metadata=meta,
                )
            action_desc = "test" if tool_name == "coding.run_tests" else "build"
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason=f"Running {action_desc} command requires user approval: {cmd}",
                tool_name=tool_name,
                metadata={"command": cmd},
            )

        path_str = args.get("path") or "."
        op = "write" if tool_name in ("coding.create_file", "coding.edit_file", "coding.write_file") else "read"

        # Dynamically determine active workspace
        ws = self.workspace_root
        try:
            from axon.tools.filesystem import _CURRENT_WORKSPACE
            ws = _CURRENT_WORKSPACE
        except Exception:
            pass

        # Workspace boundary and path security check
        is_safe, reason, norm_path = check_path_security(
            path_str,
            operation=op,
            workspace_root=ws,
            enforce_workspace=True,
        )
        if not is_safe:
            return PolicyDecision(
                level=PermissionLevel.BLOCKED,
                reason=reason,
                tool_name=tool_name,
                metadata={"path": str(norm_path)},
            )

        if tool_name in ("coding.edit_file", "coding.write_file"):
            if norm_path.exists() and norm_path.is_file():
                return PolicyDecision(
                    level=PermissionLevel.APPROVAL_REQUIRED,
                    reason=f"Modifying existing file requires user approval: {norm_path.name}",
                    tool_name=tool_name,
                    metadata={"path": str(norm_path), "overwrite": True},
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Creating file: {norm_path.name}",
                tool_name=tool_name,
                metadata={"path": str(norm_path), "overwrite": False},
            )

        if tool_name == "coding.create_file":
            if norm_path.exists():
                return PolicyDecision(
                    level=PermissionLevel.APPROVAL_REQUIRED,
                    reason=f"Overwriting existing file requires user approval: {norm_path.name}",
                    tool_name=tool_name,
                    metadata={"path": str(norm_path), "overwrite": True},
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Creating new code file: {norm_path.name}",
                tool_name=tool_name,
                metadata={"path": str(norm_path), "overwrite": False},
            )

        # Read-only coding tools: coding.list_files, coding.read_file, coding.search_code
        return PolicyDecision(
            level=PermissionLevel.SAFE,
            reason="Read-only workspace inspection",
            tool_name=tool_name,
            metadata={"path": str(norm_path)},
        )

    def _check_git_destructive(self, tool_name: str, args: dict) -> Optional[PolicyDecision]:
        """Check for strictly forbidden destructive git operations."""
        # 1. Force push check
        if tool_name == "git.push":
            if args.get("force") is True:
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason="Force pushing is strictly forbidden in AXON.",
                    tool_name=tool_name,
                )
            remote = str(args.get("remote", ""))
            branch = str(args.get("branch", ""))
            combined = f"{remote} {branch}"
            for f in ("--force", "-f", "--force-with-lease", "+"):
                if f in combined.split() or f in combined:
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason=f"Forbidden force flag or refspec '{f}' in git push is blocked.",
                        tool_name=tool_name,
                    )

        # 2. Branch deletion check
        if tool_name == "git.branch":
            if args.get("delete") or any(flag in str(args.get("name", "")).split() for flag in ("-d", "-D", "--delete")):
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason="Deleting branches via AXON is strictly blocked to prevent code loss.",
                    tool_name=tool_name,
                )

        # 3. Whole-repo checkout wipe check
        if tool_name in ("git.checkout", "git.switch"):
            target = str(args.get("target") or args.get("branch") or "")
            if target in (".", "-- .") or target.startswith("-- "):
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason="Destructive git checkout discarding workspace changes is blocked.",
                    tool_name=tool_name,
                )
            for f in ("--hard", "--force", "-f", "-D"):
                if f in target.split():
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason=f"Forbidden flag '{f}' in checkout is blocked.",
                        tool_name=tool_name,
                    )

        # 4. Rollback destructive check
        if tool_name in ("git.rollback", "git.safe_rollback"):
            fpath = str(args.get("file_path", ""))
            if fpath in (".", "*", "-- ."):
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason="Destructive wipe of entire workspace is blocked. Specify a single file.",
                    tool_name=tool_name,
                )
            commit = str(args.get("commit", ""))
            for f in ("--hard", "--force", "-f"):
                if f in commit.split():
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason=f"Destructive flag '{f}' in rollback is blocked.",
                        tool_name=tool_name,
                    )

        return None

    def _evaluate_git(self, tool_name: str, args: dict) -> PolicyDecision:
        """Evaluate permissions for Git tools."""
        destructive = self._check_git_destructive(tool_name, args)
        if destructive:
            return destructive

        if tool_name == "git.push":
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason="Pushing commits to remote repository ALWAYS requires human approval",
                tool_name=tool_name,
                metadata={"remote": args.get("remote", "origin"), "branch": args.get("branch")},
            )

        if tool_name == "git.commit":
            msg = args.get("message", "")
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason=f"Committing changes to repository requires user approval: '{msg}'",
                tool_name=tool_name,
                metadata={"message": msg, "files": args.get("files")},
            )

        if tool_name in ("git.rollback", "git.safe_rollback"):
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason="Rolling back changes via Git requires user approval",
                tool_name=tool_name,
                metadata=args,
            )

        if tool_name in ("git.checkout", "git.switch"):
            target = args.get("target") or args.get("branch") or "branch"
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Switching branch to '{target}'",
                tool_name=tool_name,
                metadata={"branch": target},
            )

        if tool_name == "git.pull":
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason="Pulling remote updates into repository",
                tool_name=tool_name,
                metadata={"remote": args.get("remote", "origin")},
            )

        if tool_name == "git.branch":
            if args.get("name"):
                return PolicyDecision(
                    level=PermissionLevel.CAUTION,
                    reason=f"Creating new branch '{args.get('name')}'",
                    tool_name=tool_name,
                    metadata={"branch": args.get("name")},
                )
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Listing repository branches",
                tool_name=tool_name,
            )

        if tool_name in ("git.status", "git.diff", "git.log", "git.info", "git.remote"):
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Read-only Git telemetry and inspection",
                tool_name=tool_name,
            )

        return PolicyDecision(
            level=PermissionLevel.CAUTION,
            reason=f"Git operation '{tool_name}'",
            tool_name=tool_name,
        )

    def _evaluate_desktop(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name == "desktop.close_window":
            target = args.get("title_or_pid") or args.get("title") or args.get("target") or ""
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason=f"Closing desktop window '{target}' requires human approval to prevent data loss",
                tool_name=tool_name,
                metadata={"target": target},
            )

        if tool_name == "desktop.switch_window":
            target = args.get("title_or_pid") or args.get("title") or ""
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Switching window focus to '{target}'",
                tool_name=tool_name,
                metadata={"target": target},
            )

        if tool_name in ("desktop.get_windows", "desktop.get_active_window", "desktop.inspect_screen"):
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Read-only desktop window inspection and telemetry",
                tool_name=tool_name,
            )

        return PolicyDecision(
            level=PermissionLevel.CAUTION,
            reason=f"Desktop action '{tool_name}'",
            tool_name=tool_name,
        )

    def _evaluate_mouse(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name == "mouse.get_position":
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Reading mouse cursor coordinates is safe",
                tool_name=tool_name,
            )

        if tool_name == "mouse.move":
            x = args.get("x")
            y = args.get("y")
            if x is not None and y is not None:
                try:
                    ix, iy = int(x), int(y)
                    # Out of bounds check (negative or absurd values)
                    if ix < 0 or iy < 0 or ix > 15000 or iy > 15000:
                        return PolicyDecision(
                            level=PermissionLevel.BLOCKED,
                            reason=f"Mouse coordinates ({ix}, {iy}) out of physical display range",
                            tool_name=tool_name,
                            metadata={"x": ix, "y": iy},
                        )
                except (ValueError, TypeError):
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason="Mouse coordinates must be numeric integers",
                        tool_name=tool_name,
                    )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Moving mouse cursor to ({x}, {y})",
                tool_name=tool_name,
                metadata={"x": x, "y": y},
            )

        if tool_name in ("mouse.click", "mouse.double_click"):
            btn = str(args.get("button", "left")).lower().strip()
            if btn not in ("left", "right", "middle"):
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason=f"Invalid mouse button '{btn}'. Allowed: left, right, middle",
                    tool_name=tool_name,
                )
            x = args.get("x")
            y = args.get("y")
            if x is not None and y is not None:
                try:
                    ix, iy = int(x), int(y)
                    if ix < 0 or iy < 0 or ix > 15000 or iy > 15000:
                        return PolicyDecision(
                            level=PermissionLevel.BLOCKED,
                            reason=f"Mouse click coordinates ({ix}, {iy}) out of bounds",
                            tool_name=tool_name,
                        )
                except (ValueError, TypeError):
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason="Mouse coordinates must be numeric integers",
                        tool_name=tool_name,
                    )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Mouse {btn}-{tool_name.split('.')[-1]} at ({x}, {y})",
                tool_name=tool_name,
                metadata={"button": btn, "x": x, "y": y},
            )

        if tool_name == "mouse.scroll":
            delta = args.get("delta", 120)
            try:
                idelta = int(delta)
                if abs(idelta) > 10000:
                    return PolicyDecision(
                        level=PermissionLevel.BLOCKED,
                        reason=f"Mouse scroll delta {idelta} exceeds safe limits",
                        tool_name=tool_name,
                    )
            except (ValueError, TypeError):
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason="Scroll delta must be an integer",
                    tool_name=tool_name,
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Scrolling mouse wheel by {delta}",
                tool_name=tool_name,
                metadata={"delta": delta},
            )

        return PolicyDecision(
            level=PermissionLevel.CAUTION,
            reason=f"Mouse action '{tool_name}'",
            tool_name=tool_name,
        )

    def _evaluate_keyboard(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name == "keyboard.type":
            text = args.get("text", "")
            s_text = str(text) if text is not None else ""
            if len(s_text) > 2000:
                return PolicyDecision(
                    level=PermissionLevel.BLOCKED,
                    reason=f"Typing exceeds safe character limit of 2000 (length: {len(s_text)})",
                    tool_name=tool_name,
                )

            # Destructive system command patterns in typed input
            import re
            destructive_cmd_pattern = re.compile(
                r"(?:\b(?:rmdir|del\s+/[fqs]|shutdown|drop\s+database|powershell.*-enc|curl.*\|\s*sh)\b|\bformat\s+[a-zA-Z]:)",
                re.IGNORECASE,
            )
            if destructive_cmd_pattern.search(s_text):
                return PolicyDecision(
                    level=PermissionLevel.APPROVAL_REQUIRED,
                    reason="Typing potentially destructive system command requires human approval",
                    tool_name=tool_name,
                    metadata={"text_preview": s_text[:60]},
                )

            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Typing text string ({len(s_text)} chars)",
                tool_name=tool_name,
                metadata={"length": len(s_text)},
            )

        if tool_name == "keyboard.press":
            key = str(args.get("key", "")).lower().strip()
            if key in ("power", "sleep"):
                return PolicyDecision(
                    level=PermissionLevel.APPROVAL_REQUIRED,
                    reason=f"Pressing system power key '{key}' requires human approval",
                    tool_name=tool_name,
                    metadata={"key": key},
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Pressing key '{key}'",
                tool_name=tool_name,
                metadata={"key": key},
            )

        if tool_name == "keyboard.hotkey":
            hotkey = str(args.get("keys", "")).lower().strip()
            # Destructive / system-altering hotkeys require human approval
            destructive_hotkeys = ("alt+f4", "ctrl+alt+del", "win+l")
            if any(d in hotkey.replace(" ", "") for d in destructive_hotkeys):
                return PolicyDecision(
                    level=PermissionLevel.APPROVAL_REQUIRED,
                    reason=f"Executing destructive system hotkey '{hotkey}' requires human approval",
                    tool_name=tool_name,
                    metadata={"hotkey": hotkey},
                )
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason=f"Executing hotkey '{hotkey}'",
                tool_name=tool_name,
                metadata={"hotkey": hotkey},
            )

        return PolicyDecision(
            level=PermissionLevel.CAUTION,
            reason=f"Keyboard action '{tool_name}'",
            tool_name=tool_name,
        )

    def _evaluate_browser(self, tool_name: str, args: dict) -> PolicyDecision:
        """Evaluate browser automation tools."""
        if tool_name == "browser.close_window":
            browser_target = args.get("browser_name") or "browser"
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason=f"Closing browser window ({browser_target}) requires user approval to prevent loss of unsaved work or open tabs",
                tool_name=tool_name,
                metadata={
                    "browser": browser_target,
                    "title": "Close Browser Window?",
                    "prompt": "Closing the browser window may lose unsaved work or open session tabs. Continue?",
                },
            )

        if tool_name == "browser.close_tab":
            return PolicyDecision(
                level=PermissionLevel.SAFE,
                reason="Closing an individual browser tab is allowed without approval",
                tool_name=tool_name,
                metadata={"tab_title": args.get("tab_title")},
            )

        return PolicyDecision(
            level=PermissionLevel.CAUTION,
            reason="Opening external browser URLs/searches is low-risk user interaction",
            tool_name=tool_name,
            metadata={"url": args.get("url") or args.get("query")},
        )

    def _evaluate_system(self, tool_name: str, args: dict) -> PolicyDecision:
        """Evaluate system power and telemetry tools."""
        if tool_name == "system.shutdown":
            delay = args.get("delay_seconds", 60)
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason="Shutdown will power off your computer and requires explicit human approval",
                tool_name=tool_name,
                metadata={
                    "action": "shutdown",
                    "delay_seconds": delay,
                    "title": "Shutdown Computer?",
                    "prompt": "Shutdown will power off your computer. Continue?",
                },
            )

        if tool_name == "system.restart":
            delay = args.get("delay_seconds", 60)
            return PolicyDecision(
                level=PermissionLevel.APPROVAL_REQUIRED,
                reason="Restart will reboot Windows and requires explicit human approval",
                tool_name=tool_name,
                metadata={
                    "action": "restart",
                    "delay_seconds": delay,
                    "title": "Restart Computer?",
                    "prompt": "This will restart Windows and may interrupt running applications. Continue?",
                },
            )

        if tool_name == "system.cancel_shutdown":
            return PolicyDecision(
                level=PermissionLevel.CAUTION,
                reason="Aborting scheduled shutdown or restart is safe",
                tool_name=tool_name,
            )

        # system.info, system.resources
        return PolicyDecision(
            level=PermissionLevel.SAFE,
            reason="Read-only system inspection telemetry",
            tool_name=tool_name,
        )



