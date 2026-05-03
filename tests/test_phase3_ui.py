"""
Phase 3 UI verification tests: Browser-side behavior via WebSocket eval channel.

The eval channel lets pytest send JS to the browser through the app's own
WebSocket and get results back. No external browser automation needed.

Prerequisites:
    - Server running: ./run.sh &
    - Browser tab open at http://localhost:9800

Run:
    source venv/bin/activate && python -m pytest tests/test_phase3_ui.py -v
"""

import asyncio
import json
import time
import uuid
from pathlib import Path

import pytest
import websockets

PROJECT_NAME = "agent-desktop-env"
WS_URL = f"ws://127.0.0.1:9800/ws/{PROJECT_NAME}"
WS_EVAL_URL = f"ws://127.0.0.1:9800/ws/{PROJECT_NAME}?eval=true"
PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "proj_docs" / "agent-desktop-env"


async def browser_eval(code, timeout=5.0):
    """Send JS code to the browser via eval channel and return the result."""
    eval_id = str(uuid.uuid4())
    async with websockets.connect(WS_EVAL_URL) as ws:
        await ws.send(json.dumps({
            "type": "eval",
            "id": eval_id,
            "payload": {"code": code},
        }))

        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"No eval_result for id={eval_id}")
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
            data = json.loads(msg)
            if data.get("type") == "eval_result" and data.get("id") == eval_id:
                payload = data["payload"]
                if payload.get("error"):
                    raise RuntimeError(f"Browser eval error: {payload['error']}")
                return payload.get("result")


def eval_js(code, timeout=5.0):
    """Synchronous wrapper for browser_eval."""
    return asyncio.run(browser_eval(code, timeout))


def reload_and_wait():
    """Reload the page with clean state and wait for it to settle."""
    # Clear localStorage to prevent auto-resume restoring stale tabs
    eval_js("localStorage.clear()")
    eval_js("location.reload()")
    time.sleep(2)
    # Dismiss session picker if it appears
    try:
        eval_js("""
          (function() {
            var picker = document.getElementById('session-picker');
            if (picker && picker.style.display !== 'none') {
              document.getElementById('session-new').click();
            }
          })()
        """)
    except Exception:
        pass
    time.sleep(0.5)
    # Close all open tabs to start with a clean document panel
    eval_js("""
      (function() {
        if (window.DocPanel) {
          var tabs = window.DocPanel.getOpenTabs();
          tabs.forEach(function(path) { window.DocPanel.closeFile(path); });
        }
      })()
    """)
    time.sleep(0.3)


def get_tree_names():
    return eval_js("""
      (function() {
        var names = document.querySelectorAll('.tree-name');
        var r = [];
        names.forEach(function(n) { r.push(n.textContent); });
        return r.join(',');
      })()
    """)


def get_tab_names():
    return eval_js("""
      (function() {
        var tabs = document.querySelectorAll('.doc-tab-name');
        var r = [];
        tabs.forEach(function(t) { r.push(t.textContent); });
        return r.join(',');
      })()
    """)


def get_doc_html():
    return eval_js("document.getElementById('document-content').innerHTML")


def open_file(path):
    result = eval_js(f"""
      (function() {{
        var labels = document.querySelectorAll('.tree-label');
        for (var i = 0; i < labels.length; i++) {{
          if (labels[i].dataset.path === '{path}') {{
            labels[i].click();
            return 'opened';
          }}
        }}
        return 'not found';
      }})()
    """)
    assert "opened" in result, f"Could not open {path}: {result}"
    time.sleep(0.5)


# ── File Tree Tests ──


class TestFileTree:

    def test_file_tree_loads(self):
        """File tree shows project files on page load."""
        reload_and_wait()
        names = get_tree_names()
        assert "SPEC.md" in names
        assert "DESIGN.md" in names
        assert "logs" in names

    def test_directory_expands(self):
        """Clicking a directory expands to show children."""
        reload_and_wait()
        eval_js("""
          (function() {
            var labels = document.querySelectorAll('.tree-label');
            for (var i = 0; i < labels.length; i++) {
              if (labels[i].dataset.path === 'logs' && labels[i].dataset.type === 'directory') {
                labels[i].click(); break;
              }
            }
          })()
        """)
        time.sleep(0.5)
        names = get_tree_names()
        assert "SESSION-LOG-TEMPLATE.md" in names

    def test_no_duplicate_trees_on_file_change(self):
        """Modifying a file does not duplicate the file tree."""
        reload_and_wait()
        count_before = int(eval_js("document.querySelectorAll('.tree-node').length"))
        # Trigger a file change
        test_file = PROJECT_DIR / "_test_nodup.md"
        test_file.write_text("test\n")
        time.sleep(2)
        try:
            count_after = int(eval_js("document.querySelectorAll('.tree-node').length"))
            # Should have exactly one more node (the new file), not doubled
            assert count_after <= count_before + 1
        finally:
            test_file.unlink(missing_ok=True)

    def test_file_tree_refreshes_on_new_file(self):
        """Creating a new file adds it to the file tree."""
        test_file = PROJECT_DIR / "_test_ui_newfile.md"
        test_file.unlink(missing_ok=True)
        reload_and_wait()
        try:
            test_file.write_text("# New\n")
            time.sleep(2)
            names = get_tree_names()
            assert "_test_ui_newfile.md" in names
        finally:
            test_file.unlink(missing_ok=True)

    def test_file_tree_refreshes_on_delete(self):
        """Deleting a file removes it from the file tree."""
        test_file = PROJECT_DIR / "_test_ui_delfile.md"
        test_file.write_text("# Delete me\n")
        time.sleep(1)
        reload_and_wait()
        names = get_tree_names()
        assert "_test_ui_delfile.md" in names
        try:
            test_file.unlink()
            time.sleep(2)
            names = get_tree_names()
            assert "_test_ui_delfile.md" not in names
        finally:
            test_file.unlink(missing_ok=True)


# ── Document Viewer Tests ──


class TestDocumentViewer:

    def test_open_markdown_renders_html(self):
        """Clicking a .md file renders it as HTML."""
        reload_and_wait()
        open_file("SPEC.md")
        html = get_doc_html()
        assert "<h1" in html
        assert "Coding Agent Desktop Environment" in html

    def test_tab_appears(self):
        """Opening a file creates a tab."""
        reload_and_wait()
        open_file("SPEC.md")
        tabs = get_tab_names()
        assert "SPEC.md" in tabs

    def test_multiple_tabs(self):
        """Opening two files creates two tabs."""
        reload_and_wait()
        open_file("SPEC.md")
        open_file("DESIGN.md")
        tabs = get_tab_names()
        assert "SPEC.md" in tabs
        assert "DESIGN.md" in tabs

    def test_tab_switch(self):
        """Clicking a tab switches the document."""
        reload_and_wait()
        open_file("SPEC.md")
        open_file("DESIGN.md")
        html = get_doc_html()
        assert "Design Philosophy" in html

        # Switch back to SPEC.md
        eval_js("""
          (function() {
            var tabs = document.querySelectorAll('.doc-tab-name');
            for (var i = 0; i < tabs.length; i++) {
              if (tabs[i].textContent === 'SPEC.md') { tabs[i].click(); break; }
            }
          })()
        """)
        time.sleep(0.3)
        html = get_doc_html()
        assert "Problem Statement" in html

    def test_close_tab(self):
        """Closing a tab removes it and shows placeholder."""
        reload_and_wait()
        open_file("SPEC.md")
        eval_js("""
          (function() {
            var close = document.querySelector('.doc-tab-close');
            if (close) close.click();
          })()
        """)
        time.sleep(0.3)
        tabs = get_tab_names()
        assert "SPEC.md" not in tabs
        html = get_doc_html()
        assert "Select a file to view" in html

    def test_reopen_same_file_no_duplicate_tab(self):
        """Opening an already-open file just switches to it."""
        reload_and_wait()
        open_file("SPEC.md")
        open_file("SPEC.md")
        count = int(eval_js("""
          document.querySelectorAll('.doc-tab-name').length
        """))
        assert count == 1

    def test_md_link_opens_tab(self):
        """Clicking a .md link in rendered doc opens a new tab instead of navigating."""
        reload_and_wait()
        open_file("SPEC.md")
        # Click the DESIGN.md link in the rendered content
        result = eval_js("""
          (function() {
            var links = document.querySelectorAll('#document-content a');
            for (var i = 0; i < links.length; i++) {
              var href = links[i].getAttribute('href');
              if (href && href.indexOf('DESIGN.md') >= 0) {
                links[i].click();
                return 'clicked';
              }
            }
            return 'no link found';
          })()
        """)
        assert "clicked" in result
        time.sleep(0.5)
        tabs = get_tab_names()
        assert "SPEC.md" in tabs
        assert "DESIGN.md" in tabs
        # Verify we're still on port 9800 (not navigated away)
        url = eval_js("location.href")
        assert ":9800" in url

    def test_fragment_link_scrolls(self):
        """Clicking a #fragment link scrolls to the heading in the same document."""
        reload_and_wait()
        open_file("DESIGN.md")
        eval_js("document.getElementById('document-content').scrollTop = 0")
        time.sleep(0.3)
        # Click a TOC fragment link
        result = eval_js("""
          (function() {
            var links = document.querySelectorAll('#document-content a');
            for (var i = 0; i < links.length; i++) {
              if (links[i].getAttribute('href') === '#data-model') {
                links[i].click();
                return 'clicked';
              }
            }
            return 'no fragment link found';
          })()
        """)
        assert "clicked" in result
        # Wait for smooth scroll to complete
        time.sleep(1.5)
        scroll = float(eval_js("document.getElementById('document-content').scrollTop"))
        assert scroll > 100, f"Expected scroll > 100 after fragment click, got {scroll}"

    def test_cross_file_fragment_link(self):
        """Clicking a file.md#section link opens the file and scrolls to the section."""
        reload_and_wait()
        open_file("SPEC.md")
        # Inject a test link to DESIGN.md#testing-architecture
        eval_js("""
          (function() {
            var link = document.createElement('a');
            link.href = 'DESIGN.md#testing-architecture';
            link.textContent = 'test';
            link.id = '_test_fragment_link';
            document.getElementById('document-content').appendChild(link);
          })()
        """)
        eval_js("document.getElementById('_test_fragment_link').click()")
        # Wait for file load + smooth scroll
        time.sleep(2)
        tabs = get_tab_names()
        assert "DESIGN.md" in tabs
        scroll = float(eval_js("document.getElementById('document-content').scrollTop"))
        assert scroll > 100, f"Expected scroll > 100 for cross-file fragment, got {scroll}"


# ── Live Update Tests ──


class TestLiveUpdates:

    def test_open_doc_updates_on_modify(self):
        """An open document re-renders when its file changes."""
        test_file = PROJECT_DIR / "_test_ui_live.md"
        test_file.write_text("# Version 1\n")
        time.sleep(1)
        try:
            reload_and_wait()
            open_file("_test_ui_live.md")
            html = get_doc_html()
            assert "Version 1" in html

            test_file.write_text("# Version 2\n\nNew paragraph.\n")
            time.sleep(2)

            html = get_doc_html()
            assert "Version 2" in html
            assert "New paragraph" in html
        finally:
            test_file.unlink(missing_ok=True)

    def test_background_tab_updates(self):
        """A background tab has updated content when switched to."""
        test_file = PROJECT_DIR / "_test_ui_bgtab.md"
        test_file.write_text("# BG V1\n")
        time.sleep(1)
        try:
            reload_and_wait()
            open_file("_test_ui_bgtab.md")
            open_file("SPEC.md")  # Switch away

            test_file.write_text("# BG V2\n")
            time.sleep(2)

            # Switch back
            eval_js("""
              (function() {
                var tabs = document.querySelectorAll('.doc-tab-name');
                for (var i = 0; i < tabs.length; i++) {
                  if (tabs[i].textContent === '_test_ui_bgtab.md') { tabs[i].click(); break; }
                }
              })()
            """)
            time.sleep(0.5)
            html = get_doc_html()
            assert "BG V2" in html
        finally:
            test_file.unlink(missing_ok=True)

    def test_scroll_preserved_on_live_update(self):
        """Scroll position is preserved when an open document is updated."""
        # Create a long file so there's something to scroll
        test_file = PROJECT_DIR / "_test_ui_scroll.md"
        lines = ["# Scroll Test\n"] + [f"Line {i}\n" for i in range(200)]
        test_file.write_text("\n".join(lines))
        time.sleep(1)
        try:
            reload_and_wait()
            open_file("_test_ui_scroll.md")

            # Scroll to a specific position
            eval_js("document.getElementById('document-content').scrollTop = 800")
            time.sleep(0.3)
            before = float(eval_js("document.getElementById('document-content').scrollTop"))
            assert before > 700, f"Expected scrollTop > 700, got {before}"

            # Modify the file
            lines.append("# Appended section\n")
            test_file.write_text("\n".join(lines))
            time.sleep(2)

            after = float(eval_js("document.getElementById('document-content').scrollTop"))
            # Allow small delta from re-render differences
            assert abs(after - before) < 50, \
                f"Scroll position not preserved: before={before}, after={after}"
        finally:
            test_file.unlink(missing_ok=True)

    def test_tab_closed_on_file_delete(self):
        """Deleting a file automatically closes its open tab."""
        test_file = PROJECT_DIR / "_test_ui_closetab.md"
        test_file.write_text("# Close on delete\n")
        time.sleep(1)
        try:
            reload_and_wait()
            open_file("SPEC.md")
            open_file("_test_ui_closetab.md")
            tabs = get_tab_names()
            assert "_test_ui_closetab.md" in tabs

            test_file.unlink()
            time.sleep(2)

            tabs = get_tab_names()
            assert "_test_ui_closetab.md" not in tabs
            # Other tab should still be there
            assert "SPEC.md" in tabs
        finally:
            test_file.unlink(missing_ok=True)

    def test_rapid_edits_no_corruption(self):
        """Rapid edits produce a consistent final render."""
        test_file = PROJECT_DIR / "_test_ui_rapid.md"
        test_file.write_text("# V0\n")
        time.sleep(1)
        try:
            reload_and_wait()
            open_file("_test_ui_rapid.md")

            for i in range(1, 6):
                test_file.write_text(f"# V{i}\n\nContent {i}\n")
                time.sleep(0.2)

            time.sleep(3)
            html = get_doc_html()
            assert "V5" in html
            assert "Content 5" in html
        finally:
            test_file.unlink(missing_ok=True)
