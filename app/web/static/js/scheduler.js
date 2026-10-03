/* ============================================
   FVFactory — Scheduler Page
   ============================================ */

const SchedulerPage = (() => {

  const PRESETS = [
    { label: 'Every day at 9am',   cron: '0 9 * * *' },
    { label: 'Twice daily (9am & 6pm)', cron: '0 9,18 * * *' },
    { label: 'Weekdays at 9am',    cron: '0 9 * * 1-5' },
    { label: 'Every 6 hours',      cron: '0 */6 * * *' },
    { label: 'Every 12 hours',     cron: '0 0,12 * * *' },
    { label: 'Weekly (Monday 9am)', cron: '0 9 * * 1' },
  ];

  const NICHES = [
    '', 'stoicism', 'philosophy', 'self-improvement', 'tech', 'science',
    'finance', 'history', 'gaming', 'health', 'lifestyle', 'trending'
  ];

  let jobs = [];
  let history = [];

  async function render(container) {
    container.innerHTML = `
      <div class="page-header flex justify-between items-center" style="flex-wrap:wrap;gap:var(--space-4)">
        <div>
          <h1 class="page-header__title">Scheduler</h1>
          <p class="page-header__subtitle">Automate video generation on a schedule</p>
        </div>
        <button class="btn btn--primary" onclick="SchedulerPage.openCreateModal()">
          + New Schedule
        </button>
      </div>

      <div class="section">
        <div class="section__title">
          <span class="section__title-icon">&#9201;</span>
          Scheduled Jobs
        </div>
        <div id="sched-jobs">
          <div class="loading-spinner"><div class="loading-spinner__circle"></div></div>
        </div>
      </div>

      <div class="section">
        <div class="section__title">
          <span class="section__title-icon">&#128203;</span>
          Run History
        </div>
        <div id="sched-history">
          <div class="loading-spinner"><div class="loading-spinner__circle"></div></div>
        </div>
      </div>
    `;

    await loadData();
  }

  async function loadData() {
    try {
      const [jobsRes, histRes] = await Promise.all([
        fetch('/api/scheduler/jobs').then(r => r.json()),
        fetch('/api/scheduler/history').then(r => r.json()),
      ]);
      jobs = jobsRes.jobs || [];
      history = histRes.history || [];
      renderJobs();
      renderHistory();
    } catch (e) {
      console.error('Scheduler load error:', e);
    }
  }

  function renderJobs() {
    const el = document.getElementById('sched-jobs');
    if (!jobs.length) {
      el.innerHTML = `
        <div class="empty-state" style="padding:var(--space-8)">
          <div class="empty-state__icon">&#9201;</div>
          <div class="empty-state__title">No scheduled jobs</div>
          <div class="empty-state__text">Create a schedule to automate video generation.</div>
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
              <th>Last Run</th>
              <th>Next Run</th>
              <th style="text-align:right">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${jobs.map(j => `
              <tr>
                <td style="color:var(--text-primary);font-weight:var(--weight-medium)">${escapeHtml(j.name)}</td>
                <td><code style="font-family:var(--font-mono);font-size:var(--text-xs)">${escapeHtml(j.cron_expression)}</code></td>
                <td>
                  <div class="toggle ${j.enabled ? 'toggle--active' : ''}" onclick="SchedulerPage.toggleJob('${j.id}', ${!j.enabled})" style="display:inline-flex">
                    <div class="toggle__track"><div class="toggle__thumb"></div></div>
                  </div>
                </td>
                <td style="font-size:var(--text-xs)">${j.last_run || '--'}</td>
                <td style="font-size:var(--text-xs)">${j.next_run || '--'}</td>
                <td style="text-align:right">
                  <div style="display:flex;gap:var(--space-2);justify-content:flex-end">
                    <button class="btn btn--ghost" onclick="SchedulerPage.runNow('${j.id}')" title="Run now">&#9654;</button>
                    <button class="btn btn--ghost" onclick="SchedulerPage.openEditModal('${j.id}')" title="Edit">&#9998;</button>
                    <button class="btn btn--ghost" style="color:var(--accent-red)" onclick="SchedulerPage.deleteJob('${j.id}')" title="Delete">&#10005;</button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderHistory() {
    const el = document.getElementById('sched-history');
    if (!history.length) {
      el.innerHTML = `
        <div class="empty-state" style="padding:var(--space-6)">
          <div class="empty-state__title" style="font-size:var(--text-sm)">No run history yet</div>
        </div>
      `;
      return;
    }

    const statusBadge = (status) => {
      const colors = { success: 'green', failed: 'red', error: 'red', running: 'yellow' };
      return `<span class="badge badge--${colors[status] || 'muted'}">${status}</span>`;
    };

    el.innerHTML = `
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Status</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            ${history.slice(0, 20).map(h => `
              <tr>
                <td style="color:var(--text-primary)">${escapeHtml(h.job_name || h.job_id)}</td>
                <td style="font-size:var(--text-xs)">${h.started_at || '--'}</td>
                <td style="font-size:var(--text-xs)">${h.finished_at || '--'}</td>
                <td>${statusBadge(h.status)}</td>
                <td style="font-size:var(--text-xs);color:var(--accent-red);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(h.error || '')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function openCreateModal(editJob) {
    const isEdit = !!editJob;
    const config = editJob?.config || {};

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.id = 'sched-modal';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
      <div class="modal" style="max-width:560px" onclick="event.stopPropagation()">
        <div class="modal__header">
          <h2 class="modal__title">${isEdit ? 'Edit Schedule' : 'New Schedule'}</h2>
          <button class="modal__close" onclick="this.closest('.modal-overlay').remove()">&times;</button>
        </div>
        <div class="modal__body">
          <div class="form-group">
            <label class="form-label">Name</label>
            <input class="form-input" id="sched-name" type="text" placeholder="e.g. Daily Stoicism Video"
                   value="${escapeHtml(editJob?.name || '')}">
          </div>

          <div class="form-group">
            <label class="form-label">Schedule Preset</label>
            <select class="form-select" id="sched-preset" onchange="SchedulerPage.applyPreset()">
              <option value="">Select a preset...</option>
              ${PRESETS.map(p => `<option value="${p.cron}" ${editJob?.cron_expression === p.cron ? 'selected' : ''}>${p.label}</option>`).join('')}
              <option value="custom">Custom cron...</option>
            </select>
          </div>

          <div class="form-group ${!editJob || PRESETS.some(p => p.cron === editJob.cron_expression) ? 'hidden' : ''}" id="sched-custom-group">
            <label class="form-label">Custom Cron Expression</label>
            <input class="form-input mono" id="sched-cron" type="text" placeholder="0 9 * * *"
                   value="${escapeHtml(editJob?.cron_expression || '')}">
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Niche</label>
              <select class="form-select" id="sched-niche">
                ${NICHES.map(n => `<option value="${n}" ${config.niche === n ? 'selected' : ''}>${n ? n.charAt(0).toUpperCase() + n.slice(1) : 'Any'}</option>`).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Voice</label>
              <select class="form-select" id="sched-voice">
                ${['auto','bill','george','daniel','josh','rachel'].map(v =>
                  `<option value="${v}" ${config.voice === v ? 'selected' : ''}>${v.charAt(0).toUpperCase() + v.slice(1)}</option>`
                ).join('')}
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Pacing</label>
              <select class="form-select" id="sched-pacing">
                <option value="">Default</option>
                ${['calm', 'standard', 'fast'].map(p =>
                  `<option value="${p}" ${config.pacing === p ? 'selected' : ''}>${p.charAt(0).toUpperCase() + p.slice(1)}</option>`
                ).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Music Source</label>
              <select class="form-select" id="sched-music-source">
                <option value="">Default</option>
                ${['any', 'mine', 'generated', 'none'].map(m =>
                  `<option value="${m}" ${config.music_source === m ? 'selected' : ''}>${m.charAt(0).toUpperCase() + m.slice(1)}</option>`
                ).join('')}
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Quality Tier</label>
              <select class="form-select" id="sched-tier">
                <option value="">Default</option>
                ${[['standard', 'Standard (Kling v3 Standard)'], ['premium', 'Premium (Kling v3 Pro)'], ['custom', 'Custom (Settings model)']].map(([t, label]) =>
                  `<option value="${t}" ${config.quality_tier === t ? 'selected' : ''}>${label}</option>`
                ).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Max Cost (USD, blank = Settings)</label>
              <input class="form-input" id="sched-max-cost" type="number" min="0" step="0.5" placeholder="Default"
                     value="${escapeHtml(config.max_cost == null ? '' : String(config.max_cost))}">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Strict (fail instead of a still)</label>
            <select class="form-select" id="sched-strict">
              <option value="" ${config.strict === true || config.strict === false ? '' : 'selected'}>Default</option>
              <option value="true" ${config.strict === true ? 'selected' : ''}>On</option>
              <option value="false" ${config.strict === false ? 'selected' : ''}>Off</option>
            </select>
          </div>

          <div style="display:flex;gap:var(--space-8);flex-wrap:wrap">
            <div class="toggle ${config.enable_motion !== false ? 'toggle--active' : ''}" id="sched-motion" onclick="SchedulerPage._toggleEl('sched-motion')">
              <div class="toggle__track"><div class="toggle__thumb"></div></div>
              <span class="toggle__label">Motion</span>
            </div>
            <div class="toggle ${config.enable_sfx !== false ? 'toggle--active' : ''}" id="sched-sfx" onclick="SchedulerPage._toggleEl('sched-sfx')">
              <div class="toggle__track"><div class="toggle__thumb"></div></div>
              <span class="toggle__label">SFX</span>
            </div>
            <div class="toggle ${config.enable_music !== false ? 'toggle--active' : ''}" id="sched-music" onclick="SchedulerPage._toggleEl('sched-music')">
              <div class="toggle__track"><div class="toggle__thumb"></div></div>
              <span class="toggle__label">Music</span>
            </div>
          </div>
        </div>
        <div class="modal__footer">
          <button class="btn btn--secondary" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
          <button class="btn btn--primary" onclick="SchedulerPage.saveJob(${isEdit ? `'${editJob.id}'` : 'null'})">${isEdit ? 'Update' : 'Create'}</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
  }

  function openEditModal(jobId) {
    const job = jobs.find(j => j.id === jobId);
    if (job) openCreateModal(job);
  }

  function applyPreset() {
    const preset = document.getElementById('sched-preset');
    const customGroup = document.getElementById('sched-custom-group');
    const cronInput = document.getElementById('sched-cron');

    if (preset.value === 'custom') {
      customGroup.classList.remove('hidden');
      cronInput.value = '';
      cronInput.focus();
    } else {
      customGroup.classList.add('hidden');
      cronInput.value = preset.value;
    }
  }

  async function saveJob(editId) {
    const name = document.getElementById('sched-name').value.trim();
    const cronInput = document.getElementById('sched-cron').value.trim();
    const presetVal = document.getElementById('sched-preset').value;
    const cron = presetVal && presetVal !== 'custom' ? presetVal : cronInput;

    if (!name) return FVToast.show('Please enter a name', 'warning');
    if (!cron) return FVToast.show('Please select or enter a schedule', 'warning');

    const previous = (editId && jobs.find(j => j.id === editId)?.config) || {};
    const strict = document.getElementById('sched-strict').value;
    const maxCost = document.getElementById('sched-max-cost').value.trim();
    const config = {
      ...previous,               // keep keys this form does not edit (e.g. subtitle_style set via the API)
      niche: document.getElementById('sched-niche').value,
      voice: document.getElementById('sched-voice').value,
      enable_motion: document.getElementById('sched-motion').classList.contains('toggle--active'),
      enable_sfx: document.getElementById('sched-sfx').classList.contains('toggle--active'),
      enable_music: document.getElementById('sched-music').classList.contains('toggle--active'),
      pacing: document.getElementById('sched-pacing').value || null,              // null = Settings default
      music_source: document.getElementById('sched-music-source').value || null,
      strict: strict === '' ? null : strict === 'true',
      quality_tier: document.getElementById('sched-tier').value || null,           // null = Settings default
      max_cost: maxCost === '' ? null : maxCost,                                   // text: the server validates
    };

    const body = { name, cron_expression: cron, enabled: true, config };

    try {
      const url = editId ? `/api/scheduler/jobs/${editId}` : '/api/scheduler/jobs';
      const method = editId ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Server error');
      }

      document.getElementById('sched-modal')?.remove();
      FVToast.show(editId ? 'Schedule updated' : 'Schedule created', 'success');
      await loadData();
    } catch (e) {
      FVToast.show('Failed to save: ' + e.message, 'error');
    }
  }

  async function toggleJob(jobId, enabled) {
    try {
      await fetch(`/api/scheduler/jobs/${jobId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      await loadData();
    } catch (e) {
      FVToast.show('Failed to update job', 'error');
    }
  }

  async function runNow(jobId) {
    try {
      await fetch(`/api/scheduler/jobs/${jobId}/run`, { method: 'POST' });
      FVToast.show('Job triggered', 'info');
    } catch (e) {
      FVToast.show('Failed to trigger job', 'error');
    }
  }

  async function deleteJob(jobId) {
    if (!confirm('Delete this scheduled job?')) return;
    try {
      await fetch(`/api/scheduler/jobs/${jobId}`, { method: 'DELETE' });
      FVToast.show('Job deleted', 'success');
      await loadData();
    } catch (e) {
      FVToast.show('Failed to delete job', 'error');
    }
  }

  function _toggleEl(id) {
    document.getElementById(id)?.classList.toggle('toggle--active');
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  return { render, openCreateModal, openEditModal, applyPreset, saveJob, toggleJob, runNow, deleteJob, _toggleEl };
})();
