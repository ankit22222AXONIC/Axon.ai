"""Terminal tool — runs shell commands. Requires approval."""

import subprocess


def terminal_run(command: str = "", timeout: int = 30) -> dict:
    """Run a shell command and return output."""
    if not command:
        return {"error": "No command provided"}
    try:
        result = subprocess.run(
            command, shell=True,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}
