"""AXON Web Interface — lightweight local server connecting the Chat UI to the AXON backend."""

import json
import os
import queue
import threading
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, Dict, Any

from axon.core import Axon


class WebApprovalBridge:
    """Bridges AXON ApprovalManager with the Web UI via request IDs and threading events."""

    def __init__(self, event_stream_queue: Optional[queue.Queue] = None):
        self.pending: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.stream_queue = event_stream_queue

    def prompt(self, tool_name: str, kwargs: dict) -> bool:
        req_id = str(uuid.uuid4())[:8]
        event = threading.Event()
        entry = {
            "id": req_id,
            "tool": tool_name,
            "args": kwargs,
            "event": event,
            "decision": False,
        }
        with self._lock:
            self.pending[req_id] = entry

        # If a live stream queue is connected, notify it immediately
        if self.stream_queue:
            self.stream_queue.put({
                "type": "approval_required",
                "id": req_id,
                "tool": tool_name,
                "args": kwargs,
            })

        # Wait up to 120 seconds for user response from UI
        event.wait(timeout=120)

        with self._lock:
            decision = entry["decision"]
            self.pending.pop(req_id, None)
        return decision

    def resolve(self, req_id: str, approved: bool) -> bool:
        with self._lock:
            entry = self.pending.get(req_id)
            if entry:
                entry["decision"] = approved
                entry["event"].set()
                return True
class ConversationStore:
    """Manages persistent conversation history, active selection, and pinned status."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (Path.home() / ".axon" / "conversations.json")
        self._lock = threading.Lock()
        self.conversations: Dict[str, Dict[str, Any]] = {}
        self.active_id: Optional[str] = None
        self._load()

    def _load(self):
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.conversations = data.get("conversations", {})
                    self.active_id = data.get("active_id", None)
            except Exception:
                self.conversations = {}
                self.active_id = None

        if not self.conversations:
            self._seed_default()
            self._save()

    def _save(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({
                    "conversations": self.conversations,
                    "active_id": self.active_id,
                }, f, indent=2)
        except Exception:
            pass

    def _seed_default(self):
        """Seed initial conversations matching the reference design layout."""
        import time
        now = time.time()
        # 2 Pinned items from screenshot
        # 6 Recents items from screenshot
        items = [
            ("conv-pinned-1", "Build Free AI Agents", True, now - 60),
            ("conv-pinned-2", "Brain Training Games", True, now - 120),
            ("conv-recent-1", "Reasoning token explanation", False, now - 180),
            ("conv-recent-2", "Orry work explained", False, now - 240),
            ("conv-recent-3", "Local AI Automation App", False, now - 300),
            ("conv-recent-4", "Reasonable AI Model", False, now - 360),
            ("conv-recent-5", "J J Thomson Model", False, now - 420),
            ("conv-recent-6", "Atomic And Mass Numbers", False, now - 480),
        ]
        self.conversations = {}
        for cid, title, pinned, updated in items:
            self.conversations[cid] = {
                "id": cid,
                "title": title,
                "pinned": pinned,
                "created_at": updated,
                "updated_at": updated,
                "messages": [
                    {"role": "user", "content": f"Tell me about {title}."},
                    {"role": "assistant", "content": f"Here is an overview of **{title}**.\n\nLet me know what details you would like to explore further!"},
                ],
            }
        self.active_id = "conv-recent-2"  # 'Orry work explained' marked active with blue dot

    def list_conversations(self) -> list:
        with self._lock:
            items = list(self.conversations.values())
            items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
            return items

    def get(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.conversations.get(conv_id)

    def create(self, title: str = "New Chat", pinned: bool = False, messages: Optional[list] = None) -> Dict[str, Any]:
        import time
        with self._lock:
            cid = f"conv-{uuid.uuid4().hex[:8]}"
            now = time.time()
            conv = {
                "id": cid,
                "title": title,
                "pinned": pinned,
                "created_at": now,
                "updated_at": now,
                "messages": messages or [],
            }
            self.conversations[cid] = conv
            self.active_id = cid
            self._save()
            return conv

    def toggle_pin(self, conv_id: str, pinned: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        import time
        with self._lock:
            if conv_id in self.conversations:
                if pinned is None:
                    self.conversations[conv_id]["pinned"] = not self.conversations[conv_id].get("pinned", False)
                else:
                    self.conversations[conv_id]["pinned"] = bool(pinned)
                self.conversations[conv_id]["updated_at"] = time.time()
                self._save()
                return self.conversations[conv_id]
            return None

    def delete(self, conv_id: str) -> bool:
        with self._lock:
            if conv_id in self.conversations:
                del self.conversations[conv_id]
                if self.active_id == conv_id:
                    self.active_id = next(iter(self.conversations.keys())) if self.conversations else None
                self._save()
                return True
            return False

    def set_active(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if conv_id in self.conversations:
                self.active_id = conv_id
                self._save()
                return self.conversations[conv_id]
            return None

    def add_message(self, conv_id: str, role: str, content: str, timestamp: Optional[str] = None) -> Dict[str, Any]:
        import time
        with self._lock:
            if conv_id not in self.conversations:
                now = time.time()
                self.conversations[conv_id] = {
                    "id": conv_id,
                    "title": content[:30] + ("..." if len(content) > 30 else "") if role == "user" else "New Chat",
                    "pinned": False,
                    "created_at": now,
                    "updated_at": now,
                    "messages": [],
                }
            conv = self.conversations[conv_id]
            if conv.get("title") in ("New Chat", "Untitled Chat") and role == "user" and content:
                clean_title = content.strip().split("\n")[0][:36]
                if clean_title:
                    conv["title"] = clean_title
            conv["messages"].append({
                "role": role,
                "content": content,
                "timestamp": timestamp or time.strftime("%I:%M %p"),
            })
            conv["updated_at"] = time.time()
            self.active_id = conv_id
            self._save()
            return conv


def create_web_handler(
    axon: Axon,
    approval_bridge: WebApprovalBridge,
    ui_html_path: Path,
    conversation_store: Optional[ConversationStore] = None,
):
    """Factory creating a BaseHTTPRequestHandler bound to the given Axon instance."""
    conv_store = conversation_store if conversation_store is not None else ConversationStore()


    class AxonWebHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Suppress noisy standard request logging
            pass

        def _send_json(self, data: Any, status: int = 200):
            body = json.dumps(data, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]

            if path in ("/", "/index.html", "/UI.html"):
                if ui_html_path.exists():
                    html_content = ui_html_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html_content)))
                    self.end_headers()
                    self.wfile.write(html_content)
                else:
                    self._send_json({"error": "UI.html not found"}, status=404)
                return

            if path.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp")):
                filename = path.lstrip("/")
                asset_path = ui_html_path.parent / filename
                if not asset_path.exists():
                    asset_path = Path(filename).resolve()
                if not asset_path.exists():
                    asset_path = Path.home() / "Desktop" / filename
                if not asset_path.exists():
                    asset_path = Path(__file__).resolve().parent.parent.parent / filename
                if asset_path.exists() and asset_path.is_file():
                    mime_types = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".svg": "image/svg+xml",
                        ".ico": "image/x-icon",
                        ".webp": "image/webp",
                    }
                    content_type = mime_types.get(asset_path.suffix.lower(), "application/octet-stream")
                    img_data = asset_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(img_data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(img_data)
                    return


            if path == "/api/status":
                workspace = Path.cwd().name
                model = axon.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
                self._send_json({
                    "status": axon.state.status.value,
                    "name": axon.config.get("name", "AXON"),
                    "version": axon.config.get("version", "0.1.0"),
                    "model": model,
                    "workspace": workspace,
                    "tools_count": len(axon.registry.list()),
                })
                return

            if path == "/api/models":
                model = axon.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
                self._send_json({
                    "models": [
                        {
                            "key": "default",
                            "label": "AXON Model",
                            "model": model,
                        }
                    ],
                    "active": "default",
                })
                return

            if path == "/api/history":
                history = [
                    m for m in axon.brain.history
                    if m.get("role") in ("user", "assistant") and m.get("content")
                ]
                self._send_json({"history": history})
                return

            if path == "/api/conversations":
                all_convs = conv_store.list_conversations()
                pinned = [c for c in all_convs if c.get("pinned")]
                recents = [c for c in all_convs if not c.get("pinned")]
                self._send_json({
                    "conversations": all_convs,
                    "pinned": pinned,
                    "recents": recents,
                    "active_id": conv_store.active_id or (all_convs[0]["id"] if all_convs else None),
                })
                return

            if path.startswith("/api/conversations/"):
                cid = path[len("/api/conversations/"):].strip()
                if cid and "/" not in cid:
                    conv = conv_store.get(cid)
                    if conv:
                        self._send_json({"success": True, "conversation": conv})
                    else:
                        self._send_json({"error": "Conversation not found"}, status=404)
                    return

            if path == "/api/tasks":
                tasks = [
                    {"id": t.id, "goal": t.goal, "status": t.status.value}
                    for t in axon.tasks.list()
                ]
                self._send_json({"tasks": tasks})
                return

            if path == "/api/memories":
                memories = [m.to_dict() for m in axon.memory.list()]
                self._send_json({"memories": memories})
                return

            self._send_json({"error": f"Not found: {path}"}, status=404)

        def do_POST(self):
            path = self.path.split("?")[0]

            # Read request body
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len) if content_len > 0 else b"{}"
            try:
                payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                payload = {}

            if path == "/api/reset":
                axon.brain.clear_history()
                if conv_store.active_id:
                    c = conv_store.get(conv_store.active_id)
                    if c:
                        c["messages"] = []
                        conv_store._save()
                self._send_json({"success": True})
                return

            if path == "/api/approve":
                req_id = payload.get("id", "")
                approved = bool(payload.get("approved", False))
                success = approval_bridge.resolve(req_id, approved)
                self._send_json({"success": success})
                return

            if path == "/api/model":
                self._send_json({"success": True})
                return

            if path == "/api/conversations":
                title = payload.get("title", "New Chat")
                pinned = bool(payload.get("pinned", False))
                conv = conv_store.create(title=title, pinned=pinned)
                self._send_json({"success": True, "conversation": conv})
                return

            if path == "/api/conversations/active":
                cid = payload.get("id", "")
                conv = conv_store.set_active(cid)
                if conv:
                    axon.brain.clear_history()
                    for msg in conv.get("messages", []):
                        if msg.get("role") in ("user", "assistant") and msg.get("content"):
                            axon.brain.history.append({"role": msg["role"], "content": msg["content"]})
                    self._send_json({"success": True, "conversation": conv})
                else:
                    self._send_json({"error": "Conversation not found"}, status=404)
                return

            if path.startswith("/api/conversations/") and path.endswith("/pin"):
                cid = path[len("/api/conversations/"): -4].strip()
                pinned_val = payload.get("pinned")
                conv = conv_store.toggle_pin(cid, pinned_val)
                if conv:
                    self._send_json({"success": True, "conversation": conv})
                else:
                    self._send_json({"error": "Conversation not found"}, status=404)
                return

            if path.startswith("/api/conversations/") and path.endswith("/delete"):
                cid = path[len("/api/conversations/"): -7].strip()
                success = conv_store.delete(cid)
                self._send_json({"success": success, "active_id": conv_store.active_id})
                return

            if path == "/api/chat":
                message = payload.get("message", "").strip()
                if not message:
                    self._send_json({"error": "Empty message"}, status=400)
                    return

                # Record user message in conversation store
                cid = payload.get("conversation_id") or conv_store.active_id
                if not cid or not conv_store.get(cid):
                    new_c = conv_store.create(title="New Chat")
                    cid = new_c["id"]
                conv_store.add_message(cid, "user", message)

                # Check if non-streaming is requested
                stream_mode = payload.get("stream", True)

                if not stream_mode:
                    tools_used = []
                    def track_event(e):
                        if e.name in ("AI_TOOL_REQUESTED", "STEP_STARTED", "TASK_STEP_STARTED"):
                            tool_name = e.data.get("tool", "")
                            tools_used.append({"name": tool_name, "status": "running"})
                        elif e.name in ("AI_TOOL_COMPLETED", "STEP_COMPLETED", "TASK_STEP_COMPLETED"):
                            tool_name = e.data.get("tool", "")
                            for t in tools_used:
                                if not tool_name or t["name"] == tool_name:
                                    t["status"] = "completed"

                    axon.events.on("AI_TOOL_REQUESTED", track_event)
                    axon.events.on("AI_TOOL_COMPLETED", track_event)
                    axon.events.on("STEP_STARTED", track_event)
                    axon.events.on("STEP_COMPLETED", track_event)
                    try:
                        resp = axon.brain.process(message)
                        conv_store.add_message(cid, "assistant", resp)
                        self._send_json({
                            "success": True,
                            "response": resp,
                            "tools": tools_used,
                            "conversation_id": cid,
                        })
                    finally:
                        axon.events.off("AI_TOOL_REQUESTED", track_event)
                        axon.events.off("AI_TOOL_COMPLETED", track_event)
                        axon.events.off("STEP_STARTED", track_event)
                        axon.events.off("STEP_COMPLETED", track_event)
                    return

                # Streaming mode: stream line-delimited JSON events
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                event_queue: queue.Queue = queue.Queue()
                tools_used = []
                approval_bridge.stream_queue = event_queue

                def stream_event(data: dict):
                    try:
                        line = json.dumps(data, default=str) + "\n"
                        self.wfile.write(line.encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass

                def on_event(e):
                    if e.name == "AI_REQUEST_STARTED":
                        event_queue.put({"type": "status", "text": "Thinking..."})
                    elif e.name in ("STEP_STARTED", "TASK_STEP_STARTED"):
                        tool_name = e.data.get("tool", "")
                        desc = e.data.get("description", "")
                        tools_used.append({"name": tool_name or desc, "status": "running"})
                        event_queue.put({"type": "status", "text": f"Step: {desc or tool_name}"})
                        event_queue.put({"type": "tool_start", "tool": tool_name or desc})
                    elif e.name in ("STEP_COMPLETED", "TASK_STEP_COMPLETED"):
                        tool_name = e.data.get("tool", "")
                        for t in tools_used:
                            if not tool_name or t["name"] == tool_name:
                                t["status"] = "completed"
                        event_queue.put({"type": "tool_done", "tool": tool_name or "step"})
                    elif e.name == "AI_TOOL_REQUESTED":
                        tool_name = e.data.get("tool", "")
                        tools_used.append({"name": tool_name, "status": "running"})
                        event_queue.put({"type": "tool_start", "tool": tool_name})
                    elif e.name == "AI_TOOL_COMPLETED":
                        tool_name = e.data.get("tool", "")
                        for t in tools_used:
                            if t["name"] == tool_name:
                                t["status"] = "completed"
                        event_queue.put({"type": "tool_done", "tool": tool_name})
                    elif e.name == "PROJECT_ANALYZED":
                        summary = e.data.get("summary", "")
                        if summary:
                            event_queue.put({"type": "status", "text": f"Project: {summary}"})

                axon.events.on("AI_REQUEST_STARTED", on_event)
                axon.events.on("PROJECT_ANALYZED", on_event)
                axon.events.on("AI_TOOL_REQUESTED", on_event)
                axon.events.on("AI_TOOL_COMPLETED", on_event)
                axon.events.on("STEP_STARTED", on_event)
                axon.events.on("STEP_COMPLETED", on_event)

                # Send initial thinking status
                stream_event({"type": "status", "text": "Thinking..."})

                response_container = []
                error_container = []

                def run_ai():
                    try:
                        res = axon.brain.process(message)
                        response_container.append(res)
                    except Exception as exc:
                        error_container.append(str(exc))
                    finally:
                        event_queue.put(None)  # Sentinel to finish

                ai_thread = threading.Thread(target=run_ai, daemon=True)
                ai_thread.start()

                # Consume event queue and stream to client
                while True:
                    try:
                        item = event_queue.get(timeout=0.2)
                    except queue.Empty:
                        if not ai_thread.is_alive():
                            break
                        continue

                    if item is None:
                        break
                    stream_event(item)

                ai_thread.join(timeout=120)
                axon.events.off("AI_REQUEST_STARTED", on_event)
                axon.events.off("AI_TOOL_REQUESTED", on_event)
                axon.events.off("AI_TOOL_COMPLETED", on_event)
                axon.events.off("STEP_STARTED", on_event)
                axon.events.off("STEP_COMPLETED", on_event)
                approval_bridge.stream_queue = None

                if error_container:
                    stream_event({"type": "error", "error": error_container[0]})
                else:
                    final_text = response_container[0] if response_container else ""
                    if final_text:
                        conv_store.add_message(cid, "assistant", final_text)
                    stream_event({
                        "type": "done",
                        "response": final_text,
                        "tools": tools_used,
                        "conversation_id": cid,
                    })
                return

            self._send_json({"error": f"Not found: {path}"}, status=404)

    return AxonWebHandler


class AxonWebServer:
    def __init__(
        self,
        axon: Optional[Axon] = None,
        host: str = "127.0.0.1",
        port: int = 8080,
        conversation_store: Optional[ConversationStore] = None,
    ):
        self.axon = axon or Axon().start()
        self.host = host
        self.port = port
        self.conversation_store = conversation_store if conversation_store is not None else ConversationStore()
        self.ui_path = Path("UI.html").resolve()
        if not self.ui_path.exists():
            # Fallback relative to repository root
            repo_ui = Path(__file__).resolve().parent.parent.parent / "UI.html"
            if repo_ui.exists():
                self.ui_path = repo_ui

        self.approval_bridge = WebApprovalBridge()
        self.axon.approval.set_prompt(self.approval_bridge.prompt)

        handler_cls = create_web_handler(
            self.axon,
            self.approval_bridge,
            self.ui_path,
            conversation_store=self.conversation_store,
        )
        self.server = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self._thread: Optional[threading.Thread] = None

    def start(self, background: bool = False):
        if background:
            self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self._thread.start()
        else:
            try:
                self.server.serve_forever()
            except KeyboardInterrupt:
                self.stop()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def run_web(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True):
    """Start the AXON Web Interface."""
    import subprocess
    import sys
    
    axon = Axon().start()
    web_server = AxonWebServer(axon=axon, host=host, port=port)
    url = f"http://{host}:{port}"
    print(f"\n  AXON Web UI running at: {url}")
    print("  Press Ctrl+C to stop.\n")

    osiris_dir = Path(__file__).resolve().parent.parent.parent / "osiris"
    osiris_proc = None
    if osiris_dir.exists():
        print("  Starting OSIRIS (Know the World) on port 3001...")
        cmd = ["npm.cmd", "run", "start"] if sys.platform == "win32" else ["npm", "run", "start"]
        osiris_proc = subprocess.Popen(
            cmd,
            cwd=str(osiris_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False
        )

    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        web_server.start(background=False)
    except KeyboardInterrupt:
        print("\nAXON Web UI stopped.")
        axon.shutdown()
        if osiris_proc:
            osiris_proc.terminate()
