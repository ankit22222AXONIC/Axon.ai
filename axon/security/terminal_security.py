"""Terminal command security inspection and risk classification."""

import re
from typing import Tuple, Dict, Any


# Strictly blocked command patterns (destructive, anti-security, or credential harvesting)
BLOCKED_COMMAND_PATTERNS = [
    # Disk formatting / partitioning
    (r"\bformat\s+[a-zA-Z]:", "Disk formatting commands are blocked"),
    (r"\bdiskpart\b", "Disk partitioning utility (diskpart) is blocked"),

    # Disabling Windows Defender / Firewalls
    (r"set-mppreference\s+.*-disablerealtime", "Disabling Windows Defender real-time monitoring is blocked"),
    (r"netsh\s+advfirewall\s+set\s+.*state\s+off", "Disabling Windows Firewall is blocked"),
    (r"sc\s+stop\s+(?:windefend|mpssvc)", "Stopping critical security services is blocked"),

    # Boot configuration tampering
    (r"\bbcdedit\b", "Boot configuration modification (bcdedit) is blocked"),

    # Windows registry SAM / SECURITY credential dumping
    (r"reg\s+save\s+hklm\\(?:sam|security|system)", "Dumping Windows credential hives from registry is blocked"),
    (r"\bmimikatz\b", "Credential harvesting tools are blocked"),

    # Destructive wipe of system drive or root
    (r"(?:del|rmdir|rd)\s+[/a-zA-Z0-9\s-]*\bc:\\windows\b", "Destructive deletion of Windows system folder is blocked"),
    (r"remove-item\s+.*c:\\windows", "Destructive deletion of Windows system folder is blocked"),

    # Shell commands targeting AXON security files or .env
    (r"(?:del|rm|remove-item)\s+.*(?:\.env|audit\.log)", "Terminal deletion of AXON configuration or audit logs is blocked"),

    # Destructive Git operations (blocked to prevent code loss)
    (r"\bgit\s+reset\s+--hard\b", "Destructive Git hard reset is blocked"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "Destructive Git clean operation is blocked"),
    (r"\bgit\s+push\s+.*(?:--force|-f\b)", "Destructive Git force push is blocked"),
    (r"\bgit\s+checkout\s+--\s+\.", "Destructive Git checkout discarding all changes is blocked"),
    (r"\bgit\s+branch\s+-[a-zA-Z]*[dD]\b", "Destructive Git branch forced deletion (-D) is blocked"),
]

# Patterns that indicate elevated risk (requiring highlighted approval)
HIGH_RISK_PATTERNS = [
    (r"\brmdir\s+/[sS]", "Recursive directory deletion"),
    (r"\bdel\s+/[sS]", "Recursive file deletion"),
    (r"\bremove-item\s+.*-recurse", "Recursive PowerShell deletion"),
    (r"\bshutdown\b", "System reboot or shutdown"),
    (r"\bcurl\b.*\|\s*(?:bash|powershell|cmd)", "Piping remote web script directly into shell execution"),
    (r"\bwget\b.*\|\s*(?:bash|powershell|cmd)", "Piping remote web script directly into shell execution"),
    (r"\biwr\b.*\|\s*iex\b", "PowerShell Invoke-Expression downloading remote payload"),
    (r"\bnet\s+user\b", "User account management"),
    (r"\btaskkill\s+/[fF]", "Forceful process termination"),
]


def inspect_terminal_command(command: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Inspect a shell command before execution.
    
    Returns:
        (is_allowed, reason, metadata)
        - is_allowed: False if strictly BLOCKED.
        - reason: Explanation of the risk classification.
        - metadata: Risk details for the approval prompt or audit log.
    """
    if not command or not command.strip():
        return False, "Empty terminal command", {"risk": "none"}

    cmd_normalized = command.strip().lower()

    # 1. Check blocked patterns
    for pattern, description in BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, cmd_normalized):
            return False, f"Blocked high-risk command: {description}", {
                "blocked": True,
                "pattern": pattern,
                "description": description,
            }

    # 2. Check elevated risk patterns
    high_risk_flags = []
    for pattern, description in HIGH_RISK_PATTERNS:
        if re.search(pattern, cmd_normalized):
            high_risk_flags.append(description)

    metadata = {
        "blocked": False,
        "high_risk": len(high_risk_flags) > 0,
        "risk_flags": high_risk_flags,
    }

    if high_risk_flags:
        reason = f"High-risk command detected: {', '.join(high_risk_flags)}"
    else:
        reason = "Standard terminal command"

    return True, reason, metadata
