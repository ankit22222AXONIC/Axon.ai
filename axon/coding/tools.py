"""AXON Coding Tools — workspace-locked tools for code inspection, editing, and testing.

All tools execute with workspace awareness, secret protection, and bounded output.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from axon.tools.filesystem import (
    resolve_path,
    filesystem_read,
    filesystem_write,
    filesystem_replace_content,
    filesystem_find_in_files,
    get_current_workspace,
)
from axon.tools.terminal import terminal_run
from axon.security.secrets import redact_secrets


# Directories to automatically skip during repository exploration to bound context
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    ".coverage",
}


def coding_list_files(
    path: str = ".",
    recursive: bool = False,
    max_depth: int = 3,
) -> Dict[str, Any]:
    """List source code and project files in the workspace, skipping large build/cache folders."""
    resolved = resolve_path(path)
    if not resolved.exists():
        return {"error": f"Path not found: {path}"}
    if not resolved.is_dir():
        return {"error": f"Path is not a directory: {path}"}

    results: List[Dict[str, Any]] = []

    if not recursive:
        try:
            for item in sorted(resolved.iterdir()):
                if item.name in IGNORED_DIRS or item.name.startswith("."):
                    continue
                results.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                })
        except Exception as e:
            return {"error": f"Failed to list directory: {e}"}
        return {"path": str(resolved), "files": results, "count": len(results)}

    # Recursive traversal with depth limit
    base_depth = len(resolved.parts)
    try:
        for root, dirs, files in os.walk(resolved):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            current_depth = len(Path(root).parts) - base_depth
            if current_depth >= max_depth:
                dirs.clear()
                continue

            rel_root = Path(root).relative_to(resolved)
            for f in sorted(files):
                if f.startswith("."):
                    continue
                file_rel = str(rel_root / f) if str(rel_root) != "." else f
                full_path = Path(root) / f
                try:
                    size = full_path.stat().st_size
                except Exception:
                    size = 0
                results.append({
                    "path": file_rel.replace("\\", "/"),
                    "size": size,
                })
                if len(results) >= 200:  # Bound listing length
                    break
            if len(results) >= 200:
                break
    except Exception as e:
        return {"error": f"Failed during recursive search: {e}"}

    return {"path": str(resolved), "files": results, "count": len(results)}


def coding_read_file(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> Dict[str, Any]:
    """Read full file or a specific line range from workspace with secret redaction."""
    resolved = resolve_path(path)
    if not resolved.exists():
        return {"error": f"File not found: {path}"}
    if not resolved.is_file():
        return {"error": f"Path is not a file: {path}"}

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Could not read file: {e}"}

    lines = content.splitlines()
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        s = max(1, start_line or 1)
        e = min(total_lines, end_line or total_lines)
        selected_lines = lines[s - 1 : e]
        content_snippet = "\n".join(
            f"{line_num:4d} | {line}"
            for line_num, line in enumerate(selected_lines, start=s)
        )
        clean_snippet, _ = redact_secrets(content_snippet)
        return {
            "path": str(resolved),
            "start_line": s,
            "end_line": e,
            "total_lines": total_lines,
            "content": clean_snippet,
        }

    # Bound reading size to prevent blowing context window (approx 20,000 chars)
    if len(content) > 25_000:
        content = content[:25_000] + "\n\n[...FILE TRUNCATED FOR CONTEXT LIMIT: USE start_line/end_line TO VIEW SPECIFIC RANGES...]"

    clean_content, _ = redact_secrets(content)
    return {
        "path": str(resolved),
        "total_lines": total_lines,
        "content": clean_content,
    }


def coding_search_code(
    query: str,
    path: str = ".",
    extension: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for code symbols, function definitions, or text patterns across workspace files."""
    res = filesystem_find_in_files(query=query, path=path)
    if isinstance(res, dict) and "match_count" in res:
        res["matches_count"] = res["match_count"]
    return res


def coding_create_file(path: str, content: str) -> Dict[str, Any]:
    """Create a new file within the workspace with the provided content."""
    return filesystem_write(path=path, content=content)


def coding_write_file(path: str, content: str) -> Dict[str, Any]:
    """Write or overwrite a file within the workspace with the provided content."""
    return filesystem_write(path=path, content=content)


def coding_edit_file(path: str, target: str, replacement: str) -> Dict[str, Any]:
    """Surgically replace exact code or text in an existing workspace file."""
    return filesystem_replace_content(path=path, target=target, replacement=replacement)


def coding_run_tests(
    command: Optional[str] = None,
    project_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run tests for the project in the active workspace.
    
    Automatically detects test runner (e.g. pytest or npm test) if no command is specified.
    """
    ws = get_current_workspace()
    cmd = command

    if not cmd:
        # Detect project type
        if (ws / "pytest.ini").exists() or (ws / "tests").exists() or any(ws.glob("*.py")):
            cmd = "python -m pytest"
        elif (ws / "package.json").exists():
            cmd = "npm test"
        else:
            cmd = "python -m pytest"

    # Execute in workspace directory using terminal_run
    orig_cwd = os.getcwd()
    try:
        os.chdir(ws)
        res = terminal_run(cmd)
    finally:
        os.chdir(orig_cwd)

    retcode = res.get("returncode", 0 if not res.get("error") else 1)
    out = (res.get("stdout", "") + ("\n" + res.get("stderr", "") if res.get("stderr") else "")).strip()
    return {
        "success": retcode == 0,
        "exit_code": retcode,
        "returncode": retcode,
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
        "output": out or res.get("error", ""),
        "workspace": str(ws),
        "command": cmd,
    }


def coding_run_build(
    command: Optional[str] = None,
) -> Dict[str, Any]:
    """Run project build command in the active workspace."""
    ws = get_current_workspace()
    cmd = command

    if not cmd:
        pkg_json = ws / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                if "build" in data.get("scripts", {}):
                    cmd = "npm run build"
            except Exception:
                pass
        if not cmd and (ws / "Cargo.toml").exists():
            cmd = "cargo build"
        if not cmd:
            cmd = "npm run build"

    orig_cwd = os.getcwd()
    try:
        os.chdir(ws)
        res = terminal_run(cmd)
    finally:
        os.chdir(orig_cwd)

    retcode = res.get("returncode", 0 if not res.get("error") else 1)
    out = (res.get("stdout", "") + ("\n" + res.get("stderr", "") if res.get("stderr") else "")).strip()
    return {
        "success": retcode == 0,
        "exit_code": retcode,
        "returncode": retcode,
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
        "output": out or res.get("error", ""),
        "workspace": str(ws),
        "command": cmd,
    }

