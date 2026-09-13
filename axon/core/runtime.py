"""AXON runtime — initializes and wires everything together."""

from axon.core.config import Config
from axon.core.state import State, AxonStatus
from axon.events import EventBus
from axon.security import SecurityManager, Permission, ApprovalManager, AuditLogger
from axon.tools import (
    ToolRegistry,
    filesystem_list,
    filesystem_list_detailed,
    filesystem_search,
    filesystem_read,
    filesystem_write,
    filesystem_create_directory,
    filesystem_delete,
    filesystem_copy,
    filesystem_move,
    filesystem_view_lines,
    filesystem_find_in_files,
    filesystem_replace_content,
    filesystem_set_workspace,
    filesystem_get_workspace,
    applications_list,
    applications_open,
    applications_is_running,
    applications_close,
    screenshot_take,
    browser_open,
    browser_search,
    browser_youtube_search,
    browser_play_video,
    browser_click_first_result,
    browser_click_link,
    system_info,
    system_resources,
    processes_list,
    processes_find,
    terminal_run,
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_branch,
    git_checkout,
    git_switch,
    git_pull,
    git_push,
    git_info,
    git_safe_rollback,
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_scroll,
    mouse_get_position,
    keyboard_type,
    keyboard_press,
    keyboard_hotkey,
    desktop_get_windows,
    desktop_get_active_window,
    desktop_switch_window,
    desktop_close_window,
    desktop_inspect_screen,
    screenshot_analyze,
    safety_reset,
    osiris_briefing,
    osiris_get_layer,
    osiris_search_region,
    osiris_open_globe,
    osiris_status,
)
from axon.router import Router
from axon.tasks import TaskManager
from axon.memory import MemoryStore
from axon.ai import OpenRouterClient, Brain, IntentRouter
from axon.coding import (
    CodingAgent,
    coding_list_files,
    coding_read_file,
    coding_search_code,
    coding_create_file,
    coding_write_file,
    coding_edit_file,
    coding_run_tests,
    coding_run_build,
)


class Axon:
    def __init__(self, config_path: str = None):
        self.config = Config(config_path)
        self.state = State()
        self.events = EventBus()
        self.security = SecurityManager()
        self.approval = ApprovalManager(self.events)
        self.audit = AuditLogger(self.config.get("audit_log_path"))
        self.registry = ToolRegistry()
        self.router = Router(
            self.registry,
            self.security,
            self.events,
            self.approval,
            audit_logger=self.audit,
        )
        self.tasks = TaskManager(self.events)
        self.memory = MemoryStore(self.config.get("memory_db_path"), self.events)

        general_model = self.config.get("GENERAL_MODEL", self.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
        coding_model = self.config.get("CODING_MODEL", "qwen/qwen-2.5-coder-32b-instruct")

        self.ai_client = OpenRouterClient(
            api_key=self.config.get("OPENROUTER_API_KEY"),
            fallback_api_key=self.config.get("OPENROUTER_FALLBACK_API_KEY"),
            model=general_model,
        )
        self.coding_client = OpenRouterClient(
            api_key=self.config.get("OPENROUTER_API_KEY"),
            fallback_api_key=self.config.get("OPENROUTER_FALLBACK_API_KEY"),
            model=coding_model,
        )
        self.intent_router = IntentRouter()
        self.coding_agent = CodingAgent(
            client=self.coding_client,
            router=self.router,
            task_manager=self.tasks,
            event_bus=self.events,
        )
        self.brain = Brain(
            client=self.ai_client,
            router=self.router,
            registry=self.registry,
            event_bus=self.events,
            tasks=self.tasks,
            coding_agent=self.coding_agent,
            intent_router=self.intent_router,
        )
        self.planner = self.brain.planner
        self.executor = self.brain.executor

    def start(self):
        """Initialize AXON and register built-in tools."""
        self._register_builtin_tools()
        self._setup_security()
        self.state.set(AxonStatus.READY)
        self.events.emit("AXON_STARTED", {
            "name": self.config.get("name"),
            "version": self.config.get("version"),
        })
        return self

    def shutdown(self):
        self.state.set(AxonStatus.SHUTTING_DOWN)
        self.memory.close()
        self.events.emit("AXON_STOPPED")
        self.state.set(AxonStatus.STOPPED)

    def _register_builtin_tools(self):
        reg = self.registry

        # Filesystem tools
        reg.register("filesystem.list", filesystem_list, "List directory contents")
        reg.register("filesystem.list_detailed", filesystem_list_detailed, "List directory contents with file size and modified timestamps")
        reg.register("filesystem.search", filesystem_search, "Search files with glob pattern")
        reg.register("filesystem.read", filesystem_read, "Read a file's contents")
        reg.register("filesystem.write", filesystem_write, "Write text content to a file")
        reg.register("filesystem.create_directory", filesystem_create_directory, "Create a directory path")
        reg.register("filesystem.delete", filesystem_delete, "Delete a file or directory (requires approval)")
        reg.register("filesystem.copy", filesystem_copy, "Copy a file or directory to a destination")
        reg.register("filesystem.move", filesystem_move, "Move or rename a file or directory")
        reg.register("filesystem.view_lines", filesystem_view_lines, "View a specific line range in a file with line numbers")
        reg.register("filesystem.find_in_files", filesystem_find_in_files, "Search for text or code symbols across files in a directory")
        reg.register("filesystem.replace_content", filesystem_replace_content, "Surgically replace exact code or text in an existing file (requires approval)")
        reg.register("filesystem.set_workspace", filesystem_set_workspace, "Set the active project workspace folder")
        reg.register("filesystem.get_workspace", filesystem_get_workspace, "Get the current active project workspace folder")

        # Dedicated Coding tools
        reg.register("coding.list_files", coding_list_files, "List project source files in workspace")
        reg.register("coding.read_file", coding_read_file, "Read a file or line range in workspace")
        reg.register("coding.search_code", coding_search_code, "Search for symbols or patterns in workspace")
        reg.register("coding.create_file", coding_create_file, "Create a new file in workspace")
        reg.register("coding.write_file", coding_write_file, "Write content to a file in workspace")
        reg.register("coding.edit_file", coding_edit_file, "Surgically edit file content in workspace")
        reg.register("coding.run_tests", coding_run_tests, "Run project test suite in workspace")
        reg.register("coding.run_build", coding_run_build, "Run project build command in workspace")

        # Application tools
        reg.register("applications.list", applications_list, "List installed applications")
        reg.register("applications.open", applications_open, "Launch an application by name or executable path")
        reg.register("applications.is_running", applications_is_running, "Check if an application or process is running")
        reg.register("applications.close", applications_close, "Close or terminate an application by name or PID (requires approval)")

        # Screenshot tools
        reg.register("screenshot.take", screenshot_take, "Capture a desktop screenshot and save to disk")
        reg.register("screenshot.analyze", screenshot_analyze, "Analyze desktop screenshot for visual telemetry and layout understanding")

        # Desktop & Window Automation
        reg.register("desktop.get_windows", desktop_get_windows, "Enumerate visible desktop windows and processes")
        reg.register("desktop.get_active_window", desktop_get_active_window, "Get active foreground window details")
        reg.register("desktop.switch_window", desktop_switch_window, "Switch active window focus by title or PID")
        reg.register("desktop.close_window", desktop_close_window, "Close an application window gracefully (requires approval)")
        reg.register("desktop.inspect_screen", desktop_inspect_screen, "Inspect full desktop visual state: display, cursor, active window, and visible apps")
        reg.register("safety_reset", safety_reset, "Safety reset to release any held mouse buttons and modifier keys")

        # Mouse Automation
        reg.register("mouse.move", mouse_move, "Move mouse cursor to coordinates (x, y)")
        reg.register("mouse.click", mouse_click, "Click mouse button at current or specified coordinates (x, y)")
        reg.register("mouse.double_click", mouse_double_click, "Double click left mouse button at coordinates (x, y)")
        reg.register("mouse.scroll", mouse_scroll, "Scroll mouse wheel up or down")
        reg.register("mouse.get_position", mouse_get_position, "Get current mouse cursor coordinates and screen bounds")

        # Keyboard Automation
        reg.register("keyboard.type", keyboard_type, "Type text string with Unicode keyboard events")
        reg.register("keyboard.press", keyboard_press, "Press a key (e.g. enter, tab, esc, space, backspace, arrows)")
        reg.register("keyboard.hotkey", keyboard_hotkey, "Press a key combination (e.g. ctrl+c, ctrl+v, alt+tab)")

        # Browser tools
        reg.register("browser.open", browser_open, "Open a URL in the default web browser (supports 'yt' or 'youtube' shortcuts)")
        reg.register("browser.search", browser_search, "Search the web or YouTube using the default web browser")
        reg.register("browser.youtube_search", browser_youtube_search, "Search YouTube for videos. If play_first=True, automatically opens and plays the first video result")
        reg.register("browser.play_video", browser_play_video, "Search YouTube for a query and immediately open and play the top video result")
        reg.register("browser.click_first_result", browser_click_first_result, "Click the first search result or video thumbnail in the currently open browser window")
        reg.register("browser.click_link", browser_click_link, "Find and click a link with matching text in the active browser window")

        # System and process tools
        reg.register("system.info", system_info, "Get basic system and OS information")
        reg.register("system.resources", system_resources, "Get system resource metrics including RAM, Disk, CPU, Battery, and Uptime")
        reg.register("processes.list", processes_list, "List running processes")
        reg.register("processes.find", processes_find, "Search running processes by name or PID")

        # Terminal execution
        reg.register("terminal.run", terminal_run, "Run a shell command (requires approval)")

        # Git Intelligence tools
        reg.register("git.status", git_status, "Inspect Git repository status: branch, tracking, staged, unstaged, untracked")
        reg.register("git.diff", git_diff, "Inspect unstaged or staged Git changes with line context")
        reg.register("git.log", git_log, "View commit history in repository")
        reg.register("git.commit", git_commit, "Commit staged changes with secret protection and changed file inspection (requires approval)")
        reg.register("git.branch", git_branch, "List branches or create a new branch")
        reg.register("git.checkout", git_checkout, "Switch branch or create and switch branch")
        reg.register("git.switch", git_switch, "Switch to a branch")
        reg.register("git.pull", git_pull, "Pull updates from remote repository")
        reg.register("git.push", git_push, "Push commits to remote repository (requires approval)")
        reg.register("git.info", git_info, "Detect repository details and GitHub remote info")
        reg.register("git.remote", git_info, "Detect repository details and GitHub remote info (alias for git.info)")
        reg.register("git.rollback", git_safe_rollback, "Safely roll back changes using Git without destructive resets (requires approval)")

        # Memory tools
        reg.register("memory.store", self._tool_memory_store, "Store a piece of information or fact in long-term memory")
        reg.register("memory.get", self._tool_memory_get, "Retrieve a stored memory by its ID")
        reg.register("memory.search", self._tool_memory_search, "Search stored memories by query text or keyword")
        reg.register("memory.list", self._tool_memory_list, "List all stored memories, optionally filtered by category")
        reg.register("memory.forget", self._tool_memory_forget, "Delete a stored memory by its ID (requires approval)")

        # Task tools
        reg.register("task.create", self._tool_task_create, "Create a new task")
        reg.register("task.list", self._tool_task_list, "List all tracked tasks")
        reg.register("task.status", self._tool_task_status, "Get status and details of a task")
        reg.register("task.plan_and_execute", self._tool_task_plan_and_execute, "Decompose a goal into a plan and execute it step-by-step")

        # OSIRIS (Know the World) 3D Global Intelligence & Globe tools
        reg.register("osiris.briefing", osiris_briefing, "Get live global situation briefing across news, conflicts, earthquakes, and cyber events from OSIRIS")
        reg.register("osiris.get_layer", osiris_get_layer, "Query live telemetry from an OSIRIS layer: news, conflicts, earthquakes, fires, weather, satellites, flights, maritime, cyber, cctv")
        reg.register("osiris.search_region", osiris_search_region, "Search OSIRIS dossiers and threat profiles for a specific country or region")
        reg.register("osiris.open_globe", osiris_open_globe, "Open the interactive OSIRIS 3D Globe in the browser, optionally centered on coordinates")
        reg.register("osiris.status", osiris_status, "Check connectivity and status of the local OSIRIS 3D intelligence subsystem on port 3001")

    def _tool_memory_store(self, content: str = "", category: str = "fact", **kwargs) -> dict:
        """Store information in memory. Content is the text to remember."""
        actual_content = (
            content
            or kwargs.get("text")
            or kwargs.get("memory")
            or kwargs.get("value")
            or kwargs.get("fact")
            or kwargs.get("information")
            or ""
        )
        cat = category or kwargs.get("cat") or "fact"
        mem = self.memory.store(actual_content, cat)
        return mem.to_dict()

    def _tool_memory_get(self, memory_id: str = "", **kwargs):
        """Get a stored memory by ID."""
        mid = memory_id or kwargs.get("id") or ""
        mem = self.memory.get(mid)
        return mem.to_dict() if mem else None

    def _tool_memory_search(self, query: str = "", category: str = None, **kwargs) -> list:
        """Search memories matching a query string."""
        q = query or kwargs.get("q") or kwargs.get("search") or kwargs.get("text") or ""
        cat = category or kwargs.get("cat")
        return [m.to_dict() for m in self.memory.search(q, cat)]

    def _tool_memory_list(self, category: str = None, **kwargs) -> list:
        """List stored memories, optionally by category."""
        cat = category or kwargs.get("cat")
        return [m.to_dict() for m in self.memory.list(cat)]

    def _tool_memory_forget(self, memory_id: str = "", **kwargs) -> bool:
        """Forget/delete a stored memory by ID."""
        mid = memory_id or kwargs.get("id") or ""
        return self.memory.forget(mid)

    def _tool_task_create(self, goal: str = "", **kwargs) -> dict:
        actual_goal = goal or kwargs.get("task") or kwargs.get("name") or kwargs.get("description") or ""
        t = self.tasks.create(actual_goal)
        return {"id": t.id, "goal": t.goal, "status": t.status.value}

    def _tool_task_list(self, **kwargs) -> list:
        return [{"id": t.id, "goal": t.goal, "status": t.status.value} for t in self.tasks.list()]

    def _tool_task_status(self, task_id: str = "", **kwargs) -> dict:
        tid = task_id or kwargs.get("id") or ""
        try:
            t = self.tasks.get(tid)
            return {
                "id": t.id,
                "goal": t.goal,
                "status": t.status.value,
                "steps": len(t.steps),
                "result": t.result,
                "error": t.error,
            }
        except KeyError:
            return {"error": f"Task not found: {tid}"}

    def _tool_task_plan_and_execute(self, goal: str = "", **kwargs) -> dict:
        actual_goal = goal or kwargs.get("task") or kwargs.get("name") or ""
        if not actual_goal:
            return {"error": "No goal provided"}
        plan = self.planner.plan(actual_goal)
        task = self.executor.execute_plan(plan)
        return task.to_dict()

    def _setup_security(self):
        # Destructive or sensitive operations require user approval
        self.security.set_permission("terminal.run", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("filesystem.delete", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("applications.close", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("memory.forget", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("coding.edit_file", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("coding.write_file", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("coding.run_tests", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("coding.run_build", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("git.commit", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("git.push", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("git.rollback", Permission.APPROVAL_REQUIRED)
        self.security.set_permission("desktop.close_window", Permission.APPROVAL_REQUIRED)
