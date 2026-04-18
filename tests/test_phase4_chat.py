"""
Phase 4 backend tests: Chat + Claude Code integration.

Tests the WebSocket chat flow — sending messages, receiving streaming
responses, and multi-turn conversation via --resume.

Prerequisites:
    - Server running: ./run.sh &
    - Claude Code CLI available in PATH

Run:
    source venv/bin/activate && python -m pytest tests/test_phase4_chat.py -v
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import websockets

BASE_URL = "http://127.0.0.1:9800"
WS_URL = "ws://127.0.0.1:9800/ws"
PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"


@pytest.fixture
def http_client():
    with httpx.Client(base_url=BASE_URL) as client:
        yield client


@pytest.fixture(autouse=True)
def reset_agent():
    """Reset the agent subprocess before each test for isolation.

    The agent maintains a long-lived subprocess across messages, so
    conversation context leaks between tests without this reset.
    """
    async def _reset():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({"type": "reset_agent_session"}))
            # Give the server time to complete agent.terminate()
            # before closing the socket (terminate can take up to 5s).
            await asyncio.sleep(1.0)
    asyncio.run(_reset())
    yield


def test_server_is_running(http_client):
    """Prerequisite: server must be running."""
    r = http_client.get("/api/health")
    assert r.status_code == 200


def test_chat_returns_response():
    """Sending a chat message returns at least one streaming chunk and a done signal."""
    async def _test():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": "chat",
                "payload": {"role": "user", "content": "say just the word pong"},
            }))

            chunks = []
            done = False
            while not done:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(msg)
                if data["type"] != "chat":
                    continue
                payload = data["payload"]
                if payload.get("streaming"):
                    chunks.append(payload["content"])
                else:
                    done = True

            assert len(chunks) >= 1, "Expected at least one streaming chunk"
            full_text = "".join(chunks).lower()
            assert "pong" in full_text

    asyncio.run(_test())


def test_chat_streaming_flag():
    """Streaming chunks have streaming=True, final message has streaming=False."""
    async def _test():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": "chat",
                "payload": {"role": "user", "content": "say ok"},
            }))

            streaming_flags = []
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(msg)
                if data["type"] != "chat":
                    continue
                streaming_flags.append(data["payload"]["streaming"])
                if not data["payload"]["streaming"]:
                    break

            # Should have some True followed by one False
            assert streaming_flags[-1] is False
            assert any(f is True for f in streaming_flags[:-1])

    asyncio.run(_test())


def test_chat_empty_message_ignored():
    """An empty chat message should not produce any response."""
    async def _test():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": "chat",
                "payload": {"role": "user", "content": "  "},
            }))

            # Send a second valid message to prove the connection works
            await ws.send(json.dumps({
                "type": "chat",
                "payload": {"role": "user", "content": "say yes"},
            }))

            # First chat response should be for "say yes", not the empty message
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(msg)
                if data["type"] == "chat" and data["payload"].get("streaming"):
                    # Got a streaming chunk — this should be from "say yes"
                    assert len(data["payload"]["content"]) > 0
                    break

    asyncio.run(_test())


def test_tool_use_events_received():
    """A prompt that triggers tool use should emit tool_use and tool_result events."""
    async def _test():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": "chat",
                "payload": {"role": "user", "content": "list files in the current directory using ls"},
            }))

            roles_seen = set()
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                data = json.loads(msg)
                if data["type"] != "chat":
                    continue
                role = data["payload"].get("role", "")
                roles_seen.add(role)
                # Done when we get the final non-streaming assistant message
                if role == "assistant" and not data["payload"].get("streaming"):
                    break

            assert "tool_use" in roles_seen, f"Expected tool_use event, got roles: {roles_seen}"
            assert "tool_result" in roles_seen, f"Expected tool_result event, got roles: {roles_seen}"

    asyncio.run(_test())


def test_agent_file_creation():
    """The agent can create files that appear on the filesystem."""
    test_file = PROJECT_DIR / "_test_agent_create.md"
    test_file.unlink(missing_ok=True)

    async def _test():
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": "chat",
                "payload": {
                    "role": "user",
                    "content": 'Create a file called _test_agent_create.md with exactly this content: "# Agent Created"',
                },
            }))

            # Wait for completion (assistant role with streaming=False).
            # Tool use/result messages have no `streaming` field, so check
            # both role and the explicit False value.
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                data = json.loads(msg)
                if data["type"] != "chat":
                    continue
                p = data["payload"]
                if p.get("role") == "assistant" and p.get("streaming") is False:
                    break

    try:
        asyncio.run(_test())
        assert test_file.exists(), "Agent did not create the file"
        content = test_file.read_text()
        assert "Agent Created" in content
    finally:
        test_file.unlink(missing_ok=True)
