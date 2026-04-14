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

  function startStreaming() {
    currentAssistantText = '';
    var msgEl = document.createElement('div');
    msgEl.className = 'chat-message chat-message-assistant';

    var roleEl = document.createElement('div');
    roleEl.className = 'chat-role';
    roleEl.textContent = 'Agent';

    var contentEl = document.createElement('div');
    contentEl.className = 'chat-content';
    contentEl.innerHTML = '<span class="streaming-cursor"></span>';

    msgEl.appendChild(roleEl);
    msgEl.appendChild(contentEl);
    messagesEl.appendChild(msgEl);
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
    setInputEnabled(true);
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

  function addToolUse(name, input) {
    // Finish any pending text streaming first
    if (currentAssistantEl) {
      if (typeof marked !== 'undefined') {
        currentAssistantEl.innerHTML = marked.parse(currentAssistantText);
      }
    }

    var wrapper = document.createElement('div');
    wrapper.className = 'chat-tool-use';

    var nameEl = document.createElement('div');
    nameEl.className = 'chat-tool-name';
    nameEl.textContent = name;

    var inputEl = document.createElement('div');
    inputEl.className = 'chat-tool-input';
    // Show a brief summary of the input
    var inputText = '';
    if (input) {
      if (input.command) inputText = input.command;
      else if (input.pattern) inputText = input.pattern;
      else if (input.file_path) inputText = input.file_path;
      else if (input.prompt) inputText = input.prompt.substring(0, 200);
      else inputText = JSON.stringify(input, null, 2);
    }
    inputEl.textContent = inputText;

    nameEl.addEventListener('click', function() {
      wrapper.classList.toggle('expanded');
    });

    wrapper.appendChild(nameEl);
    wrapper.appendChild(inputEl);

    // Add to current assistant message block, or to messages container
    if (currentAssistantEl) {
      currentAssistantEl.parentNode.appendChild(wrapper);
    } else {
      // Create a container for this turn
      var msgEl = document.createElement('div');
      msgEl.className = 'chat-message chat-message-assistant';
      var roleEl = document.createElement('div');
      roleEl.className = 'chat-role';
      roleEl.textContent = 'Agent';
      msgEl.appendChild(roleEl);
      msgEl.appendChild(wrapper);
      messagesEl.appendChild(msgEl);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addToolResult(content) {
    var resultEl = document.createElement('div');
    resultEl.className = 'chat-tool-result';
    resultEl.textContent = content;

    // Find the last tool-use block and insert result after it
    var toolBlocks = messagesEl.querySelectorAll('.chat-tool-use');
    if (toolBlocks.length > 0) {
      var lastTool = toolBlocks[toolBlocks.length - 1];
      lastTool.parentNode.insertBefore(resultEl, lastTool.nextSibling);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addThinking(text) {
    var wrapper = document.createElement('div');
    wrapper.className = 'chat-thinking';

    var labelEl = document.createElement('div');
    labelEl.className = 'chat-thinking-label';
    labelEl.textContent = 'Thinking';

    var contentEl = document.createElement('div');
    contentEl.className = 'chat-thinking-content';
    contentEl.textContent = text;

    labelEl.addEventListener('click', function() {
      wrapper.classList.toggle('expanded');
    });

    wrapper.appendChild(labelEl);
    wrapper.appendChild(contentEl);

    if (currentAssistantEl) {
      currentAssistantEl.parentNode.appendChild(wrapper);
    } else {
      var msgEl = document.createElement('div');
      msgEl.className = 'chat-message chat-message-assistant';
      var roleEl = document.createElement('div');
      roleEl.className = 'chat-role';
      roleEl.textContent = 'Agent';
      msgEl.appendChild(roleEl);
      msgEl.appendChild(wrapper);
      messagesEl.appendChild(msgEl);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // Handle incoming chat messages from WebSocket
  function handleChat(payload) {
    if (payload.role === 'assistant') {
      if (payload.streaming) {
        appendStreamChunk(payload.content);
      } else {
        finishStreaming();
      }
    } else if (payload.role === 'tool_use') {
      addToolUse(payload.name, payload.input);
    } else if (payload.role === 'tool_result') {
      addToolResult(payload.content);
    } else if (payload.role === 'thinking') {
      addThinking(payload.content);
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

  // Restore a message from a saved session (no streaming, no saving)
  function addRestoredMessage(role, content, annotation) {
    addMessage(role, content, annotation || null);
  }

  // Expose for app.js and document.js
  window.Chat = {
    handleChat: handleChat,
    setAnnotation: setAnnotation,
    addRestoredMessage: addRestoredMessage,
    setInputEnabled: setInputEnabled,
  };
})();
