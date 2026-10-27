"""Servidor HTTP local (solo 127.0.0.1) con la API JSON y la interfaz web."""
from __future__ import annotations

import json
import os
import secrets
import string
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from . import __version__, covers, jobs, organizer, scanner
from . import musicbrainz as mb

TOKEN = secrets.token_urlsafe(24)
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".navimusic", "settings.json")

STATE: Dict[str, Any] = {"root": "", "scan": None, "plans": {}}
SETTINGS: Dict[str, Any] = {"contact": "", "trash": True}


def load_settings() -> None:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            SETTINGS.update(json.load(f))
    except (OSError, ValueError):
        pass
    mb.set_contact(SETTINGS["contact"])


def save_settings() -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(SETTINGS, f)
    mb.set_contact(SETTINGS["contact"])


class ApiError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def need_scan() -> Dict[str, Any]:
    if not STATE["scan"]:
        raise ApiError("Primero escanea una carpeta")
    return STATE["scan"]


def safe_path(rel: str) -> str:
    root = STATE["root"]
    p = os.path.abspath(os.path.join(root, *rel.split("/"))) if rel else root
    if os.path.commonpath([root, p]) != root:
        raise ApiError("Ruta fuera de la biblioteca", 403)
    return p


# --- explorador de carpetas -----------------------------------------------------

def list_roots() -> List[Dict[str, str]]:
    home = os.path.expanduser("~")
    roots = [{"name": "Inicio", "path": home}]
    for sub in ("Music", "Música", "Downloads", "Descargas"):
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            roots.append({"name": sub, "path": p})
    if os.name == "nt":
        for c in string.ascii_uppercase:
            if os.path.exists(f"{c}:\\"):
                roots.append({"name": f"{c}:\\", "path": f"{c}:\\"})
    else:
        for base in ("/Volumes", "/media", "/mnt", "/run/media"):
            if os.path.isdir(base):
                try:
                    for n in sorted(os.listdir(base)):
                        p = os.path.join(base, n)
                        if os.path.isdir(p):
                            roots.append({"name": n, "path": p})
                except OSError:
                    pass
        roots.append({"name": "/", "path": "/"})
    return roots


def fs_list(path: str) -> Dict[str, Any]:
    path = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(path):
        raise ApiError("No es una carpeta")
    dirs = []
    try:
        for n in sorted(os.listdir(path), key=str.casefold):
            if n.startswith("."):
                continue
            if os.path.isdir(os.path.join(path, n)):
                dirs.append(n)
    except PermissionError:
        raise ApiError("Sin permiso para leer esta carpeta", 403)
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else "", "dirs": dirs, "roots": list_roots()}


# --- acciones -------------------------------------------------------------------

def do_scan(body: Dict[str, Any]) -> Dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(body.get("path", "")))
    if not os.path.isdir(root):
        raise ApiError("La carpeta no existe")

    def run(job: jobs.Job) -> Dict[str, Any]:
        res = scanner.scan(root, job)
        if res:
            STATE.update(root=root, scan=res, plans={})
            covers.CACHE.clear()
            return {"root": root, "stats": res["stats"]}
        return {}
    return jobs.start("scan", run).to_dict()


def do_delete(body: Dict[str, Any]) -> Dict[str, Any]:
    need_scan()
    paths: List[str] = body.get("paths", [])
    use_trash = bool(SETTINGS["trash"])
    deleted, errors = [], []
    # carpetas más profundas primero
    for rel in sorted(paths, key=lambda p: -p.count("/")):
        try:
            p = safe_path(rel)
            if p == STATE["root"]:
                raise ApiError("No se puede borrar la carpeta raíz")
            if use_trash:
                from send2trash import send2trash
                send2trash(p)
            elif os.path.isdir(p):
                os.rmdir(p)  # solo carpetas vacías
            else:
                os.remove(p)
            deleted.append(rel)
        except Exception as e:  # noqa: BLE001
            errors.append({"path": rel, "error": f"{type(e).__name__}: {e}"})
    return {"deleted": deleted, "errors": errors}


def do_cover_search(body: Dict[str, Any]) -> Dict[str, Any]:
    scan = need_scan()
    root = STATE["root"]
    dirs = body.get("dirs", [])
    emb = bool(body.get("embedded", True))
    return jobs.start("covers", lambda job: covers.search(job, root, scan, dirs, emb)).to_dict()


def do_cover_save(body: Dict[str, Any]) -> Dict[str, Any]:
    need_scan()
    saved, errors = [], []
    for d in body.get("dirs", []):
        try:
            saved.append({"dir": d, "file": os.path.basename(covers.save(STATE["root"], d))})
        except Exception as e:  # noqa: BLE001
            errors.append({"path": d, "error": str(e)})
    return {"saved": saved, "errors": errors}


def _plan_dir(d: str, mbid: str = "", cands: Any = None) -> Dict[str, Any]:
    scan, root = need_scan(), STATE["root"]
    ts = [t for t in scan["tracks"] if t["dir"] == d]
    paths = [t["path"] for t in ts]
    artist = next((t["albumartist"] or t["artist"] for t in ts if t["albumartist"] or t["artist"]), "")
    album = next((t["album"] for t in ts if t["album"]), "")
    note = ""
    release = None
    try:
        if not mbid:
            mbid = next((t["mbid"] for t in ts if t["mbid"]), "")
        if cands is None:
            cands = mb.search_releases(artist, album)
        if mbid and not any(c["id"] == mbid for c in cands):
            cands = [{"id": mbid, "title": album, "artist": artist, "date": "", "country": "", "tracks": 0,
                      "score": 100, "status": ""}] + cands
        if not mbid:
            best = mb.best_candidate(cands, len(ts))
            if best and best["score"] >= 70:
                mbid = best["id"]
            else:
                note = "Sin coincidencia fiable en MusicBrainz: solo limpieza básica"
        if mbid:
            release = mb.get_release(mbid)
            if not release:
                note = "No se pudo obtener la release de MusicBrainz"
    except Exception as e:  # noqa: BLE001
        note = f"Error consultando MusicBrainz: {type(e).__name__}: {e}"
        cands = cands or []
    return organizer.build_plan(root, d, paths, cands or [], release, note)


def do_plan(body: Dict[str, Any]) -> Dict[str, Any]:
    need_scan()
    dirs = body.get("dirs", [])

    def run(job: jobs.Job) -> List[Dict[str, Any]]:
        out = []
        for i, d in enumerate(dirs):
            if job.cancelled:
                break
            job.progress(i, len(dirs), d or "(raíz)")
            plan = _plan_dir(d)
            STATE["plans"][d] = plan
            out.append(plan)
        job.progress(len(dirs), len(dirs))
        return out
    return jobs.start("plan", run).to_dict()


def do_replan(body: Dict[str, Any]) -> Dict[str, Any]:
    d, mbid = body["dir"], body.get("mbid", "")
    old = STATE["plans"].get(d, {})
    plan = _plan_dir(d, mbid, old.get("candidates"))
    STATE["plans"][d] = plan
    return plan


def do_apply(body: Dict[str, Any]) -> Dict[str, Any]:
    need_scan()
    dirs = body.get("dirs", [])
    opts = (bool(body.get("reorganize")), bool(body.get("tags", True)), bool(body.get("rename", True)))

    def run(job: jobs.Job) -> List[Dict[str, Any]]:
        out = []
        for i, d in enumerate(dirs):
            if job.cancelled:
                break
            job.progress(i, len(dirs), d or "(raíz)")
            plan = STATE["plans"].get(d)
            if plan:
                out.append(organizer.apply_plan(STATE["root"], plan, *opts))
        job.progress(len(dirs), len(dirs))
        STATE["scan"] = None  # obliga a reescanear
        return out
    return jobs.start("apply", run).to_dict()


def view_library() -> Dict[str, Any]:
    scan = need_scan()
    return {"root": STATE["root"], "stats": scan["stats"], "tree": scanner.library_tree(scan["tracks"])}


def view_covers() -> Dict[str, Any]:
    scan = need_scan()
    albums = covers.album_dirs(scan)
    return {"albums": albums, "missing": sum(1 for a in albums if not a["cover"])}


POST: Dict[str, Any] = {
    "/api/scan": do_scan, "/api/delete": do_delete, "/api/covers/search": do_cover_search,
    "/api/covers/save": do_cover_save, "/api/organize/plan": do_plan, "/api/organize/replan": do_replan,
    "/api/organize/apply": do_apply,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "NaviMusic"

    def log_message(self, *a: Any) -> None:  # silencio
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _host_ok(self) -> bool:  # frena DNS-rebinding
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _authed(self, q: Dict[str, List[str]]) -> bool:
        tok = self.headers.get("X-Token") or (q.get("t") or [""])[0]
        return secrets.compare_digest(tok, TOKEN)

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
                html = f.read().replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if not u.path.startswith("/api/") or not self._authed(q):
            return self._send(404 if not u.path.startswith("/api/") else 403, b"{}")
        try:
            if u.path == "/api/fs":
                return self._json(200, fs_list((q.get("path") or [""])[0]))
            if u.path == "/api/state":
                return self._json(200, {"root": STATE["root"], "scanned": bool(STATE["scan"]),
                                        "stats": (STATE["scan"] or {}).get("stats"), "settings": SETTINGS,
                                        "version": __version__})
            if u.path == "/api/job":
                j = jobs.JOBS.get((q.get("id") or [""])[0])
                return self._json(200, j.to_dict() if j else {"status": "error", "error": "Tarea desconocida"})
            if u.path == "/api/library":
                return self._json(200, view_library())
            if u.path == "/api/playlists":
                return self._json(200, {"items": need_scan()["playlists"]})
            if u.path == "/api/extras":
                return self._json(200, {"items": need_scan()["extras"]})
            if u.path == "/api/covers":
                return self._json(200, view_covers())
            if u.path == "/api/covers/preview":
                entry = covers.CACHE.get((q.get("dir") or [""])[0])
                if not entry:
                    return self._send(404, b"", "text/plain")
                return self._send(200, entry[0], entry[1])
            if u.path == "/api/covers/current":
                d = (q.get("dir") or [""])[0]
                name = need_scan()["covers"].get(d)
                if not name:
                    return self._send(404, b"", "text/plain")
                with open(safe_path(f"{d}/{name}" if d else name), "rb") as f:
                    data = f.read()
                return self._send(200, data, covers.sniff(data)[1])
        except ApiError as e:
            return self._json(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self._json(404, {"error": "No encontrado"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok() or not self._authed({}):
            return self._json(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            path = urlparse(self.path).path
            if path == "/api/cancel":
                jobs.cancel(body.get("id", ""))
                return self._json(200, {})
            if path == "/api/settings":
                for k in ("contact", "trash"):
                    if k in body:
                        SETTINGS[k] = body[k]
                save_settings()
                return self._json(200, SETTINGS)
            fn = POST.get(path)
            if not fn:
                return self._json(404, {"error": "No encontrado"})
            self._json(200, fn(body))
        except ApiError as e:
            self._json(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main(argv: List[str]) -> None:
    load_settings()
    port = int(os.environ.get("NAVIMUSIC_PORT", "8765"))
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"NaviMusic en {url}  (Ctrl+C para salir)")
    if "--no-browser" not in argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAdiós")
        sys.exit(0)


def console_main() -> None:
    main(sys.argv[1:])
