"""AXON security — permission checks and policy evaluation for tools."""

from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any

from axon.security.policy import PermissionLevel, PolicyDecision, SecurityPolicyEngine


class Permission(Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"

    @classmethod
    def from_level(cls, level: PermissionLevel) -> "Permission":
        if level in (PermissionLevel.SAFE, PermissionLevel.CAUTION):
            return cls.ALLOWED
        if level == PermissionLevel.APPROVAL_REQUIRED:
            return cls.APPROVAL_REQUIRED
        return cls.DENIED


class SecurityManager:
    def __init__(self, workspace_root: Optional[Path] = None):
        self._permissions: Dict[str, Permission] = {}  # tool_name -> Permission
        self.policy_engine = SecurityPolicyEngine(workspace_root=workspace_root)

    def set_permission(self, tool_name: str, permission: Permission):
        """Set an explicit programmatic permission for a tool name."""
        self._permissions[tool_name] = permission
        level_map = {
            Permission.ALLOWED: PermissionLevel.SAFE,
            Permission.APPROVAL_REQUIRED: PermissionLevel.APPROVAL_REQUIRED,
            Permission.DENIED: PermissionLevel.BLOCKED,
        }
        self.policy_engine.set_override(tool_name, level_map.get(permission, PermissionLevel.CAUTION))

    def check(self, tool_name: str) -> Permission:
        """Check static permission for tool name (backwards compatible)."""
        if tool_name in self._permissions:
            return self._permissions[tool_name]
        decision = self.policy_engine.evaluate(tool_name, {})
        return Permission.from_level(decision.level)

    def get_permission(self, tool_name: str) -> Permission:
        """Get the effective Permission enum for a tool name."""
        return self.check(tool_name)

    def evaluate(self, tool_name: str, kwargs: Optional[Dict[str, Any]] = None) -> PolicyDecision:
        """Contextually evaluate whether an action is SAFE, CAUTION, APPROVAL_REQUIRED, or BLOCKED."""
        return self.policy_engine.evaluate(tool_name, kwargs or {})
