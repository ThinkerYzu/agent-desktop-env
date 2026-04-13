import asyncio
import json
import logging
from pathlib import Path
from watchfiles import awatch, Change

logger = logging.getLogger(__name__)


async def watch_project(project_dir: Path, broadcast_fn):
    """Watch project directory and broadcast file change events."""
    async for changes in awatch(project_dir):
        for change_type, change_path in changes:
            path = Path(change_path)

            # Skip hidden files and directories
            try:
                rel_path = path.relative_to(project_dir)
            except ValueError:
                continue

            if any(part.startswith(".") for part in rel_path.parts):
                continue

            event = {
                Change.added: "created",
                Change.modified: "modified",
                Change.deleted: "deleted",
            }.get(change_type)

            if event is None:
                continue

            payload = {
                "event": event,
                "path": str(rel_path),
            }

            # Include file content for created/modified (if readable)
            if event in ("created", "modified") and path.is_file():
                try:
                    payload["content"] = path.read_text(encoding="utf-8")
                except Exception:
                    pass

            logger.info(f"File watcher: {event} {rel_path}")
            message = json.dumps({"type": "doc_update", "payload": payload})
            await broadcast_fn(message)
