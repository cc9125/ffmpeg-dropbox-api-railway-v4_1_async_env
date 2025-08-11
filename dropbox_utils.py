
import os, requests, subprocess, tempfile

def get_access_token():
    rt = os.getenv("DROPBOX_REFRESH_TOKEN")
    cid = os.getenv("DROPBOX_CLIENT_ID")
    sec = os.getenv("DROPBOX_CLIENT_SECRET")
    at = os.getenv("DROPBOX_ACCESS_TOKEN")
    if rt and cid and sec:
        r = requests.post("https://api.dropboxapi.com/oauth2/token", data={
            "grant_type":"refresh_token","refresh_token":rt,
            "client_id":cid,"client_secret":sec
        }, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]
    if at:
        return at
    raise RuntimeError("No Dropbox token configured (refresh or access).")

def download_file(shared_url:str):
    if not shared_url: return None
    if "dl=0" in shared_url: shared_url = shared_url.replace("dl=0","dl=1")
    lp = tempfile.mktemp()
    with requests.get(shared_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(lp,"wb") as f:
            for ch in r.iter_content(chunk_size=1024*1024):
                if ch: f.write(ch)
    return lp

def upload_to_dropbox(local_path, dropbox_path):
    token = get_access_token()
    with open(local_path,"rb") as f:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": f'{{"path":"{dropbox_path}","mode":"overwrite","autorename":false,"mute":true}}'
        }
        r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=f, timeout=300)
        r.raise_for_status()

def split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir):
    tmp = tempfile.mkdtemp()
    out_tmpl = os.path.join(tmp, f"{group_prefix}-%03d.{fmt}")
    cmd = ["ffmpeg","-hide_banner","-nostdin","-y","-i",local_file,
           "-f","segment","-segment_time",str(segment_time),
           "-segment_overlap",str(overlap_seconds),
           "-c","copy", out_tmpl]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8","ignore")[:4000])
    files = sorted(os.listdir(tmp))
    res = []
    dir_idx = 1; in_dir = 0
    for fn in files:
        if in_dir >= max_files_per_dir:
            dir_idx += 1; in_dir = 0
        if dir_idx > max_dirs: break
        sub = f"{dir_idx:02d}"
        path = f"{dest_root}/{sub}/{fn}"
        upload_to_dropbox(os.path.join(tmp, fn), path)
        res.append(path); in_dir += 1
    return {"uploaded": res, "total_segments": len(res)}
