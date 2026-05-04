(function() {
  'use strict';

  var messagesEl = document.getElementById('chat-messages');
  var inputEl = document.getElementById('chat-input');
  var sendBtn = document.getElementById('chat-send');
  var inputArea = document.getElementById('chat-input-area');
  var currentAssistantEl = null;
  var currentAssistantText = '';
  var pendingAnnotation = null;
  var agentStatusEl = null;
  // Per-turn block tracking (tool_use + thinking blocks interleaved)
  var blocks = [];           // all block elements for the current turn, in order
  var currentTurnMsgEl = null;  // the .chat-message div for the current turn
  var olderCollapseEl = null;   // collapse container for older blocks
  var BLOCK_VISIBLE_COUNT = 3;  // how many most-recent blocks stay visible

  // ── Annotation badge ──

  var badgeEl = null;

  function createBadge() {
    badgeEl = document.createElement('div');
    badgeEl.className = 'annotation-badge';
    badgeEl.style.display = 'none';
    inputArea.insertBefore(badgeEl, inputArea.firstChild);
  }
  createBadge();

  function setAnnotation(annotation) {
    pendingAnnotation = annotation;
    if (annotation) {
      var preview = annotation.selectedText;
      if (preview.length > 60) preview = preview.substring(0, 60) + '...';
      var lineInfo = '';
      if (annotation.startLine) {
        lineInfo = ' L' + annotation.startLine;
        if (annotation.endLine && annotation.endLine !== annotation.startLine) {
          lineInfo += '-' + annotation.endLine;
        }
      }
      badgeEl.innerHTML = '';

      var fileSpan = document.createElement('span');
      fileSpan.className = 'annotation-badge-file';
      fileSpan.textContent = annotation.file.split('/').pop() + lineInfo;

      var textSpan = document.createElement('span');
      textSpan.className = 'annotation-badge-text';
      textSpan.textContent = preview;

      var closeSpan = document.createElement('span');
      closeSpan.className = 'annotation-badge-close';
      closeSpan.textContent = '\u00D7';
      closeSpan.addEventListener('click', function(e) {
        e.stopPropagation();
        setAnnotation(null);
        if (window.DocPanel) window.DocPanel.clearAnnotation();
      });

      badgeEl.appendChild(fileSpan);
      badgeEl.appendChild(textSpan);
      badgeEl.appendChild(closeSpan);
      badgeEl.style.display = 'flex';
    } else {
      badgeEl.style.display = 'none';
    }
  }

  // ── Messages ──

  function addMessage(role, content, annotation) {
    var msgEl = document.createElement('div');
    msgEl.className = 'chat-message chat-message-' + role;

    var roleEl = document.createElement('div');
    roleEl.className = 'chat-role';
    roleEl.textContent = role === 'user' ? 'You' : 'Agent';

    // Show annotation context if present
    if (annotation && role === 'user') {
      var annoEl = document.createElement('div');
      annoEl.className = 'chat-annotation';
      var lineInfo = '';
      if (annotation.startLine) {
        lineInfo = ':' + annotation.startLine;
        if (annotation.endLine && annotation.endLine !== annotation.startLine) {
          lineInfo += '-' + annotation.endLine;
        }
      }
      annoEl.innerHTML = '<span class="chat-annotation-file">' +
        annotation.file + lineInfo + '</span>' +
        '<span class="chat-annotation-text">' +
        annotation.selectedText.substring(0, 100) +
        (annotation.selectedText.length > 100 ? '...' : '') +
        '</span>';
      msgEl.appendChild(roleEl);
      msgEl.appendChild(annoEl);
    } else {
      msgEl.appendChild(roleEl);
    }

    var contentEl = document.createElement('div');
    contentEl.className = 'chat-content';

    if (role === 'assistant' && typeof marked !== 'undefined') {
      contentEl.innerHTML = marked.parse(content);
    } else {
      contentEl.textContent = content;
    }

    msgEl.appendChild(contentEl);
    messagesEl.appendChild(msgEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    return contentEl;
  }

  function ensureTurnMsg() {
    if (!currentTurnMsgEl) {
      currentTurnMsgEl = document.createElement('div');
      currentTurnMsgEl.className = 'chat-message chat-message-assistant';
      var roleEl = document.createElement('div');
      roleEl.className = 'chat-role';
      roleEl.textContent = 'Agent';
      currentTurnMsgEl.appendChild(roleEl);
      messagesEl.appendChild(currentTurnMsgEl);
    }
    return currentTurnMsgEl;
  }

  function startStreaming() {
    currentAssistantText = '';
    blocks = [];
    olderCollapseEl = null;
    var msgEl = ensureTurnMsg();

    var contentEl = document.createElement('div');
    contentEl.className = 'chat-content';
    contentEl.innerHTML = '<span class="streaming-cursor"></span>';

    msgEl.appendChild(contentEl);
    ensureStatusAtBottom();
    messagesEl.scrollTop = messagesEl.scrollHeight;

    currentAssistantEl = contentEl;
  }

  function appendStreamChunk(chunk) {
    if (!currentAssistantEl) {
      startStreaming();
    }
    currentAssistantText += chunk;
    if (typeof marked !== 'undefined') {
      currentAssistantEl.innerHTML = marked.parse(currentAssistantText) +
        '<span class="streaming-cursor"></span>';
    } else {
      currentAssistantEl.textContent = currentAssistantText;
    }
    ensureStatusAtBottom();
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function finishStreaming() {
    if (currentAssistantEl) {
      if (typeof marked !== 'undefined') {
        currentAssistantEl.innerHTML = marked.parse(currentAssistantText);
      } else {
        currentAssistantEl.textContent = currentAssistantText;
      }
      // Save assistant message to session
      if (currentAssistantText && window.App && window.App.saveMessage) {
        window.App.saveMessage('assistant', currentAssistantText);
      }
      currentAssistantEl = null;
      currentAssistantText = '';
    }
    currentTurnMsgEl = null;
    blocks = [];
    olderCollapseEl = null;
    setInputEnabled(true);
  }

  function ensureStatusAtBottom() {
    if (agentStatusEl && agentStatusEl.parentNode) {
      messagesEl.appendChild(agentStatusEl);
    }
  }

  function setInputEnabled(enabled) {
    inputEl.disabled = !enabled;
    sendBtn.disabled = !enabled;
    if (enabled) {
      // Remove working indicator
      if (agentStatusEl && agentStatusEl.parentNode) {
        agentStatusEl.parentNode.removeChild(agentStatusEl);
        agentStatusEl = null;
      }
      inputEl.focus();
    } else {
      // Show working indicator at bottom of messages
      if (!agentStatusEl) {
        agentStatusEl = document.createElement('div');
        agentStatusEl.className = 'agent-status';
        agentStatusEl.innerHTML =
          '<span class="agent-status-dot"></span>' +
          '<span class="agent-status-text">Working</span>';
      }
      messagesEl.appendChild(agentStatusEl);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  function sendMessage() {
    var text = inputEl.value.trim();
    if (!text) return;

    var annotation = pendingAnnotation;
    addMessage('user', text, annotation);
    inputEl.value = '';
    setInputEnabled(false);

    // Build payload
    var payload = {
      role: 'user',
      content: text,
    };
    if (annotation) {
      payload.annotation = annotation;
    }

    window.App.send({
      type: 'chat',
      payload: payload,
    });

    // Save user message to session
    if (window.App.saveMessage) {
      window.App.saveMessage('user', text, annotation);
    }

    // Clear annotation after sending
    setAnnotation(null);
    if (window.DocPanel) window.DocPanel.clearAnnotation();
  }

  // ── Tool use and thinking display ──
  //
  // Thinking and tool blocks are interleaved in arrival order.
  // The LAST BLOCK_VISIBLE_COUNT blocks are shown directly; older ones are
  // moved into a collapsible container that sits before the visible blocks.
  // Each block starts collapsed (header visible, content hidden); clicking
  // the header expands/collapses it individually.
  // Tool results are embedded inside their tool_use block so they collapse
  // and expand together with it.

  function addBlock(wrapper) {
    var parentEl = ensureTurnMsg();
    blocks.push(wrapper);
    parentEl.appendChild(wrapper);

    if (blocks.length > BLOCK_VISIBLE_COUNT) {
      // The block that just became too old to stay visible
      var hideIdx = blocks.length - 1 - BLOCK_VISIBLE_COUNT;
      var blockToHide = blocks[hideIdx];

      if (!olderCollapseEl) {
        // Create the collapse container and insert it before the oldest visible block
        olderCollapseEl = document.createElement('div');
        olderCollapseEl.className = 'chat-block-collapse';
        var toggleEl = document.createElement('div');
        toggleEl.className = 'chat-block-collapse-toggle';
        toggleEl.addEventListener('click', function() {
          olderCollapseEl.classList.toggle('expanded');
          updateCollapseToggle();
        });
        olderCollapseEl.appendChild(toggleEl);
        // Insert before blocks[hideIdx + 1] (the first block that stays visible)
        parentEl.insertBefore(olderCollapseEl, blocks[hideIdx + 1]);
      }

      olderCollapseEl.appendChild(blockToHide);
      updateCollapseToggle();
    }

    ensureStatusAtBottom();
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function updateCollapseToggle() {
    if (!olderCollapseEl) return;
    var hidden = blocks.length - BLOCK_VISIBLE_COUNT;
    var toggleEl = olderCollapseEl.querySelector('.chat-block-collapse-toggle');
    toggleEl.textContent = olderCollapseEl.classList.contains('expanded')
      ? 'Hide ' + hidden + ' older item' + (hidden > 1 ? 's' : '')
      : '+' + hidden + ' older item' + (hidden > 1 ? 's' : '');
  }

  function addToolUse(name, input) {
    // Snapshot any in-progress text so the tool block appends after it
    if (currentAssistantEl) {
      currentAssistantEl.innerHTML = marked.parse(currentAssistantText) +
        '<span class="streaming-cursor"></span>';
    }

    var wrapper = document.createElement('div');
    wrapper.className = 'chat-tool-use';

    var headerEl = document.createElement('div');
    headerEl.className = 'chat-tool-name';
    headerEl.textContent = name;
    headerEl.addEventListener('click', function() {
      wrapper.classList.toggle('expanded');
    });

    var inputEl = document.createElement('div');
    inputEl.className = 'chat-tool-input';
    var inputText = '';
    if (input) {
      if (input.command) inputText = input.command;
      else if (input.pattern) inputText = input.pattern;
      else if (input.file_path) inputText = input.file_path;
      else if (input.prompt) inputText = input.prompt.substring(0, 200);
      else inputText = JSON.stringify(input, null, 2);
    }
    inputEl.textContent = inputText;

    wrapper.appendChild(headerEl);
    wrapper.appendChild(inputEl);
    addBlock(wrapper);
  }

  function addToolResult(content) {
    // Embed result inside the last tool_use block so it collapses with it
    for (var i = blocks.length - 1; i >= 0; i--) {
      if (blocks[i].classList.contains('chat-tool-use')) {
        var resultEl = document.createElement('div');
        resultEl.className = 'chat-tool-result';
        resultEl.textContent = content;
        blocks[i].appendChild(resultEl);
        break;
      }
    }
    ensureStatusAtBottom();
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addThinking(text) {
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-thinking';

    var labelEl = document.createElement('div');
    labelEl.className = 'chat-thinking-label';
    labelEl.textContent = 'Thinking';
    labelEl.addEventListener('click', function() {
      wrapper.classList.toggle('expanded');
    });

    var contentEl = document.createElement('div');
    contentEl.className = 'chat-thinking-content';
    contentEl.textContent = text;

    wrapper.appendChild(labelEl);
    wrapper.appendChild(contentEl);
    addBlock(wrapper);
  }

  // Handle incoming chat messages from WebSocket (live path — also saves to session)
  function handleChat(payload) {
    if (payload.role === 'assistant') {
      if (payload.streaming) {
        appendStreamChunk(payload.content);
      } else {
        finishStreaming();
      }
    } else if (payload.role === 'tool_use') {
      addToolUse(payload.name, payload.input);
      if (window.App && window.App.saveMessage) {
        window.App.saveMessage('tool_use', '', null, { name: payload.name, input: payload.input });
      }
    } else if (payload.role === 'tool_result') {
      addToolResult(payload.content);
      if (window.App && window.App.saveMessage) {
        window.App.saveMessage('tool_result', payload.content);
      }
    } else if (payload.role === 'thinking') {
      addThinking(payload.content);
      if (window.App && window.App.saveMessage) {
        window.App.saveMessage('thinking', payload.content);
      }
    }
  }

  // Event listeners
  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Restore a message from a saved session (render only — no saving)
  function addRestoredMessage(msg) {
    var role = msg.role;
    if (role === 'user') {
      // User message starts a new turn; reset any pending block state first
      currentTurnMsgEl = null;
      blocks = [];
      olderCollapseEl = null;
      addMessage('user', msg.content, msg.annotation || null);
    } else if (role === 'assistant') {
      addMessage('assistant', msg.content, null);
      // Assistant message ends the turn
      currentTurnMsgEl = null;
      blocks = [];
      olderCollapseEl = null;
    } else if (role === 'tool_use') {
      addToolUse(msg.name, msg.input);
    } else if (role === 'tool_result') {
      addToolResult(msg.content);
    } else if (role === 'thinking') {
      addThinking(msg.content);
    }
  }

  function reset() {
    messagesEl.innerHTML = '';
    currentAssistantEl = null;
    currentAssistantText = '';
    currentTurnMsgEl = null;
    blocks = [];
    olderCollapseEl = null;
    agentStatusEl = null;
    setInputEnabled(true);
  }

  // Expose for app.js and document.js
  window.Chat = {
    handleChat: handleChat,
    setAnnotation: setAnnotation,
    addRestoredMessage: addRestoredMessage,
    setInputEnabled: setInputEnabled,
    reset: reset,
  };
})();
