import json
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self.connections: list[WebSocket] = []

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

    async def handle_message(self, websocket: WebSocket, data: str):
        """Handle an incoming message from a client."""
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "chat":
            # Phase 4: will dispatch to agent
            pass

        elif msg_type == "eval":
            # Relay eval request to all other clients (browser)
            await self.send_to_others(websocket, data)

        elif msg_type == "eval_result":
            # Relay eval result to all other clients (test runner)
            await self.send_to_others(websocket, data)
