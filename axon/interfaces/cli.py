"""AXON CLI — minimal REPL for testing the architecture."""

import json
import shlex
from axon.core import Axon


def format_result(result):
    """Pretty-print a tool result."""
    if isinstance(result, dict):
        return json.dumps(result, indent=2, default=str)
    if isinstance(result, list):
        return "\n".join(str(item) for item in result)
    return str(result)


def parse_input(user_input: str):
    """Parse 'tool_name arg1 key=value' into (tool_name, kwargs)."""
    parts = shlex.split(user_input)
    if not parts:
        return None, {}
    tool_name = parts[0]
    kwargs = {}
    positional = []
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            kwargs[key] = value
        else:
            positional.append(part)
    # Map positional args based on tool type
    if positional:
        if tool_name == "terminal.run":
            kwargs.setdefault("command", " ".join(positional))
        elif tool_name in ("memory.get", "memory.forget"):
            kwargs.setdefault("memory_id", positional[0])
        elif tool_name == "memory.search":
            kwargs.setdefault("query", positional[0])
            if len(positional) > 1:
                kwargs.setdefault("category", positional[1])
        elif tool_name == "memory.store":
            kwargs.setdefault("content", positional[0])
            if len(positional) > 1:
                kwargs.setdefault("category", positional[1])
        elif tool_name == "memory.list":
            kwargs.setdefault("category", positional[0])
        else:
            for key, val in zip(["path", "pattern"], positional):
                kwargs.setdefault(key, val)
    return tool_name, kwargs


def cli_approval_prompt(tool_name: str, kwargs: dict) -> bool:
    """Ask the user for approval in the terminal."""
    print(f"\n  Tool: {tool_name}")
    if kwargs:
        print("  Arguments:")
        for key, value in kwargs.items():
            print(f"    {key} = {value!r}")
    print("\n  Approval required.")
    try:
        answer = input("  Allow? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    return answer == "y"


def run_cli():
    """Start the AXON CLI REPL."""
    axon = Axon()
    axon.approval.set_prompt(cli_approval_prompt)
    axon.start()

    name = axon.config.get("name")
    version = axon.config.get("version")
    print(f"\n  {name} v{version}")
    print(f"  Status: {axon.state.status.value}")
    print(f"  Tools:  {len(axon.registry.list())}")
    print(f"  Type 'help' for commands, 'quit' to exit.\n")

    while True:
        try:
            user_input = input("axon> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input == "quit":
            break
        if user_input == "help":
            print("  Commands:")
            print("    chat <message>     — chat with AXON AI Brain (or type your message directly)")
            print("    clear              — reset AI conversation history")
            print("    tools              — list registered tools")
            print("    <tool> [args]      — execute a registered tool directly")
            print("    task create <goal> — create a task")
            print("    task list          — list all tasks")
            print("    task status <id>   — show task details")
            print("    memory store <txt> — store a memory")
            print("    memory search <q>  — search memories")
            print("    memory list        — list memories")
            print("    memory forget <id> — delete a memory")
            print("    quit               — exit")
            continue
        if user_input == "tools":
            for name, desc in axon.registry.list().items():
                print(f"  {name:25s} {desc}")
            continue

        if user_input == "clear":
            axon.brain.clear_history()
            print("  AI conversation history cleared.")
            continue

        # Chat command
        if user_input.startswith("chat "):
            response = axon.brain.process(user_input[5:].strip())
            print(f"\nAXON: {response}\n")
            continue

        # Dedicated coding command
        if user_input.startswith("code "):
            response = axon.coding_agent.handle(user_input[5:].strip())
            print(f"\n{response}\n")
            continue

        # Task commands
        if user_input.startswith("task "):
            _handle_task_command(axon, user_input[5:].strip())
            continue

        # Memory commands
        if user_input.startswith("memory "):
            _handle_memory_command(axon, user_input[7:].strip())
            continue

        tool_name, kwargs = parse_input(user_input)

        # If user entered an explicit registered tool, execute it directly
        if tool_name and axon.registry.exists(tool_name):
            result = axon.router.execute(tool_name, **kwargs)
            if result["success"]:
                print(format_result(result["result"]))
            else:
                print(f"  [error] {result['error']}")
            continue

        # Otherwise, route through the AI Brain
        response = axon.brain.process(user_input)
        print(f"\nAXON: {response}\n")

    axon.shutdown()
    print("AXON stopped.")


def _handle_task_command(axon, args: str):
    """Handle task subcommands."""
    parts = args.split(None, 1)
    if not parts:
        print("  Usage: task <create|list|status> [args]")
        return

    cmd = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "create" and rest:
        task = axon.tasks.create(rest)
        print(f"  Task created: {task.id}")
    elif cmd == "list":
        tasks = axon.tasks.list()
        if not tasks:
            print("  No tasks.")
        for t in tasks:
            print(f"  [{t.status.value:9s}] {t.id}  {t.goal}")
    elif cmd == "status" and rest:
        try:
            t = axon.tasks.get(rest.strip())
            print(f"  Task:   {t.goal}")
            print(f"  ID:     {t.id}")
            print(f"  Status: {t.status.value}")
            print(f"  Steps:  {len(t.steps)}")
            if t.result is not None:
                print(f"  Result: {t.result}")
            if t.error:
                print(f"  Error:  {t.error}")
        except KeyError as e:
            print(f"  [error] {e}")
    else:
        print("  Usage: task <create|list|status> [args]")


def _handle_memory_command(axon, args: str):
    """Handle memory subcommands."""
    try:
        parts = shlex.split(args)
    except ValueError:
        parts = args.split()
    if not parts:
        print("  Usage: memory <store|get|search|list|forget> [args]")
        return

    cmd = parts[0]
    rest = parts[1:]

    if cmd == "store" and rest:
        content = rest[0]
        category = "fact"
        i = 1
        while i < len(rest):
            if rest[i] in ("--category", "-c") and i + 1 < len(rest):
                category = rest[i + 1]
                i += 2
            elif rest[i].startswith("category="):
                category = rest[i].split("=", 1)[1]
                i += 1
            else:
                i += 1
        result = axon.router.execute("memory.store", content=content, category=category)
        if result["success"]:
            mem = result["result"]
            print(f"  Memory stored: [{mem['id']}] ({mem['category']}) {mem['content']}")
        else:
            print(f"  [error] {result['error']}")

    elif cmd == "get" and rest:
        result = axon.router.execute("memory.get", memory_id=rest[0])
        if result["success"] and result["result"]:
            mem = result["result"]
            print(f"  ID:       {mem['id']}")
            print(f"  Category: {mem['category']}")
            print(f"  Content:  {mem['content']}")
            print(f"  Created:  {mem['created_at']}")
        elif result["success"]:
            print(f"  Memory not found: {rest[0]}")
        else:
            print(f"  [error] {result['error']}")

    elif cmd == "search" and rest:
        result = axon.router.execute("memory.search", query=rest[0])
        if result["success"]:
            memories = result["result"]
            if not memories:
                print("  No matching memories.")
            for m in memories:
                print(f"  [{m['category']:10s}] {m['id']}  {m['content']}")
        else:
            print(f"  [error] {result['error']}")

    elif cmd == "list":
        category = rest[0] if rest else None
        result = axon.router.execute("memory.list", category=category)
        if result["success"]:
            memories = result["result"]
            if not memories:
                print("  No memories.")
            for m in memories:
                print(f"  [{m['category']:10s}] {m['id']}  {m['content']}")
        else:
            print(f"  [error] {result['error']}")

    elif cmd == "forget" and rest:
        result = axon.router.execute("memory.forget", memory_id=rest[0])
        if result["success"]:
            if result["result"]:
                print(f"  Memory deleted: {rest[0]}")
            else:
                print(f"  Memory not found: {rest[0]}")
        else:
            print(f"  [error] {result['error']}")

    else:
        print("  Usage: memory <store|get|search|list|forget> [args]")

