"""
FVFactory Media Library
Browse, preview, and download generated videos with platform-ready metadata.
Run: streamlit run app/library.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from app.config import settings
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
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,300;1,9..40,400&display=swap');

/* ── Global ── */
.stApp {
    background: #0a0a0c;
    color: #e8e6e1;
}

/* Hide streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; max-width: 1400px; }

/* ── Hero header ── */
.lib-header {
    padding: 2.5rem 0 1.5rem 0;
    border-bottom: 1px solid #1a1a1f;
    margin-bottom: 2rem;
}
.lib-header h1 {
    font-family: 'Instrument Serif', Georgia, serif;
    font-size: 3.2rem;
    font-weight: 400;
    color: #f5f3ef;
    margin: 0;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.lib-header .subtitle {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.95rem;
    color: #6b6966;
    margin-top: 0.5rem;
    font-weight: 300;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

/* ── Stats bar ── */
.stats-bar {
    display: flex;
    gap: 2.5rem;
    padding: 1.2rem 0;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid #1a1a1f;
}
.stat-item {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
}
.stat-value {
    font-family: 'Instrument Serif', serif;
    font-size: 1.8rem;
    color: #f5f3ef;
    line-height: 1;
}
.stat-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.7rem;
    color: #5a5854;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

/* ── Video card ── */
.video-card {
    background: #111114;
    border: 1px solid #1e1e23;
    border-radius: 12px;
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    cursor: pointer;
    position: relative;
}
.video-card:hover {
    border-color: #2a2a30;
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.card-thumb {
    width: 100%;
    aspect-ratio: 9/16;
    object-fit: cover;
    display: block;
}
.card-body {
    padding: 1rem 1.1rem;
}
.card-title {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.85rem;
    font-weight: 500;
    color: #e0ddd8;
    line-height: 1.4;
    margin: 0 0 0.5rem 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.card-date {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.72rem;
    color: #4a4845;
    letter-spacing: 0.03em;
}
.card-cost {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.72rem;
    color: #7a9e7a;
    float: right;
}

/* ── Detail panel ── */
.detail-panel {
    background: #111114;
    border: 1px solid #1e1e23;
    border-radius: 16px;
    padding: 2rem;
    margin-bottom: 1.5rem;
}
.detail-title {
    font-family: 'Instrument Serif', serif;
    font-size: 1.8rem;
    color: #f5f3ef;
    margin: 0 0 0.3rem 0;
    line-height: 1.2;
}
.detail-date {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    color: #5a5854;
    margin-bottom: 1.5rem;
}

/* ── Platform tabs ── */
.platform-section {
    background: #0d0d10;
    border: 1px solid #1a1a1f;
    border-radius: 10px;
    padding: 1.3rem;
    margin-bottom: 1rem;
}
.platform-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.7rem;
    font-weight: 600;
    color: #8a8680;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.platform-label .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
}
.dot-yt { background: #ff4444; }
.dot-tt { background: #00f2ea; }
.dot-ig { background: #f77737; }

.meta-field {
    margin-bottom: 0.9rem;
}
.meta-field-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.68rem;
    color: #4a4845;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.25rem;
}
.meta-field-value {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.88rem;
    color: #d4d0cb;
    line-height: 1.5;
    background: #0a0a0c;
    border: 1px solid #1a1a1f;
    border-radius: 6px;
    padding: 0.6rem 0.8rem;
    word-break: break-word;
}

/* ── Tags ── */
.hashtag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
}
.hashtag {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.75rem;
    color: #9a9590;
    background: #161619;
    border: 1px solid #1e1e23;
    border-radius: 4px;
    padding: 0.2rem 0.5rem;
    display: inline-block;
}

/* ── Copy button ── */
.copy-hint {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.68rem;
    color: #3a3835;
    font-style: italic;
    margin-top: 0.3rem;
}

/* ── Performance stats ── */
.perf-stat {
    text-align: center;
    padding: 1rem;
    background: #111114;
    border: 1px solid #1e1e23;
    border-radius: 10px;
}
.perf-stat .value {
    font-family: 'Instrument Serif', serif;
    font-size: 1.6rem;
    color: #f5f3ef;
    line-height: 1.2;
}
.perf-stat .label {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.65rem;
    color: #5a5854;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 0.2rem;
}
.perf-stat.positive .value { color: #7a9e7a; }
.perf-stat.views .value { color: #8aaccc; }

.link-saved {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.78rem;
    color: #7a9e7a;
    padding: 0.4rem 0.7rem;
    background: #111a14;
    border: 1px solid #1a2e1e;
    border-radius: 6px;
    display: inline-block;
    margin: 0.2rem 0;
    word-break: break-all;
}

.spark-row {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 40px;
    margin: 0.5rem 0;
}
.spark-bar {
    flex: 1;
    background: #2a4a5a;
    border-radius: 2px 2px 0 0;
    min-width: 4px;
    transition: height 0.3s ease;
}

/* ── Streamlit overrides ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #1e1e23;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    color: #6b6966;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 0.8rem 1.5rem;
    border-bottom: 2px solid transparent;
}
.stTabs [aria-selected="true"] {
    color: #f5f3ef !important;
    border-bottom-color: #f5f3ef !important;
    background: transparent !important;
}

div[data-testid="stDownloadButton"] button {
    font-family: 'DM Sans', sans-serif;
    background: #1a1a1f;
    border: 1px solid #2a2a30;
    color: #e0ddd8;
    border-radius: 8px;
    font-size: 0.8rem;
    letter-spacing: 0.03em;
    transition: all 0.2s ease;
}
div[data-testid="stDownloadButton"] button:hover {
    background: #222228;
    border-color: #3a3a42;
}

div[data-testid="stButton"] button {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    border-radius: 8px;
}

/* Text input overrides */
.stTextArea textarea, .stTextInput input {
    font-family: 'DM Sans', sans-serif !important;
    background: #0a0a0c !important;
    border: 1px solid #1e1e23 !important;
    color: #d4d0cb !important;
    border-radius: 6px !important;
}

/* Selectbox */
div[data-baseweb="select"] {
    font-family: 'DM Sans', sans-serif !important;
}

/* Metrics */
div[data-testid="stMetric"] {
    background: #111114;
    border: 1px solid #1e1e23;
    border-radius: 10px;
    padding: 1rem;
}
div[data-testid="stMetric"] label {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.68rem !important;
    color: #5a5854 !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-family: 'Instrument Serif', serif !important;
    color: #f5f3ef !important;
}

/* Video player */
video {
    border-radius: 10px;
}

/* Empty state */
.empty-state {
    text-align: center;
    padding: 6rem 2rem;
}
.empty-state h2 {
    font-family: 'Instrument Serif', serif;
    font-size: 2rem;
    color: #3a3835;
    font-weight: 400;
}
.empty-state p {
    font-family: 'DM Sans', sans-serif;
    color: #2a2825;
    font-size: 0.9rem;
}
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

        # Load metadata
        meta_path = meta_dir / f"{video_id}.json"
        metadata = {}
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Check thumbnail
        thumb_path = thumb_dir / f"{video_id}.png"

        # Parse timestamp from filename
        try:
            ts_part = video_id.rsplit("_", 2)
            date_str = f"{ts_part[-2]}_{ts_part[-1]}"
            created = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
        except (ValueError, IndexError):
            created = datetime.fromtimestamp(mp4.stat().st_mtime)

        # File size
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
    """Load cost log."""
    cost_path = Path(settings.output_dir) / "cost_log.json"
    if cost_path.exists():
        try:
            data = json.loads(cost_path.read_text())
            return data.get("videos", {})
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def build_instagram_caption(video: dict) -> str:
    """Build an Instagram-optimized caption from metadata."""
    parts = []
    if video["description"]:
        parts.append(video["description"])
    parts.append("")  # blank line
    hashtags = video["hashtags"]
    if hashtags:
        # Instagram allows up to 30 hashtags
        ig_tags = hashtags[:30]
        parts.append(" ".join(ig_tags))
    return "\n".join(parts)


def build_tiktok_caption(video: dict) -> str:
    """Build a TikTok-optimized caption (title + hashtags, max 2200 chars)."""
    title = video["title_tt"]
    hashtags = video["hashtags"][:10]  # TikTok works best with fewer tags
    caption = f"{title} {' '.join(hashtags)}"
    return caption[:2200]


def build_youtube_description(video: dict) -> str:
    """Build a YouTube-optimized description."""
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


# =============================================================================
# UI COMPONENTS
# =============================================================================

def render_header(video_count: int, total_cost: float):
    """Render the library header."""
    perf = get_performance_summary()

    st.markdown("""
    <div class="lib-header">
        <h1>Media Library</h1>
        <div class="subtitle">FVFactory &mdash; Video Production Archive</div>
    </div>
    """, unsafe_allow_html=True)

    def _fmt_count(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    st.markdown(f"""
    <div class="stats-bar">
        <div class="stat-item">
            <span class="stat-value">{video_count}</span>
            <span class="stat-label">Videos</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">${total_cost:.2f}</span>
            <span class="stat-label">Total Spend</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">${total_cost / max(video_count, 1):.2f}</span>
            <span class="stat-label">Avg Cost</span>
        </div>
        <div class="stat-item">
            <span class="stat-value" style="color: #8aaccc;">{_fmt_count(perf['total_views'])}</span>
            <span class="stat-label">Total Views</span>
        </div>
        <div class="stat-item">
            <span class="stat-value" style="color: #cc8a8a;">{_fmt_count(perf['total_likes'])}</span>
            <span class="stat-label">Total Likes</span>
        </div>
        <div class="stat-item">
            <span class="stat-value">{perf['tracked_count']}</span>
            <span class="stat-label">Tracked</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_video_grid(videos: list[dict], costs: dict):
    """Render the video thumbnail grid."""
    cols_per_row = 4
    rows = [videos[i:i + cols_per_row] for i in range(0, len(videos), cols_per_row)]

    for row in rows:
        cols = st.columns(cols_per_row)
        for idx, video in enumerate(row):
            with cols[idx]:
                cost = costs.get(video["id"], {}).get("total", 0)
                cost_str = f"${cost:.2f}" if cost > 0 else ""

                # Thumbnail
                if video["thumbnail"]:
                    st.image(video["thumbnail"], use_container_width=True)
                else:
                    st.markdown("*No thumbnail*")

                # Title + date
                st.markdown(f"""
                <div class="card-body" style="padding: 0.5rem 0;">
                    <div class="card-title">{video['title_yt']}</div>
                    <div>
                        <span class="card-date">{video['created'].strftime('%b %d, %Y &middot; %I:%M %p')}</span>
                        <span class="card-cost">{cost_str}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Select button
                if st.button("View Details", key=f"select_{video['id']}", use_container_width=True):
                    st.session_state.selected_video = video["id"]
                    st.rerun()


def render_video_detail(video: dict, costs: dict):
    """Render the detailed view for a selected video."""
    cost_info = costs.get(video["id"], {})
    cost_total = cost_info.get("total", 0)

    # Back button
    if st.button("Back to Library"):
        st.session_state.selected_video = None
        st.rerun()

    st.markdown(f"""
    <div style="margin: 1rem 0;">
        <div class="detail-title">{video['title_yt']}</div>
        <div class="detail-date">{video['created'].strftime('%B %d, %Y at %I:%M %p')} &middot; {video['size_mb']:.1f} MB</div>
    </div>
    """, unsafe_allow_html=True)

    # Two-column layout: video player + metadata
    col_video, col_meta = st.columns([1, 1], gap="large")

    with col_video:
        # Video player
        st.video(video["path"])

        # Download row
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            with open(video["path"], "rb") as f:
                st.download_button(
                    "Download Video",
                    data=f.read(),
                    file_name=video["filename"],
                    mime="video/mp4",
                    use_container_width=True,
                )
        with dl_col2:
            if video["thumbnail"]:
                with open(video["thumbnail"], "rb") as f:
                    st.download_button(
                        "Download Thumbnail",
                        data=f.read(),
                        file_name=f"{video['id']}_thumb.png",
                        mime="image/png",
                        use_container_width=True,
                    )

        # Cost breakdown
        if cost_info and cost_info.get("items"):
            st.markdown("---")
            st.markdown(f"""
            <div class="platform-label">Cost Breakdown</div>
            """, unsafe_allow_html=True)

            metric_cols = st.columns(len(cost_info["items"]))
            for i, item in enumerate(cost_info["items"]):
                with metric_cols[i]:
                    label = item["item"].replace("_", " ").title()
                    st.metric(label, f"${item['cost']:.3f}", delta=f"x{item['quantity']}")

            st.metric("Total Cost", f"${cost_total:.2f}")

    with col_meta:
        # Platform-specific metadata tabs
        tab_yt, tab_tt, tab_ig, tab_perf = st.tabs(["YouTube", "TikTok", "Instagram", "Performance"])

        with tab_yt:
            st.markdown("""
            <div class="platform-label"><span class="dot dot-yt"></span> YouTube Shorts</div>
            """, unsafe_allow_html=True)

            yt_title = video["title_yt"]
            yt_desc = build_youtube_description(video)
            yt_tags = ", ".join(h.lstrip("#") for h in video["hashtags"])

            st.markdown("""<div class="meta-field-label">Title</div>""", unsafe_allow_html=True)
            st.code(yt_title, language=None)

            st.markdown("""<div class="meta-field-label">Description</div>""", unsafe_allow_html=True)
            st.code(yt_desc, language=None)

            st.markdown("""<div class="meta-field-label">Tags (comma-separated)</div>""", unsafe_allow_html=True)
            st.code(yt_tags, language=None)

            st.markdown('<div class="copy-hint">Click the copy icon on each field to copy</div>', unsafe_allow_html=True)

        with tab_tt:
            st.markdown("""
            <div class="platform-label"><span class="dot dot-tt"></span> TikTok</div>
            """, unsafe_allow_html=True)

            tt_caption = build_tiktok_caption(video)

            st.markdown("""<div class="meta-field-label">Caption (paste in TikTok)</div>""", unsafe_allow_html=True)
            st.code(tt_caption, language=None)

            st.markdown("""<div class="meta-field-label">Title</div>""", unsafe_allow_html=True)
            st.code(video["title_tt"], language=None)

            if video["hashtags"]:
                st.markdown("""<div class="meta-field-label">Hashtags</div>""", unsafe_allow_html=True)
                tag_html = "".join(f'<span class="hashtag">{h}</span>' for h in video["hashtags"][:10])
                st.markdown(f'<div class="hashtag-list">{tag_html}</div>', unsafe_allow_html=True)

        with tab_ig:
            st.markdown("""
            <div class="platform-label"><span class="dot dot-ig"></span> Instagram Reels</div>
            """, unsafe_allow_html=True)

            ig_caption = build_instagram_caption(video)

            st.markdown("""<div class="meta-field-label">Caption (paste in Instagram)</div>""", unsafe_allow_html=True)
            st.code(ig_caption, language=None)

            if video["hashtags"]:
                st.markdown("""<div class="meta-field-label">Hashtags</div>""", unsafe_allow_html=True)
                tag_html = "".join(f'<span class="hashtag">{h}</span>' for h in video["hashtags"][:30])
                st.markdown(f'<div class="hashtag-list">{tag_html}</div>', unsafe_allow_html=True)

            st.markdown(f"""
            <div class="meta-field-label">Suggested Posting Time</div>
            """, unsafe_allow_html=True)
            st.code(video["best_time"] if video["best_time"] else "Not available", language=None)

        with tab_perf:
            render_performance_tab(video)

        # Raw metadata expander
        if video["metadata"]:
            with st.expander("Raw Metadata JSON"):
                st.json(video["metadata"])


# =============================================================================
# PERFORMANCE TAB
# =============================================================================

def render_performance_tab(video: dict):
    """Render the performance tracking tab with link inputs and stats."""
    vid_id = video["id"]
    tracking = get_video_tracking(vid_id)
    links = tracking.get("links", {})
    latest = tracking.get("latest_stats", {})
    history = tracking.get("stats_history", [])

    # ── Platform Links ──
    st.markdown("""
    <div class="platform-label" style="margin-top: 0.5rem;">Paste your upload links</div>
    """, unsafe_allow_html=True)

    # YouTube link
    yt_link = st.text_input(
        "YouTube URL",
        value=links.get("youtube", ""),
        placeholder="https://youtube.com/shorts/...",
        key=f"yt_link_{vid_id}",
    )
    if yt_link and yt_link != links.get("youtube", ""):
        save_link(vid_id, "youtube", yt_link)
        st.rerun()

    # TikTok link
    tt_link = st.text_input(
        "TikTok URL",
        value=links.get("tiktok", ""),
        placeholder="https://tiktok.com/@user/video/...",
        key=f"tt_link_{vid_id}",
    )
    if tt_link and tt_link != links.get("tiktok", ""):
        save_link(vid_id, "tiktok", tt_link)
        st.rerun()

    # Instagram link
    ig_link = st.text_input(
        "Instagram URL",
        value=links.get("instagram", ""),
        placeholder="https://instagram.com/reel/...",
        key=f"ig_link_{vid_id}",
    )
    if ig_link and ig_link != links.get("instagram", ""):
        save_link(vid_id, "instagram", ig_link)
        st.rerun()

    # ── Latest Stats ──
    if latest:
        st.markdown("---")
        st.markdown("""
        <div class="platform-label">Latest Stats</div>
        """, unsafe_allow_html=True)

        for platform, stats in latest.items():
            platform_colors = {"youtube": "#ff4444", "tiktok": "#00f2ea", "instagram": "#f77737"}
            color = platform_colors.get(platform, "#888")

            st.markdown(f"""
            <div style="font-family: 'DM Sans', sans-serif; font-size: 0.75rem;
                        color: {color}; text-transform: uppercase; letter-spacing: 0.1em;
                        margin: 0.8rem 0 0.4rem 0;">
                {platform}
            </div>
            """, unsafe_allow_html=True)

            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("Views", f"{stats.get('views', 0):,}")
            with s2:
                st.metric("Likes", f"{stats.get('likes', 0):,}")
            with s3:
                st.metric("Comments", f"{stats.get('comments', 0):,}")

        # Show history count
        if history:
            st.markdown(f"""
            <div class="copy-hint">{len(history)} stat snapshots recorded</div>
            """, unsafe_allow_html=True)

    # ── Fetch / Update Buttons ──
    st.markdown("---")

    btn_col1, btn_col2 = st.columns(2)

    with btn_col1:
        if links.get("youtube") and settings.youtube_api_key:
            if st.button("Refresh YouTube Stats", key=f"fetch_yt_{vid_id}", use_container_width=True):
                with st.spinner("Fetching..."):
                    result = fetch_youtube_stats(vid_id)
                if result:
                    st.success(f"{result['views']:,} views")
                    st.rerun()
                else:
                    st.error("Failed to fetch stats")
        elif links.get("youtube"):
            st.caption("Set YOUTUBE_API_KEY to auto-fetch stats")

    with btn_col2:
        if st.button("Update Stats Manually", key=f"manual_{vid_id}", use_container_width=True):
            st.session_state[f"show_manual_{vid_id}"] = True

    # ── Manual Stats Form ──
    if st.session_state.get(f"show_manual_{vid_id}", False):
        st.markdown("---")
        with st.form(key=f"manual_form_{vid_id}"):
            st.markdown("""
            <div class="platform-label">Update Stats Manually</div>
            """, unsafe_allow_html=True)

            manual_platform = st.selectbox(
                "Platform",
                options=["tiktok", "instagram", "youtube"],
                key=f"manual_plat_{vid_id}",
            )

            mc1, mc2 = st.columns(2)
            with mc1:
                manual_views = st.number_input("Views", min_value=0, value=0, key=f"mv_{vid_id}")
                manual_likes = st.number_input("Likes", min_value=0, value=0, key=f"ml_{vid_id}")
            with mc2:
                manual_comments = st.number_input("Comments", min_value=0, value=0, key=f"mc_{vid_id}")
                manual_shares = st.number_input("Shares", min_value=0, value=0, key=f"ms_{vid_id}")

            if st.form_submit_button("Save Stats", use_container_width=True):
                save_manual_stats(
                    vid_id, manual_platform,
                    views=manual_views, likes=manual_likes,
                    comments=manual_comments, shares=manual_shares,
                )
                st.session_state[f"show_manual_{vid_id}"] = False
                st.success("Stats saved!")
                st.rerun()

    # ── Stats History ──
    if history and len(history) > 1:
        with st.expander("Stats History"):
            for snap in reversed(history[-10:]):
                ts = snap.get("timestamp", "")[:19].replace("T", " ")
                plat = snap.get("platform", "?")
                views = snap.get("views", 0)
                likes = snap.get("likes", 0)
                st.markdown(f"""
                <div style="font-family: 'DM Sans', sans-serif; font-size: 0.78rem;
                            color: #9a9590; padding: 0.3rem 0;
                            border-bottom: 1px solid #1a1a1f;">
                    <span style="color: #5a5854;">{ts}</span> &middot;
                    <span style="text-transform: uppercase; letter-spacing: 0.05em;">{plat}</span> &middot;
                    {views:,} views &middot; {likes:,} likes
                </div>
                """, unsafe_allow_html=True)


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Init session state
    if "selected_video" not in st.session_state:
        st.session_state.selected_video = None

    # Load data
    videos = scan_videos()
    costs = load_costs()
    total_cost = sum(v.get("total", 0) for v in costs.values())

    if not videos:
        render_header(0, 0)
        st.markdown("""
        <div class="empty-state">
            <h2>No videos yet</h2>
            <p>Run <code>./daily.sh</code> or <code>python main.py --auto</code> to generate your first video.</p>
        </div>
        """, unsafe_allow_html=True)
        return

    # Detail view or grid view
    if st.session_state.selected_video:
        video = next((v for v in videos if v["id"] == st.session_state.selected_video), None)
        if video:
            render_video_detail(video, costs)
        else:
            st.session_state.selected_video = None
            st.rerun()
    else:
        render_header(len(videos), total_cost)
        render_video_grid(videos, costs)


if __name__ == "__main__":
    main()
