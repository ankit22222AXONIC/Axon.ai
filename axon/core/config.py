"""AXON configuration."""

import json
import os
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG = {
    "name": "AXON",
    "version": "0.1.0",
    "max_file_read_bytes": 1_000_000,  # 1MB safety limit for file reads
    "OPENROUTER_MODEL": "openai/gpt-4o-mini",
    "GENERAL_MODEL": "openai/gpt-4o-mini",
    "CODING_MODEL": "qwen/qwen-2.5-coder-32b-instruct",
}


def _load_env_file(env_path: Path):
    """Load key=value pairs from a .env file into os.environ."""
    if env_path.exists() and env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            os.environ.setdefault(k, v)


def _read_env_key(key_name: str, env_path: Optional[Path] = None) -> str:
    """Read key directly from environment or local .env file."""
    val = os.environ.get(key_name, "").strip()
    if val:
        return val
    target_path = env_path or (Path.cwd() / ".env")
    if target_path.exists() and target_path.is_file():
        for line in target_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key_name:
                return v.strip().strip("'\"")
    return ""


def has_openrouter_api_key(env_path: Optional[Path] = None) -> bool:
    """Check whether a valid non-placeholder OpenRouter API key is configured."""
    key = _read_env_key("OPENROUTER_API_KEY", env_path=env_path)
    return bool(key and key != "PASTE_YOUR_OPENROUTER_KEY_HERE")


def get_masked_openrouter_api_key(env_path: Optional[Path] = None) -> Optional[str]:
    """Return a masked representation of the configured key, or None if not configured.
    
    Security: The raw key is NEVER returned to callers or the browser.
    """
    if not has_openrouter_api_key(env_path=env_path):
        return None
    key = _read_env_key("OPENROUTER_API_KEY", env_path=env_path)
    if not key:
        return None
    if len(key) <= 8:
        return "sk-••••••••"
    prefix_len = 8 if len(key) >= 16 else 3
    suffix_len = 4 if len(key) >= 16 else 2
    return f"{key[:prefix_len]}••••••••{key[-suffix_len:]}"


def save_openrouter_api_key(api_key: str, env_path: Optional[Path] = None) -> bool:
    """Securely save the OpenRouter API key to local .env and update os.environ.
    
    Ensures .env is gitignored and does not expose the key.
    """
    clean_key = (api_key or "").strip()
    if not clean_key:
        return False

    target_path = env_path or (Path.cwd() / ".env")
    lines = []
    found = False

    if target_path.exists():
        for line in target_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("OPENROUTER_API_KEY="):
                lines.append(f"OPENROUTER_API_KEY={clean_key}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"OPENROUTER_API_KEY={clean_key}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["OPENROUTER_API_KEY"] = clean_key

    # Ensure .gitignore protects .env
    gitignore_path = target_path.parent / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if ".env" not in content:
            gitignore_path.write_text(content.rstrip() + "\n.env\n", encoding="utf-8")
    elif target_path.parent == Path.cwd():
        gitignore_path.write_text(".env\n", encoding="utf-8")

    return True


def remove_openrouter_api_key(env_path: Optional[Path] = None) -> bool:
    """Remove stored OpenRouter API key from .env and os.environ."""
    target_path = env_path or (Path.cwd() / ".env")
    if target_path.exists():
        lines = []
        for line in target_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("OPENROUTER_API_KEY="):
                continue
            lines.append(line)
        target_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    os.environ.pop("OPENROUTER_API_KEY", None)
    return True


class Config:
    def __init__(self, path: str = None):
        self._data = dict(DEFAULT_CONFIG)
        # Load local .env if available
        _load_env_file(Path(".env"))
        if path and Path(path).exists():
            with open(path) as f:
                self._data.update(json.load(f))
            _load_env_file(Path(path).parent / ".env")

    def get(self, key, default=None):
        if key in os.environ:
            return os.environ[key]
        if key == "GENERAL_MODEL":
            return os.environ.get("OPENROUTER_MODEL") or self._data.get("GENERAL_MODEL", default)
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        if key in os.environ:
            return os.environ[key]
        if key == "GENERAL_MODEL" and "OPENROUTER_MODEL" in os.environ:
            return os.environ["OPENROUTER_MODEL"]
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
