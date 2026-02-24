"""FastAPI backend for Instagram Story Downloader."""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

# Load .env file if it exists
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    import os
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from story_service import get_story_service, KEEPALIVE_INTERVAL

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ---------------------------------------------------------------------------
# Background keepalive task
# ---------------------------------------------------------------------------

async def _keepalive_loop():
    """Periodically ping Instagram to keep the session alive."""
    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL)
        try:
            service = get_story_service()
            service.keepalive()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Keepalive error: %s", exc)


# ---------------------------------------------------------------------------
# Lifespan — initialize session + start keepalive
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    service = get_story_service()
    if not service.session_status["logged_in"]:
        print("⚠️  No Instagram session found. Run: python setup_session.py")
    else:
        ss = service.session_status
        print(f"✅ Instagram session loaded: {ss['username']} (sessionid: {'✅' if ss['has_sessionid'] else '❌'})")

    # Start background keepalive
    task = asyncio.create_task(_keepalive_loop())
    print(f"🔄 Session keepalive started (interval: {KEEPALIVE_INTERVAL // 60}min)")
    yield
    task.cancel()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Instagram Story Downloader API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Username validation
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._]{1,30}$")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/session/status")
async def session_status():
    """Check if Instagram session is active."""
    service = get_story_service()
    return service.session_status


@app.get("/api/stories/{username}")
def get_stories(username: str):
    """Fetch Instagram stories for a given username."""
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    service = get_story_service()

    if not service.session_status["logged_in"]:
        raise HTTPException(status_code=503, detail="No Instagram session. Run setup_session.py.")

    try:
        user_info, stories = service.get_stories(username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"予期しないエラー: {exc}")

    return {
        "user": {
            "username": user_info["username"],
            "full_name": user_info["full_name"],
            "profile_pic_url": user_info["profile_pic_url"],
            "is_private": user_info["is_private"],
            "followers": user_info["followers"],
        },
        "stories": stories,
        "count": len(stories),
    }


@app.get("/api/posts/{username}")
def get_posts(username: str, count: int = 200):
    """Fetch Instagram posts for a given username."""
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    service = get_story_service()

    if not service.session_status["logged_in"]:
        raise HTTPException(status_code=503, detail="No Instagram session. Run setup_session.py.")

    try:
        user_info, posts = service.get_posts(username, max_posts=min(count, 500))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"予期しないエラー: {exc}")

    return {
        "user": {
            "username": user_info["username"],
            "full_name": user_info["full_name"],
            "profile_pic_url": user_info["profile_pic_url"],
            "is_private": user_info["is_private"],
            "followers": user_info["followers"],
        },
        "posts": posts,
        "count": len(posts),
    }


@app.get("/api/proxy/media")
async def proxy_media(url: str = Query(..., description="Instagram media URL to proxy")):
    """Proxy Instagram media to avoid CORS issues in the browser.

    Streams the response to avoid loading large videos into memory.
    """
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid URL.")

    # Only allow Instagram CDN domains
    allowed = ("scontent", "instagram", "cdninstagram", "fbcdn")
    from urllib.parse import urlparse

    hostname = urlparse(url).hostname or ""
    if not any(domain in hostname for domain in allowed):
        raise HTTPException(status_code=400, detail="URL not from Instagram CDN.")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch media: {exc}")

    content_type = resp.headers.get("content-type", "application/octet-stream")

    return StreamingResponse(
        iter([resp.content]),
        media_type=content_type,
        headers={
            "Content-Disposition": "attachment",
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static files (frontend) — must be AFTER API routes
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
