"""AXON router — maps capability requests to registered tools with security policy enforcement."""

from typing import Optional, Dict, Any
from axon.security import Permission, PermissionLevel, PolicyDecision
from axon.security.secrets import redact_secrets


class Router:
    def __init__(self, registry, security, event_bus, approval=None, audit_logger=None):
        self.registry = registry
        self.security = security
        self.event_bus = event_bus
        self.approval = approval
        self.audit_logger = audit_logger

    def execute(self, tool_name: str, **kwargs) -> dict:
        """Route a tool request: security policy check → approval if required → execute → redact secrets → audit log."""
        self.event_bus.emit("TOOL_CALLED", {"tool": tool_name, "args": kwargs})

        # 1. Check if tool exists
        if not self.registry.exists(tool_name):
            self.event_bus.emit("TOOL_FAILED", {"tool": tool_name, "error": "not found"})
            if self.audit_logger:
                self.audit_logger.log(
                    tool=tool_name,
                    operation="unknown",
                    permission_level=str(PermissionLevel.BLOCKED.value),
                    args=kwargs,
                    execution_result="FAILED",
                    failure_reason=f"Unknown tool: {tool_name}",
                )
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        # 2. Contextual security policy check
        if hasattr(self.security, "evaluate"):
            decision = self.security.evaluate(tool_name, kwargs)
        else:
            perm = self.security.check(tool_name)
            if perm == Permission.DENIED:
                decision = PolicyDecision(level=PermissionLevel.BLOCKED, reason="Permission denied", tool_name=tool_name)
            elif perm == Permission.APPROVAL_REQUIRED:
                decision = PolicyDecision(level=PermissionLevel.APPROVAL_REQUIRED, reason="Approval required", tool_name=tool_name)
            else:
                decision = PolicyDecision(level=PermissionLevel.SAFE, reason="Allowed", tool_name=tool_name)

        # 3. Handle BLOCKED
        if decision.is_blocked:
            self.event_bus.emit("SECURITY_BLOCKED", {
                "tool": tool_name,
                "reason": decision.reason,
                "args": kwargs,
            })
            self.event_bus.emit("TOOL_FAILED", {"tool": tool_name, "error": "denied"})
            if self.audit_logger:
                self.audit_logger.log(
                    tool=tool_name,
                    operation=tool_name,
                    permission_level=decision.level.value,
                    args=kwargs,
                    execution_result="BLOCKED",
                    failure_reason=decision.reason,
                )
            return {"success": False, "error": f"Permission denied: {decision.reason}"}

        # 4. Handle APPROVAL_REQUIRED
        approval_result = None
        if decision.requires_approval:
            self.event_bus.emit("APPROVAL_REQUESTED", {"tool": tool_name, "args": kwargs, "reason": decision.reason})
            granted = bool(self.approval and self.approval.request(tool_name, kwargs))
            if not granted:
                self.event_bus.emit("APPROVAL_DENIED", {"tool": tool_name, "args": kwargs})
                self.event_bus.emit("TOOL_FAILED", {"tool": tool_name, "error": "approval denied"})
                if self.audit_logger:
                    self.audit_logger.log(
                        tool=tool_name,
                        operation=tool_name,
                        permission_level=decision.level.value,
                        args=kwargs,
                        approval_required=True,
                        approval_result="DENIED",
                        execution_result="BLOCKED",
                        failure_reason="User denied approval",
                    )
                return {"success": False, "error": f"Approval denied: {tool_name}"}
            approval_result = "GRANTED"
            self.event_bus.emit("APPROVAL_GRANTED", {"tool": tool_name, "args": kwargs})

        # 5. Execute tool
        self.event_bus.emit("TOOL_EXECUTION_STARTED", {"tool": tool_name, "args": kwargs})
        try:
            func = self.registry.get(tool_name)
            raw_result = func(**kwargs)

            # Redact secrets from execution result
            clean_result, was_redacted = redact_secrets(raw_result)
            if was_redacted:
                self.event_bus.emit("SECRET_REDACTED", {"tool": tool_name})

            self.event_bus.emit("TOOL_COMPLETED", {"tool": tool_name, "result": clean_result})
            self.event_bus.emit("TOOL_EXECUTION_COMPLETED", {"tool": tool_name, "success": True})

            if self.audit_logger:
                self.audit_logger.log(
                    tool=tool_name,
                    operation=tool_name,
                    permission_level=decision.level.value,
                    args=kwargs,
                    approval_required=decision.requires_approval,
                    approval_result=approval_result,
                    execution_result="COMPLETED",
                )

            return {"success": True, "result": clean_result}

        except Exception as e:
            err_msg = str(e)
            self.event_bus.emit("TOOL_FAILED", {"tool": tool_name, "error": err_msg})
            self.event_bus.emit("TOOL_EXECUTION_FAILED", {"tool": tool_name, "error": err_msg})

            if self.audit_logger:
                self.audit_logger.log(
                    tool=tool_name,
                    operation=tool_name,
                    permission_level=decision.level.value,
                    args=kwargs,
                    approval_required=decision.requires_approval,
                    approval_result=approval_result,
                    execution_result="FAILED",
                    failure_reason=err_msg,
                )

            return {"success": False, "error": err_msg}
