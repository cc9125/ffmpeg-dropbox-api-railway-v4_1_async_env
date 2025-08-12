import os, requests, subprocess, tempfile, shutil, time, json

OAUTH_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DBX_UPLOAD_URL  = "https://content.dropboxapi.com/2/files/upload"

def get_access_token():
    """
    Always refresh on every call if refresh credentials exist; otherwise fall back to static access token.
    """
    rt  = os.getenv("DROPBOX_REFRESH_TOKEN")
    cid = os.getenv("DROPBOX_CLIENT_ID")
    sec = os.getenv("DROPBOX_CLIENT_SECRET")
    if rt and cid and sec:
        r = requests.post(OAUTH_TOKEN_URL, data={
            "grant_type":"refresh_token",
            "refresh_token":rt,
            "client_id":cid,
            "client_secret":sec
        }, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]
    at  = os.getenv("DROPBOX_ACCESS_TOKEN")
    if at:
        return at
    raise RuntimeError("No Dropbox token configured (need refresh credentials or access token).")

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

def upload_to_dropbox(local_path: str, dropbox_path: str, retries: int = 3, backoff: float = 1.0):
    """
    上傳檔案到 Dropbox，支援中文/特殊字元路徑。
    做法：Dropbox-API-Arg 用 json.dumps (ensure_ascii=True 預設)，
    將非 ASCII 自動轉成 \uXXXX，符合 HTTP header 限制且 Dropbox 可正確解析。
    """
    last_err = None
    for attempt in range(1, retries + 1):
        token = get_access_token()  # 每次都用 refresh token 取新的 access token（如果可用）
        with open(local_path, "rb") as f:
            api_args = {
                "path": dropbox_path,          # 可以直接用含中文的字串，如 "/test/錄音/檔案.wav"
                "mode": "overwrite",
                "autorename": False,
                "mute": True
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                # 注意：不要設 ensure_ascii=False，保持預設 True 才能把中文轉為 \uXXXX 放進 header
                "Dropbox-API-Arg": json.dumps(api_args)  
            }
            r = requests.post(DBX_UPLOAD_URL, headers=headers, data=f, timeout=600)

        if r.status_code == 200:
            return  # 成功

        # 保留完整錯誤細節，便於診斷（例如 missing_scope、path/not_found 等）
        last_err = f"{r.status_code} {r.reason}: {r.text}"

        # 429/5xx 採退避重試
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(backoff * attempt)
            continue

        # 其他錯誤直接丟出
        raise requests.HTTPError(last_err)
    
def probe_duration_seconds(local_file:str):
    try:
        p = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", local_file],
            capture_output=True, text=True, check=True
        )
        val = p.stdout.strip()
        return float(val) if val else None
    except Exception:
        return None

def split_audio_and_upload(local_file:str, segment_time:int, overlap_seconds:int, fmt:str,
                           dest_root:str, group_prefix:str, max_dirs:int, max_files_per_dir:int):
    tmp = tempfile.mkdtemp()
    uploaded = []
    try:
        duration = probe_duration_seconds(local_file)
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

            # fast path: copy
            cmd_copy = [
                "ffmpeg","-hide_banner","-nostdin","-y",
                "-ss", str(max(0.0, start)),
                "-i", local_file,
                "-t", str(segment_time),
                "-map","0:a:0","-vn","-c:a","copy",
                out_path
            ]
            p = subprocess.run(cmd_copy, capture_output=True)
            # fallback: re-encode
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
                    if duration is None and part_idx > 1:
                        break
                    err = (p.stderr or b"").decode("utf-8","ignore") + (p2.stderr or b"").decode("utf-8","ignore")
                    raise RuntimeError(f"ffmpeg failed around start={start}: {err[:4000]}")

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
            start += hop
            if duration is not None and start >= duration:
                break

        return {"uploaded": uploaded, "total_segments": len(uploaded), "hop": hop}
    finally:
        try:
            os.remove(local_file)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)