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


_CLOSE_NAME_MAP: dict[str, tuple[str, str]] = {
    "notepad": ("notepad.exe", "Notepad"),
    "vs code": ("code.exe", "Visual Studio Code"),
    "vscode": ("code.exe", "Visual Studio Code"),
    "visual studio code": ("code.exe", "Visual Studio Code"),
    "chrome": ("chrome.exe", "Chrome"),
    "google chrome": ("chrome.exe", "Google Chrome"),
    "edge": ("msedge.exe", "Edge"),
    "microsoft edge": ("msedge.exe", "Edge"),
    "file explorer": ("explorer.exe", "File Explorer"),
    "explorer": ("explorer.exe", "File Explorer"),
    "calc": ("calc.exe", "Calculator"),
    "calculator": ("calc.exe", "Calculator"),
    "paint": ("mspaint.exe", "Paint"),
    "wordpad": ("wordpad.exe", "WordPad"),
}


def applications_close(name_or_pid: str, force: bool = False) -> dict:
    """Close an application safely and gracefully. Never force-kills by default.
    
    Attempts graceful window close (WM_CLOSE) first so applications can prompt to save unsaved work.
    
    Args:
        name_or_pid: Application name, window title keyword, process executable, or PID.
        force: If True, force-kills the process with taskkill /F. Defaults to False (graceful close).
    """
    if not name_or_pid or not str(name_or_pid).strip():
        return {"error": "No application name or PID provided"}

    target = str(name_or_pid).strip()
    target_lower = target.lower()

    # Guard against closing protected core system processes or AXON's own process
    try:
        from axon.security.process_security import is_protected_process
        is_prot, reason = is_protected_process(target)
        if is_prot:
            return {"error": reason, "blocked": True}
    except Exception:
        pass

    is_numeric_pid = target.isdigit()

    # 1. Resolve aliases
    mapped_info = _CLOSE_NAME_MAP.get(target_lower)
    title_keyword = mapped_info[1] if mapped_info else target
    exe_name = mapped_info[0] if mapped_info else (target if target_lower.endswith(".exe") else f"{target}.exe")

    # 2. First attempt: Graceful Win32 WM_CLOSE to visible windows
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        closed_hwnds = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                # Check PID match if numeric
                if is_numeric_pid:
                    w_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                    if w_pid.value == int(target):
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        closed_hwnds.append(hwnd)
                        return True

                # Check window title match
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if title and (
                        title_keyword.lower() in title.lower()
                        or (mapped_info and mapped_info[1].lower() in title.lower())
                        or target_lower in title.lower()
                    ):
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        closed_hwnds.append(hwnd)
                        return True

                # Check File Explorer window class
                if target_lower in ("file explorer", "explorer"):
                    class_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, class_buf, 256)
                    if class_buf.value in ("CabinetWClass", "ExploreWClass"):
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        closed_hwnds.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        if closed_hwnds:
            return {
                "status": "success",
                "closed": True,
                "target": target,
                "windows_closed": len(closed_hwnds),
                "method": "wm_close",
                "message": f"Successfully sent graceful close message to {len(closed_hwnds)} window(s) of '{target}'",
            }
    except Exception:
        pass

    # Special handling for File Explorer: Do NOT terminate explorer.exe if no folder window was found
    if target_lower in ("file explorer", "explorer"):
        return {
            "status": "success",
            "closed": False,
            "target": target,
            "message": "No open File Explorer windows found to close",
        }

    # 3. Second attempt: Process termination request via taskkill (graceful by default)
    try:
        cmd = ["taskkill"]
        if is_numeric_pid:
            cmd.extend(["/PID", target])
        else:
            cmd.extend(["/IM", exe_name])

        if force:
            cmd.append("/F")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return {
                "status": "success",
                "closed": True,
                "target": target,
                "method": "force_taskkill" if force else "graceful_taskkill",
                "message": result.stdout.strip() or f"Process {target} closed successfully",
            }
        else:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            # If not running, return informative not_found status
            if "not found" in stderr.lower() or "not found" in stdout.lower() or "could not be found" in stderr.lower():
                return {
                    "status": "not_found",
                    "closed": False,
                    "target": target,
                    "message": f"No running instance or window found for '{target}'",
                }
            return {
                "error": stderr or stdout or f"Failed to close process {target}",
                "returncode": result.returncode,
            }
    except Exception as e:
        return {"error": str(e)}

