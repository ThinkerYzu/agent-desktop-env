"""
Phase 5 UI tests: Annotation and session persistence via eval channel.

Prerequisites:
    - Server running: ./run.sh &
    - Browser tab open at http://localhost:9800

Run:
    source venv/bin/activate && python -m pytest tests/test_phase5_ui.py -v
"""

import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx
import pytest
import websockets

WS_URL = "ws://127.0.0.1:9800/ws"
BASE_URL = "http://127.0.0.1:9800"
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


class EvalClient:
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


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=BASE_URL) as c:
        yield c


def clear_chat(client):
    client.eval_js("""
      (function() {
        document.getElementById('chat-messages').innerHTML = '';
        document.getElementById('chat-input').disabled = false;
        document.getElementById('chat-send').disabled = false;
        document.getElementById('chat-input').value = '';
      })()
    """)


def open_file(client, path):
    result = client.eval_js(f"""
      (function() {{
        var labels = document.querySelectorAll('.tree-label');
        for (var i = 0; i < labels.length; i++) {{
          if (labels[i].dataset.path === '{path}') {{
            labels[i].click();
            return 'opened';
          }}
        }}
        return 'not found';
      }})()
    """)
    assert "opened" in result
    time.sleep(0.5)


# ── Annotation Tests ──


class TestAnnotation:

    def test_annotation_badge_appears_on_selection(self, client):
        """Selecting text in the document panel shows an annotation badge."""
        # Dismiss session picker if showing
        client.eval_js("""
          (function() {
            var picker = document.getElementById('session-picker');
            if (picker && picker.style.display !== 'none') {
              document.getElementById('session-new').click();
            }
          })()
        """)
        time.sleep(0.5)

        open_file(client, "SPEC.md")

        # Simulate text selection by calling DocPanel's internal logic
        client.eval_js("""
          (function() {
            if (window.Chat && window.Chat.setAnnotation) {
              window.Chat.setAnnotation({
                file: 'SPEC.md',
                selectedText: 'This is a test selection',
                startLine: 5,
                endLine: 5,
              });
            }
          })()
        """)

        badge = client.eval_js("""
          (function() {
            var badge = document.querySelector('.annotation-badge');
            if (!badge || badge.style.display === 'none') return 'hidden';
            return badge.textContent;
          })()
        """)
        assert "SPEC.md" in badge
        assert "test selection" in badge

    def test_annotation_badge_dismissed(self, client):
        """Clicking close on the annotation badge removes it."""
        # Set an annotation
        client.eval_js("""
          (function() {
            window.Chat.setAnnotation({
              file: 'SPEC.md',
              selectedText: 'dismiss me',
              startLine: 1,
              endLine: 1,
            });
          })()
        """)

        # Click close
        client.eval_js("""
          (function() {
            var close = document.querySelector('.annotation-badge-close');
            if (close) close.click();
          })()
        """)

        badge = client.eval_js("""
          (function() {
            var badge = document.querySelector('.annotation-badge');
            return (!badge || badge.style.display === 'none') ? 'hidden' : 'visible';
          })()
        """)
        assert badge == "hidden"

    def test_annotation_shown_in_user_message(self, client):
        """When annotation is set and user sends a message, it shows in the chat."""
        clear_chat(client)

        # Set annotation
        client.eval_js("""
          (function() {
            window.Chat.setAnnotation({
              file: 'DESIGN.md',
              selectedText: 'annotated content here',
              startLine: 10,
              endLine: 12,
            });
          })()
        """)

        # Send a message
        client.eval_js("""
          (function() {
            document.getElementById('chat-input').value = 'explain this section';
            document.getElementById('chat-send').click();
          })()
        """)
        time.sleep(0.5)

        # Check that annotation context appears in the chat
        html = client.eval_js("""
          (function() {
            var anno = document.querySelector('.chat-annotation');
            return anno ? anno.innerHTML : 'not found';
          })()
        """)
        assert "DESIGN.md" in html
        assert "annotated content" in html

    def test_annotation_cleared_after_send(self, client):
        """Annotation badge is cleared after sending a message."""
        # Wait for any pending response
        time.sleep(1)

        badge = client.eval_js("""
          (function() {
            var badge = document.querySelector('.annotation-badge');
            return (!badge || badge.style.display === 'none') ? 'hidden' : 'visible';
          })()
        """)
        assert badge == "hidden"


# ── Session Picker UI Tests ──


class TestSessionPicker:

    def test_session_picker_shows_on_load_with_sessions(self, client, http):
        """Session picker appears when there are existing sessions."""
        # Create a session so there's something to show
        s = http.post("/api/sessions").json()
        http.post(f"/api/sessions/{s['id']}/messages",
                  json={"role": "user", "content": "picker test"})

        try:
            # Reload page
            client.eval_js("location.reload()")
            time.sleep(1.5)
            # Re-establish eval (need new connection since page reloaded)
            # Actually the persistent connection should still work since
            # the eval goes through server relay

            visible = client.eval_js("""
              (function() {
                var picker = document.getElementById('session-picker');
                return picker && picker.style.display !== 'none' ? 'visible' : 'hidden';
              })()
            """)
            assert visible == "visible"

            # Verify the session is listed
            items = client.eval_js("""
              (function() {
                var items = document.querySelectorAll('.session-item-preview');
                var texts = [];
                items.forEach(function(el) { texts.push(el.textContent); });
                return texts.join('|');
              })()
            """)
            assert "picker test" in items
        finally:
            (SESSIONS_DIR / f"{s['id']}.json").unlink(missing_ok=True)

    def test_new_session_button_dismisses_picker(self, client):
        """Clicking New Session dismisses the picker."""
        client.eval_js("""
          (function() {
            document.getElementById('session-new').click();
          })()
        """)
        time.sleep(0.5)

        visible = client.eval_js("""
          (function() {
            var picker = document.getElementById('session-picker');
            return picker && picker.style.display !== 'none' ? 'visible' : 'hidden';
          })()
        """)
        assert visible == "hidden"


# ── Session Persistence Integration Tests ──


class TestSessionIntegration:

    def test_messages_saved_to_session_file(self, client, http):
        """Chat messages are persisted to session JSON files."""
        # Start a new session
        client.eval_js("""
          (function() {
            var picker = document.getElementById('session-picker');
            if (picker && picker.style.display !== 'none') {
              document.getElementById('session-new').click();
            }
          })()
        """)
        time.sleep(0.5)

        clear_chat(client)

        # Get current session ID
        session_id = client.eval_js("window.App.getSessionId()")
        assert session_id and session_id != "null"

        # Send a message
        client.eval_js("""
          (function() {
            document.getElementById('chat-input').value = 'persistence test message';
            document.getElementById('chat-send').click();
          })()
        """)
        time.sleep(1)

        # Check the session file
        try:
            r = http.get(f"/api/sessions/{session_id}")
            data = r.json()
            user_msgs = [m for m in data["messages"] if m["role"] == "user"]
            assert any("persistence test" in m["content"] for m in user_msgs)
        finally:
            (SESSIONS_DIR / f"{session_id}.json").unlink(missing_ok=True)
