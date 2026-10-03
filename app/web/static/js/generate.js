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
    { id: 'auto',           label: 'Auto',            preview: '✦' },
    { id: 'bold_impact',    label: 'Bold Impact',    preview: 'BOLD' },
    { id: 'clean_minimal',  label: 'Clean Minimal',  preview: 'Clean' },
    { id: 'neon_glow',      label: 'Neon Glow',      preview: 'NEON' },
    { id: 'fire',           label: 'Fire',            preview: 'FIRE' },
  ];
  const VIDEO_STYLES = [
    { id: 'photorealistic', label: 'Photorealistic', desc: 'Cinematic, documentary' },
    { id: 'cartoon',        label: 'Cartoon',         desc: 'Bold, colorful, Pixar-like' },
    { id: 'anime',          label: 'Anime',           desc: 'Japanese animation' },
    { id: 'stop_motion',    label: 'Stop Motion',     desc: 'Claymation, miniatures' },
    { id: 'comic_book',     label: 'Comic Book',      desc: 'Ink, halftone, graphic novel' },
    { id: '3d_render',      label: '3D Render',       desc: 'Clean CGI, Blender-like' },
    { id: 'pixel_art',      label: 'Pixel Art',       desc: 'Retro 16-bit, game style' },
    { id: 'watercolor',     label: 'Watercolor',      desc: 'Soft washes, paper texture' },
    { id: 'oil_painting',   label: 'Oil Painting',    desc: 'Classical, rich brushstrokes' },
    { id: 'noir',           label: 'Film Noir',       desc: 'B&W, dramatic shadows' },
  ];
  const DURATIONS = [
    { id: 'short',  label: 'Short',  desc: '~30s, 5-7 scenes' },
    { id: 'medium', label: 'Medium', desc: '~60s, 8-10 scenes' },
    { id: 'long',   label: 'Long',   desc: '~90s, 11-14 scenes' },
  ];
  const STAGES = ['script', 'audio', 'images', 'motion', 'assembly'];

  // Shot editor options (spec §11). The "" option means "use the Settings default".
  const PACINGS = [
    { id: 'calm',     label: 'Calm (~4 s shots)' },
    { id: 'standard', label: 'Standard (~3 s shots)' },
    { id: 'fast',     label: 'Fast (~2 s shots)' },
  ];
  const MUSIC_SOURCES = [
    { id: 'any',       label: 'Any (my tracks + generated)' },
    { id: 'mine',      label: 'My tracks only' },
    { id: 'generated', label: 'Generated library only' },
    { id: 'none',      label: 'No music' },
  ];

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

        <!-- Video Style -->
        <div class="form-group">
          <label class="form-label">Video Style</label>
          <div class="style-grid" id="video-style-grid">
            ${VIDEO_STYLES.map(s => `
              <div class="style-card ${s.id === 'photorealistic' ? 'style-card--selected' : ''}"
                   data-vstyle="${s.id}" onclick="GeneratePage.selectVideoStyle('${s.id}')">
                <div class="style-card__name">${s.label}</div>
                <div class="style-card__desc">${s.desc}</div>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Duration -->
        <div class="form-group">
          <label class="form-label">Duration</label>
          <div class="style-grid" id="duration-grid">
            ${DURATIONS.map(d => `
              <div class="style-card ${d.id === 'medium' ? 'style-card--selected' : ''}"
                   data-dur="${d.id}" onclick="GeneratePage.selectDuration('${d.id}')">
                <div class="style-card__name">${d.label}</div>
                <div class="style-card__desc">${d.desc}</div>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Subtitle Style -->
        <div class="form-group">
          <label class="form-label">Subtitle Style</label>
          <div class="style-grid" id="style-grid">
            ${STYLES.map(s => `
              <div class="style-card ${s.id === 'auto' ? 'style-card--selected' : ''}"
                   data-style="${s.id}" onclick="GeneratePage.selectStyle('${s.id}')">
                <div class="style-card__preview style-preview--${s.id}">${s.preview}</div>
                <div class="style-card__name">${s.label}</div>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Pacing + Music Source -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Pacing</label>
            <select class="form-select" id="gen-pacing">
              <option value="">Default</option>
              ${PACINGS.map(p => `<option value="${p.id}">${p.label}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Music Source</label>
            <select class="form-select" id="gen-music-source">
              <option value="">Default</option>
              ${MUSIC_SOURCES.map(m => `<option value="${m.id}">${m.label}</option>`).join('')}
            </select>
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

        <!-- Strict checkbox (pre-checked from Settings by loadDefaults) -->
        <div class="form-group">
          <div class="checkbox" id="cb-strict" onclick="GeneratePage.toggleCheckbox('cb-strict')">
            <div class="checkbox__box">&#10003;</div>
            <span class="checkbox__label">Strict: fail the run instead of shipping a still when a motion clip fails</span>
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

        <!-- Run report (spec §10): filled from the WebSocket complete/error payload -->
        <div class="hidden" id="run-report" style="margin-top:var(--space-4)"></div>
      </div>
    `;
    loadDefaults();
  }

  async function loadDefaults() {
    try {
      const cfg = await (await fetch('/api/config')).json();
      const label = (selectId, value) => {
        const opt = document.querySelector(`#${selectId} option[value=""]`);
        if (opt && value) opt.textContent = `Default (${value})`;
      };
      label('gen-pacing', cfg.pacing);
      label('gen-music-source', cfg.music_source);
      if (cfg.strict === true) document.getElementById('cb-strict')?.classList.add('checkbox--checked');
    } catch (e) {
      // Labels stay "Default"; the server applies the Settings defaults anyway.
    }
  }

  function toggleAuto() {
    const el = document.getElementById('auto-toggle');
    const topicGroup = document.getElementById('topic-group');
    el.classList.toggle('toggle--active');
    topicGroup.classList.toggle('hidden', el.classList.contains('toggle--active'));
  }

  function selectStyle(styleId) {
    document.querySelectorAll('#style-grid .style-card').forEach(c => c.classList.remove('style-card--selected'));
    document.querySelector(`[data-style="${styleId}"]`)?.classList.add('style-card--selected');
  }

  function selectVideoStyle(styleId) {
    document.querySelectorAll('#video-style-grid .style-card').forEach(c => c.classList.remove('style-card--selected'));
    document.querySelector(`[data-vstyle="${styleId}"]`)?.classList.add('style-card--selected');
  }

  function selectDuration(durId) {
    document.querySelectorAll('#duration-grid .style-card').forEach(c => c.classList.remove('style-card--selected'));
    document.querySelector(`[data-dur="${durId}"]`)?.classList.add('style-card--selected');
  }

  function getSelectedVideoStyle() {
    return document.querySelector('#video-style-grid .style-card--selected')?.dataset.vstyle || 'photorealistic';
  }

  function getSelectedDuration() {
    return document.querySelector('#duration-grid .style-card--selected')?.dataset.dur || 'medium';
  }

  function toggleSwitch(id) {
    document.getElementById(id)?.classList.toggle('toggle--active');
  }

  function toggleCheckbox(id) {
    document.getElementById(id)?.classList.toggle('checkbox--checked');
  }

  function getSelectedStyle() {
    return document.querySelector('#style-grid .style-card--selected')?.dataset.style || 'bold_impact';
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
      video_style: getSelectedVideoStyle(),
      video_duration: getSelectedDuration(),
      pacing: document.getElementById('gen-pacing').value || null,
      music_source: document.getElementById('gen-music-source').value || null,
      strict: isChecked('cb-strict'),
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
        throw new Error(typeof data.detail === 'string' ? data.detail : 'No job_id in response');
      }
    } catch (e) {
      FVToast.show('Failed to start generation: ' + e.message, 'error');
      btn.disabled = false;
      btn.innerHTML = '&#9654; Generate Video';
    }
  }

  function showProgress() {
    document.getElementById('progress-panel')?.classList.remove('hidden');
    document.getElementById('run-report')?.classList.add('hidden');
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
      const n = ((data.result && data.result.warnings) || []).length;
      FVToast.show(n ? `Video generated with ${n} warning${n === 1 ? '' : 's'} (see Run Report)`
                     : 'Video generated successfully!', n ? 'warning' : 'success');
      showRunReport(data.result, null);
      resetButton();
    };

    const onError = (data) => {
      if (data.job_id !== currentJobId) return;
      addLog('ERROR: ' + (data.error || 'Unknown error'));
      const activeStage = document.querySelector('.progress-stage--active');
      if (activeStage) activeStage.className = 'progress-stage progress-stage--error';
      FVToast.show('Generation failed: ' + (data.error || 'Unknown'), 'error');
      showRunReport(data.result, data.error || 'Unknown error');
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

  function showRunReport(result, error) {
    const el = document.getElementById('run-report');
    if (!el) return;
    const warnings = (result && result.warnings) || [];
    const status = error
      ? '<span class="badge badge--red">failed</span>'
      : warnings.length
        ? `<span class="badge badge--yellow">${warnings.length} warning${warnings.length === 1 ? '' : 's'}</span>`
        : '<span class="badge badge--green">no warnings</span>';
    const rows = warnings.map(w => `
      <div class="progress-log__entry">
        <span class="badge badge--yellow">${escapeHtml(w.code)}</span> ${escapeHtml(w.message)}
      </div>`).join('');
    const where = result && result.video_id
      ? `<div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-2)">Job: ${escapeHtml(result.video_id)}</div>`
      : '';
    const open = !error && result && result.video_id
      ? `<button class="btn btn--secondary" style="margin-top:var(--space-3)" onclick="FVRouter.navigate('/library')">Open Library</button>`
      : '';
    el.innerHTML = `
      <div class="section__title"><span class="section__title-icon">&#128203;</span>Run Report ${status}</div>
      ${rows}${where}${open}`;
    el.classList.remove('hidden');
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

  return { render, toggleAuto, selectStyle, selectVideoStyle, selectDuration, toggleSwitch, toggleCheckbox, submit };
})();
