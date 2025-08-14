
from flask import Flask, request, jsonify
import os, tempfile, time, json

from dropbox_utils import (
    list_changes, list_slices, ensure_slices, get_shared_link,
    write_text_to_dropbox, read_text_from_dropbox, download_file, split_audio_and_upload
)

app = Flask(__name__)

API_KEY = os.getenv("API_KEY")
CURSOR_PATH = os.getenv("CURSOR_PATH", "/test/WAV/_jobs/cursor.json")

def check_api_key():
    if not API_KEY:
        return True
    return request.headers.get("X-Api-Key") == API_KEY

@app.before_request
def _guard():
    if not check_api_key():
        return jsonify({"error":"unauthorized"}), 401

@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "service": "Dropbox Orchestrator v5.1", "endpoints": ["/health","/diag","/list-changes","/ensure-slices","/list-slices","/shared-link","/cursor/get","/cursor/set","/start"]})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/diag", methods=["GET"])
def diag():
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
def shared_link_route():
    try:
        data = request.get_json(force=True) or {}
        path = data.get("path")
        prefer_tmp = data.get("temporary", True)
        if not path or not isinstance(path, str):
            return jsonify({"error": "Missing 'path'"}), 400

        out = get_shared_link(path, prefer_temporary=prefer_tmp)
        return jsonify(out), 200

    except Exception as e:
        # 盡量把 Dropbox 的錯誤訊息透出，方便你在 Make 看 log 排錯
        msg = str(e)
        # 你也可以在 api_call 裡把 HTTP 狀態碼、Dropbox .tag 帶上來
        return jsonify({"error": "shared_link_failed", "detail": msg}), 502
    
@app.route("/cursor/get", methods=["GET"])
def cursor_get():
    try:
        txt = read_text_from_dropbox(CURSOR_PATH)
        if not txt:
            return jsonify({"cursor": None})
        data = json.loads(txt)
        return jsonify({"cursor": data.get("cursor")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/cursor/set", methods=["POST"])
def cursor_set():
    try:
        cur = (request.get_json(force=True) or {}).get("cursor", None)
        write_text_to_dropbox(json.dumps({"cursor": cur}), CURSOR_PATH)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Legacy direct split
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
        result = split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir)
        return jsonify({"data": result}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT","8080"))
    app.run(host="0.0.0.0", port=port)