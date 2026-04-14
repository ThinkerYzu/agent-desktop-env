(function() {
  'use strict';

  // Configure marked to generate heading IDs for fragment links
  if (typeof marked !== 'undefined') {
    var renderer = new marked.Renderer();
    renderer.heading = function(data) {
      var id = data.text.toLowerCase()
        .replace(/<[^>]*>/g, '')
        .replace(/[^\w\s-]/g, '')
        .replace(/\s+/g, '-')
        .replace(/-+$/, '');
      return '<h' + data.depth + ' id="' + id + '">' + data.text + '</h' + data.depth + '>';
    };
    marked.use({ renderer: renderer });
  }

  var tabsEl = document.getElementById('doc-tabs');
  var contentEl = document.getElementById('document-content');
  var openTabs = [];   // [{path, content, scrollTop}]
  var activeTab = null;
  var currentAnnotation = null; // {file, selectedText, startLine, endLine}

  function openFile(path) {
    // If already open, just switch to it
    var existing = openTabs.find(function(t) { return t.path === path; });
    if (existing) {
      switchTab(path);
      return Promise.resolve();
    }

    return fetch('/api/file?path=' + encodeURIComponent(path))
      .then(function(r) { return r.text(); })
      .then(function(text) {
        var tab = { path: path, content: text, scrollTop: 0 };
        openTabs.push(tab);
        renderTabs();
        switchTab(path);
      });
  }

  function switchTab(path) {
    // Save scroll position of current tab
    if (activeTab) {
      var current = openTabs.find(function(t) { return t.path === activeTab; });
      if (current) {
        current.scrollTop = contentEl.scrollTop;
      }
    }

    activeTab = path;
    var tab = openTabs.find(function(t) { return t.path === path; });
    if (!tab) return;

    renderTabs();
    renderDocument(tab);
    notifyWorkspaceChanged();
  }

  function closeTab(path) {
    var idx = openTabs.findIndex(function(t) { return t.path === path; });
    if (idx === -1) return;

    openTabs.splice(idx, 1);

    if (activeTab === path) {
      if (openTabs.length > 0) {
        var newIdx = Math.min(idx, openTabs.length - 1);
        activeTab = openTabs[newIdx].path;
      } else {
        activeTab = null;
      }
    }

    renderTabs();
    if (activeTab) {
      var tab = openTabs.find(function(t) { return t.path === activeTab; });
      if (tab) renderDocument(tab);
    } else {
      contentEl.innerHTML = '<div class="placeholder">Select a file to view</div>';
    }
    notifyWorkspaceChanged();
  }

  function notifyWorkspaceChanged() {
    if (window.App && window.App.saveWorkspace) {
      window.App.saveWorkspace();
    }
  }

  // Debounced scroll save — records scroll position 2 seconds after scrolling stops
  var scrollSaveTimer = null;
  contentEl.addEventListener('scroll', function() {
    if (!activeTab) return;
    if (scrollSaveTimer) clearTimeout(scrollSaveTimer);
    scrollSaveTimer = setTimeout(function() {
      scrollSaveTimer = null;
      var tab = openTabs.find(function(t) { return t.path === activeTab; });
      if (tab) {
        tab.scrollTop = contentEl.scrollTop;
        notifyWorkspaceChanged();
      }
    }, 2000);
  });

  function renderTabs() {
    tabsEl.innerHTML = '';
    openTabs.forEach(function(tab) {
      var tabEl = document.createElement('div');
      tabEl.className = 'doc-tab' + (tab.path === activeTab ? ' active' : '');

      var nameEl = document.createElement('span');
      nameEl.className = 'doc-tab-name';
      nameEl.textContent = tab.path.split('/').pop();
      nameEl.title = tab.path;
      nameEl.addEventListener('click', function() { switchTab(tab.path); });

      var closeEl = document.createElement('span');
      closeEl.className = 'doc-tab-close';
      closeEl.textContent = '\u00D7';
      closeEl.addEventListener('click', function(e) {
        e.stopPropagation();
        closeTab(tab.path);
      });

      tabEl.appendChild(nameEl);
      tabEl.appendChild(closeEl);
      tabsEl.appendChild(tabEl);
    });
  }

  function renderDocument(tab) {
    if (typeof marked !== 'undefined' && tab.path.endsWith('.md')) {
      contentEl.innerHTML = marked.parse(tab.content);
    } else {
      var pre = document.createElement('pre');
      pre.textContent = tab.content;
      contentEl.innerHTML = '';
      contentEl.appendChild(pre);
    }
    contentEl.scrollTop = tab.scrollTop;
  }

  // Parse href into {path, fragment}
  function parseLink(href) {
    var hashIdx = href.indexOf('#');
    if (hashIdx === -1) return { path: href, fragment: null };
    return { path: href.substring(0, hashIdx), fragment: href.substring(hashIdx + 1) };
  }

  // Resolve a link path relative to the current document's directory
  function resolvePath(path) {
    if (!activeTab) return null;
    if (!path) return null;
    var dir = activeTab.lastIndexOf('/') >= 0
      ? activeTab.substring(0, activeTab.lastIndexOf('/') + 1)
      : '';
    return dir + path;
  }

  // Scroll to a fragment (anchor) in the rendered document
  function scrollToFragment(fragment) {
    if (!fragment) return;
    var target = contentEl.querySelector('#' + CSS.escape(fragment));
    if (target) {
      // Calculate offset relative to the scrollable container
      contentEl.scrollTop = target.offsetTop - contentEl.offsetTop;
    }
  }

  // Intercept clicks on .md links in rendered documents
  contentEl.addEventListener('click', function(e) {
    var link = e.target.closest('a');
    if (!link) return;

    var href = link.getAttribute('href');
    if (!href) return;

    // Only intercept relative links (not http://, mailto:)
    if (/^https?:|^mailto:/.test(href)) return;

    var parsed = parseLink(href);

    // Same-document fragment link (#section)
    if (!parsed.path && parsed.fragment) {
      e.preventDefault();
      scrollToFragment(parsed.fragment);
      return;
    }

    // Only intercept .md links
    if (!parsed.path.endsWith('.md')) return;

    e.preventDefault();
    var resolved = resolvePath(parsed.path);
    if (resolved) {
      openFile(resolved);
      // Scroll to fragment after the document loads
      if (parsed.fragment) {
        // Small delay for the fetch + render to complete
        setTimeout(function() { scrollToFragment(parsed.fragment); }, 300);
      }
    }
  });

  // Update tab content when file changes (called from app.js for live updates)
  function updateFile(path, content) {
    var tab = openTabs.find(function(t) { return t.path === path; });
    if (tab) {
      tab.content = content;
      if (activeTab === path) {
        // Preserve scroll position across re-render
        tab.scrollTop = contentEl.scrollTop;
        renderDocument(tab);
      }
    }
  }

  // ── Annotation ──

  // Estimate line number from selected text within the raw file content
  function estimateLineRange(fileContent, selectedText) {
    var idx = fileContent.indexOf(selectedText);
    if (idx === -1) return { startLine: null, endLine: null };
    var before = fileContent.substring(0, idx);
    var startLine = before.split('\n').length;
    var endLine = startLine + selectedText.split('\n').length - 1;
    return { startLine: startLine, endLine: endLine };
  }

  contentEl.addEventListener('mouseup', function() {
    var sel = window.getSelection();
    var text = sel.toString().trim();

    if (!text || !activeTab) {
      clearAnnotation();
      return;
    }

    var tab = openTabs.find(function(t) { return t.path === activeTab; });
    if (!tab) return;

    var lines = estimateLineRange(tab.content, text);

    currentAnnotation = {
      file: activeTab,
      selectedText: text,
      startLine: lines.startLine,
      endLine: lines.endLine,
    };

    // Notify chat panel
    if (window.Chat && window.Chat.setAnnotation) {
      window.Chat.setAnnotation(currentAnnotation);
    }
  });

  function clearAnnotation() {
    currentAnnotation = null;
    if (window.Chat && window.Chat.setAnnotation) {
      window.Chat.setAnnotation(null);
    }
  }

  // Expose public API
  window.DocPanel = {
    openFile: openFile,
    closeFile: closeTab,
    updateFile: updateFile,
    clearAnnotation: clearAnnotation,
    getActiveTab: function() { return activeTab; },
    getOpenTabs: function() { return openTabs.map(function(t) { return t.path; }); },
    getAnnotation: function() { return currentAnnotation; },
    getScrollPositions: function() {
      // Save current active tab's scroll before collecting
      if (activeTab) {
        var cur = openTabs.find(function(t) { return t.path === activeTab; });
        if (cur) cur.scrollTop = contentEl.scrollTop;
      }
      var positions = {};
      openTabs.forEach(function(t) { positions[t.path] = t.scrollTop; });
      return positions;
    },
    setScrollPositions: function(positions) {
      openTabs.forEach(function(t) {
        if (positions[t.path] !== undefined) {
          t.scrollTop = positions[t.path];
        }
      });
      // Apply to active tab
      if (activeTab) {
        var cur = openTabs.find(function(t) { return t.path === activeTab; });
        if (cur) contentEl.scrollTop = cur.scrollTop;
      }
    },
  };
})();
