
# Dropbox Orchestrator v5.1 (Railway) — with cursor persistence on Dropbox

Endpoints:
- GET  /health
- GET  /diag
- POST /list-changes   {path, recursive, cursor, limit}
- POST /ensure-slices  {url, segment_time, overlap_seconds, format, dest_root, group_prefix, max_dirs, max_files_per_dir}
- POST /list-slices    {dest_root, group_prefix, format}
- POST /shared-link    {path}
- GET  /cursor/get
- POST /cursor/set
- POST /start          (legacy)

Env:
- DROPBOX_CLIENT_ID, DROPBOX_CLIENT_SECRET, DROPBOX_REFRESH_TOKEN
- (optional) API_KEY  -> require header X-Api-Key
- (optional) CURSOR_PATH (default: /test/WAV/_jobs/cursor.json)

# Dropbox Orchestrator v5 (Railway)

Endpoints:
- GET  /health
- GET  /diag
- POST /list-changes   {path, recursive, cursor}
- POST /ensure-slices  {url, segment_time, overlap_seconds, format, dest_root, group_prefix, max_dirs, max_files_per_dir}
- POST /list-slices    {dest_root, group_prefix, format}
- POST /shared-link    {path}
- POST /start          (legacy direct split)

Env:
- DROPBOX_CLIENT_ID, DROPBOX_CLIENT_SECRET, DROPBOX_REFRESH_TOKEN
- (optional) API_KEY  -> require header X-Api-Key

#v4.2 r1 — Always Refresh Dropbox Access Token per call
Endpoints:

GET /health
GET/POST /diag (writes /test/WAV/_jobs/diag-.txt to verify Dropbox auth)
POST /start
Env vars:

DROPBOX_CLIENT_ID, DROPBOX_CLIENT_SECRET, DROPBOX_REFRESH_TOKEN (optional) DROPBOX_ACCESS_TOKEN as fallback

#railway-whisper-dropbox v4.2 (Async + Refresh + Healthcheck)
Endpoints:

GET /health -> {"ok": true}
POST /start -> 切片 + 上傳到 Dropbox 分目錄（01~05 預設）
環境變數（Railway → Variables）：

DROPBOX_CLIENT_ID
DROPBOX_CLIENT_SECRET
DROPBOX_REFRESH_TOKEN
可選備援：DROPBOX_ACCESS_TOKEN
測試： curl -s https://.up.railway.app/health curl -X POST https://.up.railway.app/start -H "Content-Type: application/json" -d '{ "url":"https://www.dropbox.com/scl/fi//meeting.WAV?dl=0", "segment_time":400,"overlap_seconds":10,"format":"wav", "dest_root":"/test/WAV","group_prefix":"meeting", "max_dirs":5,"max_files_per_dir":5 }'