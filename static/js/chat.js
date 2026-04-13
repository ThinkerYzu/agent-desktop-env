(function() {
  'use strict';

  var messagesEl = document.getElementById('chat-messages');
  var inputEl = document.getElementById('chat-input');
  var sendBtn = document.getElementById('chat-send');
  var inputArea = document.getElementById('chat-input-area');
  var currentAssistantEl = null;
  var currentAssistantText = '';
  var pendingAnnotation = null;

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
      inputEl.focus();
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

  // Handle incoming chat messages from WebSocket
  function handleChat(payload) {
    if (payload.role === 'assistant') {
      if (payload.streaming) {
        appendStreamChunk(payload.content);
      } else {
        finishStreaming();
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

  // Restore a message from a saved session (no streaming, no saving)
  function addRestoredMessage(role, content, annotation) {
    addMessage(role, content, annotation || null);
  }

  // Expose for app.js and document.js
  window.Chat = {
    handleChat: handleChat,
    setAnnotation: setAnnotation,
    addRestoredMessage: addRestoredMessage,
  };
})();
