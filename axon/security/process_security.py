"""Process security — guards essential Windows system processes and AXON itself from termination."""

import os
from typing import Tuple, Set

# Critical Windows core system processes that must never be terminated
CRITICAL_SYSTEM_PROCESSES: Set[str] = {
    "system",
    "system.exe",
    "idle",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "winlogon.exe",
    "dwm.exe",
    "fontdrvhost.exe",
    "explorer.exe",
}


def is_protected_process(target: str) -> Tuple[bool, str]:
    """Check if the target process name or PID is a protected system process or AXON itself."""
    if not target or not str(target).strip():
        return False, "No process specified"

    clean_target = str(target).strip().lower()

    # Check if target is numeric PID
    if clean_target.isdigit():
        target_pid = int(clean_target)
        current_pid = os.getpid()
        if target_pid == current_pid:
            return True, f"Terminating the running AXON process (PID {current_pid}) is blocked"
        if target_pid in (0, 4):  # System Idle and System PIDs
            return True, f"Terminating core Windows system PID {target_pid} is blocked"
        return False, "Process PID is not a protected system process"

    # Check executable name
    exe_name = clean_target if clean_target.endswith(".exe") else f"{clean_target}.exe"
    if exe_name in CRITICAL_SYSTEM_PROCESSES or clean_target in CRITICAL_SYSTEM_PROCESSES:
        return True, f"Terminating critical Windows system process '{clean_target}' is blocked"

    return False, "Process is allowed for termination review"
