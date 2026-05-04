import asyncio
import json
from fastapi import WebSocket

from .agent import AgentRunner
from . import inhibitor


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self, agent: AgentRunner):
        self.connections: list[WebSocket] = []
        self.agent = agent
        # The single active client.  Only one tab/window can use ADE at
        # a time — see connect() for displacement logic.
        self._active_ws: WebSocket | None = None
        # True between the start and end of an agent turn.  Used so a
        # reconnecting client can query whether the "working" indicator
        # should still be shown, even if the final streaming=False
        # message was dropped because the old ws was already gone.
        self._turn_active: bool = False
        # Eval-only connections (tests).  These don't displace the active
        # browser and only receive eval_result messages forwarded from it.
        self._eval_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # ADE allows only one active client at a time.  When a new
        # connection arrives, displace any existing one: tell the old
        # client it was replaced (so it shows a message and stops
        # reconnecting) and close it.  This keeps chat events going to
        # exactly one destination — the active tab — and avoids the
        # cross-session/cross-tab confusion of broadcasting.
        if self._active_ws is not None and self._active_ws is not websocket:
            # Close with a custom application close code (4001) so the
            # client's onclose handler can recognize displacement and
            # stop reconnecting.  Don't rely on a separate "displaced"
            # message because onmessage/onclose ordering isn't reliable
            # when the server sends a frame and closes immediately.
            try:
                await self._active_ws.close(code=4001, reason="displaced")
            except Exception:
                pass
            self.disconnect(self._active_ws)
        self._active_ws = websocket
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)
        if self._active_ws is websocket:
            self._active_ws = None

    async def connect_eval(self, websocket: WebSocket):
        """Connect a test eval client without displacing the active browser."""
        await websocket.accept()
        self._eval_connections.append(websocket)

    def disconnect_eval(self, websocket: WebSocket):
        if websocket in self._eval_connections:
            self._eval_connections.remove(websocket)

    async def broadcast(self, message: str):
        """Send a message to all connected clients, including eval connections."""
        disconnected = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

        eval_disconnected = []
        for ws in self._eval_connections:
            try:
                await ws.send_text(message)
            except Exception:
                eval_disconnected.append(ws)

        for ws in eval_disconnected:
            self.disconnect_eval(ws)

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
        if websocket is None:
            return
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
            asyncio.create_task(self._handle_chat(msg))

        elif msg_type == "restore_agent_session":
            agent_session_id = msg.get("payload", {}).get("agentSessionId")
            if agent_session_id:
                # End any existing process so the next message starts a
                # fresh process with --resume <agent_session_id>.
                # terminate() also clears session_id, so set it after.
                await self.agent.terminate()
                self.agent.session_id = agent_session_id

        elif msg_type == "reset_agent_session":
            await self.agent.terminate()

        elif msg_type == "status_query":
            # Reply only to the asking client so a reconnecting tab can
            # resync its "working" indicator with reality.
            await self.send_to(websocket, json.dumps({
                "type": "status",
                "payload": {"turn_active": self._turn_active},
            }))

        elif msg_type == "eval":
            if websocket in self._eval_connections:
                # eval from test client → relay to the active browser
                if self._active_ws:
                    await self.send_to(self._active_ws, data)
            else:
                # eval from browser → relay to eval clients
                for ws in list(self._eval_connections):
                    await self.send_to(ws, data)

        elif msg_type == "eval_result":
            if websocket not in self._eval_connections:
                # eval_result from browser → relay to all eval clients
                for ws in list(self._eval_connections):
                    await self.send_to(ws, data)
            else:
                # eval_result from eval client → relay to active browser
                if self._active_ws:
                    await self.send_to(self._active_ws, data)

    async def _handle_chat(self, msg: dict):
        """Handle a chat message: dispatch to agent and broadcast response.

        Events are broadcast to ALL connected WebSockets so that:
          - Multiple tabs of the same session see the same updates
          - A reconnecting browser automatically picks up in-flight events
          - There is no shared mutable per-chat state to race on
        Concurrent chats are serialized via _chat_lock so the agent's
        per-turn callbacks aren't clobbered.
        """
        payload = msg.get("payload", {})
        content = payload.get("content", "").strip()
        if not content:
            return

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

        # Callbacks read self._active_ws at call time so that if the
        # browser reconnected (which displaces the old ws and replaces
        # _active_ws), remaining events go to the new connection.
        async def send_active(msg_dict):
            ws = self._active_ws
            if ws is None:
                return
            await self.send_to(ws, json.dumps(msg_dict))

        async def on_text(chunk):
            await send_active({
                "type": "chat",
                "payload": {
                    "role": "assistant",
                    "content": chunk,
                    "streaming": True,
                },
            })

        async def on_tool_use(tool_info):
            await send_active({
                "type": "chat",
                "payload": {
                    "role": "tool_use",
                    "name": tool_info["name"],
                    "input": tool_info["input"],
                },
            })

        async def on_tool_result(result_info):
            await send_active({
                "type": "chat",
                "payload": {
                    "role": "tool_result",
                    "content": result_info["content"],
                },
            })

        async def on_thinking(text):
            await send_active({
                "type": "chat",
                "payload": {
                    "role": "thinking",
                    "content": text,
                },
            })

        async def on_done(result):
            await send_active({
                "type": "chat",
                "payload": {
                    "role": "assistant",
                    "content": "",
                    "streaming": False,
                    "session_id": result.get("session_id"),
                    "cost_usd": result.get("cost_usd"),
                    "duration_ms": result.get("duration_ms"),
                },
            })

        self._turn_active = True
        inhibitor.acquire()
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
            self._turn_active = False
            inhibitor.release()
            # Always send a done signal after agent.run() returns so the
            # UI clears the working indicator even if on_done was lost.
            # The client's finishStreaming() is idempotent.  If the ws
            # is gone this drop is silent — the client's status_query
            # on reconnect is what rescues a stuck indicator in that
            # case.
            try:
                await send_active({
                    "type": "chat",
                    "payload": {
                        "role": "assistant",
                        "content": "",
                        "streaming": False,
                    },
                })
            except Exception:
                pass
