"""
YouTube Shorts Uploader - Upload videos to YouTube using the Data API v3

Auth flow:
  1. Create OAuth2 credentials at console.cloud.google.com
     - APIs & Services > Credentials > Create OAuth Client ID (Desktop app)
     - Enable YouTube Data API v3
     - Download client_secrets.json
  2. Run: python -m app.uploader --auth
     - Opens browser for Google login (one-time)
     - Saves token to youtube_token.json
  3. Copy youtube_token.json to VPS container
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# YouTube API constants
YOUTUBE_API_SERVICE = "youtube"
YOUTUBE_API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_CATEGORY_EDUCATION = "27"
YOUTUBE_CATEGORY_ENTERTAINMENT = "24"
YOUTUBE_CATEGORY_SCIENCE = "28"
YOUTUBE_CATEGORY_HOWTO = "26"

NICHE_CATEGORY_MAP = {
    "stoicism": YOUTUBE_CATEGORY_EDUCATION,
    "philosophy": YOUTUBE_CATEGORY_EDUCATION,
    "self-improvement": YOUTUBE_CATEGORY_HOWTO,
    "motivation": YOUTUBE_CATEGORY_EDUCATION,
    "history": YOUTUBE_CATEGORY_EDUCATION,
    "science": YOUTUBE_CATEGORY_SCIENCE,
    "tech": YOUTUBE_CATEGORY_SCIENCE,
    "technology": YOUTUBE_CATEGORY_SCIENCE,
    "finance": YOUTUBE_CATEGORY_EDUCATION,
    "crypto": YOUTUBE_CATEGORY_EDUCATION,
    "gaming": YOUTUBE_CATEGORY_ENTERTAINMENT,
    "entertainment": YOUTUBE_CATEGORY_ENTERTAINMENT,
    "health": YOUTUBE_CATEGORY_HOWTO,
    "lifestyle": YOUTUBE_CATEGORY_HOWTO,
}


class UploaderError(Exception):
    """Base exception for upload errors"""
    pass


class YouTubeUploader:
    """Uploads videos to YouTube Shorts via the Data API v3."""

    def __init__(self):
        self.client_secrets_path = Path(settings.youtube_client_secrets)
        self.token_path = Path(settings.youtube_token_path)

    def _get_authenticated_service(self):
        """Build an authenticated YouTube API service."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            raise UploaderError(
                "YouTube API dependencies not installed. "
                "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )

        creds = None

        # Load existing token
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        # Refresh or re-auth if needed
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token
                self.token_path.write_text(creds.to_json())
                logger.info("YouTube token refreshed")
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}")
                creds = None

        if not creds or not creds.valid:
            raise UploaderError(
                f"YouTube token not found or expired at {self.token_path}. "
                "Run: python -m app.uploader --auth"
            )

        return build(YOUTUBE_API_SERVICE, YOUTUBE_API_VERSION, credentials=creds)

    def authenticate(self):
        """Run the interactive OAuth2 flow (one-time, requires browser)."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            raise UploaderError(
                "google-auth-oauthlib not installed. "
                "Run: pip install google-auth-oauthlib"
            )

        if not self.client_secrets_path.exists():
            raise UploaderError(
                f"Client secrets file not found: {self.client_secrets_path}\n"
                "Download it from Google Cloud Console > APIs & Services > Credentials"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_path), SCOPES
        )
        creds = flow.run_local_server(port=0)

        self.token_path.write_text(creds.to_json())
        logger.info(f"YouTube token saved to {self.token_path}")
        print(f"\nAuthentication successful! Token saved to: {self.token_path}")
        print("Copy this file to your VPS container for headless uploads.")

    def upload(
        self,
        video_path: str,
        video_id: str,
        niche: Optional[str] = None,
    ) -> str:
        """
        Upload a video to YouTube Shorts.

        Uses metadata from output/metadata/{video_id}.json if available.

        Args:
            video_path: Path to the MP4 file
            video_id: Video identifier (used to find metadata/thumbnail)
            niche: Optional niche for category mapping

        Returns:
            YouTube video URL

        Raises:
            UploaderError: If upload fails
        """
        from googleapiclient.http import MediaFileUpload

        video_file = Path(video_path)
        if not video_file.exists():
            raise UploaderError(f"Video file not found: {video_path}")

        # Load metadata
        metadata = self._load_metadata(video_id)
        title = metadata.get("title_youtube", video_id.replace("_", " "))
        description = metadata.get("description", "")
        hashtags = metadata.get("hashtags", [])

        # Build description with hashtags
        hashtag_str = " ".join(hashtags)
        if "#Shorts" not in hashtag_str:
            hashtag_str = "#Shorts " + hashtag_str
        full_description = f"{description}\n\n{hashtag_str}" if description else hashtag_str

        # Convert hashtags to tags (strip #)
        tags = [h.lstrip("#") for h in hashtags]
        if "Shorts" not in tags:
            tags.insert(0, "Shorts")

        # Pick category
        category_id = NICHE_CATEGORY_MAP.get(
            (niche or "").lower(), YOUTUBE_CATEGORY_EDUCATION
        )

        body = {
            "snippet": {
                "title": title[:100],  # YouTube max 100 chars
                "description": full_description[:5000],
                "tags": tags[:500],
                "categoryId": category_id,
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": settings.youtube_privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        logger.info(f"Uploading to YouTube: {title}")
        logger.info(f"Privacy: {settings.youtube_privacy}, Category: {category_id}")

        youtube = self._get_authenticated_service()

        media = MediaFileUpload(
            str(video_file),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        # Execute resumable upload
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info(f"Upload progress: {pct}%")

        yt_video_id = response["id"]
        video_url = f"https://youtube.com/shorts/{yt_video_id}"
        logger.info(f"Upload complete: {video_url}")

        # Upload thumbnail if available
        self._upload_thumbnail(youtube, yt_video_id, video_id)

        return video_url

    def _load_metadata(self, video_id: str) -> dict:
        """Load metadata JSON for a video."""
        meta_path = Path(settings.output_dir) / "metadata" / f"{video_id}.json"
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load metadata: {e}")
        return {}

    def _upload_thumbnail(self, youtube, yt_video_id: str, video_id: str):
        """Upload a custom thumbnail if available."""
        from googleapiclient.http import MediaFileUpload as ThumbUpload

        thumb_path = Path(settings.output_dir) / "thumbnails" / f"{video_id}.png"
        if not thumb_path.exists():
            logger.info("No thumbnail found, skipping")
            return

        try:
            youtube.thumbnails().set(
                videoId=yt_video_id,
                media_body=ThumbUpload(str(thumb_path), mimetype="image/png"),
            ).execute()
            logger.info("Thumbnail uploaded")
        except Exception as e:
            # Thumbnail upload requires channel verification - non-fatal
            logger.warning(f"Thumbnail upload failed (channel may need verification): {e}")


def main():
    """CLI entry point for auth and manual uploads."""
    parser = argparse.ArgumentParser(description="YouTube Shorts Uploader")
    parser.add_argument("--auth", action="store_true",
                        help="Run OAuth2 authentication flow (one-time)")
    parser.add_argument("--upload", type=str, default=None,
                        help="Path to video file to upload")
    parser.add_argument("--video-id", type=str, default=None,
                        help="Video ID for metadata lookup")
    parser.add_argument("--niche", type=str, default=None,
                        help="Niche for category selection")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    uploader = YouTubeUploader()

    if args.auth:
        uploader.authenticate()
    elif args.upload:
        if not args.video_id:
            # Derive video_id from filename
            args.video_id = Path(args.upload).stem
        url = uploader.upload(args.upload, args.video_id, niche=args.niche)
        print(f"\nUploaded: {url}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
