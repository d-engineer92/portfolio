# Instagram Story Downloader

Instagramのストーリーをユーザー名だけで取得・ダウンロードできるWebアプリ。

![Screenshot](screenshot.png)

## 技術スタック

| レイヤー | 技術 |
|---|---|
| Frontend | HTML / CSS / JavaScript |
| Backend | Python / FastAPI |
| Instagram連携 | instaloader |

## セットアップ

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Instagramセッション作成（初回のみ）

```bash
cd backend
python setup_session.py
```

Instagram のユーザー名・パスワードを入力してセッションを保存します。
2FA が有効な場合は、認証コードの入力も求められます。

### 3. 起動

**Backend:**
```bash
cd backend
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
# 任意のHTTPサーバーで配信
python -m http.server 5500
```

ブラウザで `http://localhost:5500` にアクセス。

## 使い方

1. ユーザー名を入力
2. 「ストーリーを取得」をクリック
3. ストーリーが表示されたら、個別 or 一括でダウンロード

## 注意事項

- 公開アカウントのストーリーのみ取得可能
- Instagram の非公式APIを使用しています
- ポートフォリオ・学習目的で作成
- セッションが期限切れの場合は `setup_session.py` を再実行してください

## API

| Method | Endpoint | 説明 |
|---|---|---|
| GET | `/api/stories/{username}` | ストーリー取得 |
| GET | `/api/proxy/media?url=...` | メディアプロキシ |
| GET | `/api/session/status` | セッション状態確認 |
| GET | `/api/health` | ヘルスチェック |
