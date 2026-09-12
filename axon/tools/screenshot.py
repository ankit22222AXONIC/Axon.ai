"""Screenshot tool — captures high-resolution screenshots of the Windows desktop."""

import os
from datetime import datetime
from pathlib import Path


def _capture_screen_gdi():
    """Capture Windows desktop screen using native Win32 GDI calls."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Set DPI awareness for full resolution on scaled displays
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)

    hdesktop = user32.GetDesktopWindow()
    desktop_dc = user32.GetWindowDC(hdesktop)
    mem_dc = gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    old_bmp = gdi32.SelectObject(mem_dc, bitmap)

    # SRCCOPY = 0x00CC0020
    gdi32.BitBlt(mem_dc, 0, 0, width, height, desktop_dc, 0, 0, 0x00CC0020)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down bitmap
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(desktop_dc, bitmap, 0, height, buf, ctypes.byref(bmi), 0)

    # Cleanup GDI handles
    gdi32.SelectObject(mem_dc, old_bmp)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hdesktop, desktop_dc)

    img = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)
    return img.convert("RGB")


def screenshot_take(save_dir: str = "") -> dict:
    """Capture a screenshot of the primary Windows monitor and save to disk.
    
    Args:
        save_dir: Optional custom directory to save the image. Defaults to ~/.axon/screenshots/
    """
    try:
        # Determine target directory
        if save_dir:
            out_dir = Path(os.path.expandvars(os.path.expanduser(save_dir)))
        else:
            out_dir = Path.home() / ".axon" / "screenshots"
        
        out_dir.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"axon_screenshot_{timestamp_str}.png"
        filepath = out_dir / filename

        # Primary method: GDI capture
        try:
            img = _capture_screen_gdi()
        except Exception:
            # Fallback method: PIL ImageGrab
            from PIL import ImageGrab
            img = ImageGrab.grab()

        img.save(filepath, format="PNG")
        file_size = filepath.stat().st_size

        return {
            "status": "success",
            "path": str(filepath),
            "filename": filename,
            "width": img.width,
            "height": img.height,
            "size_bytes": file_size,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": f"Failed to capture screenshot: {e}"}
