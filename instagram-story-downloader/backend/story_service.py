"""Instagram story service — fetches stories via direct API with web session."""

from __future__ import annotations

import json
import logging
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import instaloader

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).parent / ".sessions"

# Instagram Web App ID (required for API calls)
_IG_APP_ID = "936619743392459"

# Timeout for API calls
_API_TIMEOUT = 15


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
            logger.warning("Session dir missing: %s", SESSION_DIR)
            return False

        session_files = sorted(
            SESSION_DIR.glob("session-*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not session_files:
            logger.warning("No session files found")
            return False

        session_file = session_files[0]
        username = session_file.name.replace("session-", "")

        try:
            self._loader.load_session_from_file(username, str(session_file))
            self._session_username = username
            self._loaded = True

            # Add X-IG-App-ID header for API calls
            self._loader.context._session.headers["X-IG-App-ID"] = _IG_APP_ID

            # Verify sessionid is present
            has_sessionid = any(
                c.name == "sessionid" and c.value
                for c in self._loader.context._session.cookies
            )
            if not has_sessionid:
                logger.warning(
                    "sessionid cookie is empty. "
                    "Import it from your browser via setup_session.py --browser-cookie"
                )

            logger.info("Session loaded for user: %s", username)
            return True
        except Exception as exc:
            logger.error("Session load failed: %s", exc)
            return False

    @property
    def session_status(self) -> dict[str, Any]:
        """Get current session status."""
        has_sessionid = False
        if self._loaded:
            has_sessionid = any(
                c.name == "sessionid" and c.value
                for c in self._loader.context._session.cookies
            )
        return {
            "logged_in": self._loaded,
            "username": self._session_username,
            "has_sessionid": has_sessionid,
        }

    def get_user_info(self, target_username: str) -> dict[str, Any]:
        """Get basic profile info for display."""
        if not self._loaded:
            raise ValueError("No Instagram session loaded.")

        try:
            profile = instaloader.Profile.from_username(
                self._loader.context, target_username
            )
        except instaloader.exceptions.ProfileNotExistsException:
            raise ValueError(f"ユーザー '{target_username}' が見つかりません。")
        except instaloader.exceptions.ConnectionException as exc:
            err_str = str(exc)
            if "429" in err_str or "Too Many Requests" in err_str:
                raise ValueError(
                    "Instagramのレートリミットに達しました。数分後に再試行してください。"
                )
            raise ValueError(f"接続エラー: {exc}")

        return {
            "username": profile.username,
            "full_name": profile.full_name,
            "profile_pic_url": profile.profile_pic_url,
            "is_private": profile.is_private,
            "followers": profile.followers,
        }

    def get_stories(self, target_username: str) -> list[dict[str, Any]]:
        """Fetch current stories for a given username.

        Uses the www.instagram.com web API directly instead of
        instaloader's broken GraphQL method.
        """
        if not self._loaded:
            raise ValueError("No Instagram session loaded. Run setup_session.py first.")

        # 1. Resolve username to user ID
        try:
            profile = instaloader.Profile.from_username(
                self._loader.context, target_username
            )
        except instaloader.exceptions.ProfileNotExistsException:
            raise ValueError(f"ユーザー '{target_username}' が見つかりません。")
        except instaloader.exceptions.ConnectionException as exc:
            err_str = str(exc)
            if "429" in err_str or "Too Many Requests" in err_str:
                raise ValueError(
                    "Instagramのレートリミットに達しました。数分後に再試行してください。"
                )
            raise ValueError(f"接続エラー: {exc}")

        if profile.is_private and not profile.followed_by_viewer:
            raise ValueError(
                f"'{target_username}' は非公開アカウントです。フォロー中でないと取得できません。"
            )

        # 2. Fetch stories via reels_media API
        session = self._loader.context._session
        try:
            resp = session.post(
                "https://www.instagram.com/api/v1/feed/reels_media/",
                data={"reel_ids": json.dumps([str(profile.userid)])},
                timeout=_API_TIMEOUT,
            )
        except Exception as exc:
            raise ValueError(f"ストーリーの取得に失敗しました: {exc}")

        if resp.status_code == 429:
            raise ValueError(
                "Instagramのレートリミットに達しました。数分後に再試行してください。"
            )

        if resp.status_code != 200:
            logger.error(
                "Story API returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            raise ValueError(f"ストーリーの取得に失敗しました (HTTP {resp.status_code})")

        # 3. Parse response
        try:
            data = resp.json()
        except Exception:
            raise ValueError("Instagramからの応答を解析できませんでした。")

        reels = data.get("reels", {})
        reel = reels.get(str(profile.userid), {})
        items = reel.get("items", [])

        stories: list[dict[str, Any]] = []
        for item in items:
            has_video = bool(item.get("video_versions"))

            if has_video:
                versions = item.get("video_versions", [])
                url = versions[0]["url"] if versions else ""
                candidates = item.get("image_versions2", {}).get("candidates", [])
                thumbnail = candidates[0]["url"] if candidates else None
            else:
                candidates = item.get("image_versions2", {}).get("candidates", [])
                url = candidates[0]["url"] if candidates else ""
                thumbnail = None

            taken_at = item.get("taken_at", 0)
            ts = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat()

            stories.append({
                "id": str(item.get("pk", "")),
                "media_type": "video" if has_video else "image",
                "url": url,
                "thumbnail_url": thumbnail,
                "timestamp": ts,
                "username": target_username,
            })

        return stories


# Singleton
_service: StoryService | None = None


def get_story_service() -> StoryService:
    """Get or create the singleton StoryService instance."""
    global _service
    if _service is None:
        _service = StoryService()
        _service.load_session()
    return _service
