(function() {
  'use strict';

  var ws = null;
  var reconnectDelay = 1000;

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
      // Update open document on modify or create (atomic writes show as delete+create)
      if ((payload.event === 'modified' || payload.event === 'created') && payload.content && window.DocPanel) {
        window.DocPanel.updateFile(payload.path, payload.content);
      }
      // Refresh file tree on create/delete
      if (payload.event === 'created' || payload.event === 'deleted') {
        if (window.FileTree) {
          window.FileTree.refresh();
        }
      }
    } else if (msg.type === 'chat') {
      if (window.Chat) {
        window.Chat.handleChat(msg.payload);
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

  // Expose for other modules
  window.App = { send: send };

  connect();
})();
