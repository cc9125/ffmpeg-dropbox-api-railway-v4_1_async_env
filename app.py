from flask import Flask, request, jsonify
import os, sys, subprocess, requests, tempfile, uuid

app = Flask(__name__)

@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "msg": "Whisper+Dropbox API v4.2", "endpoints": ["/health", "/start"]})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

def refresh_access_token():
    client_id = os.getenv("DROPBOX_CLIENT_ID")
    client_secret = os.getenv("DROPBOX_CLIENT_SECRET")
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        raise Exception("Missing Dropbox OAuth credentials")
    r = requests.post(
        "https://api.dropboxapi.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        }
    )
    r.raise_for_status()
    return r.json()["access_token"]

@app.route("/start", methods=["POST"])
def start():
    data = request.get_json(force=True)
    url = data.get("url")
    segment_time = int(data.get("segment_time", 400))
    overlap = int(data.get("overlap_seconds", 10))
    fmt = data.get("format", "wav")
    dest_root = data.get("dest_root", "/test/wav")
    group_prefix = data.get("group_prefix", "meeting")
    max_dirs = int(data.get("max_dirs", 5))
    max_files_per_dir = int(data.get("max_files_per_dir", 5))

    if not url:
        return jsonify({"error": "Missing Dropbox file URL"}), 400

    try:
        token = refresh_access_token()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    dl_url = url.replace("?dl=0", "?dl=1")
    local_in = os.path.join(tempfile.gettempdir(), f"in_{uuid.uuid4().hex}.{fmt}")
    r = requests.get(dl_url)
    with open(local_in, "wb") as f:
        f.write(r.content)

    total_parts = 0
    for dir_index in range(1, max_dirs + 1):
        dir_name = f"{dir_index:02d}"
        for file_index in range(1, max_files_per_dir + 1):
            start_time = (total_parts * (segment_time - overlap))
            local_out = os.path.join(tempfile.gettempdir(), f"part_{dir_index}_{file_index}.{fmt}")
            cmd = [
                "ffmpeg", "-y",
                "-i", local_in,
                "-ss", str(start_time),
                "-t", str(segment_time),
                local_out
            ]
            subprocess.run(cmd, check=True)

            # Upload to Dropbox
            dropbox_path = f"{dest_root}/{dir_name}/{group_prefix}_{file_index}.{fmt}"
            with open(local_out, "rb") as f:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                    "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "overwrite"}}'
                }
                ur = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=f)
                ur.raise_for_status()

            total_parts += 1

    return jsonify({"ok": True, "uploaded_parts": total_parts})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"[startup] Python: {sys.version}")
    print(f"[startup] Binding 0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port)
