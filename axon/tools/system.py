"""System information and telemetry tools."""

import os
import platform
import shutil
import subprocess
from typing import Optional


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
