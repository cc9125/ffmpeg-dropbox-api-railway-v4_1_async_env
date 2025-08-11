
import os
import requests
import subprocess
import tempfile

def get_access_token():
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    client_id = os.getenv("DROPBOX_CLIENT_ID")
    client_secret = os.getenv("DROPBOX_CLIENT_SECRET")
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN")

    if refresh_token and client_id and client_secret:
        r = requests.post(
            "https://api.dropboxapi.com/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret
            },
            timeout=20
        )
        r.raise_for_status()
        return r.json().get("access_token")
    if access_token:
        return access_token
    raise RuntimeError("No Dropbox token configured (refresh or access).")

def download_file(shared_url):
    if not shared_url:
        return None
    if "dl=0" in shared_url:
        shared_url = shared_url.replace("dl=0", "dl=1")
    local_path = tempfile.mktemp()
    with requests.get(shared_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
    return local_path

def upload_to_dropbox(local_path, dropbox_path):
    token = get_access_token()
    with open(local_path, "rb") as f:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": f'{{"path":"{dropbox_path}","mode":"overwrite","autorename":false,"mute":true}}'
        }
        r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=f, timeout=300)
        r.raise_for_status()

def split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir):
    tmp_dir = tempfile.mkdtemp()
    out_tmpl = os.path.join(tmp_dir, f"{group_prefix}-%03d.{fmt}")
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-i", local_file,
        "-f", "segment",
        "-segment_time", str(segment_time),
        "-segment_overlap", str(overlap_seconds),
        "-c", "copy",
        out_tmpl
    ]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.decode('utf-8', 'ignore')[:4000]}")

    files = sorted(os.listdir(tmp_dir))
    results = []
    dir_idx = 1
    count_in_dir = 0
    for fname in files:
        if count_in_dir >= int(max_files_per_dir):
            dir_idx += 1
            count_in_dir = 0
        if dir_idx > int(max_dirs):
            break
        subdir = f"{dir_idx:02d}"
        dropbox_path = f"{dest_root}/{subdir}/{fname}"
        upload_to_dropbox(os.path.join(tmp_dir, fname), dropbox_path)
        results.append(dropbox_path)
        count_in_dir += 1
    return {"uploaded": results, "total_segments": len(results)}
