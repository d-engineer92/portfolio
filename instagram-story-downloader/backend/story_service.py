"""Instagram service — fetches stories and posts via direct Web API."""

from __future__ import annotations

import json
import logging
import pickle
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


class InstagramService:
    """Manages Instagram session and fetches stories / posts."""

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

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

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
            self._session.headers["X-IG-App-ID"] = _IG_APP_ID

            has_sessionid = any(
                c.name == "sessionid" and c.value for c in self._session.cookies
            )
            if not has_sessionid:
                logger.warning(
                    "sessionid cookie is empty. "
                    "Import it via: python setup_session.py --browser-cookie"
                )
            logger.info("Session loaded for user: %s", username)
            return True
        except Exception as exc:
            logger.error("Session load failed: %s", exc)
            return False

    @property
    def _session(self):
        """Shortcut to the internal requests session."""
        return self._loader.context._session

    @property
    def session_status(self) -> dict[str, Any]:
        has_sessionid = False
        if self._loaded:
            has_sessionid = any(
                c.name == "sessionid" and c.value for c in self._session.cookies
            )
        return {
            "logged_in": self._loaded,
            "username": self._session_username,
            "has_sessionid": has_sessionid,
        }

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str, **params) -> dict:
        """GET request to www.instagram.com/api/v1/..."""
        resp = self._session.get(
            f"https://www.instagram.com/api/v1/{path}",
            params=params,
            timeout=_API_TIMEOUT,
        )
        if resp.status_code == 429:
            raise ValueError("Instagramのレートリミットに達しました。数分後に再試行してください。")
        if resp.status_code != 200:
            raise ValueError(f"Instagram API エラー (HTTP {resp.status_code})")
        return resp.json()

    def _api_post(self, path: str, **data) -> dict:
        """POST request to www.instagram.com/api/v1/..."""
        resp = self._session.post(
            f"https://www.instagram.com/api/v1/{path}",
            data=data,
            timeout=_API_TIMEOUT,
        )
        if resp.status_code == 429:
            raise ValueError("Instagramのレートリミットに達しました。数分後に再試行してください。")
        if resp.status_code != 200:
            raise ValueError(f"Instagram API エラー (HTTP {resp.status_code})")
        return resp.json()

    # ------------------------------------------------------------------
    # User info — via reels_media (works on VPS, no web_profile_info)
    # ------------------------------------------------------------------

    def _resolve_user(self, username: str) -> dict[str, Any]:
        """Get user info + ID via instaloader or search API fallback."""
        if not self._loaded:
            raise ValueError("No Instagram session loaded. Run setup_session.py first.")

        # First try instaloader (works from residential IPs)
        try:
            profile = instaloader.Profile.from_username(
                self._loader.context, username
            )
            return {
                "user_id": profile.userid,
                "username": profile.username,
                "full_name": profile.full_name,
                "profile_pic_url": profile.profile_pic_url,
                "is_private": profile.is_private,
                "followers": profile.followers,
            }
        except instaloader.exceptions.ProfileNotExistsException:
            raise ValueError(f"ユーザー '{username}' が見つかりません。")
        except Exception as exc:
            logger.warning("Profile lookup via instaloader failed: %s", exc)

        # Fallback: search for user (works on VPS)
        try:
            data = self._api_get("web/search/topsearch/", query=username, count="1")
            users = data.get("users", [])
            for u in users:
                user = u.get("user", {})
                if user.get("username", "").lower() == username.lower():
                    return {
                        "user_id": int(user["pk"]),
                        "username": user["username"],
                        "full_name": user.get("full_name", ""),
                        "profile_pic_url": user.get("profile_pic_url", ""),
                        "is_private": user.get("is_private", False),
                        "followers": user.get("follower_count", 0),
                    }
            logger.warning("Search API returned no match for '%s'", username)
        except Exception as exc:
            logger.warning("Search API fallback failed: %s", exc)

        raise ValueError(f"ユーザー '{username}' が見つかりません。")

    def get_user_info(self, username: str) -> dict[str, Any]:
        """Get basic profile info for display."""
        info = self._resolve_user(username)
        return {
            "username": info["username"],
            "full_name": info["full_name"],
            "profile_pic_url": info["profile_pic_url"],
            "is_private": info["is_private"],
            "followers": info["followers"],
        }

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    def get_stories(self, username: str) -> list[dict[str, Any]]:
        """Fetch current stories for a given username."""
        user = self._resolve_user(username)

        if user["is_private"]:
            raise ValueError(f"'{username}' は非公開アカウントです。")

        data = self._api_post(
            "feed/reels_media/",
            reel_ids=json.dumps([str(user["user_id"])]),
        )

        reels = data.get("reels", {})
        reel = reels.get(str(user["user_id"]), {})
        items = reel.get("items", [])

        return [self._parse_story_item(item, username) for item in items]

    def _parse_story_item(self, item: dict, username: str) -> dict[str, Any]:
        has_video = bool(item.get("video_versions"))
        if has_video:
            url = item["video_versions"][0]["url"]
            candidates = item.get("image_versions2", {}).get("candidates", [])
            thumbnail = candidates[0]["url"] if candidates else None
        else:
            candidates = item.get("image_versions2", {}).get("candidates", [])
            url = candidates[0]["url"] if candidates else ""
            thumbnail = None

        taken_at = item.get("taken_at", 0)
        ts = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat()

        return {
            "id": str(item.get("pk", "")),
            "media_type": "video" if has_video else "image",
            "url": url,
            "thumbnail_url": thumbnail,
            "timestamp": ts,
            "username": username,
        }

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------

    def get_posts(self, username: str, count: int = 12) -> list[dict[str, Any]]:
        """Fetch recent posts for a given username."""
        user = self._resolve_user(username)

        if user["is_private"]:
            raise ValueError(f"'{username}' は非公開アカウントです。")

        data = self._api_get(f"feed/user/{user['user_id']}/", count=str(count))
        items = data.get("items", [])

        posts: list[dict[str, Any]] = []
        for item in items:
            posts.extend(self._parse_post_item(item, username))
        return posts

    def _parse_post_item(self, item: dict, username: str) -> list[dict[str, Any]]:
        """Parse a post item. Carousels are expanded into multiple items."""
        media_type = item.get("media_type")
        caption_obj = item.get("caption") or {}
        caption = caption_obj.get("text", "")
        taken_at = item.get("taken_at", 0)
        ts = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat()
        post_id = str(item.get("pk", ""))
        like_count = item.get("like_count", 0)

        results = []

        if media_type == 8:  # Carousel
            carousel = item.get("carousel_media", [])
            for i, sub in enumerate(carousel):
                results.append(self._extract_media(
                    sub, username, ts, caption, post_id, like_count,
                    carousel_index=i, carousel_total=len(carousel),
                ))
        else:
            results.append(self._extract_media(
                item, username, ts, caption, post_id, like_count,
            ))

        return results

    def _extract_media(
        self,
        item: dict,
        username: str,
        timestamp: str,
        caption: str,
        post_id: str,
        like_count: int,
        carousel_index: int | None = None,
        carousel_total: int | None = None,
    ) -> dict[str, Any]:
        """Extract media URL from a post or carousel sub-item."""
        has_video = bool(item.get("video_versions"))

        if has_video:
            url = item["video_versions"][0]["url"]
            candidates = item.get("image_versions2", {}).get("candidates", [])
            thumbnail = candidates[0]["url"] if candidates else None
        else:
            candidates = item.get("image_versions2", {}).get("candidates", [])
            url = candidates[0]["url"] if candidates else ""
            thumbnail = None

        media_id = str(item.get("pk", post_id))
        if carousel_index is not None:
            media_id = f"{post_id}_{carousel_index}"

        return {
            "id": media_id,
            "post_id": post_id,
            "media_type": "video" if has_video else "image",
            "url": url,
            "thumbnail_url": thumbnail,
            "timestamp": timestamp,
            "username": username,
            "caption": caption,
            "like_count": like_count,
            "carousel_index": carousel_index,
            "carousel_total": carousel_total,
        }


# Singleton
_service: InstagramService | None = None


def get_story_service() -> InstagramService:
    """Get or create the singleton InstagramService instance."""
    global _service
    if _service is None:
        _service = InstagramService()
        _service.load_session()
    return _service
