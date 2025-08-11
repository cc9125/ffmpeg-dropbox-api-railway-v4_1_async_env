# FFmpeg Dropbox Split & Upload API — v4.1 (Async + ENV token)

- Token 可來自 request body 或環境變數 `DROPBOX_ACCESS_TOKEN`。
- POST /start   -> 回傳 { job_id, state: "queued", group_prefix }
- GET  /status  -> 回傳 job 狀態（token 來自 query 或環境變數）
- 狀態 JSON 儲存位置： {dest_root}/_jobs/{job_id}.json
