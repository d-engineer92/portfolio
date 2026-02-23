"""Setup Instagram session for the Story Downloader.

Usage:
    python setup_session.py --login            Login with username/password
    python setup_session.py --browser-cookie   Import sessionid from browser
"""

from __future__ import annotations

import argparse
import getpass
import pickle
from pathlib import Path

import instaloader

SESSION_DIR = Path(__file__).parent / ".sessions"


def login_interactive() -> None:
    """Login with username and password via instaloader."""
    SESSION_DIR.mkdir(exist_ok=True)
    username = input("Instagram username: ").strip()
    password = getpass.getpass("Instagram password: ")

    loader = instaloader.Instaloader()

    try:
        loader.login(username, password)
        print(f"✅ Logged in as {username}")
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        code = input("2FA code: ").strip()
        loader.two_factor_login(code)
        print(f"✅ Logged in as {username} (2FA)")
    except Exception as exc:
        print(f"❌ Login failed: {exc}")
        return

    session_path = SESSION_DIR / f"session-{username}"
    loader.save_session_to_file(str(session_path))
    print(f"Session saved to {session_path}")

    # Check if sessionid was captured
    has_sessionid = any(
        c.name == "sessionid" and c.value
        for c in loader.context._session.cookies
    )
    if not has_sessionid:
        print()
        print("⚠️  sessionid cookie が空です。")
        print("   ストーリー取得には sessionid が必要です。")
        print("   以下のコマンドでブラウザから sessionid をインポートしてください:")
        print(f"   python setup_session.py --browser-cookie")


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
