# Instagram Story Downloader

Instagramのストーリーをユーザー名だけで取得・ダウンロードできるWebアプリ。

## 技術スタック

| レイヤー | 技術 |
|---|---|
| Frontend | HTML / CSS / JavaScript |
| Backend | Python / FastAPI |
| Instagram API | instaloader (セッション管理) + Direct Web API (ストーリー取得) |

## セットアップ

### 1. バックエンド

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Instagramセッション

```bash
# Step 1: ログイン
python setup_session.py --login

# Step 2: ブラウザからsessionidをインポート（必須）
# instagram.com → F12 → Application → Cookies → sessionid をコピー
python setup_session.py --browser-cookie
```

> **Note**: instaloader のログインだけでは `sessionid` が空になる場合があります。
> ストーリー取得にはブラウザからの `sessionid` インポートが必要です。

### 3. 起動

```bash
# バックエンド
cd backend
uvicorn main:app --port 8000

# フロントエンド（別ターミナル）
cd frontend
python -m http.server 5500
```

ブラウザで http://localhost:5500 にアクセス。

## API

| Method | Endpoint | 説明 |
|---|---|---|
| GET | `/api/session/status` | セッション状態 |
| GET | `/api/stories/{username}` | ストーリー取得 |
| GET | `/api/proxy/media?url=...` | メディアプロキシ |

## 技術的な知見

### Instagram API の制限

- **VPS/クラウドIP**: `web_profile_info` API は VPS IP からは即座に 429 を返す（リクエスト量に関係なく）
- **GraphQL**: instaloader v4.15 時点で `get_stories()` の query hash が Instagram 側で無効化されている
- **解決策**: `www.instagram.com/api/v1/feed/reels_media/` に `X-IG-App-ID` ヘッダーを付けることでストーリー取得が可能
- **sessionid**: ブラウザから取得した有効な `sessionid` cookie が必要
