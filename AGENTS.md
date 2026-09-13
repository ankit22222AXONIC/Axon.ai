# AXONIC Operational & Safety Rules

## System Power & Reset Policies
1. **No Factory Reset**: AXONIC can **NEVER** perform a Windows Factory Reset (such as `systemreset`, formatting disks, or wiping recovery partitions). Factory reset is completely unsupported and strictly blocked.
2. **Windows Reset / Restart Only**: When a user asks to "reset my computer", "reboot", or "restart", AXONIC interprets this strictly as a safe system restart (`system.restart`).
3. **Explicit Human Approval**: System shutdown (`system.shutdown`) and restart (`system.restart`) **ALWAYS** require explicit human approval via the AXONIC approval UI before execution. The AI cannot self-approve.
4. **No Force-Kill by Default**: `applications.close` must never force-kill applications by default; it sends graceful `WM_CLOSE` window messages so applications (Notepad, VS Code, etc.) can prompt to save unsaved work.
