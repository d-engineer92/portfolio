"""CLI script to create and save an Instagram session for the story downloader.

Usage:
    python setup_session.py                    # Interactive menu
    python setup_session.py --browser firefox  # Import from browser cookies
    python setup_session.py --login            # Username/password login

The session file is reused by the backend to fetch stories without end-user login.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import instaloader


SESSION_DIR = Path(__file__).parent / ".sessions"


def save_session(loader: instaloader.Instaloader, username: str) -> None:
    """Save the session to a file."""
    SESSION_DIR.mkdir(exist_ok=True)
    session_file = SESSION_DIR / f"session-{username}"
    loader.save_session_to_file(str(session_file))
    print(f"\n✅ Session saved to: {session_file}")
    print("The backend will use this session to fetch stories.")


def login_with_credentials() -> None:
    """Login with username and password."""
    print("\n--- Username/Password Login ---")
    print("⚠️  注意: Instagramがサーバーからのログインをブロックする場合があります。")
    print("   その場合はブラウザCookieインポート方式をお試しください。\n")

    username = input("Instagram username: ").strip()
    if not username:
        print("Error: Username is required.")
        sys.exit(1)

    password = getpass.getpass("Instagram password: ")
    if not password:
        print("Error: Password is required.")
        sys.exit(1)

    loader = instaloader.Instaloader()

    print(f"\nLogging in as {username}...")
    try:
        loader.login(username, password)
    except instaloader.exceptions.BadCredentialsException:
        print("Error: Invalid username or password.")
        sys.exit(1)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        print("\nTwo-factor authentication is required.")
        code = input("Enter 2FA code: ").strip()
        try:
            loader.two_factor_login(code)
        except Exception as exc:
            print(f"Error: 2FA login failed — {exc}")
            sys.exit(1)
    except instaloader.exceptions.LoginException as exc:
        print(f"\n❌ Login failed: {exc}")
        print("\n💡 ヒント: Instagramが自動ログインをブロックしている可能性があります。")
        print("   ブラウザCookieインポート方式をお試しください:")
        print("   python setup_session.py --browser firefox")
        print("   python setup_session.py --browser chrome")
        sys.exit(1)
    except instaloader.exceptions.ConnectionException as exc:
        print(f"Error: Connection failed — {exc}")
        sys.exit(1)

    save_session(loader, username)


def login_with_browser_cookies(browser_name: str) -> None:
    """Import session from browser cookies."""
    print(f"\n--- Browser Cookie Import ({browser_name}) ---")
    print(f"ブラウザ ({browser_name}) でInstagramにログイン済みであることを確認してください。\n")

    username = input("Instagram username (ブラウザでログイン中のアカウント): ").strip()
    if not username:
        print("Error: Username is required.")
        sys.exit(1)

    loader = instaloader.Instaloader()

    print(f"\n{browser_name} からCookieをインポート中...")
    try:
        loader.load_session_from_file(username, None)
    except FileNotFoundError:
        pass

    try:
        # Use instaloader's built-in cookie import
        import browser_cookie3

        if browser_name.lower() == "firefox":
            cookie_jar = browser_cookie3.firefox(domain_name=".instagram.com")
        elif browser_name.lower() == "chrome":
            cookie_jar = browser_cookie3.chrome(domain_name=".instagram.com")
        elif browser_name.lower() == "edge":
            cookie_jar = browser_cookie3.edge(domain_name=".instagram.com")
        else:
            print(f"Error: Unsupported browser '{browser_name}'.")
            print("Supported: firefox, chrome, edge")
            sys.exit(1)

        # Extract session cookies and apply to instaloader
        session = loader.context._session
        for cookie in cookie_jar:
            session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)

        # Verify the session works
        try:
            loader.test_login()
            if loader.context.username:
                print(f"✅ ログイン確認: {loader.context.username}")
                save_session(loader, loader.context.username)
            else:
                print(f"セッションを保存します（ユーザー名: {username}）")
                save_session(loader, username)
        except Exception:
            print(f"セッションを保存します（ユーザー名: {username}）")
            save_session(loader, username)
            print("⚠️  セッションの有効性を完全には確認できませんでしたが、保存しました。")
            print("   バックエンドを起動して動作確認してください。")

    except ImportError:
        print("Error: browser_cookie3 がインストールされていません。")
        print("  pip install browser_cookie3")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌ Cookie import failed: {exc}")
        print(f"\n💡 ヒント:")
        print(f"   1. {browser_name} を完全に閉じてからもう一度試してください")
        print(f"   2. {browser_name} でInstagramにログインしていることを確認してください")
        print(f"   3. ブラウザのCookieをクリアしてから再ログインしてみてください")
        sys.exit(1)


def show_menu() -> None:
    """Show interactive setup menu."""
    print("=" * 50)
    print("Instagram Session Setup")
    print("=" * 50)
    print()
    print("セッションの作成方法を選択してください:")
    print()
    print("  1. ブラウザCookieインポート (推奨)")
    print("     → ブラウザでIG にログイン済みならこちら")
    print()
    print("  2. Username/Password ログイン")
    print("     → ブロックされる場合があります")
    print()

    choice = input("選択 [1/2]: ").strip()

    if choice == "1":
        print()
        print("ブラウザを選択:")
        print("  1. Firefox")
        print("  2. Chrome")
        print("  3. Edge")
        browser_choice = input("選択 [1/2/3]: ").strip()
        browsers = {"1": "firefox", "2": "chrome", "3": "edge"}
        browser = browsers.get(browser_choice, "firefox")
        login_with_browser_cookies(browser)
    elif choice == "2":
        login_with_credentials()
    else:
        print("Invalid choice.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram session setup")
    parser.add_argument("--browser", type=str, help="Import from browser cookies (firefox/chrome/edge)")
    parser.add_argument("--login", action="store_true", help="Use username/password login")
    args = parser.parse_args()

    if args.browser:
        login_with_browser_cookies(args.browser)
    elif args.login:
        login_with_credentials()
    else:
        show_menu()


if __name__ == "__main__":
    main()
