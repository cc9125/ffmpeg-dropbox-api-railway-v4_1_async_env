
import os, json, time, tempfile, shutil, subprocess, requests

OAUTH_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
DBX_API_URL = "https://api.dropboxapi.com/2"
DBX_CONTENT_URL = "https://content.dropboxapi.com/2"

def get_access_token():
    rt  = os.getenv("DROPBOX_REFRESH_TOKEN")
    cid = os.getenv("DROPBOX_CLIENT_ID")
    sec = os.getenv("DROPBOX_CLIENT_SECRET")
    if rt and cid and sec:
        r = requests.post(OAUTH_TOKEN_URL, data={
            "grant_type":"refresh_token",
            "refresh_token":rt,
            "client_id":cid,
            "client_secret":sec
        }, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]
    at  = os.getenv("DROPBOX_ACCESS_TOKEN")
    if at:
        return at
    raise RuntimeError("No Dropbox token configured")

def api_call(endpoint:str, payload:dict, content=False, headers_extra=None, stream=False, timeout=60):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    if content:
        # caller must set Dropbox-API-Arg etc.
        if headers_extra:
            headers.update(headers_extra)
        url = f"{DBX_CONTENT_URL}/{endpoint}"
        r = requests.post(url, headers=headers, data=payload, timeout=timeout, stream=stream)
    else:
        headers["Content-Type"] = "application/json"
        url = f"{DBX_API_URL}/{endpoint}"
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout, stream=stream)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {r.text}")
    return r.json()

def list_changes(path:str, recursive:bool, cursor:str|None, limit:int=2000):
    if cursor:
        return api_call("files/list_folder/continue", {"cursor": cursor})
    body = {
        "path": path,
        "recursive": recursive,
        "include_deleted": False,
        "include_non_downloadable_files": False,
        "limit": limit
    }
    return api_call("files/list_folder", body)

def list_folder(path:str):
    return api_call("files/list_folder", {"path": path, "recursive": False})

def search_slices(dest_root:str, group_prefix:str, fmt:str):
    # Prefer search_v2 under dest_root to speed up
    body = {
        "query": group_prefix,
        "options": {
            "path": dest_root,
            "filename_only": True,
            "max_results": 500
        }
    }
    try:
        res = api_call("files/search_v2", body, timeout=30)
        matches = res.get("matches", [])
        paths = []
        for m in matches:
            md = m.get("metadata",{}).get("metadata",{})
            if md.get(".tag") == "file":
                name = md.get("name","")
                if name.lower().startswith(f"{group_prefix.lower()}-") and name.lower().endswith(f".{fmt}"):
                    paths.append(md.get("path_lower"))
        return paths
    except Exception:
        # Fallback: list each subdir
        paths = []
        for i in range(1,6):
            sub = f"{i:02d}"
            try:
                lf = list_folder(f"{dest_root}/{sub}")
                for e in lf.get("entries",[]):
                    if e.get(".tag")=="file":
                        n = e.get("name","").lower()
                        if n.startswith(f"{group_prefix.lower()}-") and n.endswith(f".{fmt}"):
                            paths.append(e.get("path_lower"))
            except Exception:
                pass
        return paths

def group_by_dir(paths:list[str], dest_root:str):
    out = {"01":[], "02":[], "03":[], "04":[], "05":[]}
    for p in paths:
        # expect .../dest_root/XX/filename
        parts = p.split("/")
        try:
            idx = parts.index(dest_root.strip("/").lower().split("/")[-1])
        except ValueError:
            # attempt approximate: find 'xx' component
            for comp in parts:
                if len(comp)==2 and comp.isdigit():
                    idx = parts.index(comp)
                    break
            else:
                continue
        # dir token likely next segment
        for comp in parts:
            if len(comp)==2 and comp.isdigit() and comp in out:
                out[comp].append(p)
                break
    # sort
    for k in out:
        out[k] = sorted(out[k])
    return out

def list_slices(dest_root:str, group_prefix:str, fmt:str):
    dest_root = dest_root.rstrip("/")
    paths = search_slices(dest_root, group_prefix, fmt)
    grouped = group_by_dir(paths, dest_root.lower())
    total = sum(len(v) for v in grouped.values())
    return {"total_segments": total, "slices_by_dir": grouped}

def get_shared_link(path:str):
    # list_shared_links first
    try:
        res = api_call("sharing/list_shared_links", {"path": path, "direct_only": True})
        links = res.get("links", [])
        if links:
            url = links[0].get("url","")
            if "dl=0" in url:
                url = url.replace("dl=0","dl=1")
            elif "dl=1" not in url:
                url = url + ("&dl=1" if "?" in url else "?dl=1")
            return {"url": url, "existed": True}
    except Exception:
        pass
    # create
    res = api_call("sharing/create_shared_link_with_settings", {"path": path, "settings": {"audience":"public","access":"viewer","allow_download": True}})
    url = res.get("url","")
    if "dl=0" in url:
        url = url.replace("dl=0","dl=1")
    elif "dl=1" not in url:
        url = url + ("&dl=1" if "?" in url else "?dl=1")
    return {"url": url, "existed": False}

def to_direct(shared_url:str)->str:
    if not shared_url: return shared_url
    if "dl=0" in shared_url: return shared_url.replace("dl=0","dl=1")
    if "dropbox.com" in shared_url and "dl=1" not in shared_url:
        return shared_url + ("&dl=1" if "?" in shared_url else "?dl=1")
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

def upload_to_dropbox(local_path:str, dropbox_path:str, retries:int=3, backoff:float=1.0):
    last_err = None
    for attempt in range(1, retries + 1):
        token = get_access_token()  # 每次都用 refresh token 取新的 access token（如果可用）
        with open(local_path,"rb") as f:
            api_args = {
                "path": dropbox_path,          # 可以直接用含中文的字串，如 "/test/錄音/檔案.wav"
                "mode": "overwrite",
                "autorename": False,
                "mute": True
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                # 讓 json.dumps 幫你 escape 中文，避免 unicodeescape 問題
                "Dropbox-API-Arg": json.dumps(api_args, ensure_ascii=True)
            }
            r = requests.post(f"{DBX_CONTENT_URL}/files/upload", headers=headers, data=f, timeout=600)
        if r.status_code == 200:
            return  # 成功

        # 保留完整錯誤細節，便於診斷（例如 missing_scope、path/not_found 等）
        last_err = f"{r.status_code} {r.reason}: {r.text}"

        # 429/5xx 採退避重試
        if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(backoff * attempt)
            continue

        # 其他錯誤直接丟出
        raise requests.HTTPError(last_err)

def probe_duration_seconds(local_file:str):
    try:
        p = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", local_file],
            capture_output=True, text=True, check=True
        )
        val = p.stdout.strip()
        return float(val) if val else None
    except Exception:
        return None

def split_audio_and_upload(local_file:str, segment_time:int, overlap_seconds:int, fmt:str,
                           dest_root:str, group_prefix:str, max_dirs:int, max_files_per_dir:int):
    tmp = tempfile.mkdtemp()
    uploaded = []
    try:
        duration = probe_duration_seconds(local_file)
        hop = max(1, int(segment_time) - int(overlap_seconds))
        start = 0.0
        dir_idx, in_dir = 1, 0
        part_idx = 1

        while True:
            if duration is not None and start >= duration:
                break
            if dir_idx > int(max_dirs):
                break

            out_name = f"{group_prefix}-{part_idx:03d}.{fmt}"
            out_path = os.path.join(tmp, out_name)

            # fast copy
            cmd_copy = ["ffmpeg","-hide_banner","-nostdin","-y","-ss", str(max(0.0, start)),"-i", local_file,"-t", str(segment_time),"-map","0:a:0","-vn","-c:a","copy", out_path]
            p = subprocess.run(cmd_copy, capture_output=True)
            if p.returncode != 0 or (not os.path.exists(out_path) or os.path.getsize(out_path) < 1024):
                cmd_re = ["ffmpeg","-hide_banner","-nostdin","-y","-ss", str(max(0.0, start)),"-i", local_file,"-t", str(segment_time),"-map","0:a:0","-vn"]
                if fmt.lower() in ("mp3","m4a","aac"):
                    cmd_re += ["-c:a","aac","-b:a","128k"]
                else:
                    cmd_re += ["-c:a","pcm_s16le"]
                cmd_re += [out_path]
                p2 = subprocess.run(cmd_re, capture_output=True)
                if p2.returncode != 0 or (not os.path.exists(out_path) or os.path.getsize(out_path) < 1024):
                    if duration is None and part_idx > 1:
                        break
                    err = (p.stderr or b"").decode("utf-8","ignore") + (p2.stderr or b"").decode("utf-8","ignore")
                    raise RuntimeError(f"ffmpeg failed around start={start}: {err[:4000]}")

            if in_dir >= int(max_files_per_dir):
                dir_idx += 1; in_dir = 0
                if dir_idx > int(max_dirs): break
            sub = f"{dir_idx:02d}"
            dropbox_path = f"{dest_root}/{sub}/{out_name}"
            upload_to_dropbox(out_path, dropbox_path)
            uploaded.append(dropbox_path)
            in_dir += 1; part_idx += 1
            start += hop
            if duration is not None and start >= duration:
                break

        return {"uploaded": uploaded, "total_segments": len(uploaded), "hop": hop}
    finally:
        try: os.remove(local_file)
        except Exception: pass
        shutil.rmtree(tmp, ignore_errors=True)

def ensure_slices(url, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir):
    # Check existing
    existing = list_slices(dest_root, group_prefix, fmt)
    if existing.get("total_segments",0) > 0:
        existing["already_sliced"] = True
        return existing
    # else slice
    local_file = download_file(url)
    if not local_file:
        raise RuntimeError("Download failed")
    created = split_audio_and_upload(local_file, segment_time, overlap_seconds, fmt, dest_root, group_prefix, max_dirs, max_files_per_dir)
    final = list_slices(dest_root, group_prefix, fmt)
    final["already_sliced"] = False
    return final

# simple flag
ACCESS_GUARD_OK = True
