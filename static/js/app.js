(function() {
  'use strict';

  var ws = null;
  var reconnectDelay = 1000;
  var currentSessionId = null;
  var displaced = false;  // set when the server tells us another tab took over

  function connect() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/ws');

    ws.onopen = function() {
      console.log('WebSocket connected');
      // If this is a reconnection (not the initial connect) and the
      // agent was mid-response, the old WebSocket is dead and the
      // server is still sending to it.  Clear the working indicator
      // so the UI isn't stuck.
      if (reconnectDelay > 1000 && window.Chat) {
        window.Chat.setInputEnabled(true);
      }
      reconnectDelay = 1000;
      flushPendingSends();
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
    return currentSessionId ? 'ade_workspace_' + currentSessionId : null;
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
    fetch('/api/sessions/' + currentSessionId + '/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        openTabs: window.DocPanel ? window.DocPanel.getOpenTabs() : [],
        activeTab: window.DocPanel ? window.DocPanel.getActiveTab() : null,
        agentSessionId: agentSessionId,
      }),
    });
  }

  function saveMessageToSession(role, content, annotation) {
    if (!currentSessionId) return;
    fetch('/api/sessions/' + currentSessionId + '/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: role, content: content, annotation: annotation || null }),
    });
  }

  function saveWorkspaceToServer() {
    if (!currentSessionId) return;
    fetch('/api/sessions/' + currentSessionId + '/workspace', {
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
    fetch('/api/sessions').then(function(r) { return r.json(); }).then(function(data) {
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
    fetch('/api/sessions/' + sessionId).then(function(r) { return r.json(); }).then(function(session) {
      currentSessionId = session.id;

      // Restore messages
      var messagesEl = document.getElementById('chat-messages');
      messagesEl.innerHTML = '';
      session.messages.forEach(function(msg) {
        if (window.Chat && window.Chat.addRestoredMessage) {
          window.Chat.addRestoredMessage(msg.role, msg.content, msg.annotation);
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
    fetch('/api/sessions', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(session) {
        currentSessionId = session.id;
        document.getElementById('session-picker').style.display = 'none';
        // Reset agent session so it doesn't --resume the old one
        send({ type: 'reset_agent_session' });
        // Initialize agent with warm-up file if it exists
        initAgentWithWarmup();
      });
  }

  function initAgentWithWarmup() {
    fetch('/api/config')
      .then(function(r) { return r.json(); })
      .then(function(cfg) {
        if (cfg.init_file_exists && cfg.init_file) {
          var prompt = 'Read ' + cfg.init_file + ' and follow its instructions.';
          // Show as a system-style message in chat
          if (window.Chat && window.Chat.addRestoredMessage) {
            window.Chat.addRestoredMessage('user', prompt);
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
    fetch('/api/sessions').then(function(r) { return r.json(); }).then(function(data) {
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
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (key && key.indexOf('ade_workspace_') === 0) {
          var id = key.substring('ade_workspace_'.length);
          if (!activeIds[id]) {
            keysToRemove.push(key);
          }
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

  // Auto-resume the most recent session, or create a new one
  fetch('/api/sessions').then(function(r) { return r.json(); }).then(function(data) {
    if (data.sessions && data.sessions.length > 0) {
      loadSession(data.sessions[0].id);
    } else {
      startNewSession();
    }
  });

  // Wire up session picker buttons
  document.getElementById('session-new').addEventListener('click', function() {
    // Clear chat and close tabs for fresh session
    document.getElementById('chat-messages').innerHTML = '';
    if (window.DocPanel) {
      var tabs = window.DocPanel.getOpenTabs();
      tabs.forEach(function(p) { window.DocPanel.closeFile(p); });
    }
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
