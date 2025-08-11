
from flask import Flask, request, jsonify
import os
from dropbox_utils import download_file, split_audio_and_upload

app = Flask(__name__)

@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok", "endpoints": ["/health","/start"]})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/start", methods=["POST"])
def start():
    try:
        data = request.get_json() or {}
        url = data.get("url")
        segment_time = data.get("segment_time", 400)
        overlap_seconds = data.get("overlap_seconds", 10)
        fmt = data.get("format", "wav")
        dest_root = data.get("dest_root", "/test/WAV")
        group_prefix = data.get("group_prefix", "meeting")
        max_dirs = data.get("max_dirs", 5)
        max_files_per_dir = data.get("max_files_per_dir", 5)

        local_file = download_file(url)
        if not local_file:
            return jsonify({"error": "Failed to download file"}), 400

        result = split_audio_and_upload(
            local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix,
            max_dirs, max_files_per_dir
        )
        return jsonify({"data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
