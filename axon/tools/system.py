"""System information and telemetry tools."""

import os
import platform
import shutil
import subprocess
from typing import Optional, Dict, Any


def system_info() -> dict:
    """Get basic system information."""
    try:
        username = os.getlogin()
    except Exception:
        username = os.environ.get("USERNAME", "unknown")

    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "hostname": platform.node(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "username": username,
    }


def system_resources(drive: str = "C:") -> dict:
    """Get dynamic hardware telemetry: RAM, Disk, CPU, Battery, and Uptime.
    
    Args:
        drive: Target drive letter for disk space check (default 'C:').
    """
    metrics = {}

    # 1. CPU cores
    metrics["cpu_count"] = os.cpu_count()

    # 2. Disk storage
    try:
        drive_path = drive if drive.endswith("\\") else f"{drive}:\\" if len(drive) == 1 else drive
        disk = shutil.disk_usage(drive_path)
        metrics["disk"] = {
            "drive": drive_path,
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent_used": round((disk.used / disk.total) * 100, 1),
        }
    except Exception as e:
        metrics["disk"] = {"error": str(e)}

    # 3. RAM usage (ctypes kernel32)
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            total_gb = mem.ullTotalPhys / (1024**3)
            avail_gb = mem.ullAvailPhys / (1024**3)
            metrics["ram"] = {
                "total_gb": round(total_gb, 2),
                "used_gb": round(total_gb - avail_gb, 2),
                "free_gb": round(avail_gb, 2),
                "percent_used": mem.dwMemoryLoad,
            }
    except Exception as e:
        metrics["ram"] = {"error": str(e)}

    # 4. Battery & Power Status
    try:
        import ctypes
        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]
        power = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)):
            percent = power.BatteryLifePercent
            ac_status = power.ACLineStatus
            metrics["power"] = {
                "battery_percent": percent if 0 <= percent <= 100 else "Desktop/No Battery",
                "charging": ac_status == 1,
                "power_source": "AC (Plugged In)" if ac_status == 1 else "Battery" if ac_status == 0 else "Unknown",
            }
    except Exception as e:
        metrics["power"] = {"error": str(e)}

    # 5. System Uptime
    try:
        import ctypes
        ticks_ms = ctypes.windll.kernel32.GetTickCount64()
        total_seconds = ticks_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        metrics["uptime"] = {
            "hours": hours,
            "minutes": minutes,
            "formatted": f"{hours}h {minutes}m",
        }
    except Exception as e:
        metrics["uptime"] = {"error": str(e)}

    return metrics


def processes_list() -> list[str]:
    """List running processes (Windows tasklist)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        lines = []
        for line in result.stdout.strip().split("\n")[:50]:  # cap at 50
            parts = line.strip().strip('"').split('","')
            if parts:
                lines.append(parts[0])
        return lines
    except Exception as e:
        return [f"Error: {e}"]


def processes_find(query: str) -> list[dict]:
    """Search running processes by name or PID."""
    if not query:
        return []
    q = query.lower().strip()
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10
        )
        matches = []
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 5:
                name = parts[0]
                pid = parts[1]
                session = parts[2]
                mem = parts[4]
                if q in name.lower() or q == pid:
                    matches.append({
                        "name": name,
                        "pid": pid,
                        "session": session,
                        "memory": mem,
                    })
        return matches
    except Exception as e:
        return [{"error": str(e)}]


# Module-level state tracking for pending system power actions
_PENDING_SYSTEM_ACTION: Optional[Dict[str, Any]] = None


def _is_pending_action_active() -> bool:
    global _PENDING_SYSTEM_ACTION
    if not _PENDING_SYSTEM_ACTION:
        return False
    import time
    scheduled_at = _PENDING_SYSTEM_ACTION.get("scheduled_at", 0)
    delay = _PENDING_SYSTEM_ACTION.get("delay_seconds", 60)
    if time.time() - scheduled_at < (delay + 10):
        return True
    _PENDING_SYSTEM_ACTION = None
    return False


def system_shutdown(delay_seconds: int = 60, message: Optional[str] = None) -> Dict[str, Any]:
    """Shut down the computer after explicit human approval.
    
    Args:
        delay_seconds: Time to wait before powering off (0 to 3600 seconds, default 60).
        message: Optional notification message displayed on Windows before shutdown.
    """
    global _PENDING_SYSTEM_ACTION

    # 1. Validate arguments
    try:
        delay = int(delay_seconds)
        if delay < 0 or delay > 3600:
            return {"error": "Invalid delay_seconds: must be an integer between 0 and 3600 seconds."}
    except (ValueError, TypeError):
        return {"error": "delay_seconds must be a valid numeric integer."}

    # 2. Prevent duplicate shutdown/restart requests
    if _is_pending_action_active():
        current_action = _PENDING_SYSTEM_ACTION.get("action", "power")
        return {
            "error": f"A system {current_action} action is already pending. Duplicate requests are blocked to prevent system instability.",
            "pending_action": _PENDING_SYSTEM_ACTION,
        }

    # 3. Sanitize message & redact secrets
    clean_msg = "AXONIC: System shutdown requested."
    if message and str(message).strip():
        raw_msg = str(message).strip()[:180].replace('"', "'")
        from axon.security.secrets import redact_text
        sanitized, _ = redact_text(raw_msg)
        clean_msg = f"AXONIC: {sanitized}"

    # 4. Execute Windows shutdown command
    try:
        cmd = ["shutdown.exe", "/s", "/t", str(delay), "/c", clean_msg]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            import time
            _PENDING_SYSTEM_ACTION = {
                "action": "shutdown",
                "delay_seconds": delay,
                "scheduled_at": time.time(),
                "message": clean_msg,
            }
            return {
                "status": "success",
                "action": "shutdown",
                "delay_seconds": delay,
                "message": f"Computer shutdown scheduled in {delay} seconds. Unsaved work should be saved now.",
            }
        else:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            return {
                "error": stderr or stdout or "Failed to initiate Windows shutdown.",
                "returncode": result.returncode,
            }
    except Exception as e:
        return {"error": f"System shutdown execution error: {e}"}


def system_restart(delay_seconds: int = 60, message: Optional[str] = None) -> Dict[str, Any]:
    """Restart / reboot the computer after explicit human approval.
    
    Args:
        delay_seconds: Time to wait before rebooting (0 to 3600 seconds, default 60).
        message: Optional notification message displayed on Windows before reboot.
    """
    global _PENDING_SYSTEM_ACTION

    # 1. Validate arguments
    try:
        delay = int(delay_seconds)
        if delay < 0 or delay > 3600:
            return {"error": "Invalid delay_seconds: must be an integer between 0 and 3600 seconds."}
    except (ValueError, TypeError):
        return {"error": "delay_seconds must be a valid numeric integer."}

    # 2. Prevent duplicate shutdown/restart requests
    if _is_pending_action_active():
        current_action = _PENDING_SYSTEM_ACTION.get("action", "power")
        return {
            "error": f"A system {current_action} action is already pending. Duplicate requests are blocked to prevent system instability.",
            "pending_action": _PENDING_SYSTEM_ACTION,
        }

    # 3. Sanitize message & redact secrets
    clean_msg = "AXONIC: System restart requested."
    if message and str(message).strip():
        raw_msg = str(message).strip()[:180].replace('"', "'")
        from axon.security.secrets import redact_text
        sanitized, _ = redact_text(raw_msg)
        clean_msg = f"AXONIC: {sanitized}"

    # 4. Execute Windows restart command
    try:
        cmd = ["shutdown.exe", "/r", "/t", str(delay), "/c", clean_msg]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            import time
            _PENDING_SYSTEM_ACTION = {
                "action": "restart",
                "delay_seconds": delay,
                "scheduled_at": time.time(),
                "message": clean_msg,
            }
            return {
                "status": "success",
                "action": "restart",
                "delay_seconds": delay,
                "message": f"Computer restart scheduled in {delay} seconds. Unsaved work should be saved now.",
            }
        else:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            return {
                "error": stderr or stdout or "Failed to initiate Windows restart.",
                "returncode": result.returncode,
            }
    except Exception as e:
        return {"error": f"System restart execution error: {e}"}


def system_cancel_shutdown() -> Dict[str, Any]:
    """Abort or cancel any currently pending Windows shutdown or restart."""
    global _PENDING_SYSTEM_ACTION
    try:
        result = subprocess.run(["shutdown.exe", "/a"], capture_output=True, text=True, timeout=10)
        _PENDING_SYSTEM_ACTION = None
        if result.returncode == 0:
            return {
                "status": "success",
                "action": "cancelled",
                "message": "Scheduled shutdown or restart has been cancelled.",
            }
        else:
            stderr = result.stderr.strip()
            return {
                "status": "info",
                "message": stderr or "No scheduled shutdown was found to cancel.",
            }
    except Exception as e:
        return {"error": f"Failed to cancel shutdown: {e}"}

