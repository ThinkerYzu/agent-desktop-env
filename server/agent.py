import asyncio
import json
from pathlib import Path


class AgentRunner:
    """Wraps Claude Code CLI as a subprocess for chat integration."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.session_id: str | None = None

    async def run(self, prompt: str, on_text=None, on_done=None,
                  on_tool_use=None, on_tool_result=None, on_thinking=None):
        """Run a prompt through Claude Code and stream the response.

        Args:
            prompt: The user's message
            on_text: async callback(text_chunk) called for each text chunk
            on_done: async callback(full_result) called when complete
            on_tool_use: async callback(tool_info) called when agent invokes a tool
            on_tool_result: async callback(result_info) called with tool result
            on_thinking: async callback(thinking_text) called for thinking blocks
        """
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

        if self.session_id:
            cmd.extend(["--resume", self.session_id])

        cmd.append(prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.project_dir),
        )

        full_text = ""
        result_received = False

        try:
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
                    # Extract content blocks from the message
                    message = event.get("message", {})
                    content_blocks = message.get("content", [])
                    for block in content_blocks:
                        block_type = block.get("type")
                        if block_type == "text":
                            text = block["text"]
                            # Each assistant event contains accumulated text
                            # for that message. If new text is shorter than
                            # full_text, it's a new message — reset tracking.
                            if len(text) < len(full_text):
                                full_text = ""
                            if text != full_text:
                                new_chunk = text[len(full_text):]
                                full_text = text
                                if on_text and new_chunk:
                                    await on_text(new_chunk)
                        elif block_type == "tool_use" and on_tool_use:
                            await on_tool_use({
                                "name": block.get("name", ""),
                                "input": block.get("input", {}),
                            })
                        elif block_type == "thinking" and on_thinking:
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                await on_thinking(thinking_text)

                elif event_type == "user":
                    # Tool results come back as user events
                    message = event.get("message", {})
                    content_blocks = message.get("content", [])
                    for block in content_blocks:
                        if block.get("type") == "tool_result" and on_tool_result:
                            # Extract text content from the tool result
                            result_content = block.get("content", "")
                            if isinstance(result_content, list):
                                parts = []
                                for part in result_content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        parts.append(part.get("text", ""))
                                result_content = "\n".join(parts)
                            await on_tool_result({
                                "tool_use_id": block.get("tool_use_id", ""),
                                "content": str(result_content)[:2000],
                            })

                elif event_type == "result":
                    result_received = True
                    # Final result — capture session_id for resume
                    sid = event.get("session_id")
                    if sid:
                        self.session_id = sid

                    result_text = event.get("result", "")
                    if result_text and result_text != full_text:
                        # Result contains only the last message's text
                        if len(result_text) < len(full_text):
                            full_text = ""
                        new_chunk = result_text[len(full_text):]
                        full_text = result_text
                        if on_text and new_chunk:
                            await on_text(new_chunk)

                    if on_done:
                        await on_done({
                            "text": full_text,
                            "session_id": self.session_id,
                            "cost_usd": event.get("total_cost_usd"),
                            "duration_ms": event.get("duration_ms"),
                        })
        finally:
            await proc.wait()
            # If the process exited without a result event (crash, OOM,
            # context limit, etc.), still notify so the UI clears the
            # working indicator.
            if not result_received and on_done:
                await on_done({
                    "text": full_text,
                    "session_id": self.session_id,
                    "cost_usd": None,
                    "duration_ms": None,
                })
