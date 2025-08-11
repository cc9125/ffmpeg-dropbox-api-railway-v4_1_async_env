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
            }
        )
        if r.status_code == 200:
            return r.json().get("access_token")
        else:
            raise Exception(f"Failed to refresh token: {r.text}")
    elif access_token:
        return access_token
    else:
        raise Exception("No Dropbox token configured.")

def download_file(shared_url):
    # 轉 dl=0 → dl=1
    if "dl=0" in shared_url:
        shared_url = shared_url.replace("dl=0", "dl=1")
    local_path = tempfile.mktemp()
    r = requests.get(shared_url, stream=True)
    if r.status_code == 200:
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return local_path
    else:
        return None

def upload_to_dropbox(local_path, dropbox_path):
    access_token = get_access_token()
    with open(local_path, "rb") as f:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": f"{{\"path\": \"{dropbox_path}\", \"mode\": \"add\", \"autorename\": true}}"
        }
        r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=f)
    if r.status_code != 200:
        raise Exception(f"Dropbox upload failed: {r.text}")

def split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir):
    tmp_dir = tempfile.mkdtemp()
    ffmpeg_cmd = [
        "ffmpeg", "-i", local_file, "-f", "segment",
        "-segment_time", str(segment_time),
        "-segment_overlap", str(overlap_seconds),
        "-c", "copy",
        os.path.join(tmp_dir, f"out_%03d.{fmt}")
    ]
    subprocess.run(ffmpeg_cmd, check=True)

    # 上傳
    results = []
    files = sorted(os.listdir(tmp_dir))
    dir_index = 1
    file_count = 0
    for f in files:
        if file_count >= max_files_per_dir:
            dir_index += 1
            file_count = 0
        if dir_index > max_dirs:
            break
        dropbox_path = f"{dest_root}/{str(dir_index).zfill(2)}/{f}"
        upload_to_dropbox(os.path.join(tmp_dir, f), dropbox_path)
        results.append(dropbox_path)
        file_count += 1
    return {"uploaded": results, "total_segments": len(results)}
