"""Unit tests for AgentRunner — exercised directly, no WebSocket server.

Prerequisites:
    - Claude Code CLI available in PATH (tests spawn real subprocess)

Run:
    source venv/bin/activate && python -m pytest tests/test_agent.py -v
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from server.agent import AgentRunner


PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"


def test_multi_turn_fires_on_done_each_turn():
    """Regression: run() used to pass send_done=resume_attempt_id is None,
    which suppressed on_done on every turn after the first.  Each turn of
    a long-lived subprocess must deliver an on_done callback."""

    async def _run():
        agent = AgentRunner(PROJECT_DIR)
        done_calls = []

        async def on_done(r):
            done_calls.append(r.get("session_id"))

        async def on_text(chunk):
            pass

        try:
            for turn in range(3):
                done_calls_before = len(done_calls)
                await asyncio.wait_for(
                    agent.run(
                        f"reply only with the word TURN{turn}",
                        on_text=on_text,
                        on_done=on_done,
                    ),
                    timeout=60,
                )
                assert len(done_calls) == done_calls_before + 1, (
                    f"turn {turn}: on_done not called "
                    f"(total calls: {len(done_calls)})"
                )
        finally:
            await agent.terminate()

    asyncio.run(_run())


def test_callback_exception_does_not_hang_agent():
    """Regression: if a callback raises inside the read loop, the reader
    task could die silently and agent.run() would hang forever on
    _turn_done.wait().  With the guard in _read_stdout, the finally block
    signals _turn_done so run() returns (even if the full response is
    lost for that turn)."""

    async def _run():
        agent = AgentRunner(PROJECT_DIR)

        async def on_text_raises(chunk):
            raise RuntimeError("boom from on_text")

        async def on_done(r):
            pass

        try:
            # If the guard isn't in place, this await hangs and the
            # wait_for triggers a TimeoutError.
            await asyncio.wait_for(
                agent.run(
                    "say HELLO briefly",
                    on_text=on_text_raises,
                    on_done=on_done,
                ),
                timeout=30,
            )
        finally:
            await agent.terminate()

    asyncio.run(_run())
