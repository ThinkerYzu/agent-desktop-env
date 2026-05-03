"""Project lifecycle management."""
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

from .agent import AgentRunner
from .websocket import ConnectionManager
from .file_watcher import watch_project


@dataclass
class ProjectInstance:
    """Per-project state and resources."""
    project_dir: Path
    project_name: str
    agent: AgentRunner
    manager: ConnectionManager
    watcher_task: asyncio.Task
    last_activity: datetime
    metadata: dict

    async def touch(self):
        """Update last_activity timestamp."""
        self.last_activity = datetime.now()

    async def is_idle(self, timeout_seconds: int) -> bool:
        """Check if project has been idle longer than timeout."""
        return (datetime.now() - self.last_activity).total_seconds() > timeout_seconds

    async def shutdown(self, clear_session: bool = True):
        """Clean shutdown of agent, watcher, connections.

        Pass clear_session=False during idle cleanup to preserve session_id
        so a reconnecting browser can --resume the conversation.
        """
        # Cancel file watcher
        if self.watcher_task and not self.watcher_task.done():
            self.watcher_task.cancel()
            try:
                await self.watcher_task
            except asyncio.CancelledError:
                pass

        # Terminate agent
        if self.agent:
            await self.agent.terminate(clear_session=clear_session)

        # Close WebSocket connections (disconnect all)
        if self.manager:
            for ws in list(self.manager.connections):
                try:
                    await ws.close()
                except Exception:
                    pass
            self.manager.connections.clear()
            self.manager._active_ws = None


class ProjectManager:
    """Manages active projects, agents, file watchers."""

    def __init__(self, root_dir: Path, idle_timeout: int = 1800, max_active: int = 10):
        self.root_dir = root_dir
        self.idle_timeout = idle_timeout
        self.max_active = max_active
        self.projects: dict[str, ProjectInstance] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_project(self, name: str) -> ProjectInstance:
        """Get or create project instance (lazy creation)."""
        async with self._lock:
            if name in self.projects:
                await self.projects[name].touch()
                return self.projects[name]

            # Check max active limit
            if len(self.projects) >= self.max_active:
                # Try to cleanup idle projects first
                await self._cleanup_idle()

                if len(self.projects) >= self.max_active:
                    raise ValueError(f"Maximum active projects ({self.max_active}) reached")

            # Create new project instance
            # In single-project mode, root_dir IS the project directory
            if self.root_dir.name == name and self.root_dir.is_dir():
                project_dir = self.root_dir
            else:
                project_dir = self.root_dir / name
                if not project_dir.exists():
                    raise ValueError(f"Project not found: {name}")
                if not project_dir.is_dir():
                    raise ValueError(f"Not a directory: {name}")

            # Load metadata
            metadata = self._load_metadata(project_dir)

            # Create agent runner
            agent = AgentRunner(project_dir)

            # Create connection manager (pass agent, not project_name)
            manager = ConnectionManager(agent)

            # Create file watcher task (pass manager.broadcast as callback)
            watcher_task = asyncio.create_task(
                watch_project(project_dir, manager.broadcast)
            )

            # Create instance
            instance = ProjectInstance(
                project_dir=project_dir,
                project_name=name,
                agent=agent,
                manager=manager,
                watcher_task=watcher_task,
                last_activity=datetime.now(),
                metadata=metadata
            )

            self.projects[name] = instance
            return instance

    def _load_metadata(self, project_dir: Path) -> dict:
        """Load .ade-project metadata if exists."""
        metadata_file = project_dir / ".ade-project"
        if metadata_file.exists():
            import json
            try:
                with open(metadata_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    async def _cleanup_idle(self):
        """Cleanup idle projects (called with lock held)."""
        to_remove = []
        for name, instance in self.projects.items():
            # Never kill a project whose agent is actively processing a turn.
            if instance.manager._turn_active:
                continue
            if await instance.is_idle(self.idle_timeout):
                await instance.shutdown(clear_session=False)
                to_remove.append(name)

        for name in to_remove:
            del self.projects[name]

    async def cleanup_task_loop(self):
        """Background task to periodically cleanup idle projects."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            async with self._lock:
                await self._cleanup_idle()

    async def shutdown(self):
        """Shutdown all active projects."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for instance in self.projects.values():
                await instance.shutdown()
            self.projects.clear()
