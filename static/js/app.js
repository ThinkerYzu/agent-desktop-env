(function() {
  'use strict';

  var ws = null;
  var reconnectDelay = 1000;
  var currentSessionId = null;

  function connect() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/ws');

    ws.onopen = function() {
      console.log('WebSocket connected');
      reconnectDelay = 1000;
    };

    ws.onmessage = function(event) {
      try {
        var msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onclose = function() {
      console.log('WebSocket disconnected, reconnecting in', reconnectDelay, 'ms');
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    };

    ws.onerror = function(err) {
      console.error('WebSocket error:', err);
      ws.close();
    };
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
          // Highlight after refresh rebuilds the DOM (debounce is 300ms + fetch time)
          setTimeout(function() {
            if (payload.event === 'created') {
              window.FileTree.highlightFile(payload.path);
            }
          }, 600);
        }
      } else if (payload.event === 'modified' && window.FileTree) {
        // Modified events don't refresh the tree, so highlight immediately
        window.FileTree.highlightFile(payload.path);
      }
    } else if (msg.type === 'chat') {
      if (window.Chat) {
        window.Chat.handleChat(msg.payload);
      }
      // Save assistant messages to session
      if (msg.payload.role === 'assistant' && !msg.payload.streaming && currentSessionId) {
        // Save the agent session ID if provided
        if (msg.payload.session_id) {
          saveAgentSessionId(msg.payload.session_id);
        }
      }
    } else if (msg.type === 'eval') {
      // Test backdoor: execute JS and send result back
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

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  // ── Session management ──

  function saveAgentSessionId(agentSessionId) {
    if (!currentSessionId) return;
    fetch('/api/sessions/' + currentSessionId, {
      method: 'GET',
    }).then(function(r) { return r.json(); }).then(function(session) {
      if (session.id) {
        session.agentSessionId = agentSessionId;
        // Save via workspace endpoint (piggyback)
        fetch('/api/sessions/' + currentSessionId + '/workspace', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            openTabs: window.DocPanel ? window.DocPanel.getOpenTabs() : [],
            activeTab: window.DocPanel ? window.DocPanel.getActiveTab() : null,
          }),
        });
      }
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

  function saveWorkspace() {
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

      // Restore workspace
      var ws = session.workspace || {};
      if (ws.openTabs && window.DocPanel) {
        ws.openTabs.forEach(function(path) {
          window.DocPanel.openFile(path);
        });
        if (ws.activeTab) {
          setTimeout(function() {
            window.DocPanel.openFile(ws.activeTab);
          }, 200);
        }
      }

      // Restore agent session
      if (session.agentSessionId) {
        // Tell server to resume this agent session
        send({
          type: 'restore_agent_session',
          payload: { agentSessionId: session.agentSessionId },
        });
      }
    });
  }

  function startNewSession() {
    fetch('/api/sessions', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(session) {
        currentSessionId = session.id;
        document.getElementById('session-picker').style.display = 'none';
      });
  }

  // ── Init ──

  // Expose for other modules
  window.App = {
    send: send,
    saveMessage: saveMessageToSession,
    saveWorkspace: saveWorkspace,
    getSessionId: function() { return currentSessionId; },
  };

  connect();

  // Check for existing sessions on startup
  fetch('/api/sessions').then(function(r) { return r.json(); }).then(function(data) {
    if (data.sessions && data.sessions.length > 0) {
      showSessionPicker();
    } else {
      startNewSession();
    }
  });

  // Wire up session picker buttons
  document.getElementById('session-new').addEventListener('click', startNewSession);
  document.getElementById('session-picker-close').addEventListener('click', function() {
    startNewSession();
  });
})();
