import asyncio
import json
from fastapi import WebSocket

from .agent import AgentRunner


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self, agent: AgentRunner):
        self.connections: list[WebSocket] = []
        self.agent = agent
        self._chat_task: asyncio.Task | None = None
        self._chat_ws: WebSocket | None = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)
        # If the previous chat websocket is gone (browser reconnected),
        # migrate the active _handle_chat to use this new connection so
        # remaining messages (including on_done) reach the client.
        if self._chat_ws is not None and self._chat_ws not in self.connections:
            self._chat_ws = websocket

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, message: str):
        """Send a message to all connected clients."""
        disconnected = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    async def send_to_others(self, sender: WebSocket, message: str):
        """Send a message to all clients except the sender."""
        disconnected = []
        for ws in self.connections:
            if ws is sender:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, message: str):
        """Send a message to a specific client."""
        try:
            await websocket.send_text(message)
        except Exception:
            self.disconnect(websocket)

    async def handle_message(self, websocket: WebSocket, data: str):
        """Handle an incoming message from a client."""
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "chat":
            # Run agent in background so the WebSocket loop stays responsive
            self._chat_task = asyncio.create_task(self._handle_chat(websocket, msg))

        elif msg_type == "restore_agent_session":
            agent_session_id = msg.get("payload", {}).get("agentSessionId")
            if agent_session_id:
                self.agent.session_id = agent_session_id

        elif msg_type == "reset_agent_session":
            self.agent.session_id = None

        elif msg_type == "eval":
            await self.send_to_others(websocket, data)

        elif msg_type == "eval_result":
            await self.send_to_others(websocket, data)

    async def _handle_chat(self, websocket: WebSocket, msg: dict):
        """Handle a chat message: dispatch to agent and stream response."""
        payload = msg.get("payload", {})
        content = payload.get("content", "").strip()
        if not content:
            return

        # Track the active chat websocket so it can be migrated on
        # reconnection (see connect()).
        self._chat_ws = websocket

        # Build prompt with annotation context if present
        annotation = payload.get("annotation")
        prompt = content
        if annotation:
            file_path = annotation.get("file", "")
            selected = annotation.get("selectedText", "")
            start = annotation.get("startLine")
            end = annotation.get("endLine")
            line_info = ""
            if start:
                line_info = f" (lines {start}"
                if end and end != start:
                    line_info += f"-{end}"
                line_info += ")"

            prompt = (
                f"[The user selected text from {file_path}{line_info}:\n"
                f"```\n{selected}\n```\n]\n\n{content}"
            )

        # Callbacks use self._chat_ws (not the captured `websocket`)
        # so that if the browser reconnects mid-response, remaining
        # messages are delivered to the new connection.
        async def on_text(chunk):
            await self.send_to(self._chat_ws, json.dumps({
                "type": "chat",
                "payload": {
                    "role": "assistant",
                    "content": chunk,
                    "streaming": True,
                },
            }))

        async def on_tool_use(tool_info):
            await self.send_to(self._chat_ws, json.dumps({
                "type": "chat",
                "payload": {
                    "role": "tool_use",
                    "name": tool_info["name"],
                    "input": tool_info["input"],
                },
            }))

        async def on_tool_result(result_info):
            await self.send_to(self._chat_ws, json.dumps({
                "type": "chat",
                "payload": {
                    "role": "tool_result",
                    "content": result_info["content"],
                },
            }))

        async def on_thinking(text):
            await self.send_to(self._chat_ws, json.dumps({
                "type": "chat",
                "payload": {
                    "role": "thinking",
                    "content": text,
                },
            }))

        async def on_done(result):
            await self.send_to(self._chat_ws, json.dumps({
                "type": "chat",
                "payload": {
                    "role": "assistant",
                    "content": "",
                    "streaming": False,
                    "session_id": result.get("session_id"),
                    "cost_usd": result.get("cost_usd"),
                    "duration_ms": result.get("duration_ms"),
                },
            }))

        try:
            await self.agent.run(
                prompt,
                on_text=on_text,
                on_done=on_done,
                on_tool_use=on_tool_use,
                on_tool_result=on_tool_result,
                on_thinking=on_thinking,
            )
        except Exception:
            pass
        finally:
            # Always send a done signal after agent.run() returns,
            # regardless of whether on_done was already called.
            # This guarantees the UI clears the working indicator
            # even if the earlier on_done send was silently lost.
            # The client's finishStreaming() is idempotent.
            ws = self._chat_ws or websocket
            self._chat_ws = None
            try:
                await self.send_to(ws, json.dumps({
                    "type": "chat",
                    "payload": {
                        "role": "assistant",
                        "content": "",
                        "streaming": False,
                    },
                }))
            except Exception:
                pass
