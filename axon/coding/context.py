"""AXON Coding Context — manages workspace inspection, framework detection, and change tracking."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from axon.tools.filesystem import _CURRENT_WORKSPACE


@dataclass
class CodingChangeReport:
    files_changed: List[str] = field(default_factory=list)
    changes: List[str] = field(default_factory=list)
    tests_run: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    final_status: str = "completed"

    def format_summary(self) -> str:
        lines = []
        if self.files_changed:
            lines.append("Files changed:")
            for f in sorted(set(self.files_changed)):
                lines.append(f"- {f}")
            lines.append("")

        if self.changes:
            lines.append("Changes:")
            for c in self.changes:
                lines.append(f"- {c}")
            lines.append("")

        if self.tests_run:
            lines.append("Tests:")
            for t in self.tests_run:
                lines.append(f"{t}")
            lines.append("")

        if self.errors:
            lines.append("Errors:")
            for e in self.errors:
                lines.append(f"! {e}")
            lines.append("")

        status_label = "Completed" if self.final_status == "completed" else "Failed"
        lines.append(f"Status: {status_label}")
        return "\n".join(lines).strip()


from axon.coding.project import ProjectIntelligence, ProjectInfo


class WorkspaceContext:
    """Discovers project structure and tracks session changes."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self._workspace = workspace_root
        self._intelligence = ProjectIntelligence(workspace_root)

    @property
    def workspace(self) -> Path:
        from axon.tools.filesystem import get_current_workspace
        current = (self._workspace or get_current_workspace() or Path.cwd()).resolve()
        if hasattr(self, "_intelligence") and self._intelligence and self._intelligence.root != current:
            self._intelligence.set_workspace(current)
        return current

    @property
    def intelligence(self) -> ProjectIntelligence:
        self.workspace  # Sync intelligence root
        return self._intelligence

    def get_project_info(self, refresh: bool = False) -> ProjectInfo:
        return self.intelligence.analyze(refresh=refresh)

    def detect_project_type(self) -> Dict[str, Any]:
        info = self.get_project_info()
        ws = self.workspace

        has_py = "Python" in info.languages or (ws / "requirements.txt").exists() or (ws / "pyproject.toml").exists()
        has_node = "JavaScript" in info.languages or "TypeScript" in info.languages or (ws / "package.json").exists()
        has_rust = "Rust" in info.languages or (ws / "Cargo.toml").exists()
        has_git = (ws / ".git").exists()

        default_test = "python -m pytest" if has_py else ("npm test" if has_node else "")
        if info.test_framework == "pytest":
            default_test = "python -m pytest"
        elif info.test_framework in ("Vitest", "Jest"):
            default_test = "npm test"

        return {
            "is_python": has_py,
            "is_node": has_node,
            "is_rust": has_rust,
            "has_git": has_git,
            "frameworks": info.frameworks,
            "package_manager": info.package_manager,
            "test_framework": info.test_framework,
            "languages": info.languages,
            "entry_points": info.entry_points,
            "important_files": info.important_files,
            "default_test_cmd": default_test,
        }
