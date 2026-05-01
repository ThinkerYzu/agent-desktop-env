(function() {
  'use strict';

  var projectsContainer = document.getElementById('projects-list');
  var errorContainer = document.getElementById('projects-error');

  /**
   * Load and render the list of projects
   */
  async function loadProjects() {
    try {
      projectsContainer.classList.add('loading');
      errorContainer.style.display = 'none';

      const response = await fetch('/api/projects');

      if (!response.ok) {
        throw new Error('Failed to load projects: ' + response.statusText);
      }

      const data = await response.json();
      projectsContainer.classList.remove('loading');

      renderProjects(data.projects);
    } catch (error) {
      console.error('Failed to load projects:', error);
      projectsContainer.classList.remove('loading');
      showError('Failed to load projects', error.message);
    }
  }

  /**
   * Render the list of projects
   */
  function renderProjects(projects) {
    if (projects.length === 0) {
      projectsContainer.innerHTML = `
        <div class="empty-state">
          <h3>No Projects Found</h3>
          <p>Add project directories to get started.</p>
        </div>
      `;
      return;
    }

    projectsContainer.innerHTML = projects.map(function(project) {
      var description = project.description ? escapeHtml(project.description) : '';
      var descriptionClass = description ? 'description' : 'description empty';
      var descriptionText = description || 'No description';

      var metaItems = [];

      // Add project name
      metaItems.push('<span class="icon">📁</span>' + escapeHtml(project.name));

      // Add session count if any
      if (project.session_count > 0) {
        metaItems.push(
          '<span><span class="icon">💬</span>' +
          project.session_count +
          (project.session_count === 1 ? ' session' : ' sessions') +
          '</span>'
        );
      }

      return `
        <a href="/${encodeURIComponent(project.name)}" class="project-card">
          <h2>${escapeHtml(project.title)}</h2>
          <div class="project-name">${escapeHtml(project.name)}</div>
          <div class="${descriptionClass}">${descriptionText}</div>
          <div class="meta">
            ${metaItems.join('')}
          </div>
        </a>
      `;
    }).join('');
  }

  /**
   * Show an error message
   */
  function showError(title, message) {
    errorContainer.innerHTML = `
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(message)}</p>
    `;
    errorContainer.style.display = 'block';
  }

  /**
   * Escape HTML to prevent XSS
   */
  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Load projects on page load
  loadProjects();
})();
