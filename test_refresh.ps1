$AppKey = $env:DROPBOX_CLIENT_ID
$AppSecret = $env:DROPBOX_CLIENT_SECRET
$RefreshToken = $env:DROPBOX_REFRESH_TOKEN

$Body = @{
    grant_type    = "refresh_token"
    refresh_token = $RefreshToken
    client_id     = $AppKey
    client_secret = $AppSecret
}

$Response = Invoke-RestMethod -Method Post -Uri "https://api.dropboxapi.com/oauth2/token" -Body $Body
$Response
