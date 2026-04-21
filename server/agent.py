import asyncio
import json
from datetime import datetime
from pathlib import Path


LOG_FILE = Path(__file__).parent.parent / "agent-stderr.log"

# asyncio's StreamReader default line-buffer limit is 64 KiB.  Claude
# stream-json events routinely exceed that when a tool result contains
# a large file read — the reader then raises
#   ValueError: Separator is found, but chunk is longer than limit
# and dies mid-stream.  Give it plenty of headroom.
_STDOUT_LINE_LIMIT = 16 * 1024 * 1024


def _log_marker(message: str) -> None:
    """Append a timestamped marker to the claude stderr log.

    Claude's own stderr is piped to the same file, so these markers
    interleave with its output and make it possible to tell which
    process invocation produced which error text.
    """
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        with open(LOG_FILE, "ab") as f:
            f.write(f"\n===== [{ts}] {message} =====\n".encode())
    except Exception:
        pass


class AgentRunner:
    """Wraps Claude Code CLI as a long-lived subprocess for chat integration.

    Uses --input-format stream-json to keep a single process alive across
    multiple user messages, sending each message as a JSON line to stdin.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.session_id: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._read_task: asyncio.Task | None = None
        # Callbacks for the current turn — set by run(), cleared on result
        self._on_text = None
        self._on_done = None
        self._on_tool_use = None
        self._on_tool_result = None
        self._on_thinking = None
        self._full_text = ""
        self._current_msg_id: str | None = None
        self._got_result: bool = False
        # Set True if the stdout reader raises — distinguishes "reader
        # crashed mid-stream" from "claude exited cleanly without a
        # result event" (the stale --resume id case).  Only the latter
        # should cause us to discard session_id.
        self._read_error: bool = False
        self._turn_done: asyncio.Event | None = None

    async def _ensure_process(self):
        """Start the Claude subprocess if it isn't running."""
        if self._proc is not None and self._proc.returncode is None:
            return  # already running

        cmd = [
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

        if self.session_id:
            cmd.extend(["--resume", self.session_id])

        _log_marker(f"claude start (resume={self.session_id})")

        # Pipe stderr to a shared log file so crashes are diagnosable.
        # We close our end right after spawn — the subprocess keeps its
        # own fd, so it can still write while our process releases the
        # handle.
        stderr_fh = open(LOG_FILE, "ab")
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr_fh,
                cwd=str(self.project_dir),
                limit=_STDOUT_LINE_LIMIT,
            )
        finally:
            stderr_fh.close()

        # Start background reader for stdout
        self._read_task = asyncio.create_task(self._read_stdout())

    async def _read_stdout(self):
        """Continuously read stdout and dispatch events to callbacks."""
        proc = self._proc
        try:
            await self._read_stdout_inner(proc)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Any unexpected error in the read loop would otherwise
            # silently kill this background task and leave run() hung
            # forever on _turn_done.wait().  Log and signal turn done.
            # Flag the error so run() doesn't mistake this for a stale
            # --resume id and clear session_id.
            self._read_error = True
            err = f"[_read_stdout] ERROR: {type(e).__name__}: {e}"
            print(err)
            _log_marker(err)
        finally:
            # Always wake up the turn, even if something went wrong —
            # otherwise agent.run() hangs forever and the UI's working
            # indicator never clears.
            if self._turn_done and not self._turn_done.is_set():
                self._turn_done.set()

    async def _read_stdout_inner(self, proc):
        async for raw_line in proc.stdout:
            # Use errors="replace" so an unexpected non-UTF-8 byte
            # doesn't kill the reader task.
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "assistant":
                message = event.get("message", {})
                # Each assistant message has a unique id.  When the id
                # changes, it's a new message — reset the accumulator so
                # the delta calculation starts fresh.  Text within one
                # message accumulates; this catches the case where the
                # new message happens to be longer than the previous one
                # and the simple length comparison would lose its prefix.
                msg_id = message.get("id")
                if msg_id and msg_id != self._current_msg_id:
                    self._current_msg_id = msg_id
                    self._full_text = ""
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    block_type = block.get("type")
                    if block_type == "text":
                        text = block["text"]
                        if text != self._full_text:
                            new_chunk = text[len(self._full_text):]
                            self._full_text = text
                            if self._on_text and new_chunk:
                                await self._on_text(new_chunk)
                    elif block_type == "tool_use" and self._on_tool_use:
                        await self._on_tool_use({
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        })
                    elif block_type == "thinking" and self._on_thinking:
                        thinking_text = block.get("thinking", "")
                        if thinking_text:
                            await self._on_thinking(thinking_text)

            elif event_type == "user":
                message = event.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "tool_result" and self._on_tool_result:
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            parts = []
                            for part in result_content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    parts.append(part.get("text", ""))
                            result_content = "\n".join(parts)
                        await self._on_tool_result({
                            "tool_use_id": block.get("tool_use_id", ""),
                            "content": str(result_content)[:2000],
                        })

            elif event_type == "result":
                # Distinguish a successful turn from an error result
                # (e.g. invalid --resume session id).  Only mark as
                # got_result on success — error results trigger the
                # retry path in run().  Also don't save a session_id
                # from an error result; it's a synthetic id, not a
                # resumable conversation.
                is_error = event.get("is_error", False) or event.get("subtype") not in (None, "success")
                if not is_error:
                    self._got_result = True
                    sid = event.get("session_id")
                    if sid:
                        self.session_id = sid

                result_text = event.get("result", "")
                # The `result` event's text is the final assistant
                # message text.  If we already streamed it via assistant
                # events, _full_text == result_text and nothing more is
                # sent.  Otherwise the result represents a new message
                # boundary — reset the accumulator before computing the
                # delta so we don't slice off characters.
                if result_text and result_text != self._full_text:
                    if not result_text.startswith(self._full_text):
                        self._full_text = ""
                    new_chunk = result_text[len(self._full_text):]
                    self._full_text = result_text
                    if self._on_text and new_chunk:
                        await self._on_text(new_chunk)

                if self._on_done:
                    await self._on_done({
                        "text": self._full_text,
                        "session_id": self.session_id,
                        "cost_usd": event.get("total_cost_usd"),
                        "duration_ms": event.get("duration_ms"),
                    })

                # Signal that this turn is complete
                if self._turn_done:
                    self._turn_done.set()

        # Process exited — log its exit status so a silent crash is
        # visible in agent-stderr.log alongside claude's own stderr.
        # proc.returncode may still be None if reap hasn't happened yet;
        # wait briefly so we record a real status.
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except Exception:
            pass
        _log_marker(f"claude exit rc={proc.returncode}")

        # Signal turn done if still waiting.  The outer _read_stdout's
        # finally will also cover this, but we fire on_done here with a
        # "no result" payload in case the subprocess died mid-turn
        # without emitting a result event.
        if self._turn_done and not self._turn_done.is_set():
            if self._on_done:
                await self._on_done({
                    "text": self._full_text,
                    "session_id": self.session_id,
                    "cost_usd": None,
                    "duration_ms": None,
                })
            self._turn_done.set()

    async def run(self, prompt: str, on_text=None, on_done=None,
                  on_tool_use=None, on_tool_result=None, on_thinking=None):
        """Send a prompt to Claude and stream the response via callbacks.

        Starts the subprocess on first call; reuses it for subsequent calls.
        If a --resume session_id is stale (no such conversation), claude
        exits without producing a result event; in that case we drop the
        bad session_id and retry once with a fresh process.
        """
        # Track whether we used --resume so we can recover from a stale id
        resume_attempt_id = self.session_id
        await self._do_one_turn(prompt, on_text, on_done, on_tool_use,
                                on_tool_result, on_thinking)

        # Two failure modes look alike (no result event) but must be
        # handled differently:
        #   (a) Reader crashed mid-stream (_read_error=True) — the
        #       subprocess may still be running, but we can no longer
        #       parse its output.  Tear it down and KEEP session_id so
        #       the next chat resumes the same conversation.  Do not
        #       retry in this turn; the user gets an empty response
        #       and can try again.
        #   (b) claude exited cleanly without a result event — the
        #       --resume id is stale (e.g. across server restarts).
        #       Drop session_id and retry once without --resume.
        if not self._got_result and self._read_error:
            # (a) Reader crash — preserve session_id, just tear down proc.
            if self._proc and self._proc.returncode is None:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None
            self._proc = None
        elif resume_attempt_id is not None and not self._got_result:
            # (b) Stale --resume id — discard and retry fresh.  The
            # retry's on_done will fire again; the client's
            # finishStreaming() is idempotent.
            self.session_id = None
            if self._proc and self._proc.returncode is None:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None
            self._proc = None
            await self._do_one_turn(prompt, on_text, on_done, on_tool_use,
                                    on_tool_result, on_thinking)

    async def _do_one_turn(self, prompt, on_text, on_done, on_tool_use,
                           on_tool_result, on_thinking):
        """One stdin write + wait-for-result cycle."""
        await self._ensure_process()

        self._on_text = on_text
        self._on_done = on_done
        self._on_tool_use = on_tool_use
        self._on_tool_result = on_tool_result
        self._on_thinking = on_thinking
        self._full_text = ""
        self._current_msg_id = None
        self._got_result = False
        self._read_error = False
        self._turn_done = asyncio.Event()

        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }) + "\n"
        try:
            self._proc.stdin.write(msg.encode())
            await self._proc.stdin.drain()
        except Exception:
            self._turn_done.set()

        await self._turn_done.wait()

        self._on_text = None
        self._on_done = None
        self._on_tool_use = None
        self._on_tool_result = None
        self._on_thinking = None
        self._turn_done = None

    async def terminate(self):
        """Terminate the subprocess (for session reset)."""
        if self._proc and self._proc.returncode is None:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        self._proc = None
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
            self._read_task = None
        self.session_id = None
