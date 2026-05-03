"""
Phase 5 backend tests: Session persistence.

Tests the session REST API — create, list, get, add messages, update workspace.

Prerequisites:
    - Server running: ./run.sh &

Run:
    source venv/bin/activate && python -m pytest tests/test_phase5_session.py -v
"""

import json
from pathlib import Path

import httpx
import pytest

BASE_URL = "http://127.0.0.1:9800"
PROJECT_NAME = "agent-desktop-env"
SESSIONS_DIR = Path(__file__).parent.parent / "sessions" / PROJECT_NAME
API_SESSIONS = f"/api/{PROJECT_NAME}/sessions"


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def session(http):
    """Create a fresh session and clean up after."""
    r = http.post(API_SESSIONS)
    data = r.json()
    yield data
    # Cleanup
    path = SESSIONS_DIR / f"{data['id']}.json"
    path.unlink(missing_ok=True)


def test_create_session(http):
    """POST /api/{project}/sessions creates a new session."""
    r = http.post(API_SESSIONS)
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["messages"] == []
    assert data["workspace"]["openTabs"] == []
    assert data["agentSessionId"] is None
    # Cleanup
    (SESSIONS_DIR / f"{data['id']}.json").unlink(missing_ok=True)


def test_list_sessions(http, session):
    """GET /api/{project}/sessions lists sessions."""
    r = http.get(API_SESSIONS)
    assert r.status_code == 200
    data = r.json()
    ids = [s["id"] for s in data["sessions"]]
    assert session["id"] in ids


def test_get_session(http, session):
    """GET /api/{project}/sessions/{id} returns the full session."""
    r = http.get(f"{API_SESSIONS}/{session['id']}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == session["id"]
    assert "messages" in data
    assert "workspace" in data


def test_get_nonexistent_session(http):
    """GET /api/{project}/sessions/{id} returns 404 for missing session."""
    r = http.get(f"{API_SESSIONS}/nonexistent-id")
    assert r.status_code == 404


def test_add_message(http, session):
    """POST /api/{project}/sessions/{id}/messages adds a message."""
    r = http.post(
        f"{API_SESSIONS}/{session['id']}/messages",
        json={"role": "user", "content": "hello"},
    )
    assert r.status_code == 200

    # Verify the message was saved
    r = http.get(f"{API_SESSIONS}/{session['id']}")
    data = r.json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "hello"
    assert "timestamp" in data["messages"][0]


def test_add_message_with_annotation(http, session):
    """Messages can include annotation metadata."""
    annotation = {
        "file": "SPEC.md",
        "selectedText": "some selected text",
        "startLine": 10,
        "endLine": 15,
    }
    r = http.post(
        f"{API_SESSIONS}/{session['id']}/messages",
        json={"role": "user", "content": "explain this", "annotation": annotation},
    )
    assert r.status_code == 200

    r = http.get(f"{API_SESSIONS}/{session['id']}")
    msg = r.json()["messages"][0]
    assert msg["annotation"]["file"] == "SPEC.md"
    assert msg["annotation"]["startLine"] == 10


def test_multiple_messages(http, session):
    """Multiple messages are stored in order."""
    http.post(f"{API_SESSIONS}/{session['id']}/messages",
              json={"role": "user", "content": "first"})
    http.post(f"{API_SESSIONS}/{session['id']}/messages",
              json={"role": "assistant", "content": "second"})
    http.post(f"{API_SESSIONS}/{session['id']}/messages",
              json={"role": "user", "content": "third"})

    r = http.get(f"{API_SESSIONS}/{session['id']}")
    msgs = r.json()["messages"]
    assert len(msgs) == 3
    assert [m["content"] for m in msgs] == ["first", "second", "third"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]


def test_update_workspace(http, session):
    """POST /api/{project}/sessions/{id}/workspace updates workspace state."""
    r = http.post(
        f"{API_SESSIONS}/{session['id']}/workspace",
        json={"openTabs": ["SPEC.md", "DESIGN.md"], "activeTab": "DESIGN.md"},
    )
    assert r.status_code == 200

    r = http.get(f"{API_SESSIONS}/{session['id']}")
    ws = r.json()["workspace"]
    assert ws["openTabs"] == ["SPEC.md", "DESIGN.md"]
    assert ws["activeTab"] == "DESIGN.md"


def test_session_last_active_updated(http, session):
    """lastActive timestamp updates when messages are added."""
    original = session["lastActive"]
    import time
    time.sleep(0.1)

    http.post(f"{API_SESSIONS}/{session['id']}/messages",
              json={"role": "user", "content": "update"})

    r = http.get(f"{API_SESSIONS}/{session['id']}")
    assert r.json()["lastActive"] > original


def test_list_sessions_sorted_by_recent(http):
    """Sessions are listed most recent first."""
    s1 = http.post(API_SESSIONS).json()
    import time
    time.sleep(0.1)
    s2 = http.post(API_SESSIONS).json()
    time.sleep(0.1)
    http.post(f"{API_SESSIONS}/{s2['id']}/messages",
              json={"role": "user", "content": "newer"})

    try:
        r = http.get(API_SESSIONS)
        sessions = r.json()["sessions"]
        ids = [s["id"] for s in sessions]
        assert ids.index(s2["id"]) < ids.index(s1["id"])
    finally:
        (SESSIONS_DIR / f"{s1['id']}.json").unlink(missing_ok=True)
        (SESSIONS_DIR / f"{s2['id']}.json").unlink(missing_ok=True)


def test_session_preview(http):
    """Session list shows preview from first user message."""
    s = http.post(API_SESSIONS).json()
    http.post(f"{API_SESSIONS}/{s['id']}/messages",
              json={"role": "user", "content": "what is the meaning of life"})

    try:
        r = http.get(API_SESSIONS)
        session_info = next(x for x in r.json()["sessions"] if x["id"] == s["id"])
        assert "meaning of life" in session_info["preview"]
    finally:
        (SESSIONS_DIR / f"{s['id']}.json").unlink(missing_ok=True)


def test_session_file_on_disk(http, session):
    """Session is persisted as a JSON file."""
    path = SESSIONS_DIR / f"{session['id']}.json"
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["id"] == session["id"]
