# ffmpeg-dropbox-api-railway-v4_2_async_refresh

## 功能
- 支援 Dropbox Refresh Token 自動換 Access Token
- 分段切音檔並上傳到 Dropbox 指定資料夾
- 可設定最大資料夾數量與每個資料夾最大檔案數

## 部署
1. 取得 Dropbox Refresh Token
2. Railway 環境變數設定：
   - DROPBOX_CLIENT_ID
   - DROPBOX_CLIENT_SECRET
   - DROPBOX_REFRESH_TOKEN
3. Deploy
