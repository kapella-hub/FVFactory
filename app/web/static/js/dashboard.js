/* ============================================
   FVFactory — Dashboard Page
   ============================================ */

const DashboardPage = (() => {

  function timeAgo(timestamp) {
    const seconds = Math.floor((Date.now() / 1000) - timestamp);
    if (seconds < 60)   return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return new Date(timestamp * 1000).toLocaleDateString();
  }

  async function render(container) {
    container.innerHTML = `
      <div class="page-header">
        <h1 class="page-header__title">Dashboard</h1>
        <p class="page-header__subtitle">Overview of your video production pipeline</p>
      </div>

      <div class="stat-grid" id="dash-stats">
        <div class="stat-card">
          <div class="stat-card__icon stat-card__icon--cyan">&#9654;</div>
          <div class="stat-card__info">
            <div class="stat-card__value" id="stat-videos">--</div>
            <div class="stat-card__label">Total Videos</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-card__icon stat-card__icon--purple">&#9201;</div>
          <div class="stat-card__info">
            <div class="stat-card__value" id="stat-schedules">--</div>
            <div class="stat-card__label">Active Schedules</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-card__icon stat-card__icon--green">&#9881;</div>
          <div class="stat-card__info">
            <div class="stat-card__value" id="stat-provider">--</div>
            <div class="stat-card__label">Provider Mode</div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section__title">
          <span class="section__title-icon">&#128250;</span>
          Recent Videos
        </div>
        <div id="dash-recent-videos">
          <div class="loading-spinner"><div class="loading-spinner__circle"></div></div>
        </div>
      </div>

      <div class="section">
        <div class="section__title">
          <span class="section__title-icon">&#9201;</span>
          Scheduled Jobs
        </div>
        <div id="dash-jobs">
          <div class="loading-spinner"><div class="loading-spinner__circle"></div></div>
        </div>
      </div>

      <div style="margin-top: var(--space-6);">
        <button class="btn btn--primary btn--lg" onclick="FVRouter.navigate('/generate')">
          &#9654; Generate New Video
        </button>
      </div>
    `;

    loadData();
  }

  async function loadData() {
    try {
      const [libraryRes, jobsRes, configRes] = await Promise.all([
        fetch('/api/library').then(r => r.json()),
        fetch('/api/scheduler/jobs').then(r => r.json()),
        fetch('/api/config').then(r => r.json()),
      ]);

      const videos = libraryRes.videos || [];
      const jobs = jobsRes.jobs || [];

      // Stats
      document.getElementById('stat-videos').textContent = videos.length;
      document.getElementById('stat-schedules').textContent = jobs.filter(j => j.enabled).length;
      document.getElementById('stat-provider').textContent = (configRes.provider_mode || 'api').toUpperCase();

      // Recent videos
      renderRecentVideos(videos.slice(0, 5));

      // Jobs
      renderJobs(jobs);
    } catch (e) {
      console.error('Dashboard load error:', e);
    }
  }

  function renderRecentVideos(videos) {
    const el = document.getElementById('dash-recent-videos');
    if (!videos.length) {
      el.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">&#128250;</div>
          <div class="empty-state__title">No videos yet</div>
          <div class="empty-state__text">Generate your first video to see it here.</div>
          <button class="btn btn--primary" onclick="FVRouter.navigate('/generate')">Generate Video</button>
        </div>
      `;
      return;
    }

    el.innerHTML = videos.map(v => {
      const title = v.metadata?.title || v.filename.replace('.mp4', '').replace(/_/g, ' ');
      const niche = v.metadata?.niche || '';
      const thumbUrl = v.has_thumbnail ? `/api/library/${v.id}/thumbnail` : '';

      return `
        <div class="card card--interactive" style="display:flex;gap:var(--space-4);align-items:center;padding:var(--space-3) var(--space-4);margin-bottom:var(--space-2);cursor:pointer"
             onclick="FVRouter.navigate('/library')">
          <div style="width:48px;height:64px;border-radius:var(--radius-md);overflow:hidden;background:var(--bg-surface);flex-shrink:0;display:flex;align-items:center;justify-content:center">
            ${thumbUrl
              ? `<img src="${thumbUrl}" style="width:100%;height:100%;object-fit:cover" alt="">`
              : '<span style="color:var(--text-muted);font-size:var(--text-lg)">&#9654;</span>'}
          </div>
          <div style="flex:1;min-width:0">
            <div style="font-size:var(--text-sm);font-weight:var(--weight-medium);color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(title)}</div>
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:2px">${timeAgo(v.created)} &middot; ${v.size_mb} MB</div>
          </div>
          ${niche ? `<span class="badge badge--purple">${escapeHtml(niche)}</span>` : ''}
        </div>
      `;
    }).join('');
  }

  function renderJobs(jobs) {
    const el = document.getElementById('dash-jobs');
    if (!jobs.length) {
      el.innerHTML = `
        <div class="empty-state" style="padding:var(--space-8)">
          <div class="empty-state__icon">&#9201;</div>
          <div class="empty-state__title">No scheduled jobs</div>
          <div class="empty-state__text">Set up automated video generation on a schedule.</div>
          <button class="btn btn--secondary" onclick="FVRouter.navigate('/scheduler')">Create Schedule</button>
        </div>
      `;
      return;
    }

    el.innerHTML = `
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Schedule</th>
              <th>Status</th>
              <th>Next Run</th>
            </tr>
          </thead>
          <tbody>
            ${jobs.map(j => `
              <tr>
                <td style="color:var(--text-primary);font-weight:var(--weight-medium)">${escapeHtml(j.name)}</td>
                <td><code style="font-family:var(--font-mono);font-size:var(--text-xs)">${escapeHtml(j.cron_expression)}</code></td>
                <td><span class="badge ${j.enabled ? 'badge--green' : 'badge--muted'}">${j.enabled ? 'Active' : 'Disabled'}</span></td>
                <td style="font-size:var(--text-xs)">${j.next_run || '--'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  return { render };
})();
