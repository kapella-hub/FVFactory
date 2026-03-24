"""
FVFactory Media Library
Browse, preview, and download generated videos with platform-ready metadata.
Run: streamlit run app/library.py
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from app.config import settings
from app.generator_worker import GeneratorWorker
from app.trend_scout import TrendScout
from app.tracker import (
    get_video_tracking,
    get_all_tracking,
    save_link,
    save_manual_stats,
    fetch_youtube_stats,
    get_performance_summary,
)


# =============================================================================
# PAGE CONFIG & STYLING
# =============================================================================

st.set_page_config(
    page_title="FVFactory Library",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Outfit:wght@300;400;500;600;700&display=swap');

/* ── Reset & Global ── */
.stApp {
    background: #09090b;
    color: #e4e4e7;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem 3rem 2rem; max-width: 1440px; }

/* ── Top bar ── */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 0 1.5rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 2rem;
}
.topbar-left {
    display: flex;
    align-items: baseline;
    gap: 1rem;
}
.topbar-logo {
    font-family: 'Space Mono', monospace;
    font-size: 0.85rem;
    font-weight: 700;
    color: #a1a1aa;
    letter-spacing: 0.15em;
    text-transform: uppercase;
}
.topbar-divider {
    color: rgba(255,255,255,0.08);
    font-size: 1.2rem;
}
.topbar-page {
    font-family: 'Outfit', sans-serif;
    font-size: 1.05rem;
    font-weight: 400;
    color: #71717a;
}

/* ── Stats pills ── */
.stats-row {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 2rem;
}
.stat-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.45rem 1rem;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 100px;
    font-family: 'Outfit', sans-serif;
    font-size: 0.78rem;
    color: #a1a1aa;
}
.stat-pill .num {
    font-weight: 600;
    color: #fafafa;
    font-size: 0.85rem;
}
.stat-pill.accent .num { color: #22d3ee; }
.stat-pill.warm .num { color: #fb923c; }
.stat-pill.green .num { color: #4ade80; }

/* ── Video grid ── */
.vid-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 1.25rem;
}

/* ── Card (rendered by Streamlit columns, styled here) ── */
.card-wrap {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 14px;
    overflow: hidden;
    transition: all 0.25s ease;
    position: relative;
}
.card-wrap:hover {
    border-color: rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.04);
    transform: translateY(-3px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
}
.card-info {
    padding: 0.85rem 1rem 0.5rem 1rem;
}
.card-title {
    font-family: 'Outfit', sans-serif;
    font-size: 0.82rem;
    font-weight: 500;
    color: #e4e4e7;
    line-height: 1.35;
    margin: 0 0 0.4rem 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.card-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.card-date {
    font-family: 'Space Mono', monospace;
    font-size: 0.62rem;
    color: #52525b;
    letter-spacing: 0.03em;
}
.card-cost {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: #4ade80;
    background: rgba(74, 222, 128, 0.08);
    padding: 0.15rem 0.45rem;
    border-radius: 4px;
}
.card-duration {
    position: absolute;
    top: 0.6rem;
    right: 0.6rem;
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: #fff;
    background: rgba(0,0,0,0.7);
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    backdrop-filter: blur(4px);
}

/* ── Detail view ── */
.detail-back {
    font-family: 'Outfit', sans-serif;
    font-size: 0.8rem;
    color: #71717a;
    cursor: pointer;
    margin-bottom: 1rem;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
}
.detail-header {
    margin-bottom: 1.5rem;
}
.detail-title {
    font-family: 'Outfit', sans-serif;
    font-size: 1.6rem;
    font-weight: 600;
    color: #fafafa;
    margin: 0 0 0.3rem 0;
    line-height: 1.25;
}
.detail-subtitle {
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    color: #52525b;
}
.detail-subtitle span {
    color: #71717a;
}

/* ── Platform sections ── */
.plat-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.8rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}
.plat-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.plat-dot-yt { background: #ef4444; }
.plat-dot-tt { background: #22d3ee; }
.plat-dot-ig { background: linear-gradient(135deg, #f59e0b, #ec4899, #8b5cf6); }
.plat-name {
    font-family: 'Outfit', sans-serif;
    font-size: 0.75rem;
    font-weight: 600;
    color: #a1a1aa;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}

.field-label {
    font-family: 'Space Mono', monospace;
    font-size: 0.6rem;
    color: #52525b;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 0.3rem;
    margin-top: 0.7rem;
}

/* ── Tags ── */
.tag-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-top: 0.3rem;
}
.tag {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: #a1a1aa;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 4px;
    padding: 0.2rem 0.5rem;
}

/* ── Cost cards ── */
.cost-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
    gap: 0.5rem;
    margin: 0.5rem 0;
}
.cost-card {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 10px;
    padding: 0.7rem;
    text-align: center;
}
.cost-card .amount {
    font-family: 'Space Mono', monospace;
    font-size: 0.9rem;
    font-weight: 700;
    color: #fafafa;
}
.cost-card .label {
    font-family: 'Outfit', sans-serif;
    font-size: 0.6rem;
    color: #52525b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.2rem;
}
.cost-card .qty {
    font-family: 'Space Mono', monospace;
    font-size: 0.55rem;
    color: #4ade80;
}
.cost-total {
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    color: #71717a;
    text-align: right;
    margin-top: 0.3rem;
}
.cost-total strong {
    color: #fafafa;
    font-size: 0.9rem;
}

/* ── Streamlit overrides ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: rgba(255,255,255,0.02);
    border-radius: 10px;
    padding: 0.25rem;
    border: 1px solid rgba(255,255,255,0.05);
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Outfit', sans-serif;
    font-size: 0.75rem;
    font-weight: 500;
    color: #52525b;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0.5rem 1.2rem;
    border-radius: 8px;
    border-bottom: none !important;
}
.stTabs [aria-selected="true"] {
    color: #fafafa !important;
    background: rgba(255,255,255,0.06) !important;
}

div[data-testid="stDownloadButton"] button,
div[data-testid="stButton"] button {
    font-family: 'Outfit', sans-serif;
    font-weight: 500;
    font-size: 0.78rem;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03);
    color: #e4e4e7;
    padding: 0.5rem 1rem;
    transition: all 0.2s ease;
}
div[data-testid="stDownloadButton"] button:hover,
div[data-testid="stButton"] button:hover {
    background: rgba(255,255,255,0.08);
    border-color: rgba(255,255,255,0.15);
}

.stTextArea textarea, .stTextInput input {
    font-family: 'Outfit', sans-serif !important;
    font-size: 0.82rem !important;
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    color: #e4e4e7 !important;
    border-radius: 10px !important;
}

div[data-testid="stMetric"] {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 10px;
    padding: 0.8rem;
}
div[data-testid="stMetric"] label {
    font-family: 'Space Mono', monospace !important;
    font-size: 0.6rem !important;
    color: #52525b !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-family: 'Outfit', sans-serif !important;
    font-weight: 600 !important;
    color: #fafafa !important;
}

/* Code blocks for copy */
div[data-testid="stCode"] {
    border-radius: 8px !important;
}
div[data-testid="stCode"] code {
    font-family: 'Space Mono', monospace !important;
    font-size: 0.72rem !important;
}

video {
    border-radius: 12px;
    max-height: 480px;
    width: auto !important;
    margin: 0 auto;
    display: block;
}

.empty-state {
    text-align: center;
    padding: 8rem 2rem;
}
.empty-state h2 {
    font-family: 'Outfit', sans-serif;
    font-size: 1.5rem;
    font-weight: 400;
    color: #3f3f46;
}
.empty-state p {
    font-family: 'Space Mono', monospace;
    color: #27272a;
    font-size: 0.8rem;
}

/* Hide fullscreen button on images */
button[title="View fullscreen"] { display: none !important; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# DATA LOADING
# =============================================================================

def scan_videos() -> list[dict]:
    """Scan output directory for videos and their associated metadata."""
    output_dir = Path(settings.output_dir)
    meta_dir = output_dir / "metadata"
    thumb_dir = output_dir / "thumbnails"

    videos = []

    for mp4 in sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        video_id = mp4.stem

        meta_path = meta_dir / f"{video_id}.json"
        metadata = {}
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        thumb_path = thumb_dir / f"{video_id}.png"

        try:
            ts_part = video_id.rsplit("_", 2)
            date_str = f"{ts_part[-2]}_{ts_part[-1]}"
            created = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
        except (ValueError, IndexError):
            created = datetime.fromtimestamp(mp4.stat().st_mtime)

        size_mb = mp4.stat().st_size / (1024 * 1024)

        videos.append({
            "id": video_id,
            "path": str(mp4),
            "filename": mp4.name,
            "thumbnail": str(thumb_path) if thumb_path.exists() else None,
            "metadata": metadata,
            "created": created,
            "size_mb": size_mb,
            "title_yt": metadata.get("title_youtube", video_id.replace("_", " ")),
            "title_tt": metadata.get("title_tiktok", video_id.replace("_", " ")),
            "description": metadata.get("description", ""),
            "hashtags": metadata.get("hashtags", []),
            "best_time": metadata.get("best_posting_time", ""),
        })

    return videos


def load_costs() -> dict:
    cost_path = Path(settings.output_dir) / "cost_log.json"
    if cost_path.exists():
        try:
            data = json.loads(cost_path.read_text())
            return data.get("videos", {})
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def build_youtube_description(video: dict) -> str:
    parts = []
    if video["description"]:
        parts.append(video["description"])
    parts.append("")
    hashtags = video["hashtags"]
    if hashtags:
        if "#Shorts" not in hashtags:
            hashtags = ["#Shorts"] + hashtags
        parts.append(" ".join(hashtags[:15]))
    return "\n".join(parts)


def build_tiktok_caption(video: dict) -> str:
    title = video["title_tt"]
    hashtags = video["hashtags"][:10]
    return f"{title} {' '.join(hashtags)}"[:2200]


def build_instagram_caption(video: dict) -> str:
    parts = []
    if video["description"]:
        parts.append(video["description"])
    parts.append("")
    if video["hashtags"]:
        parts.append(" ".join(video["hashtags"][:30]))
    return "\n".join(parts)


# =============================================================================
# RENDER: TOP BAR
# =============================================================================

def render_topbar():
    page = st.session_state.get("page", "library")
    st.markdown(f"""
    <div class="topbar">
        <div class="topbar-left">
            <span class="topbar-logo">FVFactory</span>
            <span class="topbar-divider">/</span>
            <span class="topbar-page">{'Library' if page == 'library' else 'Generate'}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, _ = st.columns([1, 1, 8])
    with c1:
        if st.button("Library", use_container_width=True,
                      disabled=(page == "library"), key="nav_library"):
            st.session_state.page = "library"
            st.rerun()
    with c2:
        if st.button("Generate", use_container_width=True,
                      disabled=(page == "generate"), key="nav_generate"):
            st.session_state.page = "generate"
            st.rerun()


# =============================================================================
# RENDER: GRID VIEW
# =============================================================================

def render_grid(videos: list[dict], costs: dict):
    perf = get_performance_summary()
    total_cost = sum(v.get("total", 0) for v in costs.values())

    # Stats pills
    st.markdown(f"""
    <div class="stats-row">
        <div class="stat-pill"><span class="num">{len(videos)}</span> videos</div>
        <div class="stat-pill green"><span class="num">${total_cost:.2f}</span> spent</div>
        <div class="stat-pill accent"><span class="num">{_fmt(perf['total_views'])}</span> views</div>
        <div class="stat-pill warm"><span class="num">{_fmt(perf['total_likes'])}</span> likes</div>
    </div>
    """, unsafe_allow_html=True)

    # Video cards — 4 per row
    cols_per_row = 4
    rows = [videos[i:i + cols_per_row] for i in range(0, len(videos), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row, gap="small")
        for idx, video in enumerate(row):
            with cols[idx]:
                cost = costs.get(video["id"], {}).get("total", 0)

                if video["thumbnail"]:
                    st.image(video["thumbnail"], use_container_width=True)

                cost_str = f"${cost:.2f}" if cost > 0 else ""
                st.markdown(f"""
                <div class="card-info">
                    <div class="card-title">{video['title_yt']}</div>
                    <div class="card-meta">
                        <span class="card-date">{video['created'].strftime('%b %d, %Y')}</span>
                        <span class="card-cost">{cost_str}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if st.button("Open", key=f"sel_{video['id']}", use_container_width=True):
                    st.session_state.selected_video = video["id"]
                    st.rerun()


# =============================================================================
# HELPERS
# =============================================================================

def _copyable_field(label: str, value: str, key: str, multiline: bool = False):
    """Render a text field with a Copy button that works over HTTP."""
    import streamlit.components.v1 as components
    import html as html_mod
    import json as json_mod

    if multiline:
        st.text_area(label, value=value, key=key, height=120)
    else:
        st.text_input(label, value=value, key=key)

    # Use components.html for JS — st.markdown escapes scripts
    val_json = json_mod.dumps(value)
    components.html(f"""
    <button id="btn_{key}" onclick="
        var ta = document.createElement('textarea');
        ta.value = {val_json};
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        this.textContent = 'Copied!';
        setTimeout(function(){{ document.getElementById('btn_{key}').textContent = 'Copy'; }}, 1500);
    " style="
        font-family: sans-serif;
        font-size: 12px;
        color: #a1a1aa;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 6px;
        padding: 4px 14px;
        cursor: pointer;
    ">Copy</button>
    """, height=36)


# =============================================================================
# RENDER: DETAIL VIEW
# =============================================================================

def render_detail(video: dict, costs: dict):
    cost_info = costs.get(video["id"], {})
    cost_total = cost_info.get("total", 0)

    if st.button("< Back to Library", key="back"):
        st.session_state.selected_video = None
        st.rerun()

    # Header
    st.markdown(f"""
    <div class="detail-header">
        <div class="detail-title">{video['title_yt']}</div>
        <div class="detail-subtitle">
            {video['created'].strftime('%b %d, %Y at %I:%M %p')}
            <span>&middot;</span> {video['size_mb']:.1f} MB
            <span>&middot;</span> ${cost_total:.2f}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Layout: video (constrained) left, metadata tabs right
    col_vid, col_meta = st.columns([4, 7], gap="large")

    with col_vid:
        st.video(video["path"])

        dl1, dl2 = st.columns(2)
        with dl1:
            with open(video["path"], "rb") as f:
                st.download_button("Download MP4", data=f.read(),
                                   file_name=video["filename"], mime="video/mp4",
                                   use_container_width=True)
        with dl2:
            if video["thumbnail"]:
                with open(video["thumbnail"], "rb") as f:
                    st.download_button("Download Thumb", data=f.read(),
                                       file_name=f"{video['id']}.png", mime="image/png",
                                       use_container_width=True)

        # Cost breakdown inline
        if cost_info and cost_info.get("items"):
            items = cost_info["items"]
            cards_html = ""
            for item in items:
                label = item["item"].replace("_", " ").replace("openai ", "").title()
                cards_html += f"""
                <div class="cost-card">
                    <div class="amount">${item['cost']:.3f}</div>
                    <div class="label">{label}</div>
                    <div class="qty">x{item['quantity']}</div>
                </div>"""

            st.markdown(f"""
            <div class="field-label" style="margin-top: 1rem;">Cost Breakdown</div>
            <div class="cost-grid">{cards_html}</div>
            <div class="cost-total">Total: <strong>${cost_total:.2f}</strong></div>
            """, unsafe_allow_html=True)

    with col_meta:
        tab_yt, tab_tt, tab_ig, tab_perf = st.tabs(["YouTube", "TikTok", "Instagram", "Performance"])

        with tab_yt:
            st.markdown('<div class="plat-header"><span class="plat-dot plat-dot-yt"></span><span class="plat-name">YouTube Shorts</span></div>', unsafe_allow_html=True)

            vid = video["id"]
            _copyable_field("Title", video["title_yt"], f"yt_title_{vid}")
            _copyable_field("Description", build_youtube_description(video), f"yt_desc_{vid}", multiline=True)
            _copyable_field("Tags", ", ".join(h.lstrip("#") for h in video["hashtags"]), f"yt_tags_{vid}")

        with tab_tt:
            st.markdown('<div class="plat-header"><span class="plat-dot plat-dot-tt"></span><span class="plat-name">TikTok</span></div>', unsafe_allow_html=True)

            _copyable_field("Caption", build_tiktok_caption(video), f"tt_cap_{vid}", multiline=True)

            if video["hashtags"]:
                _copyable_field("Hashtags", " ".join(video["hashtags"][:10]), f"tt_tags_{vid}")

        with tab_ig:
            st.markdown('<div class="plat-header"><span class="plat-dot plat-dot-ig"></span><span class="plat-name">Instagram Reels</span></div>', unsafe_allow_html=True)

            _copyable_field("Caption", build_instagram_caption(video), f"ig_cap_{vid}", multiline=True)

            if video["hashtags"]:
                _copyable_field("Hashtags", " ".join(video["hashtags"][:30]), f"ig_tags_{vid}")

        with tab_perf:
            render_performance_tab(video)

        if video["metadata"]:
            with st.expander("Raw JSON"):
                st.json(video["metadata"])


# =============================================================================
# RENDER: PERFORMANCE TAB
# =============================================================================

def render_performance_tab(video: dict):
    vid_id = video["id"]
    tracking = get_video_tracking(vid_id)
    links = tracking.get("links", {})
    latest = tracking.get("latest_stats", {})
    history = tracking.get("stats_history", [])

    st.markdown('<div class="plat-header"><span class="plat-name">Track Performance</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="field-label">Paste upload links</div>', unsafe_allow_html=True)

    yt_link = st.text_input("YouTube", value=links.get("youtube", ""),
                            placeholder="https://youtube.com/shorts/...", key=f"yt_{vid_id}")
    if yt_link and yt_link != links.get("youtube", ""):
        save_link(vid_id, "youtube", yt_link)
        st.rerun()

    tt_link = st.text_input("TikTok", value=links.get("tiktok", ""),
                            placeholder="https://tiktok.com/@user/video/...", key=f"tt_{vid_id}")
    if tt_link and tt_link != links.get("tiktok", ""):
        save_link(vid_id, "tiktok", tt_link)
        st.rerun()

    ig_link = st.text_input("Instagram", value=links.get("instagram", ""),
                            placeholder="https://instagram.com/reel/...", key=f"ig_{vid_id}")
    if ig_link and ig_link != links.get("instagram", ""):
        save_link(vid_id, "instagram", ig_link)
        st.rerun()

    # Stats display
    if latest:
        st.markdown("---")
        for platform, stats in latest.items():
            colors = {"youtube": "#ef4444", "tiktok": "#22d3ee", "instagram": "#f59e0b"}
            color = colors.get(platform, "#888")
            st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:0.65rem;color:{color};text-transform:uppercase;letter-spacing:0.1em;margin:0.6rem 0 0.3rem;">{platform}</div>', unsafe_allow_html=True)
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("Views", f"{stats.get('views', 0):,}")
            with s2:
                st.metric("Likes", f"{stats.get('likes', 0):,}")
            with s3:
                st.metric("Comments", f"{stats.get('comments', 0):,}")

    # Action buttons
    st.markdown("---")
    b1, b2 = st.columns(2)
    with b1:
        if links.get("youtube") and settings.youtube_api_key:
            if st.button("Refresh YT Stats", key=f"fetch_{vid_id}", use_container_width=True):
                with st.spinner("Fetching..."):
                    result = fetch_youtube_stats(vid_id)
                if result:
                    st.rerun()
    with b2:
        if st.button("Manual Update", key=f"manual_{vid_id}", use_container_width=True):
            st.session_state[f"show_manual_{vid_id}"] = True

    if st.session_state.get(f"show_manual_{vid_id}", False):
        with st.form(key=f"form_{vid_id}"):
            plat = st.selectbox("Platform", ["tiktok", "instagram", "youtube"], key=f"mp_{vid_id}")
            c1, c2 = st.columns(2)
            with c1:
                views = st.number_input("Views", min_value=0, value=0, key=f"v_{vid_id}")
                likes = st.number_input("Likes", min_value=0, value=0, key=f"l_{vid_id}")
            with c2:
                comments = st.number_input("Comments", min_value=0, value=0, key=f"c_{vid_id}")
                shares = st.number_input("Shares", min_value=0, value=0, key=f"s_{vid_id}")
            if st.form_submit_button("Save", use_container_width=True):
                save_manual_stats(vid_id, plat, views=views, likes=likes, comments=comments, shares=shares)
                st.session_state[f"show_manual_{vid_id}"] = False
                st.rerun()


# =============================================================================
# RENDER: GENERATE PAGE
# =============================================================================

def render_generate_page():
    st.markdown('<div class="detail-title">Generate Video</div>', unsafe_allow_html=True)

    worker = st.session_state.worker

    if worker.status == "running":
        render_generation_progress(worker)
        return

    if worker.status == "done":
        render_generation_complete(worker)
        return

    if worker.status == "error":
        render_generation_error(worker)
        return

    # Form
    auto_topic = st.checkbox("Auto-generate topic from niche", value=True)

    if auto_topic:
        topic = ""
    else:
        topic = st.text_input("Topic", placeholder="e.g., Why the Roman Empire Really Fell")

    niche = st.selectbox("Niche", ["stoicism", "self-improvement", "philosophy", "motivation", "psychology"])
    voice = st.selectbox("Voice", ["bill", "george", "daniel", "josh", "rachel"])
    motion = st.checkbox("Motion clips", value=True)

    can_generate = auto_topic or bool(topic.strip())

    if st.button("Generate Video", type="primary", disabled=not can_generate, use_container_width=True):
        if auto_topic:
            scout = TrendScout()
            topics = scout.discover_topics(niche=niche, count=1)
            topic = topics[0].title if topics else f"{niche} insights"

        worker.start(topic=topic, niche=niche, voice=voice, enable_motion=motion)
        st.rerun()


def render_generation_progress(worker):
    st.info(f"Generating video... ({len(worker.logs)} steps completed)")
    with st.container(height=400):
        st.code("\n".join(worker.logs[-30:]), language=None)
    time.sleep(2)
    st.rerun()


def render_generation_complete(worker):
    st.success(f"Video generated: {worker.result}")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("View in Library", use_container_width=True):
            worker.reset()
            st.session_state.page = "library"
            st.rerun()
    with c2:
        if st.button("Generate Another", use_container_width=True):
            worker.reset()
            st.rerun()


def render_generation_error(worker):
    st.error(f"Generation failed: {worker.error}")
    if st.button("Try Again", use_container_width=True):
        worker.reset()
        st.rerun()


# =============================================================================
# MAIN
# =============================================================================

def main():
    if "selected_video" not in st.session_state:
        st.session_state.selected_video = None
    if "page" not in st.session_state:
        st.session_state.page = "library"
    if "worker" not in st.session_state:
        st.session_state.worker = GeneratorWorker()

    videos = scan_videos()
    costs = load_costs()

    render_topbar()

    if st.session_state.page == "generate":
        render_generate_page()
    elif not videos:
        st.markdown("""
        <div class="empty-state">
            <h2>No videos yet</h2>
            <p>Run ./daily.sh or python main.py --auto</p>
        </div>
        """, unsafe_allow_html=True)
    elif st.session_state.selected_video:
        video = next((v for v in videos if v["id"] == st.session_state.selected_video), None)
        if video:
            render_detail(video, costs)
        else:
            st.session_state.selected_video = None
            st.rerun()
    else:
        render_grid(videos, costs)


if __name__ == "__main__":
    main()
