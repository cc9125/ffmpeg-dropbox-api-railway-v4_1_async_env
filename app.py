from flask import Flask, request, jsonify
import os
import subprocess
import uuid
import json
import time
import threading
import requests

app = Flask(__name__)

DROPBOX_CONTENT_UPLOAD = "https://content.dropboxapi.com/2/files/upload"
DROPBOX_LIST_FOLDER = "https://api.dropboxapi.com/2/files/list_folder"
DROPBOX_DOWNLOAD = "https://content.dropboxapi.com/2/files/download"

def to_direct_dl(url: str) -> str:
    if "dropboxusercontent.com" in url:
        return url
    if "dropbox.com" in url:
        u = url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
        u = u.replace("?dl=0", "").replace("&dl=0", "")
        return u
    return url

def ensure_dir_format(i: int) -> str:
    return f"{i:02d}"

def dbx_headers(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def dropbox_list_count(token: str, path: str) -> int:
    payload = {"path": path, "recursive": False, "include_deleted": False}
    try:
        resp = requests.post(DROPBOX_LIST_FOLDER, headers=dbx_headers(token), data=json.dumps(payload), timeout=30)
        if resp.status_code == 409:
            return 0
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("entries", [])
        return sum(1 for e in entries if e.get(".tag") == "file")
    except Exception:
        return 0

def dropbox_upload(token: str, dest_path: str, content: bytes):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps({
            "path": dest_path,
            "mode": "overwrite",
            "autorename": False,
            "mute": True,
            "strict_conflict": False
        })
    }
    resp = requests.post(DROPBOX_CONTENT_UPLOAD, headers=headers, data=content, timeout=180)
    resp.raise_for_status()
    return resp.json()

def dropbox_download(token: str, path: str) -> bytes:
    headers = {"Authorization": f"Bearer {token}", "Dropbox-API-Arg": json.dumps({"path": path})}
    resp = requests.post(DROPBOX_DOWNLOAD, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content

def write_status(token: str, dest_root: str, job_id: str, status: dict):
    path = f"{dest_root}/_jobs/{job_id}.json"
    content = json.dumps(status, ensure_ascii=False).encode("utf-8")
    dropbox_upload(token, path, content)

def read_status(token: str, dest_root: str, job_id: str):
    path = f"{dest_root}/_jobs/{job_id}.json"
    try:
        raw = dropbox_download(token, path)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None

def pick_subdir(token: str, dest_root: str, max_dirs: int, max_per: int):
    for i in range(1, max_dirs+1):
        sub = ensure_dir_format(i)
        folder_path = f"{dest_root}/{sub}"
        count = dropbox_list_count(token, folder_path)
        if count < max_per:
            return sub
    return None

def already_processed(token: str, dest_root: str, group_prefix: str, fmt: str, max_dirs: int) -> bool:
    first_piece = f"{group_prefix}-001.{fmt}"
    for i in range(1, max_dirs+1):
        sub = ensure_dir_format(i)
        folder = f"{dest_root}/{sub}"
        payload = {"path": folder, "recursive": False, "include_deleted": False}
        try:
            resp = requests.post(DROPBOX_LIST_FOLDER, headers=dbx_headers(token), data=json.dumps(payload), timeout=30)
            if resp.status_code == 200:
                for e in resp.json().get("entries", []):
                    if e.get(".tag") == "file" and e.get("name") == first_piece:
                        return True
        except Exception:
            pass
    return False

def resolve_token(body_token: str | None) -> str | None:
    tok = body_token or os.environ.get("DROPBOX_ACCESS_TOKEN")
    return tok

def worker(job_id: str, params: dict):
    token = resolve_token(params.get("dropbox_token"))
    if not token:
        print("Missing dropbox_token (env or body) in worker")
        return

    dest_root = params.get("dest_root") or "/test/wav"
    url = params["url"]
    segment_time = int(params.get("segment_time", 400))
    overlap = int(params.get("overlap_seconds", 10))
    fmt = (params.get("format") or "wav").lower().strip(".")
    group_prefix = params.get("group_prefix") or f"group-{uuid.uuid4().hex[:6]}"
    max_dirs = int(params.get("max_dirs", 5))
    max_per = int(params.get("max_files_per_dir", 5))

    status = {"job_id": job_id, "state": "running", "progress": 0, "uploaded": [], "group_prefix": group_prefix}
    try:
        if already_processed(token, dest_root, group_prefix, fmt, max_dirs):
            status.update({"state": "skipped", "reason": "already_processed"})
            write_status(token, dest_root, job_id, status)
            return

        dl_url = to_direct_dl(url)
        work_id = uuid.uuid4().hex
        in_path = f"/tmp/in_{work_id}"
        out_dir = f"/tmp/splits_{work_id}"
        os.makedirs(out_dir, exist_ok=True)

        subprocess.run(["curl", "-sS", "-L", dl_url, "-o", in_path], check=True)

        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", in_path],
                check=True, capture_output=True, text=True
            )
            duration_s = float(probe.stdout.strip())
        except Exception:
            duration_s = None

        start = 0.0
        seq = 1
        uploads = []
        while True:
            if duration_s is not None and start >= duration_s:
                break
            chunk = float(segment_time)
            if duration_s is not None:
                remaining = duration_s - start
                if remaining <= 0:
                    break
                chunk = min(chunk, remaining)

            out_file = os.path.join(out_dir, f"segment-{seq:03d}.{fmt}")
            p = subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y",
                "-ss", str(max(0.0, start)),
                "-i", in_path,
                "-t", str(chunk),
                "-c", "copy",
                out_file
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode != 0 or (not os.path.exists(out_file) or os.path.getsize(out_file) == 0):
                audio_codec = "aac" if fmt in ("mp3","m4a","aac") else "pcm_s16le"
                cmd = [
                    "ffmpeg", "-hide_banner", "-nostdin", "-y",
                    "-ss", str(max(0.0, start)),
                    "-i", in_path,
                    "-t", str(chunk),
                    "-map", "0:a:0", "-vn", "-c:a", audio_codec
                ]
                if audio_codec == "aac":
                    cmd += ["-b:a", "128k"]
                cmd += [out_file]
                p2 = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if p2.returncode != 0 or (not os.path.exists(out_file) or os.path.getsize(out_file) == 0):
                    status.update({"state": "error", "error": "ffmpeg segment failed"})
                    write_status(token, dest_root, job_id, status)
                    return

            subdir = pick_subdir(token, dest_root, max_dirs, max_per)
            if subdir is None:
                status.update({"state": "error", "error": "All destination subfolders are full"})
                write_status(token, dest_root, job_id, status)
                return

            with open(out_file, "rb") as f:
                content = f.read()
            dest_path = f"{dest_root}/{subdir}/{group_prefix}-{seq:03d}.{fmt}"
            try:
                _ = dropbox_upload(token, dest_path, content)
            except Exception as e:
                status.update({"state": "error", "error": f"Dropbox upload failed: {e}"})
                write_status(token, dest_root, job_id, status)
                return

            uploads.append({"dest": dest_path, "size": len(content)})
            status.update({"uploaded": uploads, "progress": int( (start + chunk) / max(duration_s or (start+chunk), 1) * 100 )})
            write_status(token, dest_root, job_id, status)

            seq += 1
            start += max(1.0, float(segment_time) - float(overlap))
            time.sleep(0.05)

        try:
            os.remove(in_path)
        except Exception:
            pass

        status.update({"state": "done", "progress": 100})
        write_status(token, dest_root, job_id, status)
    except subprocess.CalledProcessError as e:
        status.update({"state": "error", "error": f"subprocess error: {str(e)}"})
        write_status(token, dest_root, job_id, status)
    except Exception as e:
        status.update({"state": "error", "error": str(e)})
        write_status(token, dest_root, job_id, status)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "ffmpeg-dropbox-api", "endpoints": ["/start", "/status"]})

@app.route("/start", methods=["POST"])
def start_job():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    token = resolve_token(data.get("dropbox_token"))
    if not url or not ("dropbox.com" in url or "dropboxusercontent.com" in url):
        return jsonify({"error": "Missing or invalid Dropbox URL"}), 400
    if not token:
        return jsonify({"error": "Missing dropbox_token (body or env DROPBOX_ACCESS_TOKEN)"}), 400

    job_id = uuid.uuid4().hex[:12]
    params = {
        "url": url,
        "dropbox_token": token,
        "dest_root": data.get("dest_root") or "/test/wav",
        "segment_time": data.get("segment_time", 400),
        "overlap_seconds": data.get("overlap_seconds", 10),
        "format": data.get("format", "wav"),
        "group_prefix": data.get("group_prefix") or f"group-{job_id}",
        "max_dirs": data.get("max_dirs", 5),
        "max_files_per_dir": data.get("max_files_per_dir", 5)
    }

    try:
        write_status(token, params["dest_root"], job_id, {
            "job_id": job_id, "state": "queued", "progress": 0, "uploaded": [], "group_prefix": params["group_prefix"]
        })
    except Exception as e:
        return jsonify({"error": "Failed to write initial job status", "detail": str(e)}), 500

    t = threading.Thread(target=worker, args=(job_id, params), daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "state": "queued", "group_prefix": params["group_prefix"]}), 202

@app.route("/status", methods=["GET"])
def get_status():
    job_id = request.args.get("job_id")
    token = resolve_token(request.args.get("dropbox_token"))
    dest_root = request.args.get("dest_root") or "/test/wav"
    if not job_id or not token:
        return jsonify({"error": "Missing job_id or dropbox_token (query or env)"}), 400
    st = read_status(token, dest_root, job_id)
    if not st:
        return jsonify({"error": "Not found"}), 404
    return jsonify(st), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
