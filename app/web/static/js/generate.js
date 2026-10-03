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
    { id: 'short',  label: 'Short',  desc: '~30s, 6-8 scenes' },
    { id: 'medium', label: 'Medium', desc: '~45s, 9-11 scenes' },
    { id: 'long',   label: 'Long',   desc: '~60s, 11-14 scenes' },
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
  // Quality tiers (spec 2026-10-03 section 9): the motion model per video. "" = the Settings default.
  const TIERS = [
    { id: 'standard', label: 'Standard (MiniMax H3 Turbo)' },
    { id: 'premium',  label: 'Premium (Kling v3 Pro)' },
    { id: 'custom',   label: 'Custom (Settings model)' },
  ];
  // Source of the narration. "story" = the user's own story (app/story.py).
  const SOURCES = [
    { id: 'auto',  label: 'Auto-discover', desc: 'A trending topic for the niche' },
    { id: 'topic', label: 'Topic',         desc: 'You name it, the AI writes it' },
    { id: 'story', label: 'Your story',    desc: 'Paste the narration yourself' },
  ];
  const STORY_MODES = [
    { id: 'verbatim', label: 'Verbatim', desc: 'Your exact words; the length follows your story' },
    { id: 'adapt',    label: 'Adapt',    desc: 'Reworked into a short-form script for the duration, same facts and order' },
  ];
  let defaults = {};
  // /api/generate/options; these fallbacks match app/story.py and app/script_quality.py.
  let genOptions = { story_max_chars: 4000, words_per_second: 2.2, scene_seconds: 5,
                     personas: [], persona_ready: false, upload_ready: false };
  let storySupported = false;      // set by loadOptions from /api/generate/options

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
        <p class="page-header__subtitle">Create a short-form video from a trending topic, your own topic, or your own story</p>
      </div>

      <div class="card" style="max-width:720px">
        <!-- Source: Auto-discover | Topic | Your story -->
        <div class="form-group">
          <label class="form-label">Source</label>
          <div class="style-grid" id="source-grid" role="radiogroup" aria-label="Source">
            ${SOURCES.map(src => `
              <div class="style-card ${src.id === 'topic' ? 'style-card--selected' : ''}" role="radio" tabindex="0"
                   aria-checked="${src.id === 'topic'}" data-source="${src.id}"
                   onclick="GeneratePage.selectSource('${src.id}')"
                   onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();GeneratePage.selectSource('${src.id}')}">
                <div class="style-card__name">${src.label}</div>
                <div class="style-card__desc">${src.desc}</div>
              </div>
            `).join('')}
          </div>
          <div class="form-hint hidden" id="auto-hint">A trending topic is picked for the niche below when the run starts.</div>
        </div>

        <!-- Topic -->
        <div class="form-group" id="topic-group">
          <label class="form-label" for="gen-topic">Topic</label>
          <input class="form-input" id="gen-topic" type="text" placeholder="e.g. Why Ancient Rome fell..." autocomplete="off">
        </div>

        <!-- Your story -->
        <div class="hidden" id="story-group">
          <div class="form-group">
            <label class="form-label" for="gen-title">Title <span class="form-label__optional">(optional)</span></label>
            <input class="form-input" id="gen-title" type="text" maxlength="120" autocomplete="off"
                   placeholder="Default: the first words of your story">
          </div>
          <div class="form-group">
            <label class="form-label" for="gen-story">Your story</label>
            <textarea class="form-input form-textarea" id="gen-story" rows="10"
                      placeholder="Paste or write the narration. In verbatim mode every word is spoken exactly as written."
                      oninput="GeneratePage.updateStoryStats()"></textarea>
            <div class="form-hint" id="story-stats" aria-live="polite"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Story mode</label>
            <div class="style-grid" id="story-mode-grid" role="radiogroup" aria-label="Story mode">
              ${STORY_MODES.map(m => `
                <div class="style-card ${m.id === 'verbatim' ? 'style-card--selected' : ''}" role="radio" tabindex="0"
                     aria-checked="${m.id === 'verbatim'}" data-story-mode="${m.id}"
                     onclick="GeneratePage.selectStoryMode('${m.id}')"
                     onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();GeneratePage.selectStoryMode('${m.id}')}">
                  <div class="style-card__name">${m.label}</div>
                  <div class="style-card__desc">${m.desc}</div>
                </div>
              `).join('')}
            </div>
          </div>
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
          <div class="form-hint hidden" id="duration-story-hint">Verbatim stories set their own length: the duration only
            sets the scene count when the story fits it, and a story outside it gets a run-report warning.</div>
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

        <!-- Quality tier + spending cap (spec 2026-10-03 section 9) -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Quality Tier</label>
            <select class="form-select" id="gen-tier" onchange="GeneratePage.updateTierHint()">
              <option value="">Default</option>
              ${TIERS.map(t => `<option value="${t.id}">${t.label}</option>`).join('')}
            </select>
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-1)" id="gen-tier-hint"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Max Cost (USD)</label>
            <input class="form-input" id="gen-max-cost" type="number" min="0" step="0.5" placeholder="Default">
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-1)">Stops the run before the next paid stage if the estimate is higher. 0 = no cap.</div>
          </div>
        </div>

        <!-- Toggles -->
        <div class="option-row">
          <div class="toggle toggle--active" id="toggle-subtitles" onclick="GeneratePage.toggleSwitch('toggle-subtitles')">
            <div class="toggle__track"><div class="toggle__thumb"></div></div>
            <span class="toggle__label">Subtitles</span>
          </div>
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
          <div class="checkbox" id="cb-strict" data-defaults-loaded="false" style="pointer-events:none;opacity:.6" onclick="GeneratePage.toggleCheckbox('cb-strict')">
            <div class="checkbox__box">&#10003;</div>
            <span class="checkbox__label">Strict: fail the run instead of shipping a still when a motion clip fails</span>
          </div>
        </div>

        <!-- Classic editor -->
        <div class="form-group">
          <div class="checkbox" id="cb-classic" onclick="GeneratePage.toggleCheckbox('cb-classic')">
            <div class="checkbox__box">&#10003;</div>
            <span class="checkbox__label">Classic editor (Ken Burns slideshow instead of the shot editor; quality tier and cost cap do not apply)</span>
          </div>
        </div>

        <!-- Advanced: persona, chroma key, YouTube upload -->
        <details class="advanced" id="gen-advanced">
          <summary>Advanced</summary>
          <div class="form-group">
            <label class="form-label" for="gen-persona">Persona (talking head over the scenes; uses the classic editor)</label>
            <select class="form-select" id="gen-persona" onchange="GeneratePage.updateAdvanced()" disabled>
              <option value="">None</option>
            </select>
            <div class="form-hint" id="gen-persona-hint">Loading...</div>
          </div>
          <div class="form-group">
            <div class="checkbox checkbox--disabled" id="cb-chroma" onclick="GeneratePage.toggleCheckbox('cb-chroma')">
              <div class="checkbox__box">&#10003;</div>
              <span class="checkbox__label">Chroma key the persona (green-screen portrait)</span>
            </div>
          </div>
          <div class="form-group" style="margin-bottom:0">
            <div class="checkbox checkbox--disabled" id="cb-upload" onclick="GeneratePage.toggleCheckbox('cb-upload')">
              <div class="checkbox__box">&#10003;</div>
              <span class="checkbox__label">Upload to YouTube when the video is done</span>
            </div>
            <div class="form-hint" id="gen-upload-hint"></div>
          </div>
        </details>

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
    loadOptions();
    selectSource('topic');
  }

  async function loadOptions() {
    try {
      const res = await fetch('/api/generate/options');
      const data = res.ok ? await res.json() : {};
      // A server started before "Your story" existed answers {"error": "Not found"} here and would ignore the
      // story fields (and auto-discover a topic instead), so stories are refused until it is restarted.
      storySupported = typeof data.story_max_chars === 'number';
      genOptions = { ...genOptions, ...(storySupported ? data : {}) };
    } catch (e) {
      // Fallback values stay; the server validates every option anyway.
    }
    const select = document.getElementById('gen-persona');
    const hint = document.getElementById('gen-persona-hint');
    if (select && hint) {
      const personas = genOptions.personas || [];
      select.innerHTML = '<option value="">None</option>' +
        personas.map(p => `<option value="${escapeAttr(p)}">${escapeHtml(p)}</option>`).join('');
      select.disabled = !personas.length || !genOptions.persona_ready;
      hint.textContent = !personas.length
        ? 'No personas: add a portrait image (.png/.jpg/.webp) to assets/personas to use one.'
        : !genOptions.persona_ready
          ? 'Persona animation needs a Hedra or Replicate API key in .env.'
          : 'The narration is lip-synced onto this portrait.';
    }
    const upload = document.getElementById('cb-upload');
    const uploadHint = document.getElementById('gen-upload-hint');
    if (upload && uploadHint) {
      upload.classList.toggle('checkbox--disabled', !genOptions.upload_ready);
      if (!genOptions.upload_ready) upload.classList.remove('checkbox--checked');
      uploadHint.textContent = genOptions.upload_ready
        ? 'Uses client_secrets.json; the first upload opens a Google sign-in in a browser on the server machine.'
        : 'Needs YouTube OAuth credentials (client_secrets.json) on the server machine.';
    }
    updateAdvanced();
    updateStoryStats();
  }

  function updateAdvanced() {
    const persona = document.getElementById('gen-persona')?.value || '';
    const chroma = document.getElementById('cb-chroma');
    if (!chroma) return;
    chroma.classList.toggle('checkbox--disabled', !persona);
    if (!persona) chroma.classList.remove('checkbox--checked');
  }

  function getSource() {
    return document.querySelector('#source-grid .style-card--selected')?.dataset.source || 'topic';
  }

  function getStoryMode() {
    return document.querySelector('#story-mode-grid .style-card--selected')?.dataset.storyMode || 'verbatim';
  }

  function selectCard(gridId, attr, value) {
    document.querySelectorAll(`#${gridId} .style-card`).forEach(c => {
      const on = c.getAttribute(attr) === value;
      c.classList.toggle('style-card--selected', on);
      c.setAttribute('aria-checked', String(on));
    });
  }

  function selectSource(source) {
    selectCard('source-grid', 'data-source', source);
    document.getElementById('topic-group')?.classList.toggle('hidden', source !== 'topic');
    document.getElementById('story-group')?.classList.toggle('hidden', source !== 'story');
    document.getElementById('auto-hint')?.classList.toggle('hidden', source !== 'auto');
    updateStoryStats();
  }

  function selectStoryMode(mode) {
    selectCard('story-mode-grid', 'data-story-mode', mode);
    updateStoryStats();
  }

  // Same rules as app/story.py: whitespace is normalised before counting; a word has a letter or digit.
  function normalizedStory() {
    return (document.getElementById('gen-story')?.value || '').split(/\s+/).filter(Boolean).join(' ');
  }

  function countWords(text) {
    return text ? text.split(' ').filter(t => /[\p{L}\p{N}_]/u.test(t)).length : 0;
  }

  function updateStoryStats() {
    const stats = document.getElementById('story-stats');
    const durHint = document.getElementById('duration-story-hint');
    const isStory = getSource() === 'story';
    if (durHint) durHint.classList.toggle('hidden', !(isStory && getStoryMode() === 'verbatim'));
    if (!stats) return;
    const text = normalizedStory();
    const max = genOptions.story_max_chars;
    const words = countWords(text);
    const seconds = Math.round(words / genOptions.words_per_second);
    const over = text.length > max;
    let line = `${text.length} / ${max} characters`;
    if (words) {
      line += ` \u00b7 ${words} words \u00b7 about ${seconds} s spoken`;
      if (getStoryMode() === 'verbatim') {
        const scenes = Math.min(20, Math.max(1, Math.round(seconds / genOptions.scene_seconds)));
        line += ` \u00b7 about ${scenes} scene${scenes === 1 ? '' : 's'}`;
      }
    }
    if (over) line += ` \u2014 ${text.length - max} over the limit`;
    stats.textContent = line;
    stats.classList.toggle('form-hint--error', over);
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
      label('gen-tier', cfg.quality_tier);
      const cap = document.getElementById('gen-max-cost');
      if (cap) cap.placeholder = cfg.max_cost_per_video > 0 ? `Default ($${cfg.max_cost_per_video})` : 'Default (no cap)';
      if (cfg.strict === true) document.getElementById('cb-strict')?.classList.add('checkbox--checked');
      defaults = cfg;
    } catch (e) {
      // Labels stay "Default"; the server applies the Settings defaults anyway.
    }
    enableStrict();
    updateTierHint();
  }

  // "about $X of motion for a medium video" from /api/config tier_estimates (list prices, estimate only).
  function updateTierHint() {
    const hint = document.getElementById('gen-tier-hint');
    if (!hint) return;
    const tier = document.getElementById('gen-tier')?.value || defaults.quality_tier || 'standard';
    const dur = getSelectedDuration();
    const est = (defaults.tier_estimates || {})[tier];
    if (est && typeof est[dur] === 'number') {
      hint.textContent = `\u2248 $${est[dur].toFixed(2)} of motion for a ${dur} video (${est.model}, list-price estimate)`;
    } else if (tier === 'custom' && defaults.tier_estimates) {
      hint.textContent = 'Custom uses the fal.ai video model from Settings, which is not a known model.';
    } else {
      hint.textContent = '';
    }
  }

  // The strict box stays locked until Settings defaults are known (or failed to load), so a fast
  // submit cannot send strict:false over a Settings value of true.
  function enableStrict() {
    const el = document.getElementById('cb-strict');
    if (!el) return;
    el.dataset.defaultsLoaded = 'true';
    el.style.pointerEvents = '';
    el.style.opacity = '';
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
    updateTierHint();
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

    const source = getSource();
    const topic = document.getElementById('gen-topic')?.value.trim() || '';
    const story = normalizedStory();

    if (source === 'topic' && !topic) {
      FVToast.show('Enter a topic, or choose Auto-discover or Your story', 'warning');
      return;
    }
    if (source === 'story' && !storySupported) {
      FVToast.show('This server is running an older build without story support; restart it (python main.py --serve)', 'error', 6000);
      return;
    }
    if (source === 'story' && !story) {
      FVToast.show('Paste your story first', 'warning');
      return;
    }
    if (source === 'story' && story.length > genOptions.story_max_chars) {
      FVToast.show(`Your story is ${story.length} characters; the limit is ${genOptions.story_max_chars}`, 'warning');
      return;
    }

    if (document.getElementById('gen-max-cost').validity.badInput) {
      FVToast.show('Max cost must be a number (0 = no cap)', 'warning');
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Starting...';

    const body = {
      topic: source === 'topic' ? topic : '',
      auto_topic: source === 'auto',
      story: source === 'story' ? document.getElementById('gen-story').value : '',
      story_mode: source === 'story' ? getStoryMode() : null,
      title: source === 'story' ? document.getElementById('gen-title').value.trim() : '',
      niche: document.getElementById('gen-niche').value,
      voice: document.getElementById('gen-voice').value,
      subtitle_style: getSelectedStyle(),
      enable_subtitles: isToggleActive('toggle-subtitles'),
      enable_motion: isToggleActive('toggle-motion'),
      enable_sfx: isToggleActive('toggle-sfx'),
      enable_music: isToggleActive('toggle-music'),
      use_mock: isChecked('cb-mock'),
      video_style: getSelectedVideoStyle(),
      video_duration: getSelectedDuration(),
      pacing: document.getElementById('gen-pacing').value || null,
      music_source: document.getElementById('gen-music-source').value || null,
      quality_tier: document.getElementById('gen-tier').value || null,                 // null = Settings default
      max_cost: document.getElementById('gen-max-cost').value.trim() || null,         // text: the server validates
      // null = server uses Settings, until the defaults have loaded
      strict: document.getElementById('cb-strict')?.dataset.defaultsLoaded === 'true' ? isChecked('cb-strict') : null,
      classic: isChecked('cb-classic'),
      persona: document.getElementById('gen-persona')?.value || '',
      use_chroma_key: isChecked('cb-chroma'),
      upload: isChecked('cb-upload'),
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
    // A report that never loaded (status not "ok") must not read as a clean run.
    const unavailable = !error && !warnings.length && !(result && result.status === 'ok');
    const status = error
      ? '<span class="badge badge--red">failed</span>'
      : warnings.length
        ? `<span class="badge badge--yellow">${warnings.length} warning${warnings.length === 1 ? '' : 's'}</span>`
        : unavailable
          ? '<span class="badge badge--yellow">report unavailable</span>'
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

  function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, '&quot;');
  }

  return { render, selectSource, selectStoryMode, updateStoryStats, updateAdvanced, selectStyle, selectVideoStyle,
           selectDuration, toggleSwitch, toggleCheckbox, submit, updateTierHint };
})();
