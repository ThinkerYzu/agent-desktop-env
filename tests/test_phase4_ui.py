"""
Phase 4 UI tests: Chat panel rendering and interaction via eval channel.

Uses a persistent WebSocket connection so eval_result messages
are received on the same connection that sent the eval request.

Prerequisites:
    - Server running: ./run.sh &
    - Browser tab open at http://localhost:9800
    - Claude Code CLI available in PATH

Run:
    source venv/bin/activate && python -m pytest tests/test_phase4_ui.py -v
"""

import asyncio
import json
import time
import uuid
from pathlib import Path

import pytest
import websockets

WS_URL = "ws://127.0.0.1:9800/ws"
PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"


class EvalClient:
    """Persistent WebSocket client for eval channel communication."""

    def __init__(self):
        self.ws = None
        self.loop = asyncio.new_event_loop()

    def connect(self):
        self.ws = self.loop.run_until_complete(websockets.connect(WS_URL))

    def close(self):
        if self.ws:
            self.loop.run_until_complete(self.ws.close())
        self.loop.close()

    def eval_js(self, code, timeout=5.0):
        return self.loop.run_until_complete(self._eval(code, timeout))

    async def _eval(self, code, timeout):
        eval_id = str(uuid.uuid4())
        await self.ws.send(json.dumps({
            "type": "eval",
            "id": eval_id,
            "payload": {"code": code},
        }))
        deadline = self.loop.time() + timeout
        while True:
            remaining = deadline - self.loop.time()
            if remaining <= 0:
                raise TimeoutError(f"No eval_result for id={eval_id}")
            msg = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            data = json.loads(msg)
            if data.get("type") == "eval_result" and data.get("id") == eval_id:
                payload = data["payload"]
                if payload.get("error"):
                    raise RuntimeError(f"Browser eval error: {payload['error']}")
                return payload.get("result")


@pytest.fixture(scope="module")
def client():
    c = EvalClient()
    c.connect()
    yield c
    c.close()


def clear_chat(client):
    client.eval_js("""
      (function() {
        document.getElementById('chat-messages').innerHTML = '';
        document.getElementById('chat-input').disabled = false;
        document.getElementById('chat-send').disabled = false;
        document.getElementById('chat-input').value = '';
      })()
    """)


def send_chat(client, text):
    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    client.eval_js(f"""
      (function() {{
        var input = document.getElementById('chat-input');
        input.value = '{escaped}';
        document.getElementById('chat-send').click();
      }})()
    """)


def wait_for_response(client, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        disabled = client.eval_js("document.getElementById('chat-input').disabled")
        if disabled == "false":
            return
        time.sleep(1)
    raise TimeoutError("Agent response did not complete")


def get_message_count(client):
    return int(client.eval_js("document.querySelectorAll('.chat-message').length"))


def get_last_agent_text(client):
    return client.eval_js("""
      (function() {
        var msgs = document.querySelectorAll('.chat-message-assistant .chat-content');
        if (msgs.length === 0) return '';
        return msgs[msgs.length - 1].textContent;
      })()
    """)


def get_last_agent_html(client):
    return client.eval_js("""
      (function() {
        var msgs = document.querySelectorAll('.chat-message-assistant .chat-content');
        if (msgs.length === 0) return '';
        return msgs[msgs.length - 1].innerHTML;
      })()
    """)


def get_all_roles(client):
    return client.eval_js("""
      (function() {
        var roles = document.querySelectorAll('.chat-role');
        var r = [];
        roles.forEach(function(el) { r.push(el.textContent); });
        return r.join(',');
      })()
    """)


# ── Tests ──


class TestChatRendering:

    def test_user_message_appears(self, client):
        """Sending a message shows it in the chat panel."""
        clear_chat(client)
        send_chat(client, "say pong")
        time.sleep(0.5)
        count = get_message_count(client)
        assert count >= 1
        roles = get_all_roles(client)
        assert "You" in roles
        wait_for_response(client)  # Let it finish before next test

    def test_agent_response_appears(self, client):
        """Agent response appears after sending a message."""
        clear_chat(client)
        send_chat(client, "say just the word pong")
        wait_for_response(client)
        text = get_last_agent_text(client).lower()
        assert "pong" in text

    def test_input_re_enabled_after_response(self, client):
        """Input is re-enabled after the agent finishes responding."""
        clear_chat(client)
        send_chat(client, "say ok")
        wait_for_response(client)
        disabled = client.eval_js("document.getElementById('chat-input').disabled")
        assert disabled == "false"

    def test_message_order(self, client):
        """Messages appear in order: user, agent, user, agent."""
        clear_chat(client)
        send_chat(client, "say alpha")
        wait_for_response(client)
        send_chat(client, "say beta")
        wait_for_response(client)
        roles = get_all_roles(client)
        parts = roles.split(",")
        assert len(parts) >= 4
        assert parts[0] == "You"
        assert parts[1] == "Agent"
        assert parts[2] == "You"
        assert parts[3] == "Agent"

    def test_agent_response_has_html(self, client):
        """Agent response is rendered as HTML (not plain text)."""
        clear_chat(client)
        send_chat(client, "say hello")
        wait_for_response(client)
        html = get_last_agent_html(client)
        # Even a simple response gets wrapped in <p> by marked.js
        assert "<" in html, f"Expected HTML tags in response, got: {html}"

    def test_tool_use_rendered_in_chat(self, client):
        """A prompt triggering tool use shows tool blocks in the chat panel."""
        clear_chat(client)
        send_chat(client, "list files in the current directory using ls")
        wait_for_response(client, timeout=60)
        tool_count = int(client.eval_js(
            "document.querySelectorAll('.chat-tool-use').length"
        ))
        assert tool_count >= 1, "Expected at least one .chat-tool-use block"
        # Verify it has a tool name
        tool_name = client.eval_js("""
          (function() {
            var el = document.querySelector('.chat-tool-name');
            return el ? el.textContent : '';
          })()
        """)
        assert len(tool_name) > 0, "Tool use block should have a tool name"
