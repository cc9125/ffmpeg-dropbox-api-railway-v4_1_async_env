import os, requests, subprocess, tempfile, shutil, math, time

OAUTH_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DBX_UPLOAD_URL  = "https://content.dropboxapi.com/2/files/upload"

# --- Token 取得（優先 Refresh Token，自動換 Access Token） ---
def get_access_token():
    rt  = os.getenv("DROPBOX_REFRESH_TOKEN")
    cid = os.getenv("DROPBOX_CLIENT_ID")
    sec = os.getenv("DROPBOX_CLIENT_SECRET")
    at  = os.getenv("DROPBOX_ACCESS_TOKEN")
    if rt and cid and sec:
        r = requests.post(OAUTH_TOKEN_URL, data={
            "grant_type":"refresh_token",
            "refresh_token":rt,
            "client_id":cid,
            "client_secret":sec
        }, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]
    if at:
        return at
    raise RuntimeError("No Dropbox token configured (refresh or access).")

# --- 下載分享連結 ---
def to_direct(shared_url:str)->str:
    if not shared_url: return shared_url
    if "dl=0" in shared_url: return shared_url.replace("dl=0","dl=1")
    if "dropbox.com" in shared_url and "dl=1" not in shared_url:
        return shared_url + ("&dl=1" if "?" in shared_url else "?dl=1")
    return shared_url

def download_file(shared_url:str)->str|None:
    url = to_direct(shared_url)
    lp = tempfile.mktemp()
    with requests.get(url, stream=True, timeout=300) as r:
        if r.status_code != 200:
            return None
        with open(lp,"wb") as f:
            for ch in r.iter_content(1024*1024):
                if ch: f.write(ch)
    return lp

# --- 上傳到 Dropbox（帶簡單重試） ---
def upload_to_dropbox(local_path:str, dropbox_path:str, retries:int=3, backoff:float=1.0):
    last_err = None
    for attempt in range(1, retries+1):
        token = get_access_token()
        with open(local_path,"rb") as f:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": f'{{"path":"{dropbox_path}","mode":"overwrite","autorename":false,"mute":true}}'
            }
            r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=f, timeout=600)
        if r.status_code == 200:
            return
        # 保留錯誤細節
        last_err = f"{r.status_code} {r.reason}: {r.text}"
        if r.status_code in (429,500,502,503,504) and attempt < retries:
            time.sleep(backoff * attempt)
            continue
        raise requests.HTTPError(last_err)
    
# --- 取音檔秒數（可失敗；失敗則回傳 None） ---
def probe_duration_seconds(local_file:str)->float|None:
    try:
        p = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", local_file],
            capture_output=True, text=True, check=True
        )
        val = p.stdout.strip()
        return float(val) if val else None
    except Exception:
        return None

# --- 切片主流程：用循環 -ss/-t（相容所有常見 ffmpeg 版本） ---
def split_audio_and_upload(local_file:str, segment_time:int, overlap_seconds:int, fmt:str,
                           dest_root:str, group_prefix:str, max_dirs:int, max_files_per_dir:int):
    tmp = tempfile.mkdtemp()
    uploaded = []
    try:
        duration = probe_duration_seconds(local_file)  # 可能拿不到，拿不到就用 ffmpeg 失敗來停止
        # 以 hop = segment_time - overlap，避免空洞並保留重疊
        hop = max(1, int(segment_time) - int(overlap_seconds))
        start = 0.0
        dir_idx, in_dir = 1, 0
        part_idx = 1

        while True:
            if duration is not None and start >= duration:
                break
            if dir_idx > int(max_dirs):
                break

            out_name = f"{group_prefix}-{part_idx:03d}.{fmt}"
            out_path = os.path.join(tmp, out_name)

            # 先試 copy；失敗再回落重新編碼（避免部分檔案 copy 不可用）
            cmd_copy = [
                "ffmpeg","-hide_banner","-nostdin","-y",
                "-ss", str(max(0.0, start)),
                "-i", local_file,
                "-t", str(segment_time),
                "-map","0:a:0","-vn","-c:a","copy",
                out_path
            ]
            p = subprocess.run(cmd_copy, capture_output=True)
            # 若輸出無效，嘗試重新編碼（確保能切出音檔）
            if p.returncode != 0 or (not os.path.exists(out_path) or os.path.getsize(out_path) < 1024):
                cmd_re = ["ffmpeg","-hide_banner","-nostdin","-y",
                          "-ss", str(max(0.0, start)),
                          "-i", local_file,
                          "-t", str(segment_time),
                          "-map","0:a:0","-vn"]
                if fmt.lower() in ("mp3","m4a","aac"):
                    cmd_re += ["-c:a","aac","-b:a","128k"]
                else:
                    cmd_re += ["-c:a","pcm_s16le"]
                cmd_re += [out_path]
                p2 = subprocess.run(cmd_re, capture_output=True)
                if p2.returncode != 0 or (not os.path.exists(out_path) or os.path.getsize(out_path) < 1024):
                    # 如果已經切不到任何資料（尾段），就停；否則報錯
                    if duration is None and part_idx > 1:
                        break
                    err = (p.stderr or b"").decode("utf-8","ignore") + (p2.stderr or b"").decode("utf-8","ignore")
                    raise RuntimeError(f"ffmpeg failed around start={start}: {err[:4000]}")

            # 計算要放哪個子目錄
            if in_dir >= int(max_files_per_dir):
                dir_idx += 1
                in_dir = 0
                if dir_idx > int(max_dirs):
                    break
            sub = f"{dir_idx:02d}"
            dropbox_path = f"{dest_root}/{sub}/{out_name}"
            upload_to_dropbox(out_path, dropbox_path)

            uploaded.append(dropbox_path)
            in_dir += 1
            part_idx += 1

            # 下一段開始時間（保留重疊）
            start += hop
            # 如果知道總長度且下一段已超出，就結束
            if duration is not None and start >= duration:
                break

        return {"uploaded": uploaded, "total_segments": len(uploaded)}
    finally:
        try:
            os.remove(local_file)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
