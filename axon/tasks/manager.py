"""AXON task manager — creates, tracks, and transitions tasks."""

from typing import Optional, List
from axon.tasks.tasks import Task, TaskStatus


class TaskManager:
    def __init__(self, event_bus):
        self._tasks = {}  # id -> Task
        self.event_bus = event_bus

    def create(self, goal: str) -> Task:
        task = Task(goal=goal)
        self._tasks[task.id] = task
        self.event_bus.emit("TASK_CREATED", {"task_id": task.id, "goal": goal})
        return task

    def get(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")
        return task

    def list(self) -> List[Task]:
        return list(self._tasks.values())

    def plan(self, task_id: str):
        task = self.get(task_id)
        task.transition(TaskStatus.PLANNING)
        self.event_bus.emit("TASK_PLANNING", {"task_id": task_id})

    def start(self, task_id: str):
        task = self.get(task_id)
        task.transition(TaskStatus.RUNNING)
        self.event_bus.emit("TASK_STARTED", {"task_id": task_id})

    def wait_approval(self, task_id: str):
        task = self.get(task_id)
        task.transition(TaskStatus.WAITING_APPROVAL)
        self.event_bus.emit("TASK_WAITING_APPROVAL", {"task_id": task_id})

    def resume(self, task_id: str):
        task = self.get(task_id)
        task.transition(TaskStatus.RUNNING)
        self.event_bus.emit("TASK_RESUMED", {"task_id": task_id})

    def complete(self, task_id: str, result=None):
        task = self.get(task_id)
        task.result = result
        task.transition(TaskStatus.COMPLETED)
        self.event_bus.emit("TASK_COMPLETED", {"task_id": task_id, "result": result})

    def fail(self, task_id: str, error: str = ""):
        task = self.get(task_id)
        task.error = error
        task.transition(TaskStatus.FAILED)
        self.event_bus.emit("TASK_FAILED", {"task_id": task_id, "error": error})

    def cancel(self, task_id: str):
        task = self.get(task_id)
        task.transition(TaskStatus.CANCELLED)
        self.event_bus.emit("TASK_CANCELLED", {"task_id": task_id})
