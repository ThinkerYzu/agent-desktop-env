"""
Phase 3 verification tests: File watching + live updates via WebSocket.

Run with the server running:
    ./run.sh &
    source venv/bin/activate && python -m pytest tests/test_phase3_live_updates.py -v

Requirements: pip install pytest websockets httpx
"""

import asyncio
import json
import tempfile
import time
from pathlib import Path

import httpx
import pytest
import websockets

BASE_URL = "http://127.0.0.1:9800"
PROJECT_NAME = "agent-desktop-env"
WS_URL = f"ws://127.0.0.1:9800/ws/{PROJECT_NAME}"
WS_EVAL_URL = f"ws://127.0.0.1:9800/ws/{PROJECT_NAME}?eval=true"

# Resolve the project directory the server watches
PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"


@pytest.fixture
def http_client():
    with httpx.Client(base_url=BASE_URL) as client:
        yield client


def test_server_is_running(http_client):
    """Prerequisite: server must be running on port 9800."""
    r = http_client.get(f"/api/{PROJECT_NAME}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_websocket_connects():
    """WebSocket eval endpoint accepts connections."""
    async def _test():
        async with websockets.connect(WS_EVAL_URL) as ws:
            # Connection succeeded if we get here without exception
            pong = await ws.ping()
            await pong

    asyncio.run(_test())


def test_websocket_receives_modified_event():
    """Modifying a file sends a doc_update message with 'modified' event."""
    test_file = PROJECT_DIR / "_test_ws_modify.md"
    test_file.write_text("# Original content\n")

    async def _test():
        # Wait for the create event to settle
        await asyncio.sleep(0.5)

        async with websockets.connect(WS_EVAL_URL) as ws:
            # Modify the file
            test_file.write_text("# Modified content\n")

            # Wait for the doc_update message (timeout 5s)
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)

            assert data["type"] == "doc_update"
            assert data["payload"]["event"] == "modified"
            assert data["payload"]["path"] == "_test_ws_modify.md"
            assert "Modified content" in data["payload"]["content"]

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)


def test_websocket_receives_created_event():
    """Creating a new file sends a doc_update message with 'created' event."""
    test_file = PROJECT_DIR / "_test_ws_create.md"
    test_file.unlink(missing_ok=True)

    async def _test():
        async with websockets.connect(WS_EVAL_URL) as ws:
            # Create the file
            test_file.write_text("# New file\n")

            # Wait for the matching message (skip stale events from prior tests)
            deadline = asyncio.get_event_loop().time() + 5.0
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                data = json.loads(msg)
                if data.get("type") == "doc_update" and \
                   data["payload"]["path"] == "_test_ws_create.md":
                    assert data["payload"]["event"] in ("created", "modified")
                    return

            pytest.fail("Did not receive create event for _test_ws_create.md")

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)


def test_websocket_receives_deleted_event():
    """Deleting a file sends a doc_update message with 'deleted' event."""
    test_file = PROJECT_DIR / "_test_ws_delete.md"
    test_file.write_text("# To be deleted\n")

    async def _test():
        # Wait for create to settle
        await asyncio.sleep(0.5)

        async with websockets.connect(WS_EVAL_URL) as ws:
            # Delete the file
            test_file.unlink()

            # Wait for the doc_update message (timeout 5s)
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)

            assert data["type"] == "doc_update"
            assert data["payload"]["event"] == "deleted"
            assert data["payload"]["path"] == "_test_ws_delete.md"
            assert "content" not in data["payload"]

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)


def test_hidden_files_are_ignored():
    """Files starting with '.' should not generate events."""
    test_file = PROJECT_DIR / ".test_hidden"

    async def _test():
        async with websockets.connect(WS_EVAL_URL) as ws:
            # Create a hidden file
            test_file.write_text("hidden\n")

            # Create a visible file right after, to prove we get *some* message
            visible_file = PROJECT_DIR / "_test_visible.md"
            visible_file.write_text("visible\n")

            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)

            # The first message we get should be for the visible file, not the hidden one
            assert data["payload"]["path"] == "_test_visible.md"

            visible_file.unlink(missing_ok=True)

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)


def test_modified_content_included_in_payload():
    """Modified event payload includes the full file content."""
    test_file = PROJECT_DIR / "_test_ws_content.md"
    test_file.write_text("line one\n")

    async def _test():
        await asyncio.sleep(0.5)

        async with websockets.connect(WS_EVAL_URL) as ws:
            test_file.write_text("line one\nline two\nline three\n")

            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)

            assert data["type"] == "doc_update"
            content = data["payload"]["content"]
            assert "line one" in content
            assert "line two" in content
            assert "line three" in content

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)



def test_rapid_modifications():
    """Rapid successive modifications are all delivered (possibly batched)."""
    test_file = PROJECT_DIR / "_test_ws_rapid.md"
    test_file.write_text("v0\n")

    async def _test():
        await asyncio.sleep(0.5)

        async with websockets.connect(WS_EVAL_URL) as ws:
            # Write 3 times quickly
            for i in range(1, 4):
                test_file.write_text(f"v{i}\n")
                await asyncio.sleep(0.1)

            # Collect messages for up to 3 seconds
            messages = []
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    messages.append(json.loads(msg))
            except asyncio.TimeoutError:
                pass

            # Should have received at least one update with the final content
            assert len(messages) >= 1
            contents = [m["payload"].get("content", "") for m in messages]
            assert any("v3" in c for c in contents), \
                f"Final version not found in received messages. Got contents: {contents}"

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)
