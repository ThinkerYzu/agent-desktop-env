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

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

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

        # Send streaming chunks back to the client
        async def on_text(chunk):
            await self.send_to(websocket, json.dumps({
                "type": "chat",
                "payload": {
                    "role": "assistant",
                    "content": chunk,
                    "streaming": True,
                },
            }))

        async def on_done(result):
            await self.send_to(websocket, json.dumps({
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

        await self.agent.run(content, on_text=on_text, on_done=on_done)
