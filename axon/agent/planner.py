"""AXON Planner — decomposes high-level user goals into structured executable plans."""

import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from axon.ai.client import OpenRouterClient, AIClientError
from axon.tools import ToolRegistry


@dataclass
class PlannedStep:
    description: str
    tool: str
    tool_args: Dict[str, Any] = field(default_factory=dict)
    verification_tool: str = ""
    verification_args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "tool": self.tool,
            "tool_args": self.tool_args,
            "verification_tool": self.verification_tool,
            "verification_args": self.verification_args,
        }


@dataclass
class Plan:
    goal: str
    steps: List[PlannedStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
        }


PLANNER_SYSTEM_PROMPT = (
    "You are the AXON Task Planner. Your sole job is to break down a high-level user goal "
    "into a minimal, structured list of discrete execution steps using AXON tools.\n"
    "Available tools include:\n"
    "- applications.open(name_or_path: str)\n"
    "- applications.is_running(name: str)\n"
    "- applications.close(name_or_pid: str)\n"
    "- applications.list()\n"
    "- filesystem.list(path: str)\n"
    "- filesystem.list_detailed(path: str)\n"
    "- filesystem.read(path: str)\n"
    "- filesystem.write(path: str, content: str)\n"
    "- filesystem.create_directory(path: str)\n"
    "- filesystem.delete(path: str)\n"
    "- filesystem.copy(source: str, destination: str)\n"
    "- filesystem.move(source: str, destination: str)\n"
    "- filesystem.view_lines(path: str, start_line: int, end_line: int)\n"
    "- filesystem.find_in_files(query: str, path: str)\n"
    "- filesystem.replace_content(path: str, target: str, replacement: str)\n"
    "- filesystem.set_workspace(path: str)\n"
    "- filesystem.get_workspace()\n"
    "- browser.open(url: str)\n"
    "- browser.search(query: str)\n"
    "- browser.close_tab(tab_title: str)\n"
    "- browser.close_window(browser_name: str)\n"
    "- system.info()\n"
    "- system.resources(drive: str)\n"
    "- system.shutdown(delay_seconds: int, message: str)\n"
    "- system.restart(delay_seconds: int, message: str)\n"
    "- terminal.run(command: str)\n"
    "- memory.store(content: str, category: str)\n"
    "- screenshot.take()\n"
    "- screenshot.analyze(path: str)\n"
    "- desktop.inspect_screen()\n"
    "- desktop.get_windows()\n"
    "- desktop.switch_window(title_or_pid: str)\n"
    "- desktop.close_window(title_or_pid: str)\n"
    "- mouse.move(x: int, y: int)\n"
    "- mouse.click(x: int, y: int, button: str)\n"
    "- mouse.double_click(x: int, y: int)\n"
    "- mouse.scroll(delta: int)\n"
    "- keyboard.type(text: str)\n"
    "- keyboard.press(key: str)\n"
    "- keyboard.hotkey(keys: str)\n"
    "- safety_reset()\n\n"
    "OUTPUT FORMAT RULES:\n"
    "Respond ONLY with a JSON object with this exact structure:\n"
    "{\n"
    '  "goal": "<user goal>",\n'
    '  "steps": [\n'
    '    {\n'
    '      "description": "<what this step does>",\n'
    '      "tool": "<tool_name>",\n'
    '      "tool_args": { ... },\n'
    '      "verification_tool": "<optional verification tool name>",\n'
    '      "verification_args": { ... }\n'
    '    }\n'
    '  ]\n'
    "}\n"
    "Do NOT include markdown formatting, backticks, or extra commentary outside the JSON."
)


class Planner:
    """Plans multi-step tasks without executing any tools."""

    def __init__(
        self,
        client: Optional[OpenRouterClient] = None,
        registry: Optional[ToolRegistry] = None,
    ):
        self.client = client
        self.registry = registry

    def plan(self, goal: str, context: Optional[str] = None) -> Plan:
        """Convert a user goal into a structured Plan."""
        if not goal or not str(goal).strip():
            raise ValueError("Goal cannot be empty")

        clean_goal = str(goal).strip()

        # Try LLM-based planning if client is configured
        if self.client and getattr(self.client, "_api_key", None):
            try:
                plan = self._plan_with_llm(clean_goal, context)
                if plan and len(plan.steps) > 0:
                    return plan
            except Exception:
                pass

        # Deterministic / heuristic fallback planner
        return self._plan_heuristic(clean_goal)

    def _plan_with_llm(self, goal: str, context: Optional[str] = None) -> Optional[Plan]:
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Create a step-by-step execution plan for the following goal: '{goal}'"
                + (f"\nContext: {context}" if context else ""),
            },
        ]
        response = self.client.chat(messages)
        choices = response.get("choices", [])
        if not choices:
            return None

        content = choices[0].get("message", {}).get("content", "")
        return self._parse_plan_json(content, goal)

    def _parse_plan_json(self, raw_json: str, original_goal: str) -> Optional[Plan]:
        if not raw_json:
            return None

        # Clean JSON markdown fences if present
        text = raw_json.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            data = json.loads(text)
        except Exception:
            # Try finding first JSON object {...}
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except Exception:
                    return None
            else:
                return None

        goal = data.get("goal") or original_goal
        steps_data = data.get("steps", [])
        if not isinstance(steps_data, list):
            return None

        planned_steps = []
        for s in steps_data:
            if not isinstance(s, dict):
                continue
            desc = s.get("description", "Execute step")
            tool = s.get("tool", "")
            tool_args = s.get("tool_args") or {}
            v_tool = s.get("verification_tool", "")
            v_args = s.get("verification_args") or {}

            # Canonicalize tool name
            clean_tool = tool.replace("__", ".")
            clean_v_tool = v_tool.replace("__", ".") if v_tool else ""

            planned_steps.append(
                PlannedStep(
                    description=desc,
                    tool=clean_tool,
                    tool_args=tool_args,
                    verification_tool=clean_v_tool,
                    verification_args=v_args,
                )
            )

        return Plan(goal=goal, steps=planned_steps)

    def _plan_heuristic(self, goal: str) -> Plan:
        """Heuristic planner for common multi-step tasks."""
        lower = goal.lower()
        steps = []

        # 1. "Open <App> and verify it is running"
        if "calculator" in lower:
            steps.append(
                PlannedStep(
                    description="Launch Calculator application",
                    tool="applications.open",
                    tool_args={"name_or_path": "Calculator"},
                    verification_tool="applications.is_running",
                    verification_args={"name": "Calculator"},
                )
            )
            steps.append(
                PlannedStep(
                    description="Verify Calculator is running",
                    tool="applications.is_running",
                    tool_args={"name": "Calculator"},
                )
            )
            return Plan(goal=goal, steps=steps)

        # 2. "Take a screenshot and analyze desktop"
        if "screenshot" in lower or "analyze screen" in lower or "screen analysis" in lower:
            steps.append(
                PlannedStep(
                    description="Capture desktop screenshot",
                    tool="screenshot.take",
                    tool_args={},
                    verification_tool="screenshot.analyze",
                    verification_args={},
                )
            )
            steps.append(
                PlannedStep(
                    description="Analyze desktop screenshot visual state and layout",
                    tool="screenshot.analyze",
                    tool_args={},
                )
            )
            return Plan(goal=goal, steps=steps)

        # 3. Desktop application automation workflow (e.g. Notepad typing)
        if "notepad" in lower or "write note" in lower:
            steps.append(
                PlannedStep(
                    description="Launch Notepad application",
                    tool="applications.open",
                    tool_args={"name_or_path": "notepad"},
                    verification_tool="applications.is_running",
                    verification_args={"name": "notepad"},
                )
            )
            steps.append(
                PlannedStep(
                    description="Switch focus to Notepad window",
                    tool="desktop.switch_window",
                    tool_args={"title_or_pid": "Notepad"},
                )
            )
            steps.append(
                PlannedStep(
                    description="Type note text in Notepad",
                    tool="keyboard.type",
                    tool_args={"text": "AXON Desktop Automation active.\n"},
                )
            )
            steps.append(
                PlannedStep(
                    description="Capture verification screenshot",
                    tool="screenshot.take",
                    tool_args={},
                )
            )
            return Plan(goal=goal, steps=steps)

        # 4. "Inspect desktop state / visible windows"
        if "inspect desktop" in lower or "visible windows" in lower or "desktop state" in lower:
            steps.append(
                PlannedStep(
                    description="Inspect desktop screen and active window telemetry",
                    tool="desktop.inspect_screen",
                    tool_args={},
                )
            )
            steps.append(
                PlannedStep(
                    description="List open visible windows",
                    tool="desktop.get_windows",
                    tool_args={},
                )
            )
            return Plan(goal=goal, steps=steps)

        # 5. "Prepare coding workspace"
        if "workspace" in lower or "coding" in lower or "setup" in lower:
            steps.append(
                PlannedStep(
                    description="Check system hardware resources",
                    tool="system.resources",
                    tool_args={"drive": "C:"},
                )
            )
            steps.append(
                PlannedStep(
                    description="Check if VS Code is running",
                    tool="applications.is_running",
                    tool_args={"name": "code"},
                )
            )
            steps.append(
                PlannedStep(
                    description="List project directory contents",
                    tool="filesystem.list",
                    tool_args={"path": "."},
                )
            )
            return Plan(goal=goal, steps=steps)

        # 6. Default multi-step fallback
        steps.append(
            PlannedStep(
                description=f"Inspect system state for goal: {goal}",
                tool="system.info",
                tool_args={},
            )
        )
        return Plan(goal=goal, steps=steps)
