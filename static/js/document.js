(function() {
  'use strict';

  var tabsEl = document.getElementById('doc-tabs');
  var contentEl = document.getElementById('document-content');
  var openTabs = [];   // [{path, content, scrollTop}]
  var activeTab = null;

  function openFile(path) {
    // If already open, just switch to it
    var existing = openTabs.find(function(t) { return t.path === path; });
    if (existing) {
      switchTab(path);
      return;
    }

    fetch('/api/file?path=' + encodeURIComponent(path))
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
  }

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

  // Update tab content when file changes (called from app.js for live updates)
  function updateFile(path, content) {
    var tab = openTabs.find(function(t) { return t.path === path; });
    if (tab) {
      tab.content = content;
      if (activeTab === path) {
        renderDocument(tab);
      }
    }
  }

  // Expose public API
  window.DocPanel = {
    openFile: openFile,
    updateFile: updateFile,
    getActiveTab: function() { return activeTab; },
    getOpenTabs: function() { return openTabs.map(function(t) { return t.path; }); }
  };
})();
