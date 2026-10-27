"""Búsqueda y guardado de carátulas (C)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from . import musicbrainz as mb
from . import tags
from .jobs import Job

# dir relativo -> (bytes, mime, origen, info del match)
CACHE: Dict[str, Tuple[bytes, str, str, Dict[str, Any]]] = {}


def album_dirs(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_dir: Dict[str, List[Dict[str, Any]]] = {}
    for t in scan["tracks"]:
        by_dir.setdefault(t["dir"], []).append(t)
    out = []
    for d, ts in sorted(by_dir.items()):
        ts.sort(key=lambda x: (x["disc"], x["track"], x["path"]))
        artist = next((t["albumartist"] for t in ts if t["albumartist"]), "") or \
            next((t["artist"] for t in ts if t["artist"]), "")
        album = next((t["album"] for t in ts if t["album"]), "")
        out.append({
            "dir": d, "artist": artist, "album": album, "count": len(ts),
            "mbid": next((t["mbid"] for t in ts if t["mbid"]), ""),
            "rgid": next((t["rgid"] for t in ts if t["rgid"]), ""),
            "cover": scan["covers"].get(d, ""),
            "first": ts[0]["path"],
        })
    return out


def sniff(data: bytes) -> Tuple[str, str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    return "jpg", "image/jpeg"


def search(job: Job, root: str, scan: Dict[str, Any], dirs: List[str], use_embedded: bool) -> List[Dict[str, Any]]:
    albums = {a["dir"]: a for a in album_dirs(scan)}
    results = []
    for i, d in enumerate(dirs):
        if job.cancelled:
            break
        a = albums.get(d)
        if not a:
            continue
        label = f'{a["artist"] or "?"} – {a["album"] or d or "(raíz)"}'
        job.progress(i, len(dirs), label)
        res = {"dir": d, "artist": a["artist"], "album": a["album"], "status": "notfound",
               "source": "", "match": ""}
        try:
            data = None
            if use_embedded:
                emb = tags.extract_embedded_art(os.path.join(root, *a["first"].split("/")))
                if emb:
                    data, mime = emb
                    CACHE[d] = (data, mime, "embebida", {})
                    res.update(status="found", source="embebida", match="Incrustada en los tags")
            if data is None:
                mbid, rgid, match = a["mbid"], a["rgid"], ""
                if not mbid:
                    cands = mb.search_releases(a["artist"], a["album"])
                    c = mb.best_candidate(cands, a["count"])
                    if c and c["score"] >= 70:
                        mbid = c["id"]
                        match = f'{c["artist"]} – {c["title"]} ({c["date"][:4] or "?"}) · {c["score"]}%'
                else:
                    match = "MBID en los tags"
                if mbid:
                    data = mb.cover_art(mbid, rgid)
                    if data is None and not rgid:
                        # La release puede no tener portada pero su release-group sí
                        rel = mb.get_release(mbid) or {}
                        rgid = (rel.get("release-group") or {}).get("id", "")
                        data = mb.cover_art("", rgid) if rgid else None
                if data:
                    ext, mime = sniff(data)
                    CACHE[d] = (data, mime, "musicbrainz", {"mbid": mbid})
                    res.update(status="found", source="MusicBrainz / Cover Art Archive", match=match)
                else:
                    res["match"] = match or "Sin coincidencia en MusicBrainz"
        except Exception as e:  # noqa: BLE001
            res.update(status="error", match=f"{type(e).__name__}: {e}")
        results.append(res)
    job.progress(len(dirs), len(dirs))
    return results


def save(root: str, d: str) -> str:
    entry = CACHE.get(d)
    if not entry:
        raise KeyError("No hay carátula en caché para esta carpeta")
    data, _, _, _ = entry
    ext, _ = sniff(data)
    target = os.path.join(root, *d.split("/")) if d else root
    path = os.path.join(target, f"cover.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path
