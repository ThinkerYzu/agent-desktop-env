"""
WebSocket policy tests: single-active-client displacement.

These tests connect via the MAIN WebSocket endpoint and will DISPLACE the
active browser tab. Always run this LAST — UI tests that follow will fail
because the browser stops reconnecting after displacement.

Run standalone:
    python -m pytest tests/test_zzz_websocket_policy.py -v
"""

import asyncio
import json
import time
from pathlib import Path

import pytest
import websockets

PROJECT_NAME = "agent-desktop-env"
WS_URL = f"ws://127.0.0.1:9800/ws/{PROJECT_NAME}"
PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"


def test_second_client_displaces_first():
    """ADE enforces single-active-client: a new connection displaces the existing one.

    The displaced client receives close code 4001 and the new client
    becomes the active connection and receives file-change events.

    NOTE: This test displaces the active browser tab. Any UI tests run after
    this will fail unless the browser tab is manually reloaded.
    """
    test_file = PROJECT_DIR / "_test_ws_broadcast.md"
    test_file.write_text("initial\n")

    async def _test():
        await asyncio.sleep(0.5)

        ws1 = await websockets.connect(WS_URL)
        try:
            ws2 = await websockets.connect(WS_URL)
            try:
                # ws1 should be displaced (close code 4001)
                close_code = None
                try:
                    await asyncio.wait_for(ws1.wait_closed(), timeout=3.0)
                    close_code = ws1.close_code
                except asyncio.TimeoutError:
                    pass
                assert close_code == 4001, \
                    f"Expected close code 4001 (displaced), got {close_code}"

                # ws2 receives file change events
                test_file.write_text("updated\n")
                msg = await asyncio.wait_for(ws2.recv(), timeout=5.0)
                data = json.loads(msg)
                assert data["type"] == "doc_update"
                assert "updated" in data["payload"].get("content", "")
            finally:
                await ws2.close()
        finally:
            try:
                await ws1.close()
            except Exception:
                pass

    try:
        asyncio.run(_test())
    finally:
        test_file.unlink(missing_ok=True)
