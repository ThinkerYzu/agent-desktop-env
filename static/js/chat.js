(function() {
  'use strict';

  var messagesEl = document.getElementById('chat-messages');
  var inputEl = document.getElementById('chat-input');
  var sendBtn = document.getElementById('chat-send');
  var currentAssistantEl = null;
  var currentAssistantText = '';

  function addMessage(role, content) {
    var msgEl = document.createElement('div');
    msgEl.className = 'chat-message chat-message-' + role;

    var roleEl = document.createElement('div');
    roleEl.className = 'chat-role';
    roleEl.textContent = role === 'user' ? 'You' : 'Agent';

    var contentEl = document.createElement('div');
    contentEl.className = 'chat-content';

    if (role === 'assistant' && typeof marked !== 'undefined') {
      contentEl.innerHTML = marked.parse(content);
    } else {
      contentEl.textContent = content;
    }

    msgEl.appendChild(roleEl);
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
      // Remove streaming cursor, render final markdown
      if (typeof marked !== 'undefined') {
        currentAssistantEl.innerHTML = marked.parse(currentAssistantText);
      } else {
        currentAssistantEl.textContent = currentAssistantText;
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

    addMessage('user', text);
    inputEl.value = '';
    setInputEnabled(false);

    window.App.send({
      type: 'chat',
      payload: {
        role: 'user',
        content: text,
      },
    });
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

  // Expose for app.js
  window.Chat = { handleChat: handleChat };
})();
