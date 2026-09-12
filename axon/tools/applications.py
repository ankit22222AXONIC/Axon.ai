"""Application control tools — discovery, launching, checking, and closing Windows apps."""

import os
import shutil
import subprocess
from pathlib import Path


# ── Friendly name → Windows launch command ──────────────────────────────────
# Maps common human-friendly application names to the actual Windows command,
# executable, or URI scheme that launches them.  Checked before Start Menu
# shortcuts and PATH lookup so that "Open Calculator" just works.
_APP_ALIASES: dict[str, str] = {
    # Windows built-ins
    "calculator":       "calc",
    "calc":             "calc",
    "notepad":          "notepad",
    "paint":            "mspaint",
    "mspaint":          "mspaint",
    "wordpad":          "wordpad",
    "snipping tool":    "snippingtool",
    "task manager":     "taskmgr",
    "taskmgr":          "taskmgr",
    "cmd":              "cmd",
    "command prompt":   "cmd",
    "powershell":       "powershell",
    "terminal":         "wt",
    "windows terminal": "wt",
    "file explorer":    "explorer",
    "explorer":         "explorer",
    "control panel":    "control",
    "device manager":   "devmgmt.msc",
    "disk management":  "diskmgmt.msc",
    "registry editor":  "regedit",
    "regedit":          "regedit",
    # Windows Settings (URI scheme)
    "settings":         "ms-settings:",
    "wifi":             "ms-settings:network-wifi",
    "bluetooth":        "ms-settings:bluetooth",
    "display":          "ms-settings:display",
    "sound":            "ms-settings:sound",
    # Common third-party (executable names or Start Menu names)
    "chrome":           "chrome",
    "google chrome":    "chrome",
    "firefox":          "firefox",
    "edge":             "msedge",
    "microsoft edge":   "msedge",
    "vs code":          "code",
    "vscode":           "code",
    "visual studio code": "code",
    # Web shortcuts
    "youtube":          "https://www.youtube.com",
    "yt":               "https://www.youtube.com",
}


def _get_start_menu_shortcuts() -> dict[str, Path]:
    """Map application names (lowercased) to their .lnk shortcut paths."""
    shortcuts = {}
    search_dirs = [
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs",
    ]
    for search_dir in search_dirs:
        if search_dir.exists():
            for lnk in search_dir.rglob("*.lnk"):
                name = lnk.stem
                if name and not name.startswith("Uninstall"):
                    shortcuts[name.lower()] = lnk
    return shortcuts


def applications_list() -> list[str]:
    """List installed applications from Start Menu shortcuts and known aliases."""
    # Start Menu shortcuts
    shortcuts = _get_start_menu_shortcuts()
    apps = set(lnk.stem for lnk in shortcuts.values())
    # Also include human-friendly alias names that resolve on this machine
    for alias, cmd in _APP_ALIASES.items():
        if cmd.startswith("ms-") or shutil.which(cmd):
            apps.add(alias.title())
    return sorted(apps)


def applications_is_running(name: str) -> dict:
    """Check if an application or process matching 'name' is currently running."""
    if not name:
        return {"error": "No application name provided"}
    query = name.lower()
    if not query.endswith(".exe"):
        query_exe = query + ".exe"
    else:
        query_exe = query

    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        matches = []
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                proc_name = parts[0].strip()
                pid = parts[1].strip()
                if query in proc_name.lower() or query_exe == proc_name.lower():
                    matches.append({"name": proc_name, "pid": pid})
        return {
            "running": len(matches) > 0,
            "query": name,
            "instances_count": len(matches),
            "processes": matches[:10],
        }
    except Exception as e:
        return {"error": str(e)}


def _launch_command(cmd: str, args: str = "") -> dict:
    """Try to launch a command string via the best available Windows mechanism."""
    errors = []

    # URI schemes (e.g. ms-settings:) → os.startfile handles them natively
    if ":" in cmd and not cmd.endswith(".exe"):
        try:
            os.startfile(cmd)
            return {"status": "success", "launched": cmd, "method": "uri_scheme"}
        except Exception as e:
            errors.append(f"URI startfile failed: {e}")

    # Try shutil.which to find the real executable path
    exe = shutil.which(cmd) or shutil.which(cmd + ".exe")
    if exe:
        try:
            full_cmd = [exe] + ([args] if args else [])
            subprocess.Popen(full_cmd)
            return {"status": "success", "launched": cmd, "resolved_path": exe, "method": "executable"}
        except Exception as e:
            errors.append(f"Popen({exe}) failed: {e}")

    # Try os.startfile as a general shell fallback
    try:
        os.startfile(cmd)
        return {"status": "success", "launched": cmd, "method": "startfile"}
    except Exception as e:
        errors.append(f"startfile({cmd}) failed: {e}")

    return {"error": f"All launch methods failed for '{cmd}': {'; '.join(errors)}"}


def applications_open(name_or_path: str, args: str = "") -> dict:
    """Launch an application by friendly name, Start Menu name, or executable path.
    
    Resolution order:
      1. Direct file/folder path (os.startfile or subprocess)
      2. Known application aliases (Calculator → calc, Paint → mspaint, etc.)
      3. Start Menu shortcut (exact match then partial match)
      4. System PATH executable lookup
      5. Windows shell fallback (os.startfile)
    """
    if not name_or_path:
        return {"error": "No application name or path provided"}

    target = name_or_path.strip()
    target_lower = target.lower()

    # 1. Direct path that already exists on disk
    p = Path(target)
    if p.exists():
        try:
            if hasattr(os, "startfile") and not args:
                os.startfile(str(p))
            else:
                subprocess.Popen([str(p)] + ([args] if args else []))
            return {"status": "success", "launched": str(p), "method": "direct_path"}
        except Exception as e:
            return {"error": f"Failed to open '{p}': {e}"}

    # 2. Known friendly-name aliases (Calculator → calc, Settings → ms-settings:, etc.)
    alias_cmd = _APP_ALIASES.get(target_lower)
    if alias_cmd:
        result = _launch_command(alias_cmd, args)
        if result.get("status") == "success":
            result["alias"] = target
            return result
        # If the alias failed, don't give up yet — try subsequent methods.

    # 3. Start Menu shortcuts — exact match
    shortcuts = _get_start_menu_shortcuts()
    if target_lower in shortcuts:
        lnk = shortcuts[target_lower]
        try:
            os.startfile(str(lnk))
            return {"status": "success", "launched": lnk.stem, "path": str(lnk), "method": "start_menu_exact"}
        except Exception as e:
            pass  # fall through

    # 3b. Start Menu shortcuts — partial match
    for s_name, lnk in shortcuts.items():
        if target_lower in s_name or s_name in target_lower:
            try:
                os.startfile(str(lnk))
                return {"status": "success", "launched": lnk.stem, "path": str(lnk), "method": "start_menu_partial"}
            except Exception:
                continue

    # 4. Executable on system PATH
    which_path = shutil.which(target) or shutil.which(target + ".exe")
    if which_path:
        try:
            subprocess.Popen([which_path] + ([args] if args else []))
            return {"status": "success", "launched": target, "resolved_path": which_path, "method": "path_lookup"}
        except Exception as e:
            return {"error": f"Found '{target}' at {which_path} but failed to launch: {e}"}

    # 5. Last resort — ask Windows shell to figure it out
    try:
        os.startfile(target)
        return {"status": "success", "launched": target, "method": "shell_fallback"}
    except Exception as e:
        return {
            "error": (
                f"Could not launch '{name_or_path}'. "
                f"It was not found as a known application alias, Start Menu shortcut, "
                f"or executable on the system PATH. "
                f"Shell error: {e}"
            )
        }


def applications_close(name_or_pid: str) -> dict:
    """Close or terminate an application by process name or PID. Warning: Requires approval."""
    if not name_or_pid:
        return {"error": "No application name or PID provided"}

    target = str(name_or_pid).strip()
    is_numeric_pid = target.isdigit()

    try:
        if is_numeric_pid:
            cmd = ["taskkill", "/PID", target, "/F"]
        else:
            exe_name = target if target.lower().endswith(".exe") else f"{target}.exe"
            cmd = ["taskkill", "/IM", exe_name, "/F"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return {
                "status": "success",
                "message": result.stdout.strip() or f"Process {target} terminated",
                "target": target,
            }
        else:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            return {
                "error": stderr or stdout or f"Failed to close process {target}",
                "returncode": result.returncode,
            }
    except Exception as e:
        return {"error": str(e)}
