# v4.2 r1 — Always Refresh Dropbox Access Token per call

Endpoints:
- GET /health
- GET/POST /diag  (writes /test/WAV/_jobs/diag-<ts>.txt to verify Dropbox auth)
- POST /start

Env vars:
- DROPBOX_CLIENT_ID, DROPBOX_CLIENT_SECRET, DROPBOX_REFRESH_TOKEN
(optional) DROPBOX_ACCESS_TOKEN as fallback

# railway-whisper-dropbox v4.2 (Async + Refresh + Healthcheck)

Endpoints:
- GET /health  -> {"ok": true}
- POST /start  -> 切片 + 上傳到 Dropbox 分目錄（01~05 預設）

環境變數（Railway → Variables）：
- DROPBOX_CLIENT_ID
- DROPBOX_CLIENT_SECRET
- DROPBOX_REFRESH_TOKEN
# 可選備援：DROPBOX_ACCESS_TOKEN

測試：
curl -s https://<app>.up.railway.app/health
curl -X POST https://<app>.up.railway.app/start -H "Content-Type: application/json" -d '{
  "url":"https://www.dropbox.com/scl/fi/<id>/meeting.WAV?dl=0",
  "segment_time":400,"overlap_seconds":10,"format":"wav",
  "dest_root":"/test/WAV","group_prefix":"meeting",
  "max_dirs":5,"max_files_per_dir":5
}'