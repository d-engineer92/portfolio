"""Setup Instagram session for the Story Downloader.

Usage:
    python setup_session.py --login            Login with username/password
    python setup_session.py --browser-cookie   Import sessionid from browser
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pickle
import time
from pathlib import Path

import requests as req

SESSION_DIR = Path(__file__).parent / ".sessions"

_IG_APP_ID = "936619743392459"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


def _build_session() -> req.Session:
    """Create a requests session with browser-like headers."""
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    s = req.Session()
    s.headers.update({
        "User-Agent": _USER_AGENT,
        "X-IG-App-ID": _IG_APP_ID,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/accounts/login/",
        "Origin": "https://www.instagram.com",
    })
    if proxy_url:
        s.proxies = {"http": proxy_url, "https": proxy_url}
        print(f"🔗 Proxy: {proxy_url}")
    return s


def login_interactive() -> None:
    """Login directly via Instagram's login API (bypasses instaloader bug)."""
    SESSION_DIR.mkdir(exist_ok=True)
    username = input("Instagram username: ").strip()
    password = getpass.getpass("Instagram password: ")

    session = _build_session()

    # Step 1: Get CSRF token
    print("⏳ CSRF トークンを取得中...")
    resp = session.get("https://www.instagram.com/accounts/login/", timeout=15)
    csrf = session.cookies.get("csrftoken", "")
    if not csrf:
        # Try from response headers
        for cookie in resp.cookies:
            if cookie.name == "csrftoken":
                csrf = cookie.value
    if not csrf:
        print("❌ CSRF トークンの取得に失敗しました。")
        return

    session.headers["X-CSRFToken"] = csrf

    # Step 2: Login
    print("⏳ ログイン中...")
    ts = int(time.time())
    login_resp = session.post(
        "https://www.instagram.com/accounts/login/ajax/",
        data={
            "username": username,
            "enc_password": f"#PWD_INSTAGRAM_BROWSER:0:{ts}:{password}",
            "queryParams": "{}",
            "optIntoOneTap": "false",
        },
        timeout=15,
    )

    try:
        login_data = login_resp.json()
    except Exception:
        print(f"❌ ログインレスポンスの解析に失敗 (HTTP {login_resp.status_code})")
        return

    if login_data.get("two_factor_required"):
        tf_info = login_data.get("two_factor_info", {})
        identifier = tf_info.get("two_factor_identifier", "")
        code = input("2FA code: ").strip()
        tf_resp = session.post(
            "https://www.instagram.com/accounts/login/ajax/two_factor/",
            data={
                "username": username,
                "verificationCode": code,
                "identifier": identifier,
                "queryParams": "{}",
            },
            timeout=15,
        )
        try:
            login_data = tf_resp.json()
        except Exception:
            print(f"❌ 2FA レスポンスの解析に失敗")
            return

    if not login_data.get("authenticated"):
        msg = login_data.get("message", "不明なエラー")
        print(f"❌ ログイン失敗: {msg}")
        if "checkpoint" in str(login_data):
            print("   Instagram がチャレンジ認証を要求しています。")
            print("   ブラウザで instagram.com にログインしてチャレンジを解除してください。")
        return

    print(f"✅ Logged in as {username}")

    # Check sessionid
    sessionid = session.cookies.get("sessionid", "")
    if sessionid:
        print(f"✅ sessionid 取得成功 (length: {len(sessionid)})")
    else:
        print("⚠️  sessionid が空です。")

    # Save as instaloader-compatible session file
    session_path = SESSION_DIR / f"session-{username}"
    cookie_dict = {c.name: c.value for c in session.cookies}
    with open(session_path, "wb") as f:
        pickle.dump(cookie_dict, f)
    print(f"Session saved to {session_path}")


def import_browser_cookie() -> None:
    """Import sessionid from browser cookies."""
    SESSION_DIR.mkdir(exist_ok=True)

    # Find existing session
    session_files = sorted(
        SESSION_DIR.glob("session-*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not session_files:
        print("❌ セッションファイルが見つかりません。先に --login を実行してください。")
        return

    session_file = session_files[0]
    username = session_file.name.replace("session-", "")
    print(f"セッションファイル: {session_file} ({username})")
    print()
    print("ブラウザで instagram.com にログインし、")
    print("DevTools (F12) → Application → Cookies → https://www.instagram.com")
    print("から 'sessionid' の Value をコピーしてください。")
    print()

    sessionid = input("sessionid: ").strip()
    if not sessionid:
        print("❌ sessionid が空です。")
        return

    # Update session file
    with open(session_file, "rb") as f:
        data = pickle.load(f)

    data["sessionid"] = sessionid

    with open(session_file, "wb") as f:
        pickle.dump(data, f)

    print(f"✅ sessionid を更新しました (length: {len(sessionid)})")
    print("バックエンドを再起動してください。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram session setup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--login", action="store_true", help="Login with username/password"
    )
    group.add_argument(
        "--browser-cookie",
        action="store_true",
        help="Import sessionid from browser",
    )
    args = parser.parse_args()

    if args.login:
        login_interactive()
    elif args.browser_cookie:
        import_browser_cookie()


if __name__ == "__main__":
    main()
