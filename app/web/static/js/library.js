/* ============================================
   FVFactory — Library Page
   ============================================ */

const LibraryPage = (() => {

  const NICHE_COLORS = {
    stoicism: 'purple', philosophy: 'purple', 'self-improvement': 'cyan',
    tech: 'cyan', science: 'green', finance: 'yellow', history: 'purple',
    gaming: 'red', health: 'green', lifestyle: 'cyan', trending: 'yellow',
  };

  let videos = [];

  function timeAgo(timestamp) {
    const seconds = Math.floor((Date.now() / 1000) - timestamp);
    if (seconds < 60)    return 'just now';
    if (seconds < 3600)  return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return new Date(timestamp * 1000).toLocaleDateString();
  }

  async function render(container) {
    container.innerHTML = `
      <div class="page-header">
        <h1 class="page-header__title">Library</h1>
        <p class="page-header__subtitle">Browse and manage your generated videos</p>
      </div>
      <div id="library-content">
        <div class="loading-spinner"><div class="loading-spinner__circle"></div></div>
      </div>
    `;

    await loadVideos();
  }

  async function loadVideos() {
    try {
      const res = await fetch('/api/library');
      const data = await res.json();
      videos = data.videos || [];
      renderGrid();
    } catch (e) {
      document.getElementById('library-content').innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">&#9888;</div>
          <div class="empty-state__title">Failed to load library</div>
          <div class="empty-state__text">${escapeHtml(e.message)}</div>
        </div>
      `;
    }
  }

  function renderGrid() {
    const el = document.getElementById('library-content');
    if (!videos.length) {
      el.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">&#128250;</div>
          <div class="empty-state__title">Your library is empty</div>
          <div class="empty-state__text">Generated videos will appear here.</div>
          <button class="btn btn--primary" onclick="FVRouter.navigate('/generate')">Generate Your First Video</button>
        </div>
      `;
      return;
    }

    el.innerHTML = `
      <div class="video-grid">
        ${videos.map((v, i) => renderCard(v, i)).join('')}
      </div>
    `;
  }

  function renderCard(video, index) {
    const title = video.metadata?.title || video.filename.replace('.mp4', '').replace(/_/g, ' ');
    const niche = video.metadata?.niche || '';
    const nicheColor = NICHE_COLORS[niche] || 'muted';
    const thumbUrl = video.has_thumbnail ? `/api/library/${video.id}/thumbnail` : '';

    return `
      <div class="video-card" onclick="LibraryPage.openDetail(${index})">
        <div class="video-card__thumb">
          ${thumbUrl
            ? `<img src="${thumbUrl}" alt="" loading="lazy">`
            : '<span>&#9654;</span>'}
          <div class="video-card__play">
            <div class="video-card__play-icon">&#9654;</div>
          </div>
        </div>
        <div class="video-card__info">
          <div class="video-card__title">${escapeHtml(title)}</div>
          <div class="video-card__meta">
            <span class="video-card__date">${timeAgo(video.created)}</span>
            <span class="flex gap-2 items-center">
              ${niche ? `<span class="badge badge--${nicheColor}">${escapeHtml(niche)}</span>` : ''}
              <span class="video-card__size">${video.size_mb} MB</span>
            </span>
          </div>
        </div>
      </div>
    `;
  }

  function openDetail(index) {
    const video = videos[index];
    if (!video) return;

    const meta = video.metadata || {};
    const title = meta.title || video.filename.replace('.mp4', '').replace(/_/g, ' ');
    const description = meta.description || '';
    const hashtags = meta.hashtags || meta.tags || [];
    const bestTime = meta.best_posting_time || meta.posting_time || '';

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `
      <div class="modal" style="max-width:900px" onclick="event.stopPropagation()">
        <div class="modal__header">
          <h2 class="modal__title">${escapeHtml(title)}</h2>
          <button class="modal__close" onclick="this.closest('.modal-overlay').remove()">&times;</button>
        </div>
        <div class="modal__body">
          <div class="video-detail">
            <div class="video-detail__player">
              <video controls preload="metadata" src="/api/library/${video.id}/video"></video>
            </div>
            <div>
              ${description ? `
                <div class="video-detail__meta-section">
                  <div class="video-detail__meta-label">Description <button class="copy-btn" onclick="LibraryPage.copy(this, '${escapeAttr(description)}')">&#128203; Copy</button></div>
                  <div class="video-detail__meta-value">${escapeHtml(description)}</div>
                </div>
              ` : ''}

              ${hashtags.length ? `
                <div class="video-detail__meta-section">
                  <div class="video-detail__meta-label">Hashtags <button class="copy-btn" onclick="LibraryPage.copy(this, '${escapeAttr(hashtags.join(' '))}')">&#128203; Copy</button></div>
                  <div class="video-detail__tags">
                    ${hashtags.map(t => `<span class="badge badge--cyan">${escapeHtml(t.startsWith('#') ? t : '#' + t)}</span>`).join('')}
                  </div>
                </div>
              ` : ''}

              ${bestTime ? `
                <div class="video-detail__meta-section">
                  <div class="video-detail__meta-label">Best Posting Time</div>
                  <div class="video-detail__meta-value">${escapeHtml(bestTime)}</div>
                </div>
              ` : ''}

              <div class="video-detail__meta-section">
                <div class="video-detail__meta-label">File Info</div>
                <div class="video-detail__meta-value">${video.size_mb} MB &middot; ${new Date(video.created * 1000).toLocaleString()}</div>
              </div>

              <div style="display:flex;gap:var(--space-3);margin-top:var(--space-4)">
                <a class="btn btn--primary" href="/api/library/${video.id}/video" download="${video.filename}">
                  &#11015; Download
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
  }

  function copy(btn, text) {
    navigator.clipboard.writeText(text).then(() => {
      const orig = btn.innerHTML;
      btn.innerHTML = '&#10003; Copied';
      btn.style.color = 'var(--accent-green)';
      setTimeout(() => {
        btn.innerHTML = orig;
        btn.style.color = '';
      }, 1500);
    }).catch(() => {
      FVToast.show('Failed to copy', 'error');
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, ' ');
  }

  return { render, openDetail, copy };
})();
