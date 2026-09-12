"""AXON task engine tests."""

import pytest
from axon.tasks import Task, TaskStatus, Step, StepStatus, TaskManager
from axon.events import EventBus


# --- Task creation ---

def test_task_creation():
    task = Task(goal="Find Python projects")
    assert task.status == TaskStatus.CREATED
    assert task.goal == "Find Python projects"
    assert task.description == "Find Python projects"  # backward compat
    assert task.steps == []
    assert task.result is None
    assert task.error is None


# --- Task transitions ---

def test_task_start():
    task = Task(goal="Test")
    task.transition(TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING


def test_task_complete_with_result():
    task = Task(goal="Test")
    task.transition(TaskStatus.RUNNING)
    task.result = {"found": 3}
    task.transition(TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"found": 3}


def test_task_fail_with_error():
    task = Task(goal="Test")
    task.transition(TaskStatus.RUNNING)
    task.error = "disk not found"
    task.transition(TaskStatus.FAILED)
    assert task.status == TaskStatus.FAILED
    assert task.error == "disk not found"


def test_task_cancel_from_created():
    task = Task(goal="Test")
    task.transition(TaskStatus.CANCELLED)
    assert task.status == TaskStatus.CANCELLED


def test_task_cancel_from_running():
    task = Task(goal="Test")
    task.transition(TaskStatus.RUNNING)
    task.transition(TaskStatus.CANCELLED)
    assert task.status == TaskStatus.CANCELLED


def test_task_invalid_transition():
    task = Task(goal="Test")
    task.transition(TaskStatus.RUNNING)
    task.transition(TaskStatus.COMPLETED)
    with pytest.raises(ValueError):
        task.transition(TaskStatus.RUNNING)


# --- Steps ---

def test_add_step():
    task = Task(goal="Find files")
    step = task.add_step("Search filesystem")
    assert len(task.steps) == 1
    assert step.status == StepStatus.PENDING
    assert step.description == "Search filesystem"


def test_step_transitions():
    step = Step(description="Do something")
    step.transition(StepStatus.RUNNING)
    assert step.status == StepStatus.RUNNING
    step.transition(StepStatus.COMPLETED)
    assert step.status == StepStatus.COMPLETED


def test_step_failure():
    step = Step(description="Do something")
    step.transition(StepStatus.RUNNING)
    step.error = "timeout"
    step.transition(StepStatus.FAILED)
    assert step.status == StepStatus.FAILED
    assert step.error == "timeout"


def test_step_invalid_transition():
    step = Step(description="Do something")
    with pytest.raises(ValueError):
        step.transition(StepStatus.COMPLETED)  # can't skip RUNNING


# --- TaskManager ---

def test_manager_create_and_get():
    bus = EventBus()
    mgr = TaskManager(bus)
    task = mgr.create("Test goal")
    assert mgr.get(task.id).goal == "Test goal"


def test_manager_list():
    bus = EventBus()
    mgr = TaskManager(bus)
    mgr.create("Task A")
    mgr.create("Task B")
    assert len(mgr.list()) == 2


def test_manager_lifecycle():
    bus = EventBus()
    mgr = TaskManager(bus)
    task = mgr.create("Test")
    mgr.start(task.id)
    assert mgr.get(task.id).status == TaskStatus.RUNNING
    mgr.complete(task.id, result="done")
    assert mgr.get(task.id).status == TaskStatus.COMPLETED
    assert mgr.get(task.id).result == "done"


def test_manager_fail():
    bus = EventBus()
    mgr = TaskManager(bus)
    task = mgr.create("Test")
    mgr.start(task.id)
    mgr.fail(task.id, error="something broke")
    assert mgr.get(task.id).status == TaskStatus.FAILED
    assert mgr.get(task.id).error == "something broke"


def test_manager_cancel():
    bus = EventBus()
    mgr = TaskManager(bus)
    task = mgr.create("Test")
    mgr.cancel(task.id)
    assert mgr.get(task.id).status == TaskStatus.CANCELLED


# --- Task events ---

def test_task_events():
    bus = EventBus()
    log = []
    bus.on("TASK_CREATED", lambda e: log.append(e.name))
    bus.on("TASK_STARTED", lambda e: log.append(e.name))
    bus.on("TASK_COMPLETED", lambda e: log.append(e.name))

    mgr = TaskManager(bus)
    task = mgr.create("Test")
    mgr.start(task.id)
    mgr.complete(task.id)

    assert log == ["TASK_CREATED", "TASK_STARTED", "TASK_COMPLETED"]
