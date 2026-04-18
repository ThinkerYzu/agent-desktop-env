import asyncio
import json
from pathlib import Path


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

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self.project_dir),
        )

        # Start background reader for stdout
        self._read_task = asyncio.create_task(self._read_stdout())

    async def _read_stdout(self):
        """Continuously read stdout and dispatch events to callbacks."""
        proc = self._proc
        async for line in proc.stdout:
            line = line.decode("utf-8").strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "assistant":
                message = event.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    block_type = block.get("type")
                    if block_type == "text":
                        text = block["text"]
                        if len(text) < len(self._full_text):
                            self._full_text = ""
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
                sid = event.get("session_id")
                if sid:
                    self.session_id = sid

                result_text = event.get("result", "")
                if result_text and result_text != self._full_text:
                    if len(result_text) < len(self._full_text):
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

        # Process exited — signal turn done if still waiting
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
        If the process has died, restarts it with --resume to recover.
        """
        await self._ensure_process()

        # Set callbacks for this turn
        self._on_text = on_text
        self._on_done = on_done
        self._on_tool_use = on_tool_use
        self._on_tool_result = on_tool_result
        self._on_thinking = on_thinking
        self._full_text = ""
        self._turn_done = asyncio.Event()

        # Send user message as JSON line to stdin
        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }) + "\n"
        self._proc.stdin.write(msg.encode())
        await self._proc.stdin.drain()

        # Wait for the result event (or process exit)
        await self._turn_done.wait()

        # Clear callbacks
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
