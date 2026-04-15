# Agent Desktop Environment

A web application that puts an AI coding agent and your project documents side by side. Browse files, view rendered markdown, and chat with a Claude-powered agent — all in one window, with real-time updates as files change.

![Screenshot — file tree, document viewer, and chat side by side](screenshot.png)

## Why

Working with a coding agent today means typing in a terminal while switching to an editor or browser to read the documents it produces. You can't point at a paragraph and say "rewrite this" — you have to describe it in words. This app eliminates that friction by putting the conversation and your project documents side by side, with live rendering and a selection-based annotation mechanism that lets you point at content directly.

## What It Does

- **Three-panel layout** — file tree on the left, document viewer in the center, chat on the right
- **Live document rendering** — open markdown files as tabs; they re-render automatically when saved (works with any editor, git operations, or the agent itself)
- **Integrated chat** — converse with a Claude Code agent that has full access to your project (file I/O, shell commands, etc.)
- **Annotation** — select text in a document and it's attached as context to your next message, so the agent knows exactly what you're pointing at
- **Session persistence** — conversations are saved and resumed automatically; workspace state (open tabs, scroll positions) survives page reloads

## Requirements

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed and available on `PATH`
- Linux (file watching uses inotify)

## Quick Start

```bash
git clone https://github.com/ThinkerYzu/docforge.git
cp -r docforge/template my-project
./run.sh my-project
```

This copies a [docforge](https://github.com/ThinkerYzu/docforge) project template, sets up a virtualenv, installs Python dependencies, and starts the server at **http://localhost:9800**. Open that URL in your browser. The agent will read `AGENT-warm-up.md` on the first session and walk you through project setup.

You can also point it at any existing directory:

```bash
./run.sh /path/to/your/project
```

Or use an environment variable:

```bash
ADE_PROJECT_DIR=/path/to/your/project ./run.sh
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ADE_PROJECT_DIR` | — | Root directory shown in the file tree and watched for changes |
| `ADE_PORT` | `9800` | Port the server listens on |
| `ADE_INIT_FILE` | `AGENT-warm-up.md` | File the agent reads at the start of each new session for project context. Set to an empty string to disable. |

### Agent Warm-Up

When a new chat session starts, the agent automatically reads the file specified by `ADE_INIT_FILE` (relative to the project directory). This lets you give the agent background on your project — architecture, conventions, current status — so it's productive from the first message. Create an `AGENT-warm-up.md` in your project root, or point `ADE_INIT_FILE` to any file you prefer.

This project is designed to work with [docforge](https://github.com/ThinkerYzu/docforge), a doc-driven development template for AI-assisted projects. Copy docforge's template into your project directory and the agent will automatically pick up `AGENT-warm-up.md` on each new session — initializing the project on the first session, and loading context from `HANDOFF.md` on subsequent sessions.

## Architecture

- **Backend:** FastAPI serves static files, a REST API for the file tree, and a single multiplexed WebSocket for real-time communication (file events, chat messages, eval commands).
- **Frontend:** Vanilla JS modules with no framework and no build step. Markdown is rendered client-side with marked.js.
- **Agent:** Claude Code CLI runs as a subprocess with `--output-format stream-json --resume <session-id>`, giving it full tool access and multi-turn memory.
- **File watching:** `watchfiles` (inotify) detects saves and pushes updates over WebSocket. Handles atomic writes, debounces rapid events, and refreshes both the file tree and any open documents.

## Running Tests

```bash
source venv/bin/activate
pytest tests/
```

Some tests drive the UI via a WebSocket eval channel and require a running browser tab. Pass `--tab-id <id>` to target a specific tab.

## Project Structure

```
.
├── run.sh                  # Entry point — venv setup + server launch
├── requirements.txt        # Python dependencies
├── server/                 # FastAPI backend
│   ├── main.py             # App setup, routes, WebSocket, lifespan
│   ├── agent.py            # Claude Code CLI subprocess management
│   ├── session.py          # Session persistence (JSON files)
│   ├── file_watcher.py     # inotify filesystem watcher (watchfiles)
│   └── websocket.py        # WebSocket connection manager
├── static/                 # Frontend (vanilla HTML/CSS/JS, no build step)
│   ├── index.html          # Three-panel layout
│   ├── css/style.css       # Dark-themed styles
│   └── js/
│       ├── app.js          # Init, WebSocket, workspace restore
│       ├── filetree.js     # File tree panel
│       ├── document.js     # Document viewer — tabs, rendering, scroll
│       ├── chat.js         # Chat — messaging, streaming, annotations, sessions
│       └── marked.min.js   # Markdown parser (vendored)
├── tests/                  # Test suite (60 tests)
└── sessions/               # Saved session files (auto-created)
```

## License

[MIT](LICENSE)
