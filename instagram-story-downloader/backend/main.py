"""FastAPI backend for Instagram Story Downloader."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from story_service import get_story_service

# ---------------------------------------------------------------------------
# Lifespan — initialize session on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    service = get_story_service()
    if not service.session_status["logged_in"]:
        print("⚠️  No Instagram session found. Run: python setup_session.py")
    else:
        print(f"✅ Instagram session loaded: {service.session_status['username']}")
    yield


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
async def get_stories(username: str):
    """Fetch Instagram stories for a given username."""
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format.")

    service = get_story_service()

    if not service.session_status["logged_in"]:
        raise HTTPException(status_code=503, detail="No Instagram session. Run setup_session.py.")

    try:
        user_info = service.get_user_info(username)
        stories = service.get_stories(username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "user": user_info,
        "stories": stories,
        "count": len(stories),
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
