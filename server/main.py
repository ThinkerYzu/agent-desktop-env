import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse

from .project_manager import ProjectManager
from .projects import discover_projects, is_single_project_mode
from . import session as session_store

STATIC_DIR = Path(__file__).parent.parent / "static"
SESSIONS_BASE_DIR = Path(__file__).parent.parent / "sessions"

# Determine project mode
PROJECT_ROOT = Path(os.environ.get(
    "ADE_PROJECT_DIR",
    Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"
)).resolve()
SINGLE_PROJECT_MODE, SINGLE_PROJECT_NAME = is_single_project_mode(PROJECT_ROOT)

# Create project manager
IDLE_TIMEOUT = int(os.environ.get("ADE_PROJECT_IDLE_TIMEOUT", "1800"))
MAX_ACTIVE = int(os.environ.get("ADE_MAX_ACTIVE_PROJECTS", "10"))
project_manager = ProjectManager(PROJECT_ROOT, IDLE_TIMEOUT, MAX_ACTIVE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start cleanup task for idle projects
    cleanup_task = asyncio.create_task(project_manager.cleanup_task_loop())
    yield
    # Shutdown all projects
    cleanup_task.cancel()
    await project_manager.shutdown()


app = FastAPI(title="Agent Desktop Environment", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    """Root page - project listing or redirect to single project."""
    if SINGLE_PROJECT_MODE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"/{SINGLE_PROJECT_NAME}")
    return FileResponse(STATIC_DIR / "projects.html")


@app.get("/{project_name}")
async def project_index(project_name: str):
    """Project three-panel UI."""
    # Validate project exists
    try:
        await project_manager.get_project(project_name)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))

    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/projects")
async def list_projects():
    """List all available projects."""
    if SINGLE_PROJECT_MODE:
        # Return single project
        projects = [{
            "name": SINGLE_PROJECT_NAME,
            "title": SINGLE_PROJECT_NAME,
            "description": "",
            "has_sessions": False,
            "session_count": 0,
            "last_session_time": None
        }]
    else:
        # Discover projects
        project_infos = discover_projects(PROJECT_ROOT, SESSIONS_BASE_DIR)
        projects = [
            {
                "name": p.name,
                "title": p.title,
                "description": p.description,
                "has_sessions": p.has_sessions,
                "session_count": p.session_count,
                "last_session_time": p.last_session_time.isoformat() if p.last_session_time else None
            }
            for p in project_infos
        ]

    return {"projects": projects}


@app.get("/api/{project_name}/health")
async def health(project_name: str):
    project = await project_manager.get_project(project_name)
    return {"status": "ok", "project_dir": str(project.project_dir)}


@app.get("/api/{project_name}/config")
async def config(project_name: str):
    """Return app configuration including init file info."""
    project = await project_manager.get_project(project_name)
    init_file = project.metadata.get("init_file", "AGENT-warm-up.md")
    init_path = project.project_dir / init_file
    return {
        "project_dir": str(project.project_dir),
        "project_name": project_name,
        "init_file": init_file,
        "init_file_exists": init_path.is_file(),
    }


@app.get("/api/{project_name}/files")
async def list_files(project_name: str, path: str = Query("")):
    """List files and directories at the given relative path."""
    project = await project_manager.get_project(project_name)
    target = (project.project_dir / path).resolve()
    if not str(target).startswith(str(project.project_dir.resolve())):
        return {"error": "Access denied"}, 403

    if not target.is_dir():
        return {"error": "Not a directory"}

    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith("."):
            continue
        entries.append({
            "name": item.name,
            "path": str(item.relative_to(project.project_dir)),
            "type": "directory" if item.is_dir() else "file",
        })
    return {"entries": entries, "path": path}


@app.get("/api/{project_name}/file")
async def get_file(project_name: str, path: str = Query(...)):
    """Return the content of a file."""
    project = await project_manager.get_project(project_name)
    target = (project.project_dir / path).resolve()
    if not str(target).startswith(str(project.project_dir.resolve())):
        return PlainTextResponse("Access denied", status_code=403)

    if not target.is_file():
        return PlainTextResponse("Not found", status_code=404)

    return PlainTextResponse(target.read_text(encoding="utf-8"))


# ── Session endpoints ──


@app.get("/api/{project_name}/sessions")
async def list_sessions(project_name: str):
    """List all sessions."""
    return {"sessions": session_store.list_sessions(project_name)}


@app.post("/api/{project_name}/sessions")
async def create_session(project_name: str):
    """Create a new session."""
    return session_store.create_session(project_name)


@app.get("/api/{project_name}/sessions/{session_id}")
async def get_session(project_name: str, session_id: str):
    """Get a full session by ID."""
    session = session_store.get_session(project_name, session_id)
    if not session:
        return PlainTextResponse("Not found", status_code=404)
    return session


@app.post("/api/{project_name}/sessions/{session_id}/messages")
async def add_session_message(project_name: str, session_id: str, body: dict):
    """Add a message to a session."""
    known = {"role", "content", "annotation"}
    extra = {k: v for k, v in body.items() if k not in known} or None
    session = session_store.add_message(
        project_name,
        session_id,
        body.get("role", "user"),
        body.get("content", ""),
        body.get("annotation"),
        extra,
    )
    if not session:
        return PlainTextResponse("Not found", status_code=404)
    return {"status": "ok"}


@app.post("/api/{project_name}/sessions/{session_id}/workspace")
async def update_session_workspace(project_name: str, session_id: str, body: dict):
    """Update the workspace state of a session."""
    session = session_store.update_workspace(
        project_name,
        session_id,
        body.get("openTabs", []),
        body.get("activeTab"),
        body.get("agentSessionId"),
    )
    if not session:
        return PlainTextResponse("Not found", status_code=404)
    return {"status": "ok"}


@app.websocket("/ws/{project_name}")
async def websocket_endpoint(websocket: WebSocket, project_name: str, eval: bool = Query(False)):
    """Main WebSocket endpoint.

    Pass ?eval=true for test eval connections — these receive broadcast events
    and can exchange eval/eval_result messages without displacing the browser.
    """
    try:
        project = await project_manager.get_project(project_name)
    except ValueError:
        await websocket.close(code=1008, reason="Project not found")
        return

    if eval:
        await project.manager.connect_eval(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await project.manager.handle_message(websocket, data)
        except WebSocketDisconnect:
            project.manager.disconnect_eval(websocket)
    else:
        await project.manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await project.manager.handle_message(websocket, data)
        except WebSocketDisconnect:
            project.manager.disconnect(websocket)
