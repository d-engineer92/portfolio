"""Instagram service — fetches stories and posts via direct Web API."""

from __future__ import annotations

import json
import logging
import os
import pickle
import re
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

# Keepalive interval (seconds) — 30 minutes
KEEPALIVE_INTERVAL = 30 * 60


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
        self._needs_manual_refresh = False
        self._last_keepalive: float = 0

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def load_session(self) -> bool:
        """Load the most recent saved session. Returns True if successful."""
        if self._loaded:
            return True

        if not SESSION_DIR.exists():
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            logger.warning("Created session dir: %s", SESSION_DIR)

        session_files = sorted(
            SESSION_DIR.glob("session-*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not session_files:
            # Try auto-login if credentials are available
            if self._try_login():
                return True
            logger.warning("No session files found")
            return False

        session_file = session_files[0]
        username = session_file.name.replace("session-", "")

        try:
            self._loader.load_session_from_file(username, str(session_file))
            self._session_username = username
            self._loaded = True
            self._session.headers["X-IG-App-ID"] = _IG_APP_ID

            has_sessionid = any(
                c.name == "sessionid" and c.value for c in self._session.cookies
            )
            if not has_sessionid:
                logger.warning("sessionid cookie empty — trying auto-login")
                if not self._try_login():
                    logger.warning(
                        "Auto-login failed. Import sessionid via: "
                        "python setup_session.py --browser-cookie"
                    )
            logger.info("Session loaded for user: %s", username)
            self._last_keepalive = time.time()
            return True
        except Exception as exc:
            logger.error("Session load failed: %s", exc)
            return False

    def _try_login(self) -> bool:
        """Attempt login using credentials from environment variables."""
        username = os.environ.get("IG_USERNAME", "").strip()
        password = os.environ.get("IG_PASSWORD", "").strip()

        if not username or not password:
            return False

        logger.info("Attempting auto-login for %s...", username)
        try:
            self._loader.login(username, password)
            self._session_username = username
            self._loaded = True
            self._session.headers["X-IG-App-ID"] = _IG_APP_ID
            self._needs_manual_refresh = False

            # Save session
            session_file = SESSION_DIR / f"session-{username}"
            self._loader.save_session_to_file(str(session_file))
            logger.info("Auto-login successful, session saved")
            self._last_keepalive = time.time()
            return True
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            logger.error("Auto-login failed: 2FA required")
            self._needs_manual_refresh = True
            return False
        except instaloader.exceptions.ConnectionException as exc:
            if "challenge_required" in str(exc):
                logger.warning("Auto-login blocked: challenge_required")
                self._needs_manual_refresh = True
            else:
                logger.error("Auto-login failed: %s", exc)
            return False
        except Exception as exc:
            logger.error("Auto-login failed: %s", exc)
            return False

    def _refresh_session(self) -> bool:
        """Try to refresh the session when it expires (401/403)."""
        logger.info("Session expired — attempting refresh...")
        self._loaded = False

        # First try re-login
        if self._try_login():
            return True

        # If login failed, try reloading from file
        session_files = sorted(
            SESSION_DIR.glob("session-*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if session_files:
            session_file = session_files[0]
            username = session_file.name.replace("session-", "")
            try:
                self._loader.load_session_from_file(username, str(session_file))
                self._session_username = username
                self._loaded = True
                self._session.headers["X-IG-App-ID"] = _IG_APP_ID
                logger.info("Session reloaded from file")
                return True
            except Exception:
                pass

        self._needs_manual_refresh = True
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
            "needs_manual_refresh": self._needs_manual_refresh,
        }

    def keepalive(self) -> bool:
        """Send a lightweight request to keep the session alive."""
        if not self._loaded:
            return False

        try:
            resp = self._session.get(
                "https://www.instagram.com/api/v1/accounts/current_user/",
                timeout=_API_TIMEOUT,
            )
            if resp.status_code == 200:
                self._last_keepalive = time.time()
                self._needs_manual_refresh = False
                logger.info("Session keepalive OK")
                return True
            elif resp.status_code in (401, 403):
                logger.warning("Keepalive failed (%d) — session expired", resp.status_code)
                return self._refresh_session()
            else:
                logger.warning("Keepalive got HTTP %d", resp.status_code)
                return False
        except Exception as exc:
            logger.warning("Keepalive failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # API helpers (with auto-retry on session expiry)
    # ------------------------------------------------------------------

    def _api_get(self, path: str, **params) -> dict:
        """GET request to www.instagram.com/api/v1/..."""
        resp = self._session.get(
            f"https://www.instagram.com/api/v1/{path}",
            params=params,
            timeout=_API_TIMEOUT,
        )
        if resp.status_code in (401, 403):
            if self._refresh_session():
                # Retry once
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
        if resp.status_code in (401, 403):
            if self._refresh_session():
                # Retry once
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
        """Get user info + ID via instaloader, search API, or HTML scrape."""
        if not self._loaded:
            raise ValueError("No Instagram session loaded. Run setup_session.py first.")

        # Method 1: instaloader (works from residential IPs)
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

        # Method 2: search API (works on VPS)
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

        # Method 3: scrape public profile page for user ID
        try:
            resp = self._session.get(
                f"https://www.instagram.com/{username}/",
                timeout=_API_TIMEOUT,
            )
            if resp.status_code == 200:
                html = resp.text
                match = re.search(r'"profilePage_(\d+)"', html)
                if not match:
                    match = re.search(r'"user_id":"(\d+)"', html)
                if not match:
                    match = re.search(
                        r'"id":"(\d+)".*?"username":"%s"' % re.escape(username), html
                    )
                if match:
                    user_id = int(match.group(1))
                    name_match = re.search(
                        r'<meta property="og:title" content="([^"]*)"', html
                    )
                    full_name = (
                        name_match.group(1).split("(")[0].strip()
                        if name_match
                        else username
                    )
                    pic_match = re.search(
                        r'"profile_pic_url":"(https://[^"]+)"', html
                    )
                    profile_pic = (
                        pic_match.group(1).replace("\\u0026", "&")
                        if pic_match
                        else ""
                    )
                    logger.info(
                        "Resolved user via HTML scrape: %s -> %s", username, user_id
                    )
                    return {
                        "user_id": user_id,
                        "username": username,
                        "full_name": full_name,
                        "profile_pic_url": profile_pic,
                        "is_private": False,
                        "followers": 0,
                    }
            elif resp.status_code == 404:
                raise ValueError(f"ユーザー '{username}' が見つかりません。")
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("HTML scrape fallback failed: %s", exc)

        raise ValueError(f"ユーザー '{username}' が見つかりません。")

    def _enrich_user_info(self, user: dict[str, Any]) -> dict[str, Any]:
        """Enrich user info with follower count from users/{id}/info/ API."""
        if user.get("followers"):
            return user  # Already have follower count

        try:
            data = self._api_get(f"users/{user['user_id']}/info/")
            api_user = data.get("user", {})
            user["followers"] = api_user.get("follower_count", 0)
            user["media_count"] = api_user.get("media_count", 0)
            if not user.get("full_name"):
                user["full_name"] = api_user.get("full_name", "")
            if not user.get("profile_pic_url"):
                user["profile_pic_url"] = api_user.get("profile_pic_url", "")
        except Exception as exc:
            logger.warning("Failed to enrich user info: %s", exc)

        return user

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    def get_stories(self, username: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Fetch current stories for a given username.

        Returns (enriched_user_info, stories_list).
        """
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

        # Enrich user info from reels_media response
        reel_user = reel.get("user", {})
        if reel_user:
            if not user.get("full_name"):
                user["full_name"] = reel_user.get("full_name", user.get("full_name", ""))
            if not user.get("profile_pic_url"):
                user["profile_pic_url"] = reel_user.get("profile_pic_url", "")

        user = self._enrich_user_info(user)
        return user, [self._parse_story_item(item, username) for item in items]

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

    def get_posts(self, username: str, max_posts: int = 100) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Fetch posts for a given username with pagination.

        Returns (user_info, posts_list).
        """
        user = self._resolve_user(username)

        if user["is_private"]:
            raise ValueError(f"'{username}' は非公開アカウントです。")

        user = self._enrich_user_info(user)

        all_posts: list[dict[str, Any]] = []
        max_id = None
        page_size = 12

        while len(all_posts) < max_posts:
            params: dict[str, str] = {"count": str(page_size)}
            if max_id:
                params["max_id"] = max_id

            try:
                data = self._api_get(f"feed/user/{user['user_id']}/", **params)
            except Exception as exc:
                logger.warning("Post pagination error: %s", exc)
                break

            items = data.get("items", [])
            if not items:
                break

            for item in items:
                all_posts.extend(self._parse_post_item(item, username))

            if not data.get("more_available", False):
                break

            max_id = data.get("next_max_id")
            if not max_id:
                break

            time.sleep(0.5)  # Rate limit protection

        return user, all_posts[:max_posts]

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
