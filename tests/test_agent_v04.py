"""AXON v0.4 Test Suite — Planner + Agent Loop.
Verifies Planner, AgentExecutor, Verification, Task State Transitions,
Approval Pausing/Resuming, Loop Limits, and Brain Integration.
"""

import pytest
from pathlib import Path

from axon.core import Axon
from axon.agent import Planner, Plan, PlannedStep, AgentExecutor, Verifier
from axon.tasks.tasks import Task, TaskStatus, Step, StepStatus
from axon.ai.client import OpenRouterClient


def _make_mock_client(responses):
    resp_queue = list(responses)
    def mock_transport(payload):
        if not resp_queue:
            return {"choices": [{"message": {"role": "assistant", "content": "Done."}}]}
        return resp_queue.pop(0)
    return OpenRouterClient(api_key="sk-testkey12345678901234567890", model="test_model", transport_fn=mock_transport)


# ── 1. Planner Tests ──────────────────────────────────────────────────────────

def test_planner_creates_valid_plan_and_does_not_execute_tools():
    planner = Planner()
    plan = planner.plan("Prepare my coding workspace")

    assert isinstance(plan, Plan)
    assert plan.goal == "Prepare my coding workspace"
    assert len(plan.steps) >= 2
    for step in plan.steps:
        assert isinstance(step, PlannedStep)
        assert step.description
        assert step.tool
        assert isinstance(step.tool_args, dict)


def test_planner_rejects_empty_goal():
    planner = Planner()
    with pytest.raises(ValueError):
        planner.plan("")


def test_planner_with_llm_json_response():
    mock_json = """
    {
      "goal": "Check system metrics",
      "steps": [
        {
          "description": "Inspect OS info",
          "tool": "system.info",
          "tool_args": {}
        },
        {
          "description": "Inspect memory and disk resources",
          "tool": "system.resources",
          "tool_args": {"drive": "C:"}
        }
      ]
    }
    """
    client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": mock_json}}]}
    ])
    planner = Planner(client=client)
    plan = planner.plan("Check system metrics")

    assert plan.goal == "Check system metrics"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "system.info"
    assert plan.steps[1].tool == "system.resources"


# ── 2. Agent Executor & Multi-Step Flow ───────────────────────────────────────

def test_agent_executor_runs_steps_in_order_through_router(tmp_path):
    axon = Axon()
    axon.config._data["memory_db_path"] = str(tmp_path / "mem.db")
    axon.start()

    plan = Plan(
        goal="Test multi-step read operations",
        steps=[
            PlannedStep(
                description="Get system information",
                tool="system.info",
                tool_args={},
            ),
            PlannedStep(
                description="List current workspace files",
                tool="filesystem.list",
                tool_args={"path": str(tmp_path)},
            ),
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.COMPLETED
    assert len(task.steps) == 2
    assert task.steps[0].status == StepStatus.COMPLETED
    assert task.steps[1].status == StepStatus.COMPLETED
    assert task.steps[0].result is not None
    assert task.steps[1].result is not None

    axon.shutdown()


def test_agent_executor_stops_on_failure(tmp_path):
    axon = Axon()
    axon.start()

    plan = Plan(
        goal="Test failure halt",
        steps=[
            PlannedStep(
                description="Call a non-existent failing tool",
                tool="nonexistent.tool",
                tool_args={},
            ),
            PlannedStep(
                description="Step that should never run",
                tool="system.info",
                tool_args={},
            ),
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.FAILED
    assert task.steps[0].status == StepStatus.FAILED
    assert task.steps[1].status == StepStatus.PENDING  # Skipped after failure

    axon.shutdown()


# ── 3. Security & Approval Enforcement in Agent Loop ─────────────────────────

def test_security_denial_blocks_step_and_fails_task():
    axon = Axon()
    axon.start()

    # Attempting to write into .env through a planned step
    plan = Plan(
        goal="Malicious step",
        steps=[
            PlannedStep(
                description="Attempt to overwrite .env file",
                tool="filesystem.write",
                tool_args={"path": ".env", "content": "BAD_KEY=123"},
            ),
            PlannedStep(
                description="Next step",
                tool="system.info",
                tool_args={},
            ),
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.FAILED
    assert "blocked" in task.error.lower()
    assert task.steps[0].status == StepStatus.FAILED
    assert task.steps[1].status == StepStatus.PENDING

    axon.shutdown()


def test_approval_required_step_fails_when_denied(tmp_path):
    axon = Axon()
    axon.start()

    dummy = tmp_path / "temp.txt"
    dummy.write_text("content")

    # filesystem.delete requires approval; prompt is None so it's denied
    plan = Plan(
        goal="Delete temp file",
        steps=[
            PlannedStep(
                description="Delete file",
                tool="filesystem.delete",
                tool_args={"path": str(dummy)},
            )
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.FAILED
    assert "approval denied" in task.error.lower()
    assert dummy.exists()  # Ensure destructive action was prevented

    axon.shutdown()


def test_approval_required_step_succeeds_when_approved(tmp_path):
    axon = Axon()
    axon.start()
    axon.approval.set_prompt(lambda name, kwargs: True)

    dummy = tmp_path / "delete_me.txt"
    dummy.write_text("content")

    plan = Plan(
        goal="Delete temp file with approval",
        steps=[
            PlannedStep(
                description="Delete file",
                tool="filesystem.delete",
                tool_args={"path": str(dummy)},
            )
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.COMPLETED
    assert not dummy.exists()

    axon.shutdown()


# ── 4. Verification & Retries ─────────────────────────────────────────────────

def test_step_verification_success(tmp_path):
    axon = Axon()
    axon.start()

    new_dir = tmp_path / "new_project_folder"
    plan = Plan(
        goal="Create and verify folder",
        steps=[
            PlannedStep(
                description="Create project directory",
                tool="filesystem.create_directory",
                tool_args={"path": str(new_dir)},
            )
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.COMPLETED
    assert task.steps[0].status == StepStatus.COMPLETED
    assert new_dir.exists() and new_dir.is_dir()

    axon.shutdown()


def test_step_verification_failure_triggers_bounded_retry(tmp_path):
    axon = Axon()
    axon.start()

    # Create step with an explicit verification tool that will fail
    plan = Plan(
        goal="Action with failing verification",
        steps=[
            PlannedStep(
                description="Get system info",
                tool="system.info",
                tool_args={},
                verification_tool="applications.is_running",
                verification_args={"name": "non_existent_fake_app_xyz_123"},
            )
        ],
    )

    task = axon.executor.execute_plan(plan)

    assert task.status == TaskStatus.FAILED
    assert "verification failed" in task.steps[0].error.lower()
    assert task.steps[0].retry_count >= 2

    axon.shutdown()


# ── 5. Anti-Loop & Max Step Limits ────────────────────────────────────────────

def test_executor_enforces_max_steps_limit():
    axon = Axon()
    axon.start()

    # Plan with 5 steps, but we set max_steps=2
    plan = Plan(
        goal="Long plan",
        steps=[
            PlannedStep(description=f"Step {i}", tool="system.info", tool_args={})
            for i in range(5)
        ],
    )

    task = axon.executor.execute_plan(plan, max_steps=2)

    assert task.status == TaskStatus.FAILED
    assert "exceeded maximum step limit" in task.error.lower()

    axon.shutdown()


# ── 6. Brain execute_goal & UI Output Formatting ──────────────────────────────

def test_brain_execute_goal():
    axon = Axon()
    mock_plan_json = """
    {
      "goal": "Inspect system resources",
      "steps": [
        {
          "description": "Check system info",
          "tool": "system.info",
          "tool_args": {}
        },
        {
          "description": "Check disk space",
          "tool": "system.resources",
          "tool_args": {"drive": "C:"}
        }
      ]
    }
    """
    axon.ai_client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": mock_plan_json}}]}
    ])
    axon.brain.client = axon.ai_client
    axon.brain.planner.client = axon.ai_client
    axon.start()

    summary = axon.brain.execute_goal("Inspect system resources")

    assert "Goal: Inspect system resources" in summary
    assert "[x] Step" in summary
    assert "Task completed successfully" in summary

    # Check that task was tracked in TaskManager
    tasks = axon.tasks.list()
    assert len(tasks) >= 1
    assert any("system resources" in t.goal.lower() for t in tasks)

    axon.shutdown()


def test_brain_process_routes_multi_step_goal_to_planner():
    axon = Axon()
    mock_plan_json = """
    {
      "goal": "Prepare my coding workspace",
      "steps": [
        {
          "description": "Check system info",
          "tool": "system.info",
          "tool_args": {}
        },
        {
          "description": "List directory contents",
          "tool": "filesystem.list",
          "tool_args": {"path": "."}
        }
      ]
    }
    """
    axon.ai_client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": mock_plan_json}}]}
    ])
    axon.brain.client = axon.ai_client
    axon.brain.planner.client = axon.ai_client
    axon.start()

    result = axon.brain.process("Prepare my coding workspace")

    assert "Goal: Prepare my coding workspace" in result
    assert "Task completed successfully" in result

    axon.shutdown()

