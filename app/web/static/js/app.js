/* ============================================
   FVFactory — SPA Router + Toast + Init
   ============================================ */

/* ---- Toast System ---- */
const FVToast = (() => {
  const ICONS = {
    success: '&#10003;',
    error:   '&#10007;',
    info:    '&#8505;',
    warning: '&#9888;',
  };

  function show(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `
      <span class="toast__icon">${ICONS[type] || ICONS.info}</span>
      <span class="toast__message">${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('toast--removing');
      toast.addEventListener('animationend', () => toast.remove());
    }, duration);
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  return { show };
})();


/* ---- Router ---- */
const FVRouter = (() => {

  const routes = {
    '/':          { page: 'dashboard', title: 'Dashboard',  module: () => DashboardPage },
    '/generate':  { page: 'generate',  title: 'Generate',   module: () => GeneratePage },
    '/library':   { page: 'library',   title: 'Library',    module: () => LibraryPage },
    '/scheduler': { page: 'scheduler', title: 'Scheduler',  module: () => SchedulerPage },
    '/settings':  { page: 'settings',  title: 'Settings',   module: () => SettingsPage },
  };

  function init() {
    // Intercept clicks on sidebar links
    document.addEventListener('click', (e) => {
      const link = e.target.closest('a[data-page]');
      if (link) {
        e.preventDefault();
        navigate(link.getAttribute('href'));
      }
    });

    // Handle back/forward
    window.addEventListener('popstate', () => {
      renderCurrentRoute();
    });

    // Initial render
    renderCurrentRoute();
  }

  function navigate(path) {
    if (window.location.pathname === path) return;
    window.history.pushState({}, '', path);
    renderCurrentRoute();
  }

  function renderCurrentRoute() {
    const path = window.location.pathname;
    const route = routes[path] || routes['/'];

    // Update sidebar active state
    document.querySelectorAll('.sidebar__link').forEach(link => {
      const isActive = link.getAttribute('href') === path ||
                       (path === '/' && link.dataset.page === 'dashboard');
      link.classList.toggle('sidebar__link--active', isActive);
    });

    // Update page title
    const titleEl = document.getElementById('page-title');
    if (titleEl) titleEl.textContent = route.title;
    document.title = `FVFactory - ${route.title}`;

    // Render page with fade
    const app = document.getElementById('app');
    if (app) {
      app.style.animation = 'none';
      app.offsetHeight; // Force reflow
      app.style.animation = '';

      const mod = route.module();
      if (mod && mod.render) {
        mod.render(app);
      }
    }
  }

  return { init, navigate };
})();


/* ---- Init ---- */
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', FVRouter.init);
} else {
  FVRouter.init();
}
