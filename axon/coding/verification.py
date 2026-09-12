"""AXON Verification & Self-Correction Engine — coordinates build/test runs, error analysis, and rollback."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Optional, Dict, Any, List, Set, Tuple, Union

from axon.router import Router
from axon.security.path_security import is_within_workspace, is_sensitive_credential_path
from axon.coding.project import ProjectInfo


@dataclass
class VerificationResult:
    """Outcome of running project build and test verification."""
    passed: bool
    build_passed: bool = True
    tests_passed: bool = True
    build_output: str = ""
    test_output: str = ""
    build_command: Optional[str] = None
    test_command: Optional[str] = None
    error: str = ""
    errors: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.error and not self.errors:
            self.errors = [self.error]
        elif self.errors and not self.error:
            self.error = self.errors[0]

    @property
    def test_passed(self) -> bool:
        return self.tests_passed

    @test_passed.setter
    def test_passed(self, val: bool):
        self.tests_passed = val


class WorkspaceRollback:
    """Safely snapshots and rolls back workspace file changes if a coding task fails."""

    def __init__(self, workspace_root: Optional[Union[str, Path]] = None):
        self._custom_root = Path(workspace_root).resolve() if workspace_root else None
        # Maps relative path string -> original content string (or None if newly created)
        self._snapshots: Dict[str, Optional[str]] = {}

    @property
    def workspace_root(self) -> Path:
        if self._custom_root:
            return self._custom_root
        from axon.tools.filesystem import get_current_workspace
        return get_current_workspace()

    def snapshot(self, file_path_str: str) -> bool:
        """Record pre-modification state of a file before editing or writing."""
        if not file_path_str:
            return False

        p = Path(file_path_str)
        if p.is_absolute():
            target = p.resolve()
        else:
            target = (self.workspace_root / file_path_str).resolve()

        if not is_within_workspace(target, self.workspace_root):
            return False
        if is_sensitive_credential_path(target):
            return False

        try:
            rel = str(target.relative_to(self.workspace_root)).replace("\\", "/")
        except Exception:
            return False

        # Only snapshot once per file per task to keep true initial state
        if rel in self._snapshots:
            return True

        if target.exists() and target.is_file():
            try:
                self._snapshots[rel] = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return False
        else:
            # File does not exist yet (will be newly created)
            self._snapshots[rel] = None

        return True

    def rollback(self) -> Dict[str, Any]:
        """Revert all tracked files to their original pre-task state."""
        reverted: List[str] = []
        deleted: List[str] = []
        errors: List[str] = []

        for rel, original_content in list(self._snapshots.items()):
            target = (self.workspace_root / rel).resolve()
            if not is_within_workspace(target, self.workspace_root) or is_sensitive_credential_path(target):
                continue

            try:
                if original_content is None:
                    # Newly created file: unlink it
                    if target.exists():
                        target.unlink()
                        deleted.append(rel)
                else:
                    # Modified file: restore original text
                    target.write_text(original_content, encoding="utf-8")
                    reverted.append(rel)
            except Exception as e:
                errors.append(f"Failed rollback for {rel}: {e}")

        # Clear snapshots after rollback
        self._snapshots.clear()

        return {
            "success": len(errors) == 0,
            "reverted_files": reverted,
            "deleted_files": deleted,
            "restored": reverted,
            "deleted": deleted,
            "errors": errors,
        }

    def clear(self):
        """Clear recorded snapshots without reverting (task succeeded)."""
        self._snapshots.clear()

    @property
    def has_changes(self) -> bool:
        return len(self._snapshots) > 0

    def has_snapshots(self) -> bool:
        return len(self._snapshots) > 0


class ErrorAnalyzer:
    """Analyzes compiler, linter, runtime, and test failure outputs to pinpoint affected files and errors."""

    @classmethod
    def analyze(cls, output: str, workspace_root: Optional[Path] = None) -> Dict[str, Any]:
        if not output:
            return {
                "affected_files": [],
                "error_type": "Unknown",
                "error_summary": "Empty error output",
                "summary": "Empty error output",
                "errors": [],
            }

        ws_resolved = (workspace_root or Path.cwd()).resolve()

        affected: Set[str] = set()
        error_types: List[str] = []
        error_lines: List[str] = []
        structured_errors: List[Dict[str, Any]] = []

        # 1. Python tracebacks: File "path/to/file.py", line 123
        py_matches = re.findall(r'File "([^"]+)", line (\d+)(?:, in (\w+))?', output)
        for path_str, line_num, func in py_matches:
            clean_rel = path_str.replace("\\", "/").lstrip("./")
            affected.add(clean_rel)
            structured_errors.append({
                "file": clean_rel,
                "line": int(line_num),
                "function": func or "",
                "type": "RuntimeError",
            })

        # Python exception lines: NameError: name 'x' is not defined
        exc_match = re.search(r'\n([a-zA-Z0-9_]+Error|[a-zA-Z0-9_]+Exception):\s*(.*)', output)
        if exc_match:
            exc_type = exc_match.group(1)
            exc_msg = exc_match.group(2).strip()
            error_types.append(exc_type)
            if structured_errors:
                structured_errors[-1]["type"] = exc_type
                structured_errors[-1]["message"] = exc_msg

        # 2. JS / TS compiler errors: src/index.ts:15:7 - error TS2322: ...
        ts_matches = re.findall(r'(?:^|\s|\()([a-zA-Z0-9_\-./\\]+\.(?:js|jsx|ts|tsx|vue|svelte)):(\d+)(?::(\d+))?\s*(?:-\s*error\s*([a-zA-Z0-9_]+))?(?::|\s*)(.*)', output)
        for path_str, line_num, col_num, err_code, msg in ts_matches:
            clean_rel = path_str.replace("\\", "/").lstrip("./")
            affected.add(clean_rel)
            structured_errors.append({
                "file": clean_rel,
                "line": int(line_num),
                "col": int(col_num) if col_num else None,
                "type": err_code or "SyntaxError",
                "message": msg.strip() if msg else "",
            })
            if err_code:
                error_types.append(err_code)

        # 3. pytest failure summaries: FAILED tests/test_calc.py::test_add - AssertionError: ...
        pytest_summary_matches = re.findall(r'FAILED\s+([a-zA-Z0-9_\-./\\]+\.py)(?:::([a-zA-Z0-9_]+))?\s*(?:-\s*([a-zA-Z0-9_]+Error|[a-zA-Z0-9_]+Exception))?(?::|\s*)(.*)', output)
        for file_str, test_func, err_type, msg in pytest_summary_matches:
            clean_rel = file_str.replace("\\", "/").lstrip("./")
            affected.add(clean_rel)
            structured_errors.append({
                "file": clean_rel,
                "test": test_func or "",
                "type": err_type or "AssertionError",
                "message": msg.strip() if msg else "",
            })
            if err_type:
                error_types.append(err_type)

        # 4. Standard errors
        standard_errors = [
            "AssertionError", "SyntaxError", "NameError", "TypeError", "ValueError",
            "AttributeError", "ImportError", "ModuleNotFoundError", "IndexError", "KeyError",
            "ReferenceError", "CompilationError"
        ]
        for err in standard_errors:
            if re.search(rf"\b{err}\b", output) and err not in error_types:
                error_types.append(err)

        # 5. Extract short error summary line
        lines = output.splitlines()
        for line in reversed(lines):
            clean_l = line.strip()
            if any(err in clean_l for err in standard_errors) or clean_l.startswith("E   ") or "FAILED" in clean_l or "error:" in clean_l.lower():
                error_lines.append(clean_l.lstrip("E ").strip())
                if len(error_lines) >= 2:
                    break

        error_summary = " | ".join(reversed(error_lines)) if error_lines else (output.strip().splitlines()[-1] if output.strip() else "Unknown error")

        return {
            "affected_files": sorted(list(affected)),
            "error_type": error_types[0] if error_types else "Error",
            "error_summary": error_summary[:200],
            "summary": error_summary[:200],
            "errors": structured_errors,
            "full_error": output[:1000],
        }


class BuildTestVerifier:
    """Detects and runs project build and test commands through the AXON Router."""

    def __init__(self, router: Router):
        self.router = router

    def detect_test_command(self, project_info: ProjectInfo, workspace: Path) -> Optional[str]:
        """Detect the appropriate test command for the project."""
        default_cmd = getattr(project_info, "default_test_cmd", None)
        if default_cmd:
            return default_cmd

        # 1. Check package.json scripts for 'test'
        pkg_json = workspace / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    pm = project_info.package_manager or "npm"
                    return f"{pm} test" if pm != "npm" else "npm test"
            except Exception:
                pass

        # 2. Python test runner
        langs_lower = [l.lower() for l in project_info.languages]
        if project_info.test_framework == "pytest" or "python" in langs_lower:
            return "python -m pytest"

        # 3. Vitest or Jest
        if project_info.test_framework and "vitest" in project_info.test_framework.lower():
            return "npx vitest run"
        if project_info.test_framework and "jest" in project_info.test_framework.lower():
            return "npx jest"

        # 4. Cargo
        if "rust" in langs_lower or (workspace / "Cargo.toml").exists():
            return "cargo test"

        return None

    def detect_build_command(self, project_info: ProjectInfo, workspace: Path) -> Optional[str]:
        """Detect build command if the project defines a build system or build script."""
        pkg_json = workspace / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                scripts = data.get("scripts", {})
                if "build" in scripts:
                    pm = project_info.package_manager or "npm"
                    return f"{pm} run build" if pm in ("npm", "pnpm") else f"{pm} build"
            except Exception:
                pass

        langs_lower = [l.lower() for l in project_info.languages]
        if project_info.build_system == "Vite" or (workspace / "vite.config.js").exists() or (workspace / "vite.config.ts").exists():
            return "npx vite build"
        if project_info.build_system == "Next.js":
            return "npx next build"
        if "rust" in langs_lower or (workspace / "Cargo.toml").exists():
            return "cargo build"

        return None

    def verify(
        self,
        workspace: Path,
        project_info: ProjectInfo,
        test_command_override: Optional[str] = None,
        build_command_override: Optional[str] = None,
        test_command: Optional[str] = None,
        build_command: Optional[str] = None,
    ) -> VerificationResult:
        """Run build and test verification on the active workspace."""
        build_cmd = build_command or build_command_override or self.detect_build_command(project_info, workspace)
        test_cmd = test_command or test_command_override or self.detect_test_command(project_info, workspace)

        build_passed = True
        build_output = ""
        tests_passed = True
        test_output = ""

        # 1. Run build verification if build command detected
        if build_cmd:
            b_res = self.router.execute("coding.run_build", command=build_cmd)
            r_dict = b_res.get("result", {})
            build_passed = b_res.get("success", False) and (r_dict.get("exit_code", 0) == 0)
            build_output = r_dict.get("output", "") or b_res.get("error", "")

            if not build_passed:
                analysis = ErrorAnalyzer.analyze(build_output, workspace)
                return VerificationResult(
                    passed=False,
                    build_passed=False,
                    tests_passed=True,
                    build_output=build_output,
                    build_command=build_cmd,
                    test_command=test_cmd,
                    error=f"Build failed: {analysis.get('error_summary', 'Unknown build error')}",
                    affected_files=analysis.get("affected_files", []),
                    details=analysis,
                )

        # 2. Run test verification if test command detected
        if test_cmd:
            t_res = self.router.execute("coding.run_tests", command=test_cmd)
            r_dict = t_res.get("result", {})
            tests_passed = t_res.get("success", False) and (r_dict.get("exit_code", 0) == 0)
            test_output = r_dict.get("output", "") or t_res.get("error", "")

            if not tests_passed:
                analysis = ErrorAnalyzer.analyze(test_output, workspace)
                return VerificationResult(
                    passed=False,
                    build_passed=build_passed,
                    tests_passed=False,
                    build_output=build_output,
                    test_output=test_output,
                    build_command=build_cmd,
                    test_command=test_cmd,
                    error=f"Tests failed: {analysis.get('error_summary', 'Test failure')}",
                    affected_files=analysis.get("affected_files", []),
                    details=analysis,
                )

        # Both build and tests passed or none configured
        return VerificationResult(
            passed=True,
            build_passed=True,
            tests_passed=True,
            build_output=build_output,
            test_output=test_output,
            build_command=build_cmd,
            test_command=test_cmd,
            error="",
            affected_files=[],
            details={},
        )
