"""AXON task representation with extended lifecycle states for multi-step agent execution."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from uuid import uuid4


class TaskStatus(Enum):
    CREATED = "created"
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid transitions: from_status -> set of allowed to_statuses
_TRANSITIONS = {
    TaskStatus.CREATED: {TaskStatus.PLANNING, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.PENDING: {TaskStatus.PLANNING, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.WAITING_APPROVAL, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.WAITING_APPROVAL: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
}


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


_STEP_TRANSITIONS = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.FAILED},
    StepStatus.RUNNING: {StepStatus.WAITING_APPROVAL, StepStatus.COMPLETED, StepStatus.FAILED},
    StepStatus.WAITING_APPROVAL: {StepStatus.RUNNING, StepStatus.FAILED},
}


@dataclass
class Step:
    description: str
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    status: StepStatus = StepStatus.PENDING
    tool: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    result: object = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    verification_tool: str = ""
    verification_args: Dict[str, Any] = field(default_factory=dict)

    def transition(self, new_status: StepStatus):
        allowed = _STEP_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Step cannot transition from {self.status.value} to {new_status.value}"
            )
        self.status = new_status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "tool": self.tool,
            "tool_args": self.tool_args,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


@dataclass
class Task:
    goal: str
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    status: TaskStatus = TaskStatus.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    steps: List[Step] = field(default_factory=list)
    result: object = None
    error: Optional[str] = None

    # Keep backward compat: 'description' maps to 'goal'
    @property
    def description(self) -> str:
        return self.goal

    def transition(self, new_status: TaskStatus):
        allowed = _TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition from {self.status.value} to {new_status.value}"
            )
        self.status = new_status

    def add_step(
        self,
        description: str,
        tool: str = "",
        tool_args: Optional[Dict[str, Any]] = None,
        verification_tool: str = "",
        verification_args: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> Step:
        step = Step(
            description=description,
            tool=tool,
            tool_args=tool_args or {},
            verification_tool=verification_tool,
            verification_args=verification_args or {},
            max_retries=max_retries,
        )
        self.steps.append(step)
        return step

    def get_step(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(f"Unknown step: {step_id}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "steps": [s.to_dict() for s in self.steps],
            "result": self.result,
            "error": self.error,
        }
