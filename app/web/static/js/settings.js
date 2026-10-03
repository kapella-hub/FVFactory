/* ============================================
   FVFactory — Settings Page
   ============================================ */

const SettingsPage = (() => {

  let config = {};

  async function render(container) {
    container.innerHTML = `
      <div class="page-header">
        <h1 class="page-header__title">Settings</h1>
        <p class="page-header__subtitle">Configure providers, defaults, and preferences</p>
      </div>
      <div id="settings-content">
        <div class="loading-spinner"><div class="loading-spinner__circle"></div></div>
      </div>
    `;

    await loadConfig();
  }

  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      config = await res.json();
      renderSettings();
    } catch (e) {
      document.getElementById('settings-content').innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">&#9888;</div>
          <div class="empty-state__title">Failed to load settings</div>
        </div>
      `;
    }
  }

  function renderSettings() {
    const el = document.getElementById('settings-content');

    el.innerHTML = `
      <!-- Providers -->
      ${accordion('Providers', 'providers', true, `
        <div class="form-group">
          <label class="form-label">Provider Mode</label>
          <div class="btn-group">
            ${['local', 'api', 'mixed'].map(m => `
              <button class="btn-group__item ${config.provider_mode === m ? 'btn-group__item--active' : ''}"
                      onclick="SettingsPage.setProviderMode('${m}')" data-mode="${m}">
                ${m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            `).join('')}
          </div>
        </div>

        <div class="form-row mt-4">
          <div class="form-group">
            <label class="form-label">LLM Provider</label>
            <select class="form-select" data-key="llm_provider">
              ${['openai', 'claude_cli', 'ollama'].map(p => `<option value="${p}" ${config.llm_provider === p ? 'selected' : ''}>${p}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Image Provider</label>
            <select class="form-select" data-key="image_provider">
              ${['fal', 'local', 'replicate'].map(p => `<option value="${p}" ${config.image_provider === p ? 'selected' : ''}>${p === 'fal' ? 'fal.ai FLUX (recommended)' : p === 'local' ? 'Local FLUX' : 'Replicate'}</option>`).join('')}
            </select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Motion Provider</label>
            <select class="form-select" data-key="motion_provider">
              ${['fal', 'replicate', 'local'].map(p => `<option value="${p}" ${config.motion_provider === p ? 'selected' : ''}>${p === 'fal' ? 'fal.ai (recommended)' : p}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">fal.ai Video Model</label>
            <select class="form-select" data-key="fal_video_model">
              ${falModelOptions().map(m => `<option value="${escapeHtml(m.key)}" ${config.fal_video_model === m.key ? 'selected' : ''}>${escapeHtml(m.label)}${m.price_text ? ` (${escapeHtml(m.price_text)})` : ''}</option>`).join('')}
            </select>
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-1)">Used by the Custom quality tier and the classic editor.</div>
          </div>
        </div>
      `)}

      <!-- Generation Defaults -->
      ${accordion('Generation Defaults', 'defaults', false, `
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Default Niche</label>
            <select class="form-select" data-key="niche">
              <option value="">Any</option>
              ${['stoicism','philosophy','self-improvement','tech','science','finance','history','gaming','health','lifestyle','trending']
                .map(n => `<option value="${n}" ${config.niche === n ? 'selected' : ''}>${n.charAt(0).toUpperCase() + n.slice(1)}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Subtitle Style</label>
            <select class="form-select" data-key="subtitle_style">
              ${['bold_impact','clean_minimal','neon_glow','fire']
                .map(s => `<option value="${s}" ${config.subtitle_style === s ? 'selected' : ''}>${s.replace(/_/g, ' ')}</option>`).join('')}
            </select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Default Pacing</label>
            <select class="form-select" data-key="pacing">
              ${['calm', 'standard', 'fast']
                .map(p => `<option value="${p}" ${(config.pacing || 'standard') === p ? 'selected' : ''}>${p}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Default Music Source</label>
            <select class="form-select" data-key="music_source">
              ${['any', 'mine', 'generated', 'none']
                .map(m => `<option value="${m}" ${(config.music_source || 'any') === m ? 'selected' : ''}>${m}</option>`).join('')}
            </select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Default Quality Tier</label>
            <select class="form-select" data-key="quality_tier">
              ${[['standard', 'Standard (Kling v3 Standard)'], ['premium', 'Premium (Kling v3 Pro)'], ['custom', 'Custom (fal.ai video model)']]
                .map(([t, label]) => `<option value="${t}" ${(config.quality_tier || 'standard') === t ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Max Cost per Video (USD, 0 = no cap)</label>
            <input class="form-input" type="number" min="0" step="0.5" data-key="max_cost_per_video"
                   value="${Number(config.max_cost_per_video) || 0}">
          </div>
        </div>

        <div style="display:flex;gap:var(--space-8);flex-wrap:wrap;margin-top:var(--space-2)">
          ${settingToggle('cinematic_enabled', 'Shot editor (off = classic)', config.cinematic_enabled !== false)}
          ${settingToggle('enable_motion', 'Motion', config.enable_motion !== false)}
          ${settingToggle('enable_sfx', 'SFX', config.enable_sfx !== false)}
          ${settingToggle('music_enabled', 'Music', config.music_enabled !== false)}
          ${settingToggle('strict', 'Strict (fail instead of a still)', config.strict === true)}
        </div>

        <div class="form-group mt-4">
          <label class="form-label">Music Volume</label>
          <div class="range-slider">
            <input type="range" min="0" max="1" step="0.05" value="${config.music_volume || 0.15}" data-key="music_volume"
                   oninput="this.nextElementSibling.textContent = this.value">
            <span class="range-slider__value">${config.music_volume || 0.15}</span>
          </div>
        </div>
      `)}

      <!-- Model Settings -->
      ${accordion('Model Settings', 'models', false, `
        <div class="form-group">
          <label class="form-label">Wan Model Size</label>
          <div class="btn-group">
            ${['1.3b', '14b'].map(s => `
              <button class="btn-group__item ${config.wan_model_size === s ? 'btn-group__item--active' : ''}"
                      data-wan="${s}" onclick="SettingsPage.setWanSize('${s}')">
                ${s.toUpperCase()}
              </button>
            `).join('')}
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Flux Model</label>
          <input class="form-input" data-key="flux_local_model" type="text" value="${escapeHtml(config.flux_local_model || '')}" placeholder="e.g. flux-schnell">
        </div>

        <div class="form-group">
          <label class="form-label">CLI Timeout (seconds)</label>
          <div class="range-slider">
            <input type="range" min="60" max="3600" step="60" value="${config.claude_cli_timeout || 300}" data-key="claude_cli_timeout"
                   oninput="this.nextElementSibling.textContent = this.value + 's'">
            <span class="range-slider__value">${config.claude_cli_timeout || 300}s</span>
          </div>
        </div>
      `)}

      <!-- API Keys -->
      ${accordion('API Keys', 'keys', false, `
        ${keyStatus('fal.ai', config.has_fal_key)}
        ${keyStatus('OpenAI', config.has_openai_key)}
        ${keyStatus('ElevenLabs', config.has_elevenlabs_key)}
        ${keyStatus('Replicate', config.has_replicate_key)}
        ${keyStatus('YouTube', config.has_youtube_key)}
        <p style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-4)">
          API keys are configured via environment variables or .env file. They cannot be changed from this UI for security.
        </p>
      `)}

      <!-- Output -->
      ${accordion('Output', 'output', false, `
        <div class="form-group">
          <label class="form-label">Output Directory</label>
          <input class="form-input mono" data-key="output_dir" type="text" value="${escapeHtml(config.output_dir || 'output')}">
        </div>
      `)}

      <!-- Footer -->
      <div class="sticky-footer">
        <button class="btn btn--danger" onclick="SettingsPage.resetDefaults()">Reset to Defaults</button>
        <button class="btn btn--primary btn--lg" onclick="SettingsPage.save()">Save Settings</button>
      </div>
    `;
  }

  function accordion(title, id, open, content) {
    return `
      <div class="accordion ${open ? 'accordion--open' : ''}" id="acc-${id}">
        <div class="accordion__header" onclick="SettingsPage.toggleAccordion('acc-${id}')">
          <span class="accordion__title">${title}</span>
          <span class="accordion__arrow">&#9660;</span>
        </div>
        <div class="accordion__body">${content}</div>
      </div>
    `;
  }

  function settingToggle(key, label, active) {
    return `
      <div class="toggle ${active ? 'toggle--active' : ''}" data-toggle-key="${key}"
           onclick="this.classList.toggle('toggle--active')">
        <div class="toggle__track"><div class="toggle__thumb"></div></div>
        <span class="toggle__label">${label}</span>
      </div>
    `;
  }

  function keyStatus(name, isSet) {
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-2) 0;border-bottom:1px solid var(--border-subtle)">
        <span style="font-size:var(--text-sm);color:var(--text-primary)">${name}</span>
        <span class="masked-input__status ${isSet ? 'masked-input__status--set' : 'masked-input__status--unset'}">
          ${isSet ? '&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226; configured' : 'Not set'}
        </span>
      </div>
    `;
  }

  function toggleAccordion(id) {
    document.getElementById(id)?.classList.toggle('accordion--open');
  }

  function setProviderMode(mode) {
    document.querySelectorAll('.btn-group__item[data-mode]').forEach(b => {
      b.classList.toggle('btn-group__item--active', b.dataset.mode === mode);
    });
    config.provider_mode = mode;
  }

  function setWanSize(size) {
    document.querySelectorAll('[data-wan]').forEach(b => {
      b.classList.toggle('btn-group__item--active', b.dataset.wan === size);
    });
    config.wan_model_size = size;
  }

  // fal_video_model choices from /api/config clip_models; a saved key that is no longer known stays
  // selectable (marked unknown) so saving the page never changes it silently.
  function falModelOptions() {
    const models = Array.isArray(config.clip_models) && config.clip_models.length
      ? config.clip_models.slice()
      : [{ key: 'hailuo', label: 'Minimax video-01', price_text: '' }];
    if (config.fal_video_model && !models.some(m => m.key === config.fal_video_model)) {
      models.push({ key: config.fal_video_model, label: `${config.fal_video_model} (unknown)`, price_text: '' });
    }
    return models;
  }

  async function save() {
    const updates = {};

    // Collect select/input values
    document.querySelectorAll('[data-key]').forEach(el => {
      const key = el.dataset.key;
      let val = el.value;
      if (el.type === 'range') val = parseFloat(val);
      if (key === 'max_cost_per_video' && String(val).trim() === '') val = 0;   // blank = no cap
      updates[key] = val;
    });

    // Collect toggles
    document.querySelectorAll('[data-toggle-key]').forEach(el => {
      updates[el.dataset.toggleKey] = el.classList.contains('toggle--active');
    });

    // Provider mode and wan size from state
    updates.provider_mode = config.provider_mode;
    updates.wan_model_size = config.wan_model_size;

    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Server error');
      }
      config = { ...config, ...updates };
      FVToast.show('Settings saved', 'success');
    } catch (e) {
      FVToast.show('Failed to save settings: ' + e.message, 'error');
    }
  }

  async function resetDefaults() {
    if (!confirm('Reset all settings to defaults? This cannot be undone.')) return;
    try {
      await fetch('/api/config/reset', { method: 'POST' });
      FVToast.show('Settings reset to defaults', 'success');
      await loadConfig();
    } catch (e) {
      FVToast.show('Failed to reset settings', 'error');
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');   // attribute-safe too
  }

  return { render, toggleAccordion, setProviderMode, setWanSize, save, resetDefaults };
})();
