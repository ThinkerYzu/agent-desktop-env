import asyncio
import json
from pathlib import Path


class AgentRunner:
    """Wraps Claude Code CLI as a subprocess for chat integration."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.session_id: str | None = None

    async def run(self, prompt: str, on_text=None, on_done=None):
        """Run a prompt through Claude Code and stream the response.

        Args:
            prompt: The user's message
            on_text: async callback(text_chunk) called for each text chunk
            on_done: async callback(full_result) called when complete
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
                # Extract text from the message content
                message = event.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block["text"]
                        # For streaming, send the full text so far
                        # (each assistant event contains the accumulated text)
                        if text != full_text:
                            new_chunk = text[len(full_text):]
                            full_text = text
                            if on_text and new_chunk:
                                await on_text(new_chunk)

            elif event_type == "result":
                # Final result — capture session_id for resume
                sid = event.get("session_id")
                if sid:
                    self.session_id = sid

                result_text = event.get("result", "")
                if result_text and result_text != full_text:
                    # Send any remaining text
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

        await proc.wait()
