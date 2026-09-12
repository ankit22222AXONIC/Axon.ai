"""AXON Security Audit Logger — append-only, thread-safe structured security logging."""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from axon.security.secrets import redact_secrets


class AuditLogger:
    def __init__(self, log_path: Optional[str] = None):
        self._lock = threading.Lock()
        if log_path is None:
            data_dir = Path.home() / ".axon"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = str(data_dir / "audit.log")
        elif log_path == ":memory:":
            self.log_path = ":memory:"
        else:
            self.log_path = log_path
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)

        self._in_memory_records: List[Dict[str, Any]] = []

    def log(
        self,
        tool: str,
        operation: str,
        permission_level: str,
        args: Optional[Dict[str, Any]] = None,
        approval_required: bool = False,
        approval_result: Optional[str] = None,  # "GRANTED", "DENIED", "SKIPPED", None
        execution_result: str = "COMPLETED",   # "COMPLETED", "BLOCKED", "FAILED"
        failure_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record an audited security event."""
        clean_args, _ = redact_secrets(args or {})
        clean_reason, _ = redact_secrets(failure_reason or "") if failure_reason else (None, False)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool,
            "operation": operation,
            "permission_level": str(permission_level),
            "args": clean_args,
            "approval_required": approval_required,
            "approval_result": approval_result,
            "execution_result": execution_result,
            "failure_reason": clean_reason,
        }

        with self._lock:
            self._in_memory_records.append(entry)
            if self.log_path != ":memory:":
                try:
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, default=str) + "\n")
                except Exception:
                    pass

        return entry

    def get_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent audit log entries."""
        with self._lock:
            if self.log_path == ":memory:":
                return list(self._in_memory_records[-limit:])

            records = []
            try:
                p = Path(self.log_path)
                if p.exists():
                    lines = p.read_text(encoding="utf-8", errors="replace").strip().split("\n")
                    for line in lines[-limit:]:
                        if line.strip():
                            records.append(json.loads(line))
            except Exception:
                records = list(self._in_memory_records[-limit:])
            return records

    def clear(self):
        """Clear log (primarily for testing)."""
        with self._lock:
            self._in_memory_records.clear()
            if self.log_path != ":memory:":
                p = Path(self.log_path)
                if p.exists():
                    p.write_text("", encoding="utf-8")
