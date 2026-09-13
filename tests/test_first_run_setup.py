"""Tests for AXONIC First-Run API Key Setup and Management.

Covers:
1. First launch with no API key
2. Existing API key skips setup
3. Valid API key validation
4. Invalid API key validation
5. Invalid key is not saved
6. API key is never written to logs
7. API key removal
8. API key replacement
9. Web interface endpoints & security
"""

import io
import json
import os
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from axon.core import Axon
from axon.core.config import (
    has_openrouter_api_key,
    get_masked_openrouter_api_key,
    save_openrouter_api_key,
    remove_openrouter_api_key,
    Config,
)
from axon.ai.client import OpenRouterClient
from axon.interfaces.web import create_web_handler, WebApprovalBridge, ConversationStore
from axon.security.audit import AuditLogger
from axon.security.terminal_security import inspect_terminal_command


# ── 1. First Launch with No API Key ─────────────────────────────────────────

def test_first_launch_no_api_key(tmp_path, monkeypatch):
    """When no API key is configured or is empty, has_openrouter_api_key returns False."""
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_MODEL=openai/gpt-4o-mini\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert has_openrouter_api_key(env_path=env_file) is False
    assert get_masked_openrouter_api_key(env_path=env_file) is None


def test_placeholder_api_key_treated_as_missing(tmp_path, monkeypatch):
    """Placeholder keys (e.g. PASTE_YOUR_OPENROUTER_KEY_HERE) are treated as missing."""
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=PASTE_YOUR_OPENROUTER_KEY_HERE\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert has_openrouter_api_key(env_path=env_file) is False
    assert get_masked_openrouter_api_key(env_path=env_file) is None


# ── 2. Existing API Key Skips Setup ──────────────────────────────────────────

def test_existing_api_key_detected_and_masked(tmp_path, monkeypatch):
    """A configured API key returns configured=True and masks the key properly."""
    env_file = tmp_path / ".env"
    fake_key = "sk-or-v1-mock-dummy-token-sample-value-xyz-7890"
    env_file.write_text(f"OPENROUTER_API_KEY={fake_key}\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", fake_key)

    assert has_openrouter_api_key(env_path=env_file) is True
    masked = get_masked_openrouter_api_key(env_path=env_file)
    assert masked is not None
    # Key should be masked with bullets and never expose the entire secret
    assert "••••••••" in masked
    assert fake_key not in masked
    assert masked.startswith("sk-or-v1")
    assert masked.endswith("7890")


# ── 3. Valid API Key Validation ─────────────────────────────────────────────

def test_validate_api_key_success():
    """Mocking successful 200 response from OpenRouter auth/key endpoint."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        valid, msg = OpenRouterClient.validate_api_key("sk-or-v1-validkey1234567890")
        assert valid is True
        assert "verified successfully" in msg.lower()


# ── 4. Invalid API Key Validation ───────────────────────────────────────────

def test_validate_api_key_empty():
    """Empty or whitespace-only API keys fail validation immediately without network requests."""
    valid, msg = OpenRouterClient.validate_api_key("")
    assert valid is False
    assert "empty" in msg.lower()

    valid2, msg2 = OpenRouterClient.validate_api_key("   ")
    assert valid2 is False


def test_validate_api_key_http_401():
    """Mocking 401 Unauthorized from OpenRouter."""
    err = urllib.error.HTTPError(
        url="https://openrouter.ai/api/v1/auth/key",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=io.BytesIO(b'{"error": {"message": "Invalid API key"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        valid, msg = OpenRouterClient.validate_api_key("sk-or-v1-invalidkey")
        assert valid is False
        assert "invalid" in msg.lower()


def test_validate_api_key_network_error():
    """Mocking network connection failure to OpenRouter."""
    err = urllib.error.URLError(reason="Connection refused")

    with patch("urllib.request.urlopen", side_effect=err):
        valid, msg = OpenRouterClient.validate_api_key("sk-or-v1-somekey")
        assert valid is False
        assert "unable to reach openrouter" in msg.lower()


# ── 5. Invalid Key Is Not Saved ─────────────────────────────────────────────

def test_invalid_key_not_saved(tmp_path, monkeypatch):
    """If an API key is invalid, save_openrouter_api_key is not called or fails."""
    env_file = tmp_path / ".env"
    initial_content = "OPENROUTER_MODEL=openai/gpt-4o-mini\n"
    env_file.write_text(initial_content, encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    # Empty key check
    result = save_openrouter_api_key("", env_path=env_file)
    assert result is False
    assert env_file.read_text(encoding="utf-8") == initial_content
    assert "OPENROUTER_API_KEY" not in os.environ


# ── 6. API Key Never Written to Logs ────────────────────────────────────────

def test_api_key_never_written_to_logs():
    """AuditLogger must redact API keys and bearer tokens from entries."""
    logger = AuditLogger(log_path=":memory:")
    secret_key = "sk-mock-dummy-secret-redacted-token-for-test-12345"

    entry = logger.log(
        tool="key.save",
        operation="save",
        permission_level="SAFE",
        args={"api_key": secret_key, "nested": {"token": f"Bearer {secret_key}"}},
        failure_reason=f"Failed for key {secret_key}",
    )

    logged_str = json.dumps(entry)
    assert secret_key not in logged_str
    assert "[REDACTED_API_KEY]" in logged_str or "[REDACTED_SECRET]" in logged_str


# ── 7. Terminal Protection Blocks Reading .env ──────────────────────────────

def test_terminal_security_blocks_reading_env():
    """Terminal commands attempting to cat, type, or get-content .env must be blocked."""
    for cmd in ("cat .env", "type .env", "Get-Content .env", "head -n 5 .env"):
        allowed, reason, meta = inspect_terminal_command(cmd)
        assert allowed is False, f"Command '{cmd}' should have been blocked"
        assert meta["blocked"] is True


# ── 8. API Key Removal & Replacement ────────────────────────────────────────

def test_api_key_replacement_and_removal(tmp_path, monkeypatch):
    """Test saving, replacing, and removing an OpenRouter API key."""
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_MODEL=openai/gpt-4o-mini\n", encoding="utf-8")

    key1 = "sk-mock-first-test-token-value-1111111111111111111111111111"
    key2 = "sk-mock-second-test-token-value-2222222222222222222222222222"

    # 1. Save key1
    ok1 = save_openrouter_api_key(key1, env_path=env_file)
    assert ok1 is True
    assert os.environ.get("OPENROUTER_API_KEY") == key1
    assert key1 in env_file.read_text(encoding="utf-8")

    # 2. Replace with key2
    ok2 = save_openrouter_api_key(key2, env_path=env_file)
    assert ok2 is True
    assert os.environ.get("OPENROUTER_API_KEY") == key2
    content2 = env_file.read_text(encoding="utf-8")
    assert key2 in content2
    assert key1 not in content2

    # 3. Remove key
    ok_rem = remove_openrouter_api_key(env_path=env_file)
    assert ok_rem is True
    assert "OPENROUTER_API_KEY" not in os.environ
    content_rem = env_file.read_text(encoding="utf-8")
    assert key2 not in content_rem
    assert has_openrouter_api_key(env_path=env_file) is False


# ── 9. Web Interface API Endpoints ──────────────────────────────────────────

class MockClientHandler:
    def __init__(self, handler_cls):
        self.handler_cls = handler_cls

    def request(self, method: str, path: str, body: dict = None):
        body_bytes = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        rfile = io.BytesIO(body_bytes)
        wfile = io.BytesIO()

        # Instantiate mock request handler
        handler = object.__new__(self.handler_cls)
        handler.rfile = rfile
        handler.wfile = wfile
        handler.path = path
        handler.command = method
        handler.headers = {
            "Content-Length": str(len(body_bytes)),
            "Content-Type": "application/json",
        }
        handler.close_connection = False

        status_container = []
        headers_container = {}

        def send_response(status):
            status_container.append(status)

        def send_header(k, v):
            headers_container[k] = v

        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()

        response_bytes = wfile.getvalue()
        try:
            resp_data = json.loads(response_bytes.decode("utf-8")) if response_bytes else {}
        except Exception:
            resp_data = response_bytes.decode("utf-8", errors="replace")

        return {
            "status": status_container[0] if status_container else 200,
            "data": resp_data,
        }


@pytest.fixture
def mock_web_client(tmp_path, monkeypatch):
    """Fixture providing a mock web client bound to an initialized Axon runtime."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_MODEL=openai/gpt-4o-mini\n", encoding="utf-8")

    axon = Axon()
    axon.config._data["memory_db_path"] = str(tmp_path / "mem.db")
    axon.config._data["audit_log_path"] = str(tmp_path / "audit.log")
    axon.start()

    approval_bridge = WebApprovalBridge()
    conv_store = ConversationStore(storage_path=tmp_path / "convs.json")
    ui_path = tmp_path / "UI.html"
    ui_path.write_text("<html><body>AXONIC</body></html>", encoding="utf-8")

    handler_cls = create_web_handler(
        axon=axon,
        approval_bridge=approval_bridge,
        ui_html_path=ui_path,
        conversation_store=conv_store,
    )
    client = MockClientHandler(handler_cls)
    yield client, axon
    axon.shutdown()


def test_web_key_status_unconfigured(mock_web_client, monkeypatch):
    """GET /api/key/status returns configured=False when no key is set."""
    client, _ = mock_web_client
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    res = client.request("GET", "/api/key/status")
    assert res["status"] == 200
    assert res["data"]["configured"] is False
    assert res["data"]["masked_key"] is None


def test_web_key_validate_endpoint(mock_web_client):
    """POST /api/key/validate returns validation response."""
    client, _ = mock_web_client

    with patch("axon.ai.client.OpenRouterClient.validate_api_key", return_value=(True, "Key is valid")):
        res = client.request("POST", "/api/key/validate", {"api_key": "sk-or-v1-mockvalid"})
        assert res["status"] == 200
        assert res["data"]["valid"] is True


def test_web_key_save_invalid_rejected(mock_web_client):
    """POST /api/key/save rejects invalid keys with 400 and does not save."""
    client, _ = mock_web_client

    with patch("axon.ai.client.OpenRouterClient.validate_api_key", return_value=(False, "Invalid OpenRouter API key")):
        res = client.request("POST", "/api/key/save", {"api_key": "sk-or-v1-badkey"})
        assert res["status"] == 400
        assert res["data"]["success"] is False
        assert "Invalid OpenRouter API key" in res["data"]["error"]


def test_web_key_save_valid_updates_runtime(mock_web_client, monkeypatch):
    """POST /api/key/save saves valid key and updates the in-memory runtime."""
    client, axon = mock_web_client
    valid_key = "sk-mock-valid-test-key-1234567890-sample-token"

    with patch("axon.ai.client.OpenRouterClient.validate_api_key", return_value=(True, "Key is valid")):
        res = client.request("POST", "/api/key/save", {"api_key": valid_key})
        assert res["status"] == 200
        assert res["data"]["success"] is True
        assert "••••••••" in res["data"]["masked_key"]

        # Runtime AI client must be updated
        assert axon.ai_client._api_key == valid_key
        assert axon.coding_client._api_key == valid_key


def test_web_key_remove_endpoint(mock_web_client, monkeypatch):
    """POST /api/key/remove clears key and clears runtime clients."""
    client, axon = mock_web_client
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-testkey12345")
    axon.update_api_key("sk-or-v1-testkey12345")

    res = client.request("POST", "/api/key/remove", {})
    assert res["status"] == 200
    assert res["data"]["success"] is True
    assert axon.ai_client._api_key == ""
    assert "OPENROUTER_API_KEY" not in os.environ


def test_web_chat_blocked_without_api_key(mock_web_client, monkeypatch):
    """POST /api/chat returns HTTP 401 if no OpenRouter key is configured."""
    client, _ = mock_web_client
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    res = client.request("POST", "/api/chat", {"message": "Hello AXON", "stream": False})
    assert res["status"] == 401
    assert "API key is not configured" in res["data"]["error"]
