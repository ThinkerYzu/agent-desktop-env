"""Project discovery and metadata."""
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json


@dataclass
class ProjectInfo:
    """Project metadata for listing."""
    name: str
    path: Path
    title: str
    description: str
    has_sessions: bool
    session_count: int
    last_session_time: Optional[datetime]


def discover_projects(root_dir: Path, sessions_base_dir: Path) -> list[ProjectInfo]:
    """Scan root_dir for project subdirectories."""
    projects = []

    if not root_dir.exists() or not root_dir.is_dir():
        return projects

    for item in sorted(root_dir.iterdir()):
        # Skip hidden directories
        if item.name.startswith('.'):
            continue

        # Only include directories
        if not item.is_dir():
            continue

        # Load metadata
        metadata = load_project_metadata(item)

        # Check sessions
        sessions_dir = sessions_base_dir / item.name
        has_sessions = sessions_dir.exists() and any(sessions_dir.glob("*.json"))
        session_count = len(list(sessions_dir.glob("*.json"))) if has_sessions else 0

        # Get last session time
        last_session_time = None
        if has_sessions:
            session_files = list(sessions_dir.glob("*.json"))
            if session_files:
                last_session_time = max(f.stat().st_mtime for f in session_files)
                last_session_time = datetime.fromtimestamp(last_session_time)

        projects.append(ProjectInfo(
            name=item.name,
            path=item,
            title=metadata.get("title", item.name),
            description=metadata.get("description", ""),
            has_sessions=has_sessions,
            session_count=session_count,
            last_session_time=last_session_time
        ))

    return projects


def load_project_metadata(project_dir: Path) -> dict:
    """Load .ade-project if exists."""
    metadata_file = project_dir / ".ade-project"
    if metadata_file.exists():
        try:
            with open(metadata_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def is_single_project_mode(root_dir: Path) -> tuple[bool, Optional[str]]:
    """
    Detect if root_dir is itself a project or a multi-project root.

    Returns:
        (is_single_project, project_name_if_single)
    """
    if not root_dir.exists() or not root_dir.is_dir():
        return (True, root_dir.name)

    # Check for project marker
    if (root_dir / ".ade-project").exists():
        return (True, root_dir.name)

    # Check for common project files that suggest this is a project, not a root
    project_markers = [
        "README.md",
        "SPEC.md",
        "DESIGN.md",
        "AGENT-warm-up.md",
        ".git"
    ]

    marker_count = sum(1 for marker in project_markers if (root_dir / marker).exists())

    # If 2+ markers found, treat as single project
    if marker_count >= 2:
        return (True, root_dir.name)

    # Otherwise, treat as multi-project root
    return (False, None)
