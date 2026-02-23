"""Instagram story service — fetches stories via instaloader with server-side session."""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import instaloader
import logging

logger = logging.getLogger(__name__)

# Timeout for Instagram API calls (seconds)
_API_TIMEOUT = 15

SESSION_DIR = Path(__file__).parent / ".sessions"


@dataclass
class StoryItem:
    """A single story media item."""

    id: str
    media_type: str  # "image" or "video"
    url: str
    thumbnail_url: str | None
    timestamp: str
    username: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "media_type": self.media_type,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
            "timestamp": self.timestamp,
            "username": self.username,
        }


class StoryService:
    """Manages Instagram session and fetches stories."""

    def __init__(self) -> None:
        self._loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=1,
        )
        self._session_username: str | None = None
        self._loaded = False

    def load_session(self) -> bool:
        """Load the most recent saved session. Returns True if successful."""
        if self._loaded:
            return True

        if not SESSION_DIR.exists():
            logger.warning("session_dir_missing", path=str(SESSION_DIR))
            return False

        # Find session files
        session_files = sorted(SESSION_DIR.glob("session-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not session_files:
            logger.warning("no_session_files")
            return False

        session_file = session_files[0]
        username = session_file.name.replace("session-", "")

        try:
            self._loader.load_session_from_file(username, str(session_file))
            self._session_username = username
            self._loaded = True
            logger.info("session_loaded", username=username)
            return True
        except Exception as exc:
            logger.error("session_load_failed", error=str(exc))
            return False

    @property
    def session_status(self) -> dict[str, Any]:
        """Get current session status."""
        return {
            "logged_in": self._loaded,
            "username": self._session_username,
        }

    def _resolve_profile(self, target_username: str) -> instaloader.Profile:
        """Resolve username to Profile with timeout protection."""
        def _fetch():
            return instaloader.Profile.from_username(self._loader.context, target_username)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_fetch)
            try:
                return future.result(timeout=_API_TIMEOUT)
            except concurrent.futures.TimeoutError:
                raise ValueError(
                    "Instagramからの応答がタイムアウトしました。"
                    "レートリミットの可能性があります。数分後に再試行してください。"
                )

    def get_stories(self, target_username: str) -> list[dict[str, Any]]:
        """Fetch current stories for a given username.

        Returns list of story items as dicts.
        Raises ValueError if session not loaded or user not found.
        """
        if not self._loaded:
            raise ValueError("No Instagram session loaded. Run setup_session.py first.")

        try:
            profile = self._resolve_profile(target_username)
        except instaloader.exceptions.ProfileNotExistsException:
            raise ValueError(f"User '{target_username}' not found.")
        except instaloader.exceptions.ConnectionException as exc:
            err_str = str(exc)
            if "429" in err_str or "Too Many Requests" in err_str:
                raise ValueError(
                    "Instagramのレートリミットに達しました。数分後に再試行してください。"
                )
            raise ValueError(f"Connection error: {exc}")

        if profile.is_private and not profile.followed_by_viewer:
            raise ValueError(f"'{target_username}' は非公開アカウントです。フォロー中でないと取得できません。")

        stories: list[dict[str, Any]] = []

        def _fetch_stories():
            for story in self._loader.get_stories(userids=[profile.userid]):
                for item in story.get_items():
                    story_item = StoryItem(
                        id=str(item.mediaid),
                        media_type="video" if item.is_video else "image",
                        url=item.video_url if item.is_video else item.url,
                        thumbnail_url=item.url if item.is_video else None,
                        timestamp=item.date_utc.replace(tzinfo=timezone.utc).isoformat(),
                        username=target_username,
                    )
                    stories.append(story_item.to_dict())
                    time.sleep(0.2)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_fetch_stories)
                future.result(timeout=_API_TIMEOUT)
        except concurrent.futures.TimeoutError:
            raise ValueError(
                "Instagramからの応答がタイムアウトしました。"
                "レートリミットの可能性があります。数分後に再試行してください。"
            )
        except instaloader.exceptions.LoginRequiredException:
            raise ValueError("セッションが期限切れです。setup_session.py を再実行してください。")
        except instaloader.exceptions.QueryReturnedNotFoundException:
            pass
        except ValueError:
            raise
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "Too Many Requests" in err_str:
                raise ValueError(
                    "Instagramのレートリミットに達しました。数分後に再試行してください。"
                )
            logger.error("story_fetch_error", username=target_username, error=err_str)
            raise ValueError(f"ストーリーの取得に失敗しました: {exc}")

        return stories

    def get_user_info(self, target_username: str) -> dict[str, Any]:
        """Get basic profile info for display."""
        if not self._loaded:
            raise ValueError("No Instagram session loaded.")

        try:
            profile = self._resolve_profile(target_username)
        except instaloader.exceptions.ProfileNotExistsException:
            raise ValueError(f"User '{target_username}' not found.")
        except instaloader.exceptions.ConnectionException as exc:
            err_str = str(exc)
            if "429" in err_str or "Too Many Requests" in err_str:
                raise ValueError(
                    "Instagramのレートリミットに達しました。数分後に再試行してください。"
                )
            raise ValueError(f"Connection error: {exc}")

        return {
            "username": profile.username,
            "full_name": profile.full_name,
            "profile_pic_url": profile.profile_pic_url,
            "is_private": profile.is_private,
            "followers": profile.followers,
        }


# Singleton instance
_service: StoryService | None = None


def get_story_service() -> StoryService:
    """Get or create the singleton StoryService instance."""
    global _service
    if _service is None:
        _service = StoryService()
        _service.load_session()
    return _service
