(function() {
  'use strict';

  // Extract project name from URL path (e.g., /myproject -> "myproject")
  var projectName = window.location.pathname.split('/').filter(Boolean)[0];
  if (!projectName) {
    console.error('No project name in URL');
    document.body.innerHTML = '<div style="color:#f88;padding:2rem;text-align:center;">Error: No project specified in URL</div>';
    return;
  }

  var ws = null;
  var reconnectDelay = 1000;
  var currentSessionId = null;
  var currentAgentSessionId = null;  // tracked so we can re-send on WS reconnect
  var displaced = false;  // set when the server tells us another tab took over

  function connect() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/ws/' + projectName);

    ws.onopen = function() {
      console.log('WebSocket connected');
      var isReconnect = reconnectDelay > 1000;
      reconnectDelay = 1000;
      flushPendingSends();
      // On reconnect, the final streaming=false message may have been
      // dropped by the server's send_active() because the old ws was
      // already gone.  Ask the server whether a turn is actually in
      // progress and let the `status` reply drive the indicator.
      if (isReconnect) {
        send({ type: 'status_query' });
        // Re-sync the agent session so the server resumes the right
        // conversation even if it restarted or idle-cleaned while we
        // were disconnected.
        if (currentAgentSessionId) {
          send({ type: 'restore_agent_session', payload: { agentSessionId: currentAgentSessionId } });
        }
      }
    };

    ws.onmessage = function(event) {
      try {
        var msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onclose = function(event) {
      // Close code 4001 = displaced by another tab/window.
      if (event.code === 4001) {
        displaced = true;
        showDisplacedBanner();
        console.log('WebSocket displaced by another tab — not reconnecting');
        return;
      }
      if (displaced) {
        return;
      }
      console.log('WebSocket disconnected, reconnecting in', reconnectDelay, 'ms');
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    };

    ws.onerror = function(err) {
      console.error('WebSocket error:', err);
      ws.close();
    };
  }

  function showDisplacedBanner() {
    if (document.getElementById('ade-displaced-banner')) return;
    var banner = document.createElement('div');
    banner.id = 'ade-displaced-banner';
    banner.style.cssText =
      'position:fixed;top:0;left:0;right:0;background:#b00;color:#fff;' +
      'padding:12px;text-align:center;z-index:99999;font-family:sans-serif;';
    banner.textContent =
      'This tab was disconnected because another ADE tab took over. Reload to use this tab instead.';
    document.body.appendChild(banner);
  }

  function handleMessage(msg) {
    if (msg.type === 'status') {
      if (window.Chat && window.Chat.setInputEnabled) {
        window.Chat.setInputEnabled(!msg.payload.turn_active);
      }
      return;
    }
    if (msg.type === 'doc_update') {
      var payload = msg.payload;
      // Update open document on modify or create (atomic writes use delete+create)
      if ((payload.event === 'modified' || payload.event === 'created') && payload.content && window.DocPanel) {
        window.DocPanel.updateFile(payload.path, payload.content);
      }
      // Close tab when file is deleted
      if (payload.event === 'deleted' && window.DocPanel) {
        window.DocPanel.closeFile(payload.path);
      }
      // Refresh file tree on create/delete, then highlight
      if (payload.event === 'created' || payload.event === 'deleted') {
        if (window.FileTree) {
          window.FileTree.refresh();
          setTimeout(function() {
            if (payload.event === 'created') {
              window.FileTree.highlightFile(payload.path);
            }
          }, 600);
        }
      } else if (payload.event === 'modified' && window.FileTree) {
        window.FileTree.highlightFile(payload.path);
      }
    } else if (msg.type === 'chat') {
      if (window.Chat) {
        window.Chat.handleChat(msg.payload);
      }
      if (msg.payload.role === 'assistant' && !msg.payload.streaming && currentSessionId) {
        if (msg.payload.session_id) {
          saveAgentSessionId(msg.payload.session_id);
        }
      }
    } else if (msg.type === 'eval') {
      var result = null;
      var error = null;
      try {
        result = String(eval(msg.payload.code));
      } catch (e) {
        error = e.message;
      }
      send({
        type: 'eval_result',
        id: msg.id,
        payload: { result: result, error: error }
      });
    }
  }

  var pendingSends = [];

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    } else {
      pendingSends.push(msg);
    }
  }

  function flushPendingSends() {
    while (pendingSends.length > 0 && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(pendingSends.shift()));
    }
  }

  // ── localStorage workspace persistence ──

  function workspaceKey() {
    return currentSessionId ? 'ade_workspace_' + projectName + '_' + currentSessionId : null;
  }

  function saveWorkspaceToLocal() {
    var key = workspaceKey();
    if (!key || !window.DocPanel) return;
    var state = {
      openTabs: window.DocPanel.getOpenTabs(),
      activeTab: window.DocPanel.getActiveTab(),
      scrollPositions: window.DocPanel.getScrollPositions ? window.DocPanel.getScrollPositions() : {},
    };
    try {
      localStorage.setItem(key, JSON.stringify(state));
    } catch (e) {
      // localStorage full or unavailable — ignore
    }
  }

  function loadWorkspaceFromLocal() {
    var key = workspaceKey();
    if (!key) return null;
    try {
      var data = localStorage.getItem(key);
      return data ? JSON.parse(data) : null;
    } catch (e) {
      return null;
    }
  }

  function restoreWorkspace(workspace) {
    if (!workspace || !window.DocPanel) return;
    var tabs = workspace.openTabs || [];
    var active = workspace.activeTab;
    var scrolls = workspace.scrollPositions || {};

    // Open tabs sequentially to preserve order
    var chain = Promise.resolve();
    tabs.forEach(function(path) {
      chain = chain.then(function() {
        return window.DocPanel.openFile(path);
      });
    });

    chain.then(function() {
      // Switch to active tab after all tabs are loaded
      if (active) {
        window.DocPanel.openFile(active);
      }
      // Restore scroll positions
      if (window.DocPanel.setScrollPositions) {
        window.DocPanel.setScrollPositions(scrolls);
      }
    });
  }

  // ── Session management ──

  function saveAgentSessionId(agentSessionId) {
    if (!currentSessionId) return;
    currentAgentSessionId = agentSessionId;
    fetch('/api/' + projectName + '/sessions/' + currentSessionId + '/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        openTabs: window.DocPanel ? window.DocPanel.getOpenTabs() : [],
        activeTab: window.DocPanel ? window.DocPanel.getActiveTab() : null,
        agentSessionId: agentSessionId,
      }),
    });
  }

  function saveMessageToSession(role, content, annotation, extra) {
    if (!currentSessionId) return;
    var body = { role: role, content: content, annotation: annotation || null };
    if (extra) Object.assign(body, extra);
    fetch('/api/' + projectName + '/sessions/' + currentSessionId + '/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  function saveWorkspaceToServer() {
    if (!currentSessionId) return;
    fetch('/api/' + projectName + '/sessions/' + currentSessionId + '/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        openTabs: window.DocPanel ? window.DocPanel.getOpenTabs() : [],
        activeTab: window.DocPanel ? window.DocPanel.getActiveTab() : null,
      }),
    });
  }

  // Debounced workspace save — called on tab changes
  var workspaceSaveTimer = null;
  function debouncedWorkspaceSave() {
    if (workspaceSaveTimer) clearTimeout(workspaceSaveTimer);
    workspaceSaveTimer = setTimeout(function() {
      workspaceSaveTimer = null;
      saveWorkspaceToLocal();
      saveWorkspaceToServer();
    }, 500);
  }

  function showSessionPicker() {
    fetch('/api/' + projectName + '/sessions').then(function(r) { return r.json(); }).then(function(data) {
      var sessions = data.sessions || [];
      var picker = document.getElementById('session-picker');
      var list = document.getElementById('session-list');
      list.innerHTML = '';

      sessions.forEach(function(s) {
        var item = document.createElement('div');
        item.className = 'session-item';
        item.innerHTML =
          '<div class="session-item-preview">' + (s.preview || '(empty)') + '</div>' +
          '<div class="session-item-meta">' + s.messageCount + ' messages &middot; ' +
          new Date(s.lastActive).toLocaleString() + '</div>';
        item.addEventListener('click', function() {
          loadSession(s.id);
          picker.style.display = 'none';
        });
        list.appendChild(item);
      });

      picker.style.display = 'flex';
    });
  }

  function loadSession(sessionId) {
    fetch('/api/' + projectName + '/sessions/' + sessionId).then(function(r) { return r.json(); }).then(function(session) {
      currentSessionId = session.id;
      // Remember which session this tab is on so reload picks it up
      // again (instead of falling back to "most recently messaged").
      try { localStorage.setItem('ade_active_session', session.id); } catch (e) {}

      // Restore messages
      var messagesEl = document.getElementById('chat-messages');
      messagesEl.innerHTML = '';
      session.messages.forEach(function(msg) {
        if (window.Chat && window.Chat.addRestoredMessage) {
          window.Chat.addRestoredMessage(msg);
        }
      });

      // Restore workspace — prefer localStorage (has scroll positions), fall back to server
      var localWs = loadWorkspaceFromLocal();
      if (localWs && localWs.openTabs && localWs.openTabs.length > 0) {
        restoreWorkspace(localWs);
      } else {
        var serverWs = session.workspace || {};
        restoreWorkspace(serverWs);
      }

      // Restore agent session.  Always notify the server so any
      // process from a previous session is terminated; only pass
      // an agentSessionId if this session has one (otherwise the
      // next message starts a fresh conversation).
      currentAgentSessionId = session.agentSessionId || null;
      if (session.agentSessionId) {
        send({
          type: 'restore_agent_session',
          payload: { agentSessionId: session.agentSessionId },
        });
      } else {
        send({ type: 'reset_agent_session' });
      }
    });
  }

  function startNewSession() {
    // Snapshot current workspace before switching sessions so the new session
    // inherits open tabs and scroll positions.
    var inheritedWs = null;
    if (window.DocPanel) {
      inheritedWs = {
        openTabs: window.DocPanel.getOpenTabs(),
        activeTab: window.DocPanel.getActiveTab(),
        scrollPositions: window.DocPanel.getScrollPositions ? window.DocPanel.getScrollPositions() : {},
      };
    }

    fetch('/api/' + projectName + '/sessions', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(session) {
        currentSessionId = session.id;
        currentAgentSessionId = null;
        try { localStorage.setItem('ade_active_session', session.id); } catch (e) {}

        // Persist inherited workspace so a page reload restores the same tabs
        if (inheritedWs && inheritedWs.openTabs && inheritedWs.openTabs.length > 0) {
          // localStorage (includes scroll positions)
          var key = workspaceKey();
          try { localStorage.setItem(key, JSON.stringify(inheritedWs)); } catch (e) {}
          // Server (open tabs + active tab, no scroll positions)
          fetch('/api/' + projectName + '/sessions/' + currentSessionId + '/workspace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ openTabs: inheritedWs.openTabs, activeTab: inheritedWs.activeTab }),
          });
        }

        document.getElementById('session-picker').style.display = 'none';
        // Reset agent session so it doesn't --resume the old one
        send({ type: 'reset_agent_session' });
        // Initialize agent with warm-up file if it exists
        initAgentWithWarmup();
      });
  }

  function initAgentWithWarmup() {
    fetch('/api/' + projectName + '/config')
      .then(function(r) { return r.json(); })
      .then(function(cfg) {
        if (cfg.init_file_exists && cfg.init_file) {
          var prompt = 'Read ' + cfg.init_file + ' and follow its instructions.';
          // Show as a system-style message in chat
          if (window.Chat && window.Chat.addRestoredMessage) {
            window.Chat.addRestoredMessage({ role: 'user', content: prompt });
          }
          // Save to session
          saveMessageToSession('user', prompt);
          // Send to agent
          send({
            type: 'chat',
            payload: { role: 'user', content: prompt },
          });
          // Disable input and show working indicator
          if (window.Chat && window.Chat.setInputEnabled) {
            window.Chat.setInputEnabled(false);
          }
        }
      });
  }

  // ── Stale localStorage cleanup ──

  function cleanupStaleWorkspaces() {
    var MAX_AGE_MS = 180 * 24 * 60 * 60 * 1000; // 180 days
    fetch('/api/' + projectName + '/sessions').then(function(r) { return r.json(); }).then(function(data) {
      var sessions = data.sessions || [];
      var activeIds = {};
      var now = Date.now();
      sessions.forEach(function(s) {
        var age = now - new Date(s.lastActive).getTime();
        if (age < MAX_AGE_MS) {
          activeIds[s.id] = true;
        }
      });

      // Remove localStorage keys for sessions that are stale or no longer exist
      var keysToRemove = [];
      var prefix = 'ade_workspace_' + projectName + '_';
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (key && key.indexOf(prefix) === 0) {
          var id = key.substring(prefix.length);
          if (!activeIds[id]) {
            keysToRemove.push(key);
          }
        }
        // Also clean up old format keys (without project name)
        else if (key && key.match(/^ade_workspace_[a-f0-9-]+$/)) {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach(function(key) {
        localStorage.removeItem(key);
      });
      if (keysToRemove.length > 0) {
        console.log('Cleaned up ' + keysToRemove.length + ' stale workspace(s) from localStorage');
      }
    });
  }

  // ── Init ──

  // Expose for other modules
  window.App = {
    send: send,
    saveMessage: saveMessageToSession,
    saveWorkspace: debouncedWorkspaceSave,
    getSessionId: function() { return currentSessionId; },
  };

  connect();
  cleanupStaleWorkspaces();

  // Resume this tab's previously-active session if we have one saved;
  // otherwise fall back to the most recently messaged session, or
  // create a new one.
  fetch('/api/' + projectName + '/sessions').then(function(r) { return r.json(); }).then(function(data) {
    var sessions = data.sessions || [];
    var saved = null;
    try { saved = localStorage.getItem('ade_active_session'); } catch (e) {}
    var picked = null;
    if (saved && sessions.some(function(s){ return s.id === saved; })) {
      picked = saved;
    } else if (sessions.length > 0) {
      picked = sessions[0].id;
    }
    if (picked) {
      loadSession(picked);
    } else {
      startNewSession();
    }
  });

  // Wire up session picker buttons
  document.getElementById('session-new').addEventListener('click', function() {
    // Clear chat messages only; tabs are inherited by the new session
    document.getElementById('chat-messages').innerHTML = '';
    if (window.Chat && window.Chat.reset) window.Chat.reset();
    startNewSession();
  });
  document.getElementById('session-picker-close').addEventListener('click', function() {
    document.getElementById('session-picker').style.display = 'none';
  });

  // Wire up session switch button in chat header
  var switchBtn = document.getElementById('session-switch');
  if (switchBtn) {
    switchBtn.addEventListener('click', showSessionPicker);
  }
})();
