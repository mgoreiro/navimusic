"""Cliente mínimo de MusicBrainz + Cover Art Archive (solo stdlib).

Respeta el límite de 1 petición/segundo y exige un User-Agent identificable.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

API = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
VARIOUS_ARTISTS_ID = "89ad4ac3-39f7-470e-963a-56509c546377"

_lock = threading.Lock()
_last = 0.0
user_agent = "NaviMusic/0.1 ( https://github.com/navimusic/navimusic )"


def set_contact(contact: str) -> None:
    global user_agent
    contact = (contact or "").strip()
    user_agent = f"NaviMusic/0.1 ( {contact} )" if contact else \
        "NaviMusic/0.1 ( https://github.com/navimusic/navimusic )"


def _open(url: str, accept: str = "application/json", timeout: int = 30) -> Optional[bytes]:
    """GET con rate-limit global y reintentos. 404 -> None."""
    global _last
    for attempt in range(4):
        with _lock:
            wait = 1.1 - (time.time() - _last)
            if wait > 0:
                time.sleep(wait)
            _last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(20 * 1024 * 1024)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2)
    return None


def _json(path: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    params = dict(params, fmt="json")
    data = _open(f"{API}/{path}?{urllib.parse.urlencode(params)}")
    return json.loads(data) if data else None


def _q(s: str) -> str:
    return s.replace("\\", " ").replace('"', " ").strip()


def credit_string(credit: List[Dict[str, Any]]) -> str:
    return "".join((c.get("name") or c["artist"]["name"]) + (c.get("joinphrase") or "") for c in credit)


def search_releases(artist: str, album: str, limit: int = 8) -> List[Dict[str, Any]]:
    if not album:
        return []
    query = f'release:"{_q(album)}"'
    if artist:
        query += f' AND artist:"{_q(artist)}"'
    data = _json("release", {"query": query, "limit": str(limit)})
    out = []
    for r in (data or {}).get("releases", []):
        out.append({
            "id": r["id"],
            "title": r.get("title", ""),
            "artist": credit_string(r.get("artist-credit", [])),
            "date": r.get("date", ""),
            "country": r.get("country", ""),
            "tracks": sum(m.get("track-count", 0) for m in r.get("media", [])),
            "score": int(r.get("score", 0)),
            "status": r.get("status", ""),
        })
    return out


def get_release(mbid: str) -> Optional[Dict[str, Any]]:
    return _json(f"release/{mbid}", {"inc": "recordings+artist-credits+release-groups"})


def best_candidate(cands: List[Dict[str, Any]], n_tracks: int) -> Optional[Dict[str, Any]]:
    """Prefiere coincidencia de nº de pistas y puntuación alta; desempata por 'Official'."""
    def key(c: Dict[str, Any]):
        return (c["score"] + (15 if n_tracks and c["tracks"] == n_tracks else 0)
                + (3 if c.get("status") == "Official" else 0))
    return max(cands, key=key) if cands else None


def cover_art(release_id: str, release_group_id: str = "") -> Optional[bytes]:
    """Descarga la portada frontal (500 px) de la release o, si no, del release-group."""
    for kind, ident in (("release", release_id), ("release-group", release_group_id)):
        if not ident:
            continue
        try:
            data = _open(f"{CAA}/{kind}/{ident}/front-500", accept="image/*")
        except urllib.error.HTTPError:
            data = None
        if data:
            return data
    return None
