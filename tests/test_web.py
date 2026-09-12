"""AXON Web Interface tests — verifies HTTP endpoints, streaming, and approval bridge."""

import json
import urllib.request
import urllib.error
import pytest
from axon.core import Axon
from axon.ai.client import OpenRouterClient
from axon.interfaces.web import AxonWebServer, WebApprovalBridge, ConversationStore


def _make_mock_client(responses):
    resp_queue = list(responses)
    def mock_transport(payload):
        if not resp_queue:
            return {"choices": [{"message": {"role": "assistant", "content": "Done."}}]}
        resp = resp_queue.pop(0)
        return resp
    return OpenRouterClient(api_key="test_key", model="test_model", transport_fn=mock_transport)


@pytest.fixture
def web_test_server(tmp_path):
    """Start an AxonWebServer on an ephemeral localhost port for testing."""
    axon = Axon().start()
    # Mock AI client to prevent real network calls
    axon.ai_client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": "Hello from web AXON!"}}]}
    ])
    axon.brain.client = axon.ai_client

    conv_store = ConversationStore(storage_path=tmp_path / "conversations.json")
    server = AxonWebServer(axon=axon, host="127.0.0.1", port=0, conversation_store=conv_store)
    server_port = server.server.server_address[1]
    server.start(background=True)
    base_url = f"http://127.0.0.1:{server_port}"

    yield server, base_url, axon

    server.stop()
    axon.shutdown()


def test_get_ui_html(web_test_server):
    _, base_url, _ = web_test_server
    req = urllib.request.Request(f"{base_url}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read().decode("utf-8")
        assert "AXON" in content
        assert "AxonicA.jpeg" in content
        assert "chat-input" in content


def test_get_static_image(web_test_server):
    _, base_url, _ = web_test_server
    req = urllib.request.Request(f"{base_url}/AxonicA.jpeg")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "image/jpeg"
        content = resp.read()
        assert len(content) > 0



def test_get_status(web_test_server):
    _, base_url, axon = web_test_server
    req = urllib.request.Request(f"{base_url}/api/status")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ready"
        assert "model" in data
        assert "workspace" in data


def test_chat_non_streaming(web_test_server):
    _, base_url, axon = web_test_server
    axon.ai_client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": "Chat test response"}}]}
    ])
    axon.brain.client = axon.ai_client

    payload = json.dumps({"message": "Hello", "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["success"] is True
        assert data["response"] == "Chat test response"


def test_chat_streaming(web_test_server):
    _, base_url, axon = web_test_server
    axon.ai_client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": "Streamed message"}}]}
    ])
    axon.brain.client = axon.ai_client

    payload = json.dumps({"message": "Hello stream", "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        lines = [
            json.loads(line)
            for line in resp.read().decode("utf-8").splitlines()
            if line.strip()
        ]
        types = [l["type"] for l in lines]
        assert "status" in types
        assert "done" in types
        done_event = next(l for l in lines if l["type"] == "done")
        assert done_event["response"] == "Streamed message"


def test_web_approval_flow(web_test_server):
    _, base_url, axon = web_test_server
    import threading

    # Round 1: Model requests risky tool terminal.run
    # Round 2: Model acknowledges approval and returns final text
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "terminal__run",
                        "arguments": '{"command": "echo 42"}',
                    },
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Terminal output was 42",
            }
        }]
    }
    axon.ai_client = _make_mock_client([round1, round2])
    axon.brain.client = axon.ai_client

    # Send chat in background thread because approval blocks until approved
    result_container = []

    def send_chat():
        payload = json.dumps({"message": "Run terminal command", "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result_container.append(json.loads(resp.read().decode("utf-8")))
        except Exception as e:
            result_container.append({"error": str(e)})

    t = threading.Thread(target=send_chat)
    t.start()

    # Poll server's approval bridge for the pending approval request
    import time
    req_id = None
    for _ in range(50):
        time.sleep(0.05)
        with web_test_server[0].approval_bridge._lock:
            pending = list(web_test_server[0].approval_bridge.pending.keys())
            if pending:
                req_id = pending[0]
                break

    assert req_id is not None

    # Approve the request via POST /api/approve
    approve_payload = json.dumps({"id": req_id, "approved": True}).encode("utf-8")
    approve_req = urllib.request.Request(
        f"{base_url}/api/approve",
        data=approve_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(approve_req) as a_resp:
        assert a_resp.status == 200
        a_data = json.loads(a_resp.read().decode("utf-8"))
        assert a_data["success"] is True

    t.join(timeout=10)
    assert len(result_container) == 1
    assert result_container[0]["success"] is True
    assert "Terminal output was 42" in result_container[0]["response"]


def test_reset_and_history(web_test_server):
    _, base_url, axon = web_test_server
    axon.brain.history.append({"role": "user", "content": "Test history message"})

    # Check history
    req_hist = urllib.request.Request(f"{base_url}/api/history")
    with urllib.request.urlopen(req_hist) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert len(data["history"]) >= 1

    # Call reset
    req_reset = urllib.request.Request(
        f"{base_url}/api/reset",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_reset) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["success"] is True

    # History should be cleared (only system prompt remains)
    assert len(axon.brain.history) == 1


def test_chat_streaming_memory_store(web_test_server):
    """Verify that the web interface handles memory.store calls from AI threads cleanly."""
    _, base_url, axon = web_test_server

    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "mem_call_web_1",
                    "type": "function",
                    "function": {
                        "name": "memory__store",
                        "arguments": '{"content": "Favorite programming language is Python", "category": "preference"}',
                    },
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "I have remembered that your favorite programming language is Python.",
            }
        }]
    }

    axon.ai_client = _make_mock_client([round1, round2])
    axon.brain.client = axon.ai_client

    payload = json.dumps({
        "message": "Remember that my favorite programming language is Python.",
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    events = []
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str:
                events.append(json.loads(line_str))

    types = [e.get("type") for e in events]
    assert "tool_start" in types
    assert "tool_done" in types
    assert "done" in types

    # Verify that the memory was actually stored in the database
    stored_memories = axon.memory.list()
    assert len(stored_memories) >= 1
    assert any("Python" in m.content for m in stored_memories)


def test_conversations_api(web_test_server):
    """Verify listing, creating, pinning, switching, and deleting conversations."""
    _, base_url, _ = web_test_server

    # 1. GET /api/conversations
    req = urllib.request.Request(f"{base_url}/api/conversations")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "conversations" in data
        assert "pinned" in data
        assert "recents" in data
        assert len(data["pinned"]) >= 2
        assert any(c["title"] == "Build Free AI Agents" for c in data["pinned"])
        assert any(c["title"] == "Orry work explained" for c in data["recents"])
        active_id = data["active_id"]
        assert active_id is not None

    # 2. POST /api/conversations (create new chat)
    payload = json.dumps({"title": "Quantum Computing 101", "pinned": False}).encode("utf-8")
    req_create = urllib.request.Request(
        f"{base_url}/api/conversations",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_create) as resp:
        assert resp.status == 200
        res_data = json.loads(resp.read().decode("utf-8"))
        assert res_data["success"] is True
        new_conv = res_data["conversation"]
        assert new_conv["title"] == "Quantum Computing 101"
        new_id = new_conv["id"]

    # 3. POST /api/conversations/<id>/pin (pin the new chat)
    pin_payload = json.dumps({"pinned": True}).encode("utf-8")
    req_pin = urllib.request.Request(
        f"{base_url}/api/conversations/{new_id}/pin",
        data=pin_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_pin) as resp:
        assert resp.status == 200
        pin_data = json.loads(resp.read().decode("utf-8"))
        assert pin_data["success"] is True
        assert pin_data["conversation"]["pinned"] is True

    # 4. POST /api/conversations/active (switch to new chat)
    active_payload = json.dumps({"id": new_id}).encode("utf-8")
    req_active = urllib.request.Request(
        f"{base_url}/api/conversations/active",
        data=active_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_active) as resp:
        assert resp.status == 200
        act_data = json.loads(resp.read().decode("utf-8"))
        assert act_data["success"] is True
        assert act_data["conversation"]["id"] == new_id

    # 5. POST /api/conversations/<id>/delete (delete conversation)
    req_del = urllib.request.Request(
        f"{base_url}/api/conversations/{new_id}/delete",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_del) as resp:
        assert resp.status == 200
        del_data = json.loads(resp.read().decode("utf-8"))
        assert del_data["success"] is True


def test_chat_saves_to_conversation(web_test_server):
    """Verify that chat messages are recorded into the conversation store."""
    _, base_url, axon = web_test_server
    axon.ai_client = _make_mock_client([
        {"choices": [{"message": {"role": "assistant", "content": "Sure, here are agent tips!"}}]}
    ])
    axon.brain.client = axon.ai_client

    # Send chat with specific conversation_id
    payload = json.dumps({
        "message": "Give me agent tips",
        "stream": False,
        "conversation_id": "conv-pinned-1",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["conversation_id"] == "conv-pinned-1"

    # Verify conversation history updated
    req_get = urllib.request.Request(f"{base_url}/api/conversations/conv-pinned-1")
    with urllib.request.urlopen(req_get) as resp:
        assert resp.status == 200
        c_data = json.loads(resp.read().decode("utf-8"))
        messages = c_data["conversation"]["messages"]
        assert any(m["content"] == "Give me agent tips" for m in messages)
        assert any("Sure, here are agent tips!" in m["content"] for m in messages)

