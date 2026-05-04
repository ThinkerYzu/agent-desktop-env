import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


SESSIONS_BASE_DIR = Path(__file__).parent.parent / "sessions"


def get_sessions_dir(project_name: str) -> Path:
    """Get sessions directory for a project."""
    project_sessions = SESSIONS_BASE_DIR / project_name
    project_sessions.mkdir(parents=True, exist_ok=True)
    return project_sessions


def list_sessions(project_name: str) -> list[dict]:
    """Return a list of session summaries, sorted by lastActive descending."""
    sessions_dir = get_sessions_dir(project_name)
    sessions = []
    for f in sessions_dir.glob("*.json"):
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


def get_session(project_name: str, session_id: str) -> dict | None:
    """Load a full session by ID."""
    sessions_dir = get_sessions_dir(project_name)
    path = sessions_dir / f"{session_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def create_session(project_name: str) -> dict:
    """Create a new empty session."""
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
    _save(project_name, session)
    return session


def save_session(project_name: str, session: dict):
    """Save a session to disk."""
    session["lastActive"] = datetime.now(timezone.utc).isoformat()
    _save(project_name, session)


def add_message(project_name: str, session_id: str, role: str, content: str,
                annotation=None, extra: dict = None):
    """Add a message to a session and save.

    extra holds role-specific fields (e.g. name+input for tool_use).
    """
    session = get_session(project_name, session_id)
    if not session:
        return None

    msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if annotation:
        msg["annotation"] = annotation
    if extra:
        msg.update(extra)

    session["messages"].append(msg)
    save_session(project_name, session)
    return session


def update_workspace(project_name: str, session_id: str, open_tabs: list[str], active_tab: str | None,
                     agent_session_id: str | None = None):
    """Update the workspace state of a session."""
    session = get_session(project_name, session_id)
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
    save_session(project_name, session)
    return session


def _save(project_name: str, session: dict):
    sessions_dir = get_sessions_dir(project_name)
    path = sessions_dir / f"{session['id']}.json"
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
