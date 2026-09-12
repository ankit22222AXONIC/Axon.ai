"""AXON Desktop Automation Tools — mouse, keyboard, window control, and desktop understanding."""

import ctypes
from ctypes import wintypes
import csv
import io
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image

from axon.tools.screenshot import screenshot_take
from axon.security.secrets import redact_secrets


# ── Win32 Constants & Key Codes ─────────────────────────────────────────────

# Mouse event flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

# Keyboard event flags
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Window management
SW_HIDE = 0
SW_NORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010

# Virtual-Key codes mapping
VK_MAP = {
    "backspace": 0x08,
    "tab": 0x09,
    "clear": 0x0C,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "caps_lock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "page_up": 0x21,
    "pagedown": 0x22,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "select": 0x29,
    "print": 0x2A,
    "printscreen": 0x2C,
    "prtscr": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "windows": 0x5B,
    "num0": 0x60,
    "num1": 0x61,
    "num2": 0x62,
    "num3": 0x63,
    "num4": 0x64,
    "num5": 0x65,
    "num6": 0x66,
    "num7": 0x67,
    "num8": 0x68,
    "num9": 0x69,
    "multiply": 0x6A,
    "add": 0x6B,
    "separator": 0x6C,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "numlock": 0x90,
    "scrolllock": 0x91,
}

# Populate alphanumeric keys
for c in "abcdefghijklmnopqrstuvwxyz":
    VK_MAP[c] = ord(c.upper())
for c in "0123456789":
    VK_MAP[c] = ord(c)


# ── Safety Boundaries & Reset ───────────────────────────────────────────────

def get_screen_bounds() -> Tuple[int, int]:
    """Return primary display (width, height)."""
    try:
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def clamp_coordinates(x: int, y: int) -> Tuple[int, int]:
    """Clamp (x, y) coordinates to display bounds."""
    width, height = get_screen_bounds()
    clamped_x = max(0, min(int(x), width - 1))
    clamped_y = max(0, min(int(y), height - 1))
    return clamped_x, clamped_y


def safety_reset() -> Dict[str, Any]:
    """Release all modifier keys and mouse buttons to guarantee a clean state."""
    try:
        user32 = ctypes.windll.user32
        # Release mouse buttons
        user32.mouse_event(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_RIGHTUP | MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        # Release modifier keys
        for vk in (0x10, 0x11, 0x12, 0x5B):  # Shift, Ctrl, Alt, Win
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return {"status": "success", "message": "All keys and mouse buttons released"}
    except Exception as e:
        return {"status": "error", "error": f"Failed safety reset: {e}"}


# ── Mouse Automation ────────────────────────────────────────────────────────

def mouse_get_position() -> Dict[str, Any]:
    """Get current mouse cursor coordinates and display bounds."""
    try:
        user32 = ctypes.windll.user32
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        w, h = get_screen_bounds()
        return {
            "status": "success",
            "x": pt.x,
            "y": pt.y,
            "screen_width": w,
            "screen_height": h,
        }
    except Exception as e:
        return {"error": f"Failed to get mouse position: {e}"}


def mouse_move(x: int, y: int) -> Dict[str, Any]:
    """Move cursor to clamped (x, y) coordinates."""
    try:
        cx, cy = clamp_coordinates(x, y)
        user32 = ctypes.windll.user32
        res = user32.SetCursorPos(cx, cy)
        if not res:
            # Fallback to mouse_event absolute coordinate positioning
            w, h = get_screen_bounds()
            norm_x = int((cx / max(1, w - 1)) * 65535)
            norm_y = int((cy / max(1, h - 1)) * 65535)
            user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, norm_x, norm_y, 0, 0)
        return {
            "status": "success",
            "x": cx,
            "y": cy,
            "original_requested": {"x": x, "y": y},
        }
    except Exception as e:
        return {"error": f"Failed to move mouse: {e}"}


def mouse_click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Dict[str, Any]:
    """Click mouse button at current or specified (x, y) coordinates.
    
    Args:
        x: Optional target x coordinate.
        y: Optional target y coordinate.
        button: "left", "right", or "middle". Defaults to "left".
    """
    try:
        user32 = ctypes.windll.user32
        btn = (button or "left").lower().strip()
        if btn not in ("left", "right", "middle"):
            return {"error": f"Invalid mouse button '{button}'. Must be 'left', 'right', or 'middle'."}

        if x is not None and y is not None:
            cx, cy = clamp_coordinates(x, y)
            user32.SetCursorPos(cx, cy)
            time.sleep(0.02)
        else:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            cx, cy = pt.x, pt.y

        if btn == "left":
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        elif btn == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        else:
            down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

        user32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(up_flag, 0, 0, 0, 0)

        return {
            "status": "success",
            "action": "click",
            "button": btn,
            "x": cx,
            "y": cy,
        }
    except Exception as e:
        safety_reset()
        return {"error": f"Failed mouse click: {e}"}


def mouse_double_click(x: Optional[int] = None, y: Optional[int] = None) -> Dict[str, Any]:
    """Perform a double left-click at current or specified (x, y) coordinates."""
    try:
        user32 = ctypes.windll.user32
        if x is not None and y is not None:
            cx, cy = clamp_coordinates(x, y)
            user32.SetCursorPos(cx, cy)
            time.sleep(0.02)
        else:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            cx, cy = pt.x, pt.y

        # First click
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.08)
        # Second click
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        return {
            "status": "success",
            "action": "double_click",
            "button": "left",
            "x": cx,
            "y": cy,
        }
    except Exception as e:
        safety_reset()
        return {"error": f"Failed double-click: {e}"}


def mouse_scroll(delta: int = 120) -> Dict[str, Any]:
    """Scroll mouse wheel. Positive values scroll up, negative values scroll down.
    
    Standard wheel notch is 120 units.
    """
    try:
        user32 = ctypes.windll.user32
        d = int(delta)
        # Bounded between -1200 and +1200 per action (10 wheel notches)
        d_clamped = max(-1200, min(1200, d))
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, d_clamped, 0)
        return {
            "status": "success",
            "action": "scroll",
            "delta": d_clamped,
        }
    except Exception as e:
        return {"error": f"Failed mouse scroll: {e}"}


# ── Keyboard Automation ─────────────────────────────────────────────────────

def keyboard_press(key: str) -> Dict[str, Any]:
    """Press and release a single key.
    
    Supports: enter, tab, esc, backspace, space, delete, home, end,
    pageup, pagedown, up, down, left, right, f1-f12, and letters/digits.
    """
    if not key or not str(key).strip():
        return {"error": "No key provided"}

    k_clean = str(key).strip().lower()
    vk = VK_MAP.get(k_clean)
    if vk is None:
        return {"error": f"Unrecognized key: '{key}'"}

    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, KEYEVENTF_KEYDOWN, 0)
        time.sleep(0.03)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return {"status": "success", "key": k_clean, "vk": vk}
    except Exception as e:
        safety_reset()
        return {"error": f"Failed to press key '{key}': {e}"}


def keyboard_hotkey(keys: str) -> Dict[str, Any]:
    """Press a key combination simultaneously, e.g. 'ctrl+c', 'ctrl+v', 'alt+tab'.
    
    Keys are joined by '+'.
    """
    if not keys or not str(keys).strip():
        return {"error": "No hotkey combination provided"}

    parts = [p.strip().lower() for p in str(keys).split("+") if p.strip()]
    if not parts:
        return {"error": "Invalid hotkey format"}

    vk_list = []
    for p in parts:
        vk = VK_MAP.get(p)
        if vk is None:
            return {"error": f"Unrecognized key in hotkey: '{p}'"}
        vk_list.append((p, vk))

    try:
        user32 = ctypes.windll.user32
        # Press all keys down in order
        for _, vk in vk_list:
            user32.keybd_event(vk, 0, KEYEVENTF_KEYDOWN, 0)
            time.sleep(0.02)

        time.sleep(0.04)

        # Release all keys in reverse order
        for _, vk in reversed(vk_list):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

        return {"status": "success", "hotkey": "+".join(parts), "keys_pressed": len(vk_list)}
    except Exception as e:
        safety_reset()
        return {"error": f"Failed to execute hotkey '{keys}': {e}"}


def keyboard_type(text: str) -> Dict[str, Any]:
    """Type a string of text using Unicode keyboard events.
    
    Supports alphanumeric, punctuation, spaces, and multi-line strings.
    Bounded to 2000 characters per call for safety.
    """
    if text is None:
        return {"error": "No text provided"}

    s_text = str(text)
    if len(s_text) > 2000:
        return {"error": f"Text exceeds maximum safe limit of 2000 characters (length: {len(s_text)})"}

    try:
        user32 = ctypes.windll.user32

        # Define SendInput structures for Unicode input
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("_input",)
            _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

        INPUT_KEYBOARD = 1

        for char in s_text:
            if char == "\n":
                # Send Enter
                user32.keybd_event(0x0D, 0, KEYEVENTF_KEYDOWN, 0)
                time.sleep(0.01)
                user32.keybd_event(0x0D, 0, KEYEVENTF_KEYUP, 0)
            elif char == "\t":
                # Send Tab
                user32.keybd_event(0x09, 0, KEYEVENTF_KEYDOWN, 0)
                time.sleep(0.01)
                user32.keybd_event(0x09, 0, KEYEVENTF_KEYUP, 0)
            else:
                code = ord(char)
                inp_down = INPUT()
                inp_down.type = INPUT_KEYBOARD
                inp_down.ki.wVk = 0
                inp_down.ki.wScan = code
                inp_down.ki.dwFlags = KEYEVENTF_UNICODE
                inp_down.ki.time = 0
                inp_down.ki.dwExtraInfo = None

                inp_up = INPUT()
                inp_up.type = INPUT_KEYBOARD
                inp_up.ki.wVk = 0
                inp_up.ki.wScan = code
                inp_up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                inp_up.ki.time = 0
                inp_up.ki.dwExtraInfo = None

                user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
                time.sleep(0.005)
                user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
                time.sleep(0.005)

        return {
            "status": "success",
            "action": "type",
            "characters_typed": len(s_text),
        }
    except Exception as e:
        safety_reset()
        return {"error": f"Failed keyboard typing: {e}"}


# ── Window & Desktop Control ────────────────────────────────────────────────

def desktop_get_windows() -> List[Dict[str, Any]]:
    """Enumerate visible desktop windows and processes with titles.
    
    Uses Windows tasklist telemetry combined with Win32 window metrics.
    """
    windows = []
    seen_titles = set()

    try:
        # 1. Query tasklist for window titles
        result = subprocess.run(
            ["tasklist", "/V", "/FO", "CSV"],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0:
            reader = csv.reader(io.StringIO(result.stdout))
            next(reader, None)  # skip header
            for row in reader:
                if len(row) >= 9:
                    proc_name = row[0].strip()
                    pid = row[1].strip()
                    mem = row[4].strip()
                    title = row[8].strip()

                    # Filter out headless/background placeholders and empty titles
                    if (
                        title
                        and title != "N/A"
                        and title != "OleMainThreadWndName"
                        and not title.startswith(".NET-BroadcastEventWindow")
                        and title not in seen_titles
                    ):
                        seen_titles.add(title)
                        windows.append({
                            "title": title,
                            "process": proc_name,
                            "pid": pid,
                            "memory": mem,
                        })
    except Exception:
        pass

    return windows


def desktop_get_active_window() -> Dict[str, Any]:
    """Retrieve details for the current active/foreground window."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            return {
                "status": "success",
                "hwnd": hwnd,
                "title": title or "Unknown",
                "pid": pid.value,
                "bounds": {
                    "left": rect.left,
                    "top": rect.top,
                    "right": rect.right,
                    "bottom": rect.bottom,
                    "width": max(0, rect.right - rect.left),
                    "height": max(0, rect.bottom - rect.top),
                },
            }
        else:
            # Fallback to inspecting visible windows
            wins = desktop_get_windows()
            first = wins[0] if wins else {}
            return {
                "status": "success",
                "hwnd": 0,
                "title": first.get("title", "Desktop"),
                "process": first.get("process", "explorer.exe"),
                "pid": first.get("pid", 0),
            }
    except Exception as e:
        return {"error": f"Failed to get active window: {e}"}


def desktop_switch_window(title_or_pid: str) -> Dict[str, Any]:
    """Switch focus to an open window by matching its title or PID."""
    if not title_or_pid:
        return {"error": "No window title or PID provided"}

    target = str(title_or_pid).strip().lower()

    # 1. Native Win32 search by window text
    try:
        user32 = ctypes.windll.user32
        found_hwnd = None
        found_title = None

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, lparam):
            nonlocal found_hwnd, found_title
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    val = buf.value.lower()
                    if target in val:
                        found_hwnd = hwnd
                        found_title = buf.value
                        return False
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)

        if found_hwnd:
            user32.ShowWindow(found_hwnd, SW_RESTORE)
            user32.SetForegroundWindow(found_hwnd)
            return {
                "status": "success",
                "switched": True,
                "hwnd": found_hwnd,
                "title": found_title,
                "method": "win32_enum",
            }
    except Exception:
        pass

    # 2. Windows shell activation fallback via PowerShell AppActivate
    try:
        ps_cmd = f"(New-Object -ComObject WScript.Shell).AppActivate('{title_or_pid}')"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5
        )
        activated = "true" in res.stdout.lower() or res.returncode == 0
        return {
            "status": "success",
            "switched": activated,
            "target": title_or_pid,
            "method": "wscript_appactivate",
        }
    except Exception as e:
        return {"error": f"Failed to switch to window '{title_or_pid}': {e}"}


def desktop_close_window(title_or_pid: str) -> Dict[str, Any]:
    """Close an application window gracefully (sends WM_CLOSE). Requires user approval."""
    if not title_or_pid:
        return {"error": "No window title or PID provided"}

    target = str(title_or_pid).strip()

    # 1. Win32 graceful WM_CLOSE
    try:
        user32 = ctypes.windll.user32
        closed_hwnds = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _close_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if target.lower() in buf.value.lower():
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        closed_hwnds.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_close_cb), 0)
        if closed_hwnds:
            return {
                "status": "success",
                "closed": True,
                "target": target,
                "hwnds": closed_hwnds,
                "method": "wm_close",
            }
    except Exception:
        pass

    # 2. Fallback to process termination via taskkill
    try:
        if target.isdigit():
            cmd = ["taskkill", "/PID", target]
        else:
            exe = target if target.lower().endswith(".exe") else f"{target}.exe"
            cmd = ["taskkill", "/IM", exe]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if res.returncode == 0:
            return {
                "status": "success",
                "closed": True,
                "target": target,
                "method": "taskkill",
            }
        else:
            return {
                "error": res.stderr.strip() or res.stdout.strip() or f"Could not close {target}",
            }
    except Exception as e:
        return {"error": f"Failed to close window '{target}': {e}"}


def desktop_inspect_screen() -> Dict[str, Any]:
    """Aggregate desktop state: resolution, mouse position, active window, and visible apps."""
    w, h = get_screen_bounds()
    pos = mouse_get_position()
    active = desktop_get_active_window()
    windows = desktop_get_windows()

    return {
        "status": "success",
        "display": {"width": w, "height": h, "aspect_ratio": f"{round(w/max(1,h), 2)}:1"},
        "cursor": {"x": pos.get("x", 0), "y": pos.get("y", 0)},
        "active_window": active.get("title", "Desktop"),
        "visible_windows_count": len(windows),
        "visible_windows": windows[:10],
        "untrusted_data": True,
    }


# ── Screenshot Understanding ────────────────────────────────────────────────

def screenshot_analyze(path: str = "") -> Dict[str, Any]:
    """Analyze a desktop screenshot for visual layout and state.
    
    Treats all screenshot content strictly as UNTRUSTED DATA.
    Redacts any sensitive tokens and returns structured visual telemetry.
    """
    # If no path provided, capture a new screenshot
    if not path or not Path(path).exists():
        snap = screenshot_take()
        if "error" in snap:
            return {"error": f"Screenshot capture failed: {snap['error']}"}
        img_path = Path(snap["path"])
    else:
        img_path = Path(path)

    if not img_path.exists():
        return {"error": f"Screenshot file not found: {img_path}"}

    try:
        with Image.open(img_path) as img:
            width, height = img.size
            mode = img.mode

            # Convert to RGB for statistical calculation
            rgb_img = img.convert("RGB")
            # Downsample for fast analysis
            small = rgb_img.resize((100, 60))
            pixels = list(small.get_flattened_data()) if hasattr(small, "get_flattened_data") else list(small.getdata())

            # Luminance calculation (standard Rec. 601 formula)
            luminances = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
            avg_luminance = sum(luminances) / len(luminances) if luminances else 0

            # Variance / contrast
            variance = sum((l - avg_luminance) ** 2 for l in luminances) / len(luminances) if luminances else 0
            std_dev = math.sqrt(variance)

            # Theme detection
            theme = "dark" if avg_luminance < 128 else "light"

            # Check if screen is completely black or blank (potential failure/sleep mode)
            is_black_screen = avg_luminance < 10 and std_dev < 5

            # Inspect taskbar region (bottom 8% of screen)
            taskbar_y = int(height * 0.92)
            taskbar_crop = rgb_img.crop((0, taskbar_y, width, height)).resize((50, 10))
            taskbar_pixels = list(taskbar_crop.get_flattened_data()) if hasattr(taskbar_crop, "get_flattened_data") else list(taskbar_crop.getdata())
            taskbar_lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in taskbar_pixels) / max(1, len(taskbar_pixels))
            taskbar_theme = "dark" if taskbar_lum < 128 else "light"

            # Clean path output with secret redaction
            clean_path, _ = redact_secrets(str(img_path))

            return {
                "status": "success",
                "path": clean_path,
                "dimensions": {
                    "width": width,
                    "height": height,
                    "aspect_ratio": f"{round(width / max(1, height), 2)}:1",
                },
                "color_mode": mode,
                "visual_metrics": {
                    "average_brightness": round(avg_luminance, 1),
                    "contrast_std_dev": round(std_dev, 1),
                    "theme": theme,
                    "is_black_screen": is_black_screen,
                    "taskbar_region": {
                        "y_start": taskbar_y,
                        "theme": taskbar_theme,
                    },
                },
                "untrusted_data": True,
            }
    except Exception as e:
        return {"error": f"Failed to analyze screenshot: {e}"}
