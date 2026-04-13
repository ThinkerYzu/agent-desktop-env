(function() {
  'use strict';

  var container = document.getElementById('file-tree-content');

  function createTreeNode(entry) {
    var node = document.createElement('div');
    node.className = 'tree-node';

    var label = document.createElement('div');
    label.className = 'tree-label';
    label.dataset.path = entry.path;
    label.dataset.type = entry.type;

    var icon = document.createElement('span');
    icon.className = 'tree-icon';

    if (entry.type === 'directory') {
      icon.textContent = '\u25B6';
      icon.className += ' tree-icon-dir';
    } else {
      icon.textContent = '\u00A0\u00A0';
    }

    var name = document.createElement('span');
    name.className = 'tree-name';
    name.textContent = entry.name;

    label.appendChild(icon);
    label.appendChild(name);
    node.appendChild(label);

    if (entry.type === 'directory') {
      var children = document.createElement('div');
      children.className = 'tree-children';
      children.style.display = 'none';
      node.appendChild(children);

      label.addEventListener('click', function() {
        toggleDirectory(node, entry.path);
      });
    } else {
      label.addEventListener('click', function() {
        window.DocPanel.openFile(entry.path);
      });
    }

    return node;
  }

  function toggleDirectory(node, path) {
    var children = node.querySelector('.tree-children');
    var icon = node.querySelector('.tree-icon-dir');

    if (children.style.display === 'none') {
      if (children.children.length === 0) {
        loadDirectory(path, children);
      }
      children.style.display = 'block';
      icon.textContent = '\u25BC';
    } else {
      children.style.display = 'none';
      icon.textContent = '\u25B6';
    }
  }

  function loadDirectory(path, targetEl) {
    fetch('/api/files?path=' + encodeURIComponent(path))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.entries) {
          data.entries.forEach(function(entry) {
            targetEl.appendChild(createTreeNode(entry));
          });
        }
      });
  }

  var refreshTimer = null;

  function refresh() {
    // Debounce: coalesce rapid events into a single refresh
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function() {
      refreshTimer = null;
      fetch('/api/files?path=')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          container.innerHTML = '';
          if (data.entries) {
            data.entries.forEach(function(entry) {
              container.appendChild(createTreeNode(entry));
            });
          }
        });
    }, 300);
  }

  function highlightFile(path) {
    var labels = container.querySelectorAll('.tree-label');
    for (var i = 0; i < labels.length; i++) {
      if (labels[i].dataset.path === path) {
        labels[i].classList.remove('tree-highlight');
        // Force reflow so the animation restarts if already applied
        void labels[i].offsetWidth;
        labels[i].classList.add('tree-highlight');
        break;
      }
    }
  }

  // Load root on startup
  refresh();

  // Expose for app.js
  window.FileTree = { refresh: refresh, highlightFile: highlightFile };
})();
