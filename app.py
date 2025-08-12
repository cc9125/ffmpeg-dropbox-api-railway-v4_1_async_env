from flask import Flask, request, jsonify
import os, tempfile, time

app = Flask(__name__)

@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "msg": "Whisper+Dropbox API v4.2 r1", "endpoints": ["/health","/diag","/start"]})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/diag", methods=["GET","POST"])
def diag():
    # quick write test to Dropbox: /test/WAV/_jobs/diag-<ts>.txt
    try:
        from dropbox_utils import upload_to_dropbox  # lazy import
        ts = int(time.time())
        local_tmp = os.path.join(tempfile.gettempdir(), f"diag-{ts}.txt")
        with open(local_tmp, "w", encoding="utf-8") as f:
            f.write(f"diag {ts}")
        path = f"/test/WAV/_jobs/diag-{ts}.txt"
        upload_to_dropbox(local_tmp, path)
        return jsonify({"ok": True, "path": path}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/start", methods=["POST"])
def start():
    try:
        from dropbox_utils import download_file, split_audio_and_upload
        data = request.get_json(force=True) or {}
        url = data.get("url")
        if not url:
            return jsonify({"error":"Missing url (Dropbox share link)"}), 400

        segment_time = int(data.get("segment_time", 400))
        overlap_seconds = int(data.get("overlap_seconds", 10))
        fmt = (data.get("format","wav")).lower().strip(".")
        dest_root = data.get("dest_root", "/test/WAV")
        group_prefix = data.get("group_prefix", "meeting")
        max_dirs = int(data.get("max_dirs", 5))
        max_files_per_dir = int(data.get("max_files_per_dir", 5))

        local_file = download_file(url)
        if not local_file:
            return jsonify({"error":"Failed to download source"}), 400

        result = split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt,
                                        dest_root, group_prefix, max_dirs, max_files_per_dir)
        return jsonify({"data": result}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT","8080"))
    app.run(host="0.0.0.0", port=port)