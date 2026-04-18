import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


def ensure_sessions_dir():
    SESSIONS_DIR.mkdir(exist_ok=True)


def list_sessions() -> list[dict]:
    """Return a list of session summaries, sorted by lastActive descending."""
    ensure_sessions_dir()
    sessions = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "id": data.get("id"),
                "created": data.get("created"),
                "lastActive": data.get("lastActive"),
                "messageCount": len(data.get("messages", [])),
                "preview": _preview(data),
            })
        except Exception:
            continue

    sessions.sort(key=lambda s: s.get("lastActive", ""), reverse=True)
    return sessions


def get_session(session_id: str) -> dict | None:
    """Load a full session by ID."""
    ensure_sessions_dir()
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def create_session() -> dict:
    """Create a new empty session."""
    ensure_sessions_dir()
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "id": str(uuid.uuid4()),
        "created": now,
        "lastActive": now,
        "messages": [],
        "workspace": {
            "openTabs": [],
            "activeTab": None,
        },
        "agentSessionId": None,
    }
    _save(session)
    return session


def save_session(session: dict):
    """Save a session to disk."""
    session["lastActive"] = datetime.now(timezone.utc).isoformat()
    _save(session)


def add_message(session_id: str, role: str, content: str, annotation=None):
    """Add a message to a session and save."""
    session = get_session(session_id)
    if not session:
        return None

    msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if annotation:
        msg["annotation"] = annotation

    session["messages"].append(msg)
    save_session(session)
    return session


def update_workspace(session_id: str, open_tabs: list[str], active_tab: str | None,
                     agent_session_id: str | None = None):
    """Update the workspace state of a session."""
    session = get_session(session_id)
    if not session:
        return None
    session["workspace"] = {
        "openTabs": open_tabs,
        "activeTab": active_tab,
    }
    # Only overwrite agentSessionId when a value is explicitly provided
    # (workspace updates from tab changes don't include it).
    if agent_session_id is not None:
        session["agentSessionId"] = agent_session_id
    save_session(session)
    return session


def _save(session: dict):
    ensure_sessions_dir()
    path = SESSIONS_DIR / f"{session['id']}.json"
    path.write_text(json.dumps(session, indent=2), encoding="utf-8")


def _preview(data: dict) -> str:
    """Generate a preview string from the first user message."""
    for msg in data.get("messages", []):
        if msg.get("role") == "user":
            text = msg.get("content", "")
            if len(text) > 80:
                return text[:80] + "..."
            return text
    return "(empty session)"
