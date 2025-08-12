import os, requests, subprocess, tempfile, shutil

OAUTH_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DBX_UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"

def get_access_token():
    rt = os.getenv("DROPBOX_REFRESH_TOKEN")
    cid = os.getenv("DROPBOX_CLIENT_ID")
    sec = os.getenv("DROPBOX_CLIENT_SECRET")
    at = os.getenv("DROPBOX_ACCESS_TOKEN")
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

def to_direct(shared_url:str)->str:
    if not shared_url: return shared_url
    if "dl=0" in shared_url: return shared_url.replace("dl=0","dl=1")
    if "dropbox.com" in shared_url and "dl=1" not in shared_url:
        if "?" in shared_url: return shared_url + "&dl=1"
        return shared_url + "?dl=1"
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

def upload_to_dropbox(local_path:str, dropbox_path:str):
    token = get_access_token()
    with open(local_path,"rb") as f:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": f'{{"path":"{dropbox_path}","mode":"overwrite","autorename":false,"mute":true}}'
        }
        r = requests.post(DBX_UPLOAD_URL, headers=headers, data=f, timeout=600)
        r.raise_for_status()

def split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir):
    tmp = tempfile.mkdtemp()
    try:
        out_tmpl = os.path.join(tmp, f"{group_prefix}-%03d.{fmt}")
        cmd = ["ffmpeg","-hide_banner","-nostdin","-y","-i",local_file,
               "-f","segment","-segment_time",str(segment_time),
               "-segment_overlap",str(overlap_seconds),
               "-map","0:a:0","-vn","-c:a","copy", out_tmpl]
        p = subprocess.run(cmd, capture_output=True)
        if p.returncode != 0 or not os.listdir(tmp):
            # 回退：重新編碼避免容器內無法 copy 編碼
            cmd = ["ffmpeg","-hide_banner","-nostdin","-y","-i",local_file,
                   "-f","segment","-segment_time",str(segment_time),
                   "-segment_overlap",str(overlap_seconds)]
            if fmt in ("mp3","m4a","aac"):
                cmd += ["-c:a","aac","-b:a","128k"]
            else:
                cmd += ["-c:a","pcm_s16le"]
            cmd += [out_tmpl]
            p2 = subprocess.run(cmd, capture_output=True)
            if p2.returncode != 0 or not os.listdir(tmp):
                err = (p.stderr or b"").decode("utf-8","ignore") + (p2.stderr or b"").decode("utf-8","ignore")
                raise RuntimeError(f"ffmpeg failed: {err[:4000]}")

        files = sorted(os.listdir(tmp))
        res = []
        d = 1; n = 0
        for fn in files:
            if n >= max_files_per_dir:
                d += 1; n = 0
            if d > max_dirs: break
            sub = f"{d:02d}"
            path = f"{dest_root}/{sub}/{fn}"
            upload_to_dropbox(os.path.join(tmp, fn), path)
            res.append(path); n += 1
        return {"uploaded": res, "total_segments": len(res)}
    finally:
        try:
            os.remove(local_file)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)