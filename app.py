
from flask import Flask, request, jsonify
import os, time, tempfile

from dropbox_utils import (
    list_changes, list_slices, ensure_slices,
    get_shared_link, ACCESS_GUARD_OK
)

app = Flask(__name__)

def guard():
    # Optional API key check
    api_key_env = os.getenv("API_KEY")
    if not api_key_env:
        return True
    return request.headers.get("X-Api-Key") == api_key_env

@app.before_request
def _check_key():
    if not guard():
        return jsonify({"error":"unauthorized"}), 401

@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "service": "Dropbox Orchestrator v5", "endpoints": ["/health","/diag","/list-changes","/ensure-slices","/list-slices","/shared-link","/start"]})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/diag", methods=["GET"])
def diag():
    # quickly verify token refresh & simple API call (list root)
    try:
        res = list_changes(path="", recursive=False, cursor=None, limit=1)
        return jsonify({"ok": True, "sample": res.get("entries", [])[:1]}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/list-changes", methods=["POST"])
def api_list_changes():
    data = request.get_json(force=True) or {}
    path = data.get("path", "/test/wav")
    recursive = bool(data.get("recursive", True))
    cursor = data.get("cursor")
    limit = int(data.get("limit", 2000))
    res = list_changes(path, recursive, cursor, limit)
    return jsonify(res), 200

@app.route("/list-slices", methods=["POST"])
def api_list_slices():
    data = request.get_json(force=True) or {}
    dest_root = data.get("dest_root", "/test/WAV")
    group_prefix = data.get("group_prefix")
    fmt = (data.get("format","wav")).lower().strip(".")
    if not group_prefix:
        return jsonify({"error":"Missing group_prefix"}), 400
    res = list_slices(dest_root, group_prefix, fmt)
    return jsonify(res), 200

@app.route("/ensure-slices", methods=["POST"])
def api_ensure_slices():
    data = request.get_json(force=True) or {}
    url = data.get("url")
    segment_time = int(data.get("segment_time", 400))
    overlap_seconds = int(data.get("overlap_seconds", 10))
    fmt = (data.get("format","wav")).lower().strip(".")
    dest_root = data.get("dest_root", "/test/WAV")
    group_prefix = data.get("group_prefix", "meeting")
    max_dirs = int(data.get("max_dirs", 5))
    max_files_per_dir = int(data.get("max_files_per_dir", 5))
    if not url or not group_prefix:
        return jsonify({"error":"Missing url/group_prefix"}), 400
    res = ensure_slices(url, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir)
    return jsonify(res), 200

@app.route("/shared-link", methods=["POST"])
def api_shared_link():
    data = request.get_json(force=True) or {}
    path = data.get("path")
    if not path:
        return jsonify({"error":"Missing path"}), 400
    res = get_shared_link(path)
    return jsonify(res), 200

# Legacy: keep /start for direct split+upload
from dropbox_utils import download_file, split_audio_and_upload
@app.route("/start", methods=["POST"])
def start():
    try:
        data = request.get_json(force=True) or {}
        url = data.get("url")
        if not url:
            return jsonify({"error":"Missing url"}), 400
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
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
