/* ============================================
   FVFactory — Generate Page
   ============================================ */

const GeneratePage = (() => {

  const NICHES = [
    'stoicism', 'philosophy', 'self-improvement', 'tech', 'science',
    'finance', 'history', 'gaming', 'health', 'lifestyle', 'trending'
  ];
  const VOICES = ['auto', 'bill', 'george', 'daniel', 'josh', 'rachel'];
  const STYLES = [
    { id: 'bold_impact',    label: 'Bold Impact',    preview: 'BOLD' },
    { id: 'clean_minimal',  label: 'Clean Minimal',  preview: 'Clean' },
    { id: 'neon_glow',      label: 'Neon Glow',      preview: 'NEON' },
    { id: 'fire',           label: 'Fire',            preview: 'FIRE' },
  ];
  const STAGES = ['script', 'audio', 'images', 'motion', 'assembly'];

  let currentJobId = null;
  let wsCleanup = [];
  let logEntries = [];

  function render(container) {
    currentJobId = null;
    logEntries = [];
    cleanupWs();

    container.innerHTML = `
      <div class="page-header">
        <h1 class="page-header__title">Generate Video</h1>
        <p class="page-header__subtitle">Create a new short-form video from a topic or auto-discover trending content</p>
      </div>

      <div class="card" style="max-width:720px">
        <!-- Auto Toggle -->
        <div class="form-group">
          <div class="toggle" id="auto-toggle" onclick="GeneratePage.toggleAuto()">
            <div class="toggle__track"><div class="toggle__thumb"></div></div>
            <span class="toggle__label">Auto-discover topic</span>
          </div>
        </div>

        <!-- Topic -->
        <div class="form-group" id="topic-group">
          <label class="form-label">Topic</label>
          <input class="form-input" id="gen-topic" type="text" placeholder="e.g. Why Ancient Rome fell..." autocomplete="off">
        </div>

        <!-- Niche + Voice -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Niche</label>
            <select class="form-select" id="gen-niche">
              <option value="">Any</option>
              ${NICHES.map(n => `<option value="${n}">${n.charAt(0).toUpperCase() + n.slice(1)}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Voice</label>
            <select class="form-select" id="gen-voice">
              ${VOICES.map(v => `<option value="${v}">${v.charAt(0).toUpperCase() + v.slice(1)}</option>`).join('')}
            </select>
          </div>
        </div>

        <!-- Subtitle Style -->
        <div class="form-group">
          <label class="form-label">Subtitle Style</label>
          <div class="style-grid" id="style-grid">
            ${STYLES.map(s => `
              <div class="style-card ${s.id === 'bold_impact' ? 'style-card--selected' : ''}"
                   data-style="${s.id}" onclick="GeneratePage.selectStyle('${s.id}')">
                <div class="style-card__preview style-preview--${s.id}">${s.preview}</div>
                <div class="style-card__name">${s.label}</div>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Toggles -->
        <div style="display:flex;gap:var(--space-8);flex-wrap:wrap;margin-bottom:var(--space-5)">
          <div class="toggle toggle--active" id="toggle-motion" onclick="GeneratePage.toggleSwitch('toggle-motion')">
            <div class="toggle__track"><div class="toggle__thumb"></div></div>
            <span class="toggle__label">Motion</span>
          </div>
          <div class="toggle toggle--active" id="toggle-sfx" onclick="GeneratePage.toggleSwitch('toggle-sfx')">
            <div class="toggle__track"><div class="toggle__thumb"></div></div>
            <span class="toggle__label">SFX</span>
          </div>
          <div class="toggle toggle--active" id="toggle-music" onclick="GeneratePage.toggleSwitch('toggle-music')">
            <div class="toggle__track"><div class="toggle__thumb"></div></div>
            <span class="toggle__label">Music</span>
          </div>
        </div>

        <!-- Mock checkbox -->
        <div class="form-group">
          <div class="checkbox" id="cb-mock" onclick="GeneratePage.toggleCheckbox('cb-mock')">
            <div class="checkbox__box">&#10003;</div>
            <span class="checkbox__label">Use mock images (free, for testing)</span>
          </div>
        </div>

        <!-- Generate Button -->
        <button class="btn btn--primary btn--lg btn--full" id="gen-submit" onclick="GeneratePage.submit()">
          &#9654; Generate Video
        </button>
      </div>

      <!-- Progress Panel (hidden initially) -->
      <div class="progress-panel hidden" id="progress-panel">
        <div class="section__title">
          <span class="section__title-icon">&#9881;</span>
          Pipeline Progress
        </div>

        <div class="progress-stages" id="progress-stages">
          ${STAGES.map(s => `
            <div class="progress-stage" data-stage="${s}">${s.charAt(0).toUpperCase() + s.slice(1)}</div>
          `).join('')}
        </div>

        <div class="progress-bar-container">
          <div class="progress-bar" id="progress-bar" style="width:0%"></div>
        </div>

        <div class="progress-log" id="progress-log"></div>
      </div>
    `;
  }

  function toggleAuto() {
    const el = document.getElementById('auto-toggle');
    const topicGroup = document.getElementById('topic-group');
    el.classList.toggle('toggle--active');
    topicGroup.classList.toggle('hidden', el.classList.contains('toggle--active'));
  }

  function selectStyle(styleId) {
    document.querySelectorAll('.style-card').forEach(c => c.classList.remove('style-card--selected'));
    document.querySelector(`[data-style="${styleId}"]`)?.classList.add('style-card--selected');
  }

  function toggleSwitch(id) {
    document.getElementById(id)?.classList.toggle('toggle--active');
  }

  function toggleCheckbox(id) {
    document.getElementById(id)?.classList.toggle('checkbox--checked');
  }

  function getSelectedStyle() {
    return document.querySelector('.style-card--selected')?.dataset.style || 'bold_impact';
  }

  function isToggleActive(id) {
    return document.getElementById(id)?.classList.contains('toggle--active') ?? false;
  }

  function isChecked(id) {
    return document.getElementById(id)?.classList.contains('checkbox--checked') ?? false;
  }

  async function submit() {
    const btn = document.getElementById('gen-submit');
    if (btn.disabled) return;

    const autoDiscover = isToggleActive('auto-toggle');
    const topic = document.getElementById('gen-topic')?.value.trim() || '';

    if (!autoDiscover && !topic) {
      FVToast.show('Please enter a topic or enable auto-discover', 'warning');
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Starting...';

    const body = {
      topic: autoDiscover ? '' : topic,
      auto_topic: autoDiscover,
      niche: document.getElementById('gen-niche').value,
      voice: document.getElementById('gen-voice').value,
      subtitle_style: getSelectedStyle(),
      enable_motion: isToggleActive('toggle-motion'),
      enable_sfx: isToggleActive('toggle-sfx'),
      enable_music: isToggleActive('toggle-music'),
      use_mock: isChecked('cb-mock'),
    };

    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (data.job_id) {
        currentJobId = data.job_id;
        showProgress();
        listenToWs();
        FVToast.show('Generation started', 'info');
      } else {
        throw new Error('No job_id in response');
      }
    } catch (e) {
      FVToast.show('Failed to start generation: ' + e.message, 'error');
      btn.disabled = false;
      btn.innerHTML = '&#9654; Generate Video';
    }
  }

  function showProgress() {
    document.getElementById('progress-panel')?.classList.remove('hidden');
    logEntries = [];
  }

  function listenToWs() {
    cleanupWs();

    const onProgress = (data) => {
      if (data.job_id !== currentJobId) return;
      updateStage(data.stage, 'active');
      updateBar(data.progress);
      addLog(data.message);
    };

    const onComplete = (data) => {
      if (data.job_id !== currentJobId) return;
      STAGES.forEach(s => updateStage(s, 'complete'));
      updateBar(1);
      addLog('Pipeline complete!');
      FVToast.show('Video generated successfully!', 'success');
      resetButton();
    };

    const onError = (data) => {
      if (data.job_id !== currentJobId) return;
      addLog('ERROR: ' + (data.error || 'Unknown error'));
      const activeStage = document.querySelector('.progress-stage--active');
      if (activeStage) activeStage.className = 'progress-stage progress-stage--error';
      FVToast.show('Generation failed: ' + (data.error || 'Unknown'), 'error');
      resetButton();
    };

    wsCleanup.push(FVWebSocket.on('progress', onProgress));
    wsCleanup.push(FVWebSocket.on('complete', onComplete));
    wsCleanup.push(FVWebSocket.on('error', onError));
  }

  function cleanupWs() {
    wsCleanup.forEach(fn => fn());
    wsCleanup = [];
  }

  function updateStage(stageName, status) {
    const stageEl = document.querySelector(`[data-stage="${stageName}"]`);
    if (!stageEl) return;

    // Mark all previous stages as complete
    const stageIdx = STAGES.indexOf(stageName);
    STAGES.forEach((s, i) => {
      const el = document.querySelector(`[data-stage="${s}"]`);
      if (!el) return;
      if (i < stageIdx) {
        el.className = 'progress-stage progress-stage--complete';
      } else if (i === stageIdx) {
        el.className = `progress-stage progress-stage--${status}`;
      }
    });
  }

  function updateBar(progress) {
    const bar = document.getElementById('progress-bar');
    if (bar) bar.style.width = `${Math.min(progress * 100, 100)}%`;
  }

  function addLog(message) {
    const log = document.getElementById('progress-log');
    if (!log) return;
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    logEntries.push({ time, message });
    log.innerHTML = logEntries.map(e =>
      `<div class="progress-log__entry"><span class="progress-log__time">${e.time}</span>${escapeHtml(e.message)}</div>`
    ).join('');
    log.scrollTop = log.scrollHeight;
  }

  function resetButton() {
    const btn = document.getElementById('gen-submit');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '&#9654; Generate Video';
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  return { render, toggleAuto, selectStyle, toggleSwitch, toggleCheckbox, submit };
})();
