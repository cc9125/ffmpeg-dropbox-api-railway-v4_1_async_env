
# v4.2 Async + Refresh (Nixpacks)

- 使用 Nixpacks：自動安裝 Python 3.11 + ffmpeg
- 綁定 `$PORT`；提供 `/` 與 `/health`
- 自動用 Refresh Token 換 Access Token

## 部署（Railway）
1. 推送本專案到 GitHub
2. Railway → New Project → Deploy from GitHub
3. Variables：`DROPBOX_CLIENT_ID`, `DROPBOX_CLIENT_SECRET`, `DROPBOX_REFRESH_TOKEN`（或備援 `DROPBOX_ACCESS_TOKEN`）
4. Healthcheck Path：`/health`（或 `/`）

## 測試
```
curl -s https://<app>.up.railway.app/health
curl -X POST https://<app>.up.railway.app/start -H "Content-Type: application/json" -d '{
  "url":"https://www.dropbox.com/scl/fi/<id>/meeting.WAV?dl=0",
  "segment_time":400,"overlap_seconds":10,"format":"wav",
  "dest_root":"/test/WAV","group_prefix":"meeting",
  "max_dirs":5,"max_files_per_dir":5
}'
```
