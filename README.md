
# v4.2 Async + Refresh Patch

## 修正內容
- 綁定 `$PORT`（Railway 相容）
- 新增 `/` 路由，通過 Healthcheck
- 內建 ffmpeg
- 自動使用 Refresh Token 換取 Access Token

## 部署
1. 設定環境變數：DROPBOX_CLIENT_ID, DROPBOX_CLIENT_SECRET, DROPBOX_REFRESH_TOKEN
2. Healthcheck Path 設 `/health` 或 `/`
3. Start Command: `gunicorn -b 0.0.0.0:$PORT app:app`
