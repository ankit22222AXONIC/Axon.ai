"""AXON Agent Loop / Executor — executes multi-step plans sequentially through the Router."""

import json
from typing import Optional, Dict, Any, List

from axon.agent.planner import Plan
from axon.agent.verifier import Verifier
from axon.events import EventBus
from axon.router import Router
from axon.tasks.tasks import Task, TaskStatus, Step, StepStatus
from axon.tasks.manager import TaskManager


MAX_TOTAL_STEPS = 20
MAX_STEP_RETRIES = 2


class AgentExecutor:
    """Autonomous agent loop that executes planned steps strictly through the Router."""

    def __init__(
        self,
        router: Router,
        task_manager: TaskManager,
        event_bus: Optional[EventBus] = None,
        verifier: Optional[Verifier] = None,
    ):
        self.router = router
        self.tasks = task_manager
        self.event_bus = event_bus
        self.verifier = verifier or Verifier(router)

    def execute_plan(
        self,
        plan: Plan,
        task: Optional[Task] = None,
        max_steps: int = MAX_TOTAL_STEPS,
    ) -> Task:
        """Execute a Plan step-by-step through the Router, returning the resulting Task."""
        # 1. Create or bind task
        if task is None:
            task = self.tasks.create(goal=plan.goal)
            for p_step in plan.steps:
                task.add_step(
                    description=p_step.description,
                    tool=p_step.tool,
                    tool_args=p_step.tool_args,
                    verification_tool=p_step.verification_tool,
                    verification_args=p_step.verification_args,
                )

        # Transition task to RUNNING
        if task.status in (TaskStatus.CREATED, TaskStatus.PENDING, TaskStatus.PLANNING):
            self.tasks.start(task.id)

        executed_count = 0
        duplicate_tracker: Dict[str, int] = {}

        for step in task.steps:
            # If step was already completed in a previous resume, skip
            if step.status == StepStatus.COMPLETED:
                continue

            executed_count += 1
            if executed_count > max_steps:
                error_msg = f"Task execution exceeded maximum step limit of {max_steps}"
                self._fail_step(step, error_msg)
                self.tasks.fail(task.id, error=error_msg)
                return task

            # Loop detection: detect repeated identical failing attempts
            step_sig = f"{step.tool}:{json.dumps(step.tool_args, sort_keys=True, default=str)}"
            duplicate_tracker[step_sig] = duplicate_tracker.get(step_sig, 0) + 1
            if duplicate_tracker[step_sig] > MAX_STEP_RETRIES + 2:
                error_msg = f"Infinite loop detected: step '{step.description}' attempted too many times"
                self._fail_step(step, error_msg)
                self.tasks.fail(task.id, error=error_msg)
                return task

            # Execute step with bounded retries
            success = self._execute_step_with_retries(task, step)
            if not success:
                # If step entered WAITING_APPROVAL, task is paused
                if step.status == StepStatus.WAITING_APPROVAL:
                    self.tasks.wait_approval(task.id)
                    return task
                # Otherwise, task has failed
                self.tasks.fail(task.id, error=step.error or "Step execution failed")
                return task

        # All steps completed successfully
        self.tasks.complete(
            task.id,
            result={"steps_completed": len(task.steps), "goal": task.goal},
        )
        return task

    def resume_task(self, task_id: str) -> Task:
        """Resume a paused task (e.g. after approval was granted)."""
        task = self.tasks.get(task_id)
        if task.status != TaskStatus.WAITING_APPROVAL:
            return task

        self.tasks.resume(task.id)
        return self.execute_plan(Plan(goal=task.goal), task=task)

    def _execute_step_with_retries(self, task: Task, step: Step) -> bool:
        """Execute a single step, handling retries and verification."""
        while step.retry_count <= step.max_retries:
            step.retry_count += 1

            if step.status != StepStatus.RUNNING:
                step.transition(StepStatus.RUNNING)

            if self.event_bus:
                self.event_bus.emit("STEP_STARTED", {
                    "task_id": task.id,
                    "step_id": step.id,
                    "description": step.description,
                    "tool": step.tool,
                })

            # Authoritative execution via Router
            result = self.router.execute(step.tool, **step.tool_args)

            # Check if approval was denied or required
            if not result.get("success", False):
                err = result.get("error", "")
                if "approval denied" in err.lower():
                    step.error = err
                    self._fail_step(step, err)
                    if self.event_bus:
                        self.event_bus.emit("STEP_FAILED", {
                            "task_id": task.id,
                            "step_id": step.id,
                            "error": err,
                        })
                    return False

                # Other tool execution failure
                step.error = err
                # If a desktop tool failed, trigger a safety reset before retrying
                if any(step.tool.startswith(prefix) for prefix in ("desktop.", "mouse.", "keyboard.")):
                    try:
                        from axon.tools.desktop import safety_reset
                        safety_reset()
                    except Exception:
                        pass

                if step.retry_count <= step.max_retries:
                    continue  # Retry step
                else:
                    self._fail_step(step, err)
                    if self.event_bus:
                        self.event_bus.emit("STEP_FAILED", {
                            "task_id": task.id,
                            "step_id": step.id,
                            "error": err,
                        })
                    return False

            # Tool returned success — run verification
            is_verified, v_details = self.verifier.verify(step, result)
            if not is_verified:
                step.error = f"Verification failed: {v_details}"
                if any(step.tool.startswith(prefix) for prefix in ("desktop.", "mouse.", "keyboard.")):
                    try:
                        from axon.tools.desktop import safety_reset
                        safety_reset()
                    except Exception:
                        pass

                if step.retry_count <= step.max_retries:
                    continue  # Retry step
                else:
                    self._fail_step(step, step.error)
                    if self.event_bus:
                        self.event_bus.emit("STEP_FAILED", {
                            "task_id": task.id,
                            "step_id": step.id,
                            "error": step.error,
                        })
                    return False

            # Step verified and completed
            step.result = result.get("result")
            step.transition(StepStatus.COMPLETED)
            if self.event_bus:
                self.event_bus.emit("STEP_COMPLETED", {
                    "task_id": task.id,
                    "step_id": step.id,
                    "result": step.result,
                })
            return True

        self._fail_step(step, step.error or "Max retries exceeded")
        return False

    def _fail_step(self, step: Step, error: str):
        step.error = error
        # Ensure any held mouse buttons or modifier keys are released on step failure
        try:
            from axon.tools.desktop import safety_reset
            safety_reset()
        except Exception:
            pass
        if step.status != StepStatus.FAILED:
            step.transition(StepStatus.FAILED)
