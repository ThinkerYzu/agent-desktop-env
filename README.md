# Agent Desktop Environment

A web application that puts an AI coding agent and your project documents side by side. Browse files, view rendered markdown, and chat with a Claude-powered agent — all in one window, with real-time updates as files change.

**New:** Multi-project support! Serve multiple projects from a single ADE instance with isolated sessions, lazy resource management, and automatic mode detection.

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

### Single Project Mode

```bash
git clone https://github.com/ThinkerYzu/docforge.git
cp -r docforge/template my-project
./run.sh my-project
```

This copies a [docforge](https://github.com/ThinkerYzu/docforge) project template, sets up a virtualenv, installs Python dependencies, and starts the server at **http://localhost:9800**. The root URL redirects to the project, and the agent reads `AGENT-warm-up.md` on the first session.

You can also point it at any existing directory:

```bash
./run.sh /path/to/your/project
```

Or use an environment variable:

```bash
ADE_PROJECT_DIR=/path/to/your/project ./run.sh
```

### Multi-Project Mode

Serve multiple projects from a single ADE instance:

```bash
# Point to a directory containing multiple project subdirectories
./run.sh /path/to/projects

# Or use environment variable
ADE_PROJECT_DIR=/path/to/projects ./run.sh
```

ADE auto-detects the mode:
- **Single-project**: Root URL redirects to `/{project_name}`
- **Multi-project**: Root URL shows a project listing page

Each project gets isolated sessions, its own agent process, and independent file watching. Resources are created lazily (only when accessed) and cleaned up after idle timeout (default 30 min).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ADE_PROJECT_DIR` | — | Project directory (single-project) or projects root (multi-project). Mode auto-detected. |
| `ADE_PORT` | `9800` | Port the server listens on |
| `ADE_INIT_FILE` | `AGENT-warm-up.md` | File the agent reads at the start of each new session. Can be overridden per-project via `.ade-project` file. |
| `ADE_PROJECT_IDLE_TIMEOUT` | `1800` | Seconds before cleaning up idle project resources (30 min) |
| `ADE_MAX_ACTIVE_PROJECTS` | `10` | Maximum simultaneously active projects (multi-project mode) |

### Agent Working Directory

The Claude Code subprocess runs with the **project directory** as its working directory — not the multi-project root. In single-project mode that is the path you passed to `run.sh` (or `ADE_PROJECT_DIR`). In multi-project mode each project's agent uses its own subdirectory, so relative file paths, Bash commands, and file reads/writes all resolve against that project's root.

### Agent Warm-Up

When a new chat session starts, the agent automatically reads the file specified by `ADE_INIT_FILE` (relative to the project directory). This lets you give the agent background on your project — architecture, conventions, current status — so it's productive from the first message. Create an `AGENT-warm-up.md` in your project root, or point `ADE_INIT_FILE` to any file you prefer.

This project is designed to work with [docforge](https://github.com/ThinkerYzu/docforge), a doc-driven development template for AI-assisted projects. Copy docforge's template into your project directory and the agent will automatically pick up `AGENT-warm-up.md` on each new session — initializing the project on the first session, and loading context from `HANDOFF.md` on subsequent sessions.

### Per-Project Configuration (`.ade-project`)

In multi-project mode, you can customize individual projects by adding a `.ade-project` JSON file to the project root:

```json
{
  "title": "My Project",
  "description": "A custom description shown on the project listing page",
  "init_file": "docs/SETUP.md"
}
```

**Fields:**
- `title` — Display name (defaults to directory name)
- `description` — Brief description shown on listing page
- `init_file` — Override `ADE_INIT_FILE` for this project

**Mode Detection:**
The presence of `.ade-project` explicitly marks a directory as a single project. ADE also uses heuristics (checks for `README.md`, `SPEC.md`, `DESIGN.md`, `AGENT-warm-up.md`, `.git`) to detect single projects vs multi-project roots.

## Architecture

- **Backend:** FastAPI serves static files, a REST API for the file tree, and project-scoped WebSockets for real-time communication. ProjectManager handles lazy resource creation and idle cleanup.
- **Frontend:** Vanilla JS modules with no framework and no build step. Markdown is rendered client-side with marked.js. Project name extracted from URL path for API routing.
- **Agent:** Claude Code CLI runs as a subprocess with `--input-format stream-json --output-format stream-json`, giving it full tool access and multi-turn memory. One long-lived process per project.
- **File watching:** `watchfiles` (inotify) detects saves and pushes updates over WebSocket. One watcher per active project, handles atomic writes, debounces rapid events.
- **Multi-project:** Resources (agents, file watchers, WebSocket connections) are created on demand and cleaned up after idle timeout. Sessions stored in nested directories (`sessions/{project_name}/`).

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
│   ├── session.py          # Session persistence (project-scoped)
│   ├── file_watcher.py     # inotify filesystem watcher (watchfiles)
│   ├── websocket.py        # WebSocket connection manager
│   ├── project_manager.py  # Multi-project lifecycle management
│   └── projects.py         # Project discovery and metadata
├── static/                 # Frontend (vanilla HTML/CSS/JS, no build step)
│   ├── index.html          # Three-panel layout (project UI)
│   ├── projects.html       # Project listing page (multi-project mode)
│   ├── css/
│   │   ├── style.css       # Dark-themed styles
│   │   └── projects.css    # Project listing styles
│   └── js/
│       ├── app.js          # Init, WebSocket, workspace restore
│       ├── filetree.js     # File tree panel
│       ├── document.js     # Document viewer — tabs, rendering, scroll
│       ├── chat.js         # Chat — messaging, streaming, annotations
│       ├── projects.js     # Project listing logic
│       └── marked.min.js   # Markdown parser (vendored)
├── tests/                  # Test suite (64 tests)
└── sessions/               # Saved session files (nested by project)
    ├── project-a/
    └── project-b/
```

## License

[MIT](LICENSE)
