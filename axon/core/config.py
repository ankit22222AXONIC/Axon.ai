"""AXON configuration."""

import json
import os
from pathlib import Path

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
