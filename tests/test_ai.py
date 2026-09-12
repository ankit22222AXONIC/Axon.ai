"""AXON AI Brain tests — mocks OpenRouter API to verify agent behavior."""

import pytest
from axon.ai.client import OpenRouterClient, AIClientError
from axon.ai.brain import Brain
from axon.ai.schema import tool_registry_to_schemas
from axon.tools import ToolRegistry
from axon.security import SecurityManager, Permission, ApprovalManager
from axon.events import EventBus
from axon.router import Router


def _make_mock_client(responses, api_key="test_key", model="test_model"):
    """Helper: create an OpenRouterClient with queued canned responses."""
    resp_queue = list(responses)

    def mock_transport(payload):
        if not resp_queue:
            raise AIClientError("No more mock responses queued.")
        resp = resp_queue.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    return OpenRouterClient(
        api_key=api_key,
        model=model,
        transport_fn=mock_transport,
    )


def _make_brain(mock_responses, prompt_fn=None):
    """Helper: create a fully wired Brain with mocked OpenRouter client."""
    client = _make_mock_client(mock_responses)
    reg = ToolRegistry()
    reg.register("safe.greet", lambda name="world": f"Hello, {name}!", "Greet someone")
    reg.register("risky.action", lambda target="": f"Modified {target}", "Risky action")

    sec = SecurityManager()
    sec.set_permission("safe.greet", Permission.ALLOWED)
    sec.set_permission("risky.action", Permission.APPROVAL_REQUIRED)

    events = EventBus()
    approval = ApprovalManager(events, prompt_fn=prompt_fn)
    router = Router(reg, sec, events, approval)

    brain = Brain(
        client=client,
        router=router,
        registry=reg,
        event_bus=events,
    )
    return brain, router, events


# --- Missing API Key ---

def test_missing_api_key_raises_error():
    client = OpenRouterClient(api_key="")
    reg = ToolRegistry()
    sec = SecurityManager()
    events = EventBus()
    router = Router(reg, sec, events)
    brain = Brain(client=client, router=router, registry=reg, event_bus=events)

    response = brain.process("Hello AXON")
    assert "[AXON Error]" in response
    assert "OPENROUTER_API_KEY" in response


# --- Basic Response (No tools) ---

def test_basic_response():
    mock_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Hello! I am AXON, how can I help you?",
            }
        }]
    }
    brain, _, _ = _make_brain([mock_resp])

    result = brain.process("Hello")
    assert result == "Hello! I am AXON, how can I help you?"
    assert len(brain.history) == 3  # system, user, assistant
    assert brain.history[-1]["content"] == "Hello! I am AXON, how can I help you?"


# --- Tool Call & Tool Result Sent Back ---

def test_tool_call_execution_and_result_flow():
    # Round 1: Model requests safe.greet tool
    round1_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_greet_1",
                    "type": "function",
                    "function": {
                        "name": "safe.greet",
                        "arguments": '{"name": "Ankit"}',
                    },
                }],
            }
        }]
    }
    # Round 2: Model receives tool output and gives final response
    round2_resp = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "I greeted Ankit successfully!",
            }
        }]
    }

    brain, router, _ = _make_brain([round1_resp, round2_resp])
    final_output = brain.process("Say hi to Ankit")

    assert final_output == "I greeted Ankit successfully!"

    # Verify history contains tool execution result
    tool_msg = next((m for m in brain.history if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert tool_msg["tool_call_id"] == "call_greet_1"
    assert tool_msg["name"] == "safe.greet"
    assert "Hello, Ankit!" in tool_msg["content"]


# --- Multiple Tool Rounds ---

def test_multiple_tool_rounds():
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "safe.greet", "arguments": '{"name": "Step 1"}'},
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "safe.greet", "arguments": '{"name": "Step 2"}'},
                }],
            }
        }]
    }
    round3 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "All 2 greeting steps completed.",
            }
        }]
    }

    brain, _, _ = _make_brain([round1, round2, round3])
    output = brain.process("Execute 2 steps")
    assert output == "All 2 greeting steps completed."

    tool_msgs = [m for m in brain.history if m["role"] == "tool"]
    assert len(tool_msgs) == 2


# --- Unknown Tool Request Handled Safely ---

def test_unknown_tool_handled_safely():
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_unknown",
                    "type": "function",
                    "function": {"name": "nonexistent.tool", "arguments": "{}"},
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "That tool does not exist.",
            }
        }]
    }

    brain, _, _ = _make_brain([round1, round2])
    output = brain.process("Run mysterious tool")
    assert output == "That tool does not exist."

    tool_msg = next((m for m in brain.history if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert "Unknown tool" in tool_msg["content"]


# --- Malformed Tool Arguments Handled ---

def test_invalid_arguments_handled_safely():
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_bad_json",
                    "type": "function",
                    "function": {"name": "safe.greet", "arguments": "NOT_VALID_JSON{}"},
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Tool call failed due to bad arguments.",
            }
        }]
    }

    brain, _, _ = _make_brain([round1, round2])
    output = brain.process("Trigger broken json")
    assert output == "Tool call failed due to bad arguments."

    tool_msg = next((m for m in brain.history if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert "Invalid arguments format" in tool_msg["content"]


# --- Approval Denial Enforced on AI ---

def test_approval_denied_for_ai_tool_call():
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_risky",
                    "type": "function",
                    "function": {"name": "risky.action", "arguments": '{"target": "system"}'},
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "The user denied the risky action, so I stopped.",
            }
        }]
    }

    # prompt_fn returns False -> user denies approval
    brain, _, _ = _make_brain([round1, round2], prompt_fn=lambda name, kwargs: False)
    output = brain.process("Do something risky")
    assert "denied" in output.lower()

    tool_msg = next((m for m in brain.history if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert "Approval denied" in tool_msg["content"]


# --- Approval Granted Allows AI Tool Call ---

def test_approval_granted_for_ai_tool_call():
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_risky",
                    "type": "function",
                    "function": {"name": "risky.action", "arguments": '{"target": "config"}'},
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Risky action approved and completed.",
            }
        }]
    }

    # prompt_fn returns True -> user approves
    brain, _, _ = _make_brain([round1, round2], prompt_fn=lambda name, kwargs: True)
    output = brain.process("Modify config")
    assert output == "Risky action approved and completed."

    tool_msg = next((m for m in brain.history if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert "Modified config" in tool_msg["content"]


# --- API Failure / Network Error Handling ---

def test_api_network_failure_handled():
    mock_err = AIClientError("Network error connecting to OpenRouter: Connection refused")
    brain, _, events = _make_brain([mock_err])

    events_logged = []
    events.on("AI_ERROR", lambda e: events_logged.append(e.data))

    output = brain.process("Hello?")
    assert "[AXON Error]" in output
    assert "Network error" in output
    assert len(events_logged) == 1


# --- Events Emitted ---

def test_ai_events_emitted():
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "safe.greet", "arguments": '{"name": "World"}'},
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Done greeting.",
            }
        }]
    }

    brain, _, events = _make_brain([round1, round2])
    event_names = []
    events.on("AI_REQUEST_STARTED", lambda e: event_names.append(e.name))
    events.on("AI_RESPONSE_RECEIVED", lambda e: event_names.append(e.name))
    events.on("AI_TOOL_REQUESTED", lambda e: event_names.append(e.name))
    events.on("AI_TOOL_COMPLETED", lambda e: event_names.append(e.name))

    brain.process("Greet world")

    assert "AI_REQUEST_STARTED" in event_names
    assert "AI_RESPONSE_RECEIVED" in event_names
    assert "AI_TOOL_REQUESTED" in event_names
    assert "AI_TOOL_COMPLETED" in event_names


# --- Schema Generation ---

def test_tool_registry_to_schemas():
    reg = ToolRegistry()
    def demo_tool(path: str, count: int = 10):
        """Demo description."""
        pass

    reg.register("demo.test", demo_tool, "A demo tool")
    schemas = tool_registry_to_schemas(reg)

    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "demo__test"
    assert s["function"]["description"] == "A demo tool"

    params = s["function"]["parameters"]
    assert "path" in params["properties"]
    assert params["properties"]["path"]["type"] == "string"
    assert "count" in params["properties"]
    assert params["properties"]["count"]["type"] == "integer"
    assert params["properties"]["count"]["default"] == 10
    assert params["required"] == ["path"]


# --- Integration with Runtime Memory & Task Tools ---

def test_ai_uses_runtime_memory_tools(tmp_path):
    from axon.core import Axon

    db_path = str(tmp_path / "ai_mem.db")
    from axon.memory import MemoryStore
    axon = Axon()
    axon.memory = MemoryStore(db_path, axon.events)
    axon.start()

    # Mock model storing memory then responding
    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "mem_call_1",
                    "type": "function",
                    "function": {
                        "name": "memory.store",
                        "arguments": '{"content": "User prefers tabs over spaces", "category": "preference"}',
                    },
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "I remembered your preference for tabs!",
            }
        }]
    }

    axon.ai_client._api_key = "test_key"
    axon.ai_client._transport_fn = _make_mock_client([round1, round2])._transport_fn

    response = axon.brain.process("Remember that I prefer tabs over spaces")
    assert response == "I remembered your preference for tabs!"

    # Verify directly in memory store
    stored = axon.memory.search("tabs")
    assert len(stored) == 1
    assert stored[0].content == "User prefers tabs over spaces"

    axon.shutdown()


def test_ai_uses_runtime_task_tools():
    from axon.core import Axon

    axon = Axon()
    axon.start()

    round1 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "task_call_1",
                    "type": "function",
                    "function": {
                        "name": "task.create",
                        "arguments": '{"goal": "Organize Downloads folder"}',
                    },
                }],
            }
        }]
    }
    round2 = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Created task to organize Downloads.",
            }
        }]
    }

    axon.ai_client._api_key = "test_key"
    axon.ai_client._transport_fn = _make_mock_client([round1, round2])._transport_fn

    response = axon.brain.process("Create a task to organize Downloads")
    assert response == "Created task to organize Downloads."

    tasks = axon.tasks.list()
    assert len(tasks) == 1
    assert tasks[0].goal == "Organize Downloads folder"

    axon.shutdown()


def test_brain_clear_history():
    mock_resp = {
        "choices": [{"message": {"role": "assistant", "content": "Sure!"}}]
    }
    brain, _, _ = _make_brain([mock_resp])
    brain.process("First message")
    assert len(brain.history) == 3

    brain.clear_history()
    assert len(brain.history) == 1
    assert brain.history[0]["role"] == "system"


def test_brain_handles_error_response():
    """Verify that in-band errors from AI responses are surfaced clearly rather than masked."""
    error_resp = {
        "error": {
            "message": "Upstream error from Nvidia: Service temporarily overloaded",
            "code": 502,
        }
    }
    brain, _, _ = _make_brain([error_resp])
    res = brain.process("Hello")
    assert "[AXON Error]" in res
    assert "Upstream error from Nvidia: Service temporarily overloaded" in res
    assert "Empty response" not in res


def test_openrouter_client_retry_on_transient_error(monkeypatch):
    """Verify that OpenRouterClient retries on transient errors and succeeds when an attempt resolves."""
    import json
    import unittest.mock
    from axon.ai.client import OpenRouterClient

    client = OpenRouterClient(api_key="test_key")
    call_count = 0

    class MockHttpResp:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data.encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=30):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockHttpResp(json.dumps({
                "error": {"message": "Service temporarily overloaded", "code": 502}
            }))
        return MockHttpResp(json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "Success after retry!"}}]
        }))

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    res = client._send_request({"messages": []})
    assert call_count == 2
    assert res["choices"][0]["message"]["content"] == "Success after retry!"
