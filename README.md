# AXON

A personal AI agent for Windows. This is the foundation layer — the infrastructure that future UI, LLM, and autonomous systems will build on.

## Architecture

```
axon/
├── core/          Runtime, config, state
├── tools/         Tool registry + built-in tools
├── router/        Routes capability requests to tools
├── events/        Simple event bus
├── security/      Permission checks (allowed/denied/approval_required)
├── tasks/         Task representation with state machine
└── interfaces/    CLI for testing
```

## How It Works

**Tools** are functions registered with a name:

```python
from axon.core import Axon

axon = Axon().start()
axon.registry.register("my.tool", my_function, "Description")
```

**Router** receives a request, checks security, executes the tool, and emits events:

```python
result = axon.router.execute("system.info")
# {"success": True, "result": {...}}
```

**Security** controls access:

```python
from axon.security import Permission
axon.security.set_permission("dangerous.tool", Permission.DENIED)
```

## Built-in Tools

| Tool | Description | Security |
|------|-------------|----------|
| `filesystem.list` | List directory contents | allowed |
| `filesystem.search` | Glob search for files | allowed |
| `filesystem.read` | Read file contents | allowed |
| `system.info` | OS, hostname, CPU, Python version | allowed |
| `processes.list` | List running processes | allowed |
| `applications.list` | List installed applications | allowed |
| `terminal.run` | Run a shell command | approval_required |

## Run

```bash
# Start the CLI
python -m axon

# Quick status check
python -m axon --status
```

### CLI Usage

```
axon> tools                    # list all tools
axon> system.info              # run a tool
axon> filesystem.list C:\      # tool with argument
axon> quit                     # exit
```

## Add a New Tool

1. Create a function:

```python
# axon/tools/my_tools.py
def my_tool(arg1: str = "") -> str:
    return f"Result: {arg1}"
```

2. Register it in `axon/core/runtime.py`:

```python
from axon.tools.my_tools import my_tool

# Inside _register_builtin_tools():
reg.register("my.tool", my_tool, "My custom tool")
```

3. Set security if needed:

```python
# Inside _setup_security():
self.security.set_permission("my.tool", Permission.APPROVAL_REQUIRED)
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```
