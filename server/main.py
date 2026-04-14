import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse

from .agent import AgentRunner
from .websocket import ConnectionManager
from .file_watcher import watch_project
from . import session as session_store

STATIC_DIR = Path(__file__).parent.parent / "static"
PROJECT_DIR = Path(os.environ.get(
    "ADE_PROJECT_DIR",
    Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"
)).resolve()

agent = AgentRunner(PROJECT_DIR)
manager = ConnectionManager(agent)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start file watcher as background task
    task = asyncio.create_task(watch_project(PROJECT_DIR, manager.broadcast))
    yield
    task.cancel()


app = FastAPI(title="Agent Desktop Environment", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "project_dir": str(PROJECT_DIR)}


@app.get("/api/files")
async def list_files(path: str = Query("")):
    """List files and directories at the given relative path."""
    target = (PROJECT_DIR / path).resolve()
    if not str(target).startswith(str(PROJECT_DIR.resolve())):
        return {"error": "Access denied"}, 403

    if not target.is_dir():
        return {"error": "Not a directory"}

    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith("."):
            continue
        entries.append({
            "name": item.name,
            "path": str(item.relative_to(PROJECT_DIR)),
            "type": "directory" if item.is_dir() else "file",
        })
    return {"entries": entries, "path": path}


@app.get("/api/file")
async def get_file(path: str = Query(...)):
    """Return the content of a file."""
    target = (PROJECT_DIR / path).resolve()
    if not str(target).startswith(str(PROJECT_DIR.resolve())):
        return PlainTextResponse("Access denied", status_code=403)

    if not target.is_file():
        return PlainTextResponse("Not found", status_code=404)

    return PlainTextResponse(target.read_text(encoding="utf-8"))


# ── Session endpoints ──


@app.get("/api/sessions")
async def list_sessions():
    """List all sessions."""
    return {"sessions": session_store.list_sessions()}


@app.post("/api/sessions")
async def create_session():
    """Create a new session."""
    return session_store.create_session()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a full session by ID."""
    session = session_store.get_session(session_id)
    if not session:
        return PlainTextResponse("Not found", status_code=404)
    return session


@app.post("/api/sessions/{session_id}/messages")
async def add_session_message(session_id: str, body: dict):
    """Add a message to a session."""
    session = session_store.add_message(
        session_id,
        body.get("role", "user"),
        body.get("content", ""),
        body.get("annotation"),
    )
    if not session:
        return PlainTextResponse("Not found", status_code=404)
    return {"status": "ok"}


@app.post("/api/sessions/{session_id}/workspace")
async def update_session_workspace(session_id: str, body: dict):
    """Update the workspace state of a session."""
    session = session_store.update_workspace(
        session_id,
        body.get("openTabs", []),
        body.get("activeTab"),
    )
    if not session:
        return PlainTextResponse("Not found", status_code=404)
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.handle_message(websocket, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
