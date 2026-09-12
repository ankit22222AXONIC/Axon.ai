"""Filesystem tools — file and directory management."""

import os
import shutil
import glob as glob_mod
from datetime import datetime
from pathlib import Path


_CURRENT_WORKSPACE: Path = Path.cwd().resolve()


def get_current_workspace() -> Path:
    """Get the current active workspace Path dynamically."""
    global _CURRENT_WORKSPACE
    return _CURRENT_WORKSPACE


def filesystem_set_workspace(path: str) -> dict:
    """Set the active workspace or project folder for all relative operations."""
    global _CURRENT_WORKSPACE
    if path is None:
        _CURRENT_WORKSPACE = Path.cwd().resolve()
        return {"status": "success", "workspace": str(_CURRENT_WORKSPACE)}
    if not path:
        return {"error": "No workspace path provided"}
    p = resolve_path(path)
    if not p.exists():
        return {"error": f"Path '{path}' does not exist"}
    if not p.is_dir():
        return {"error": f"Path '{path}' is not a directory"}
    _CURRENT_WORKSPACE = p.resolve()
    return {"status": "success", "workspace": str(_CURRENT_WORKSPACE)}


def filesystem_get_workspace() -> dict:
    """Get the current active workspace or project folder."""
    return {"status": "success", "workspace": str(_CURRENT_WORKSPACE)}


def resolve_path(path: str) -> Path:
    """Resolve paths expanding user home, environment variables, and relative to active workspace."""
    if not path or path.strip() in (".", ""):
        return _CURRENT_WORKSPACE
    p_str = os.path.expandvars(path.strip())
    p_str = os.path.expanduser(p_str)
    
    # Common user folder shortcuts
    lower = p_str.lower()
    home = Path.home()
    if lower == "desktop":
        return (home / "Desktop").resolve()
    elif lower == "downloads":
        return (home / "Downloads").resolve()
    elif lower == "documents":
        return (home / "Documents").resolve()
    
    p = Path(p_str)
    if not p.is_absolute():
        return (_CURRENT_WORKSPACE / p).resolve()
    return p.resolve()


def filesystem_list(path: str = ".") -> list[str]:
    """List contents of a directory."""
    resolved = resolve_path(path)
    if not resolved.exists():
        return [f"Error: {path} not found"]
    if not resolved.is_dir():
        return [f"Error: {path} is not a directory"]

    entries = []
    for entry in os.scandir(resolved):
        kind = "dir" if entry.is_dir() else "file"
        entries.append(f"[{kind}] {entry.name}")
    return sorted(entries)


def filesystem_list_detailed(path: str = ".") -> list[dict]:
    """List detailed contents of a directory with metadata."""
    resolved = resolve_path(path)
    if not resolved.exists():
        return [{"error": f"{path} not found"}]
    if not resolved.is_dir():
        return [{"error": f"{path} is not a directory"}]

    results = []
    for entry in os.scandir(resolved):
        try:
            stat = entry.stat()
            results.append({
                "name": entry.name,
                "path": entry.path,
                "is_dir": entry.is_dir(),
                "size_bytes": stat.st_size if entry.is_file() else 0,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            results.append({
                "name": entry.name,
                "path": entry.path,
                "is_dir": entry.is_dir(),
            })
    return sorted(results, key=lambda x: (not x.get("is_dir", False), x.get("name", "").lower()))


def filesystem_search(path: str = ".", pattern: str = "*") -> list[str]:
    """Search for files matching a glob pattern."""
    resolved = resolve_path(path)
    search_path = str(resolved / "**" / pattern)
    results = glob_mod.glob(search_path, recursive=True)
    return results[:100]  # cap results for safety


def filesystem_read(path: str = "", max_bytes: int = 1_000_000) -> str:
    """Read a file's contents (text, with size limit)."""
    if not path:
        return "Error: no path provided"
    p = resolve_path(path)
    if not p.exists():
        return f"Error: {path} not found"
    if not p.is_file():
        return f"Error: {path} is not a file"
    if p.stat().st_size > max_bytes:
        return f"Error: file too large ({p.stat().st_size} bytes, limit {max_bytes})"
    return p.read_text(encoding="utf-8", errors="replace")


def filesystem_write(path: str, content: str, append: bool = False) -> dict:
    """Write text content to a file. Creates parent directories if missing."""
    if not path:
        return {"error": "No path provided"}
    try:
        p = resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        return {
            "status": "success",
            "path": str(p),
            "bytes_written": len(content.encode("utf-8")),
            "mode": "append" if append else "overwrite",
        }
    except Exception as e:
        return {"error": str(e)}


def filesystem_create_directory(path: str) -> dict:
    """Create a directory (recursively)."""
    if not path:
        return {"error": "No path provided"}
    try:
        p = resolve_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return {"status": "success", "path": str(p)}
    except Exception as e:
        return {"error": str(e)}


def filesystem_delete(path: str) -> dict:
    """Delete a file or directory. Warning: Destructive operation requiring approval."""
    if not path:
        return {"error": "No path provided"}
    try:
        p = resolve_path(path)
        if not p.exists():
            return {"error": f"{path} does not exist"}
        
        if p.is_file():
            p.unlink()
            return {"status": "success", "path": str(p), "type": "file", "action": "deleted"}
        elif p.is_dir():
            shutil.rmtree(p)
            return {"status": "success", "path": str(p), "type": "directory", "action": "deleted"}
        else:
            return {"error": f"Unknown file system item at {path}"}
    except Exception as e:
        return {"error": str(e)}


def filesystem_copy(source: str, destination: str) -> dict:
    """Copy a file or directory to a destination."""
    if not source or not destination:
        return {"error": "Both source and destination must be provided"}
    try:
        src = resolve_path(source)
        dst = resolve_path(destination)
        if not src.exists():
            return {"error": f"Source {source} not found"}

        if src.is_file():
            if dst.is_dir():
                dst = dst / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return {"status": "success", "source": str(src), "destination": str(dst), "type": "file"}
        elif src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            return {"status": "success", "source": str(src), "destination": str(dst), "type": "directory"}
        return {"error": "Unsupported file system item"}
    except Exception as e:
        return {"error": str(e)}


def filesystem_move(source: str, destination: str) -> dict:
    """Move or rename a file or directory."""
    if not source or not destination:
        return {"error": "Both source and destination must be provided"}
    try:
        src = resolve_path(source)
        dst = resolve_path(destination)
        if not src.exists():
            return {"error": f"Source {source} not found"}

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"status": "success", "source": str(src), "destination": str(dst)}
    except Exception as e:
        return {"error": str(e)}


def filesystem_view_lines(path: str, start_line: int = 1, end_line: int = 100) -> dict:
    """Read a specific slice of lines from a file with line numbers for precise code inspection."""
    if not path:
        return {"error": "No path provided"}
    p = resolve_path(path)
    if not p.exists():
        return {"error": f"{path} not found"}
    if not p.is_file():
        return {"error": f"{path} is not a file"}
    
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(lines)
        start = max(1, start_line)
        end = min(total_lines, max(start, end_line))
        
        sliced = lines[start - 1 : end]
        numbered = [f"{i}: {line}" for i, line in enumerate(sliced, start=start)]
        return {
            "status": "success",
            "path": str(p),
            "total_lines": total_lines,
            "start_line": start,
            "end_line": end,
            "lines": "\n".join(numbered),
        }
    except Exception as e:
        return {"error": str(e)}


def filesystem_find_in_files(query: str, path: str = ".", case_sensitive: bool = False, max_results: int = 50) -> dict:
    """Search for text, function, variable, or code pattern across all files in a folder."""
    if not query:
        return {"error": "No search query provided"}
    root = resolve_path(path)
    if not root.exists():
        return {"error": f"{path} not found"}
    if not root.is_dir():
        return {"error": f"{path} is not a directory"}

    ignored_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode", "dist", "build"}
    matches = []
    q = query if case_sensitive else query.lower()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in-place
        dirnames[:] = [d for d in dirnames if d not in ignored_dirs and not d.startswith(".")]
        for filename in filenames:
            if len(matches) >= max_results:
                break
            file_path = Path(dirpath) / filename
            try:
                # Skip large files (> 2MB)
                if file_path.stat().st_size > 2_000_000:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                file_lines = content.splitlines()
                for line_idx, line in enumerate(file_lines, 1):
                    compare_line = line if case_sensitive else line.lower()
                    if q in compare_line:
                        matches.append({
                            "file": str(file_path.relative_to(root)),
                            "line_number": line_idx,
                            "line_content": line.strip(),
                        })
                        if len(matches) >= max_results:
                            break
            except Exception:
                continue

    return {
        "status": "success",
        "query": query,
        "match_count": len(matches),
        "matches": matches,
    }


def filesystem_replace_content(path: str, target: str, replacement: str, allow_multiple: bool = False) -> dict:
    """Surgically replace exact code or text content in an existing file."""
    if not path:
        return {"error": "No path provided"}
    if not target:
        return {"error": "Target content to replace cannot be empty"}
    
    p = resolve_path(path)
    if not p.exists():
        return {"error": f"{path} does not exist"}
    if not p.is_file():
        return {"error": f"{path} is not a file"}
    
    try:
        content = p.read_text(encoding="utf-8")
        occurrences = content.count(target)
        if occurrences == 0:
            return {
                "error": f"Target content not found in '{p.name}'. Please check formatting and whitespace.",
                "target_preview": target[:100],
            }
        if occurrences > 1 and not allow_multiple:
            return {
                "error": f"Target content found {occurrences} times in '{p.name}'. Set allow_multiple=True or provide a more specific code block.",
                "occurrences": occurrences,
            }
        
        new_content = content.replace(target, replacement) if allow_multiple else content.replace(target, replacement, 1)
        p.write_text(new_content, encoding="utf-8")
        return {
            "status": "success",
            "path": str(p),
            "replacements_made": occurrences if allow_multiple else 1,
        }
    except Exception as e:
        return {"error": str(e)}
