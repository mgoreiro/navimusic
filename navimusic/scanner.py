"""Escaneo de la biblioteca: pistas, listas de reproducción, carátulas y ficheros sobrantes."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from . import tags
from .jobs import Job

PLAYLIST_EXTS = {".m3u", ".m3u8", ".pls", ".wpl", ".zpl", ".xspf", ".asx", ".mpcpl", ".vlc"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
COVER_NAMES = {"cover", "folder", "front", "albumart", "album", "albumartsmall", "thumb"}
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".localized", "ehthumbs.db", ".directory",
              "albumartsmall.jpg", ".nomedia"}
JUNK_EXTS = {
    ".nfo": "Información de release (.nfo)", ".txt": "Fichero de texto", ".url": "Acceso directo web",
    ".log": "Log de ripeo", ".sfv": "Checksum SFV", ".md5": "Checksum MD5", ".sha1": "Checksum SHA1",
    ".ffp": "Checksum FFP", ".accurip": "Informe AccurateRip", ".st5": "Checksum", ".db": "Base de datos de miniaturas",
    ".ini": "Fichero de configuración", ".tmp": "Temporal", ".torrent": "Torrent", ".html": "Página web",
    ".htm": "Página web", ".lnk": "Acceso directo", ".par2": "Paridad PAR2", ".diz": "File_id.diz",
    ".bak": "Copia de seguridad", ".part": "Descarga incompleta", ".crdownload": "Descarga incompleta",
}


def human_reason(name: str, ext: str) -> Tuple[str, bool]:
    """(motivo, sugerido) para un fichero que no es audio/lista/carátula."""
    low = name.lower()
    if low in JUNK_NAMES:
        return "Fichero del sistema", True
    if name.startswith("._"):
        return "Metadatos AppleDouble (macOS)", True
    if name.endswith("~"):
        return "Temporal", True
    if ext in JUNK_EXTS:
        return JUNK_EXTS[ext], True
    if ext == ".cue":
        return "Hoja CUE (útil solo si hay un único fichero de álbum)", False
    if ext in IMAGE_EXTS:
        return "Imagen que no es carátula estándar", False
    return "Tipo de fichero desconocido", False


def is_cover_name(name: str) -> bool:
    stem, ext = os.path.splitext(name.lower())
    return ext in IMAGE_EXTS and stem in COVER_NAMES


# Caché de tags por (ruta, mtime, tamaño) para que reescanear sea rápido.
_cache: Dict[Tuple[str, float, int], tags.AudioInfo] = {}


def _read_cached(path: str) -> tags.AudioInfo:
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except OSError:
        return tags.AudioInfo(path=path, ext=os.path.splitext(path)[1].lower(), error="No accesible")
    info = _cache.get(key)
    if info is None:
        info = tags.read(path)
        _cache[key] = info
    return info


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def scan(root: str, job: Optional[Job] = None) -> Dict[str, Any]:
    root = os.path.abspath(root)
    audio_paths: List[str] = []
    playlists: List[Dict[str, Any]] = []
    extras: List[Dict[str, Any]] = []
    covers: Dict[str, str] = {}          # dir relativo -> nombre de carátula
    dirs_seen: Dict[str, int] = {}       # dir -> nº de entradas (para detectar vacías)

    if job:
        job.progress(0, 0, "Recorriendo carpetas…")
    for dirpath, dirnames, filenames in os.walk(root):
        if job and job.cancelled:
            return {}
        dirnames.sort()
        d = rel(root, dirpath) if dirpath != root else ""
        dirs_seen[d] = len(dirnames) + len(filenames)
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            r = rel(root, full)
            if ext in tags.AUDIO_EXTS and not fn.startswith("._"):
                audio_paths.append(full)
            elif ext in PLAYLIST_EXTS and not fn.startswith("._"):
                playlists.append({"path": r, "size": size, "kind": "playlist",
                                  "reason": f"Lista de reproducción ({ext})", "suggested": True})
            elif is_cover_name(fn):
                covers.setdefault(d, fn)
            else:
                reason, suggested = human_reason(fn, ext)
                if size == 0:
                    reason, suggested = "Fichero vacío (0 bytes)", True
                extras.append({"path": r, "size": size, "kind": "file", "reason": reason,
                               "suggested": suggested})

    # Directorios vacíos (sin ficheros ni subcarpetas)
    for d, n in dirs_seen.items():
        if d and n == 0:
            extras.append({"path": d, "size": 0, "kind": "dir", "reason": "Carpeta vacía", "suggested": True})

    total = len(audio_paths)
    infos: List[tags.AudioInfo] = []
    if job:
        job.progress(0, total, f"Leyendo tags de {total} ficheros…")
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, info in enumerate(ex.map(_read_cached, audio_paths), 1):
            infos.append(info)
            if job:
                if job.cancelled:
                    return {}
                if i % 25 == 0 or i == total:
                    job.progress(i, total)

    tracks: List[Dict[str, Any]] = []
    for info in infos:
        if info.error:
            extras.append({"path": rel(root, info.path), "size": _size(info.path), "kind": "file",
                           "reason": f"Audio ilegible o corrupto ({info.error})", "suggested": False})
            continue
        trk, trk_total = tags.parse_num(info.first("tracknumber"))
        disc, disc_total = tags.parse_num(info.first("discnumber"))
        tracks.append({
            "path": rel(root, info.path),
            "dir": rel(root, os.path.dirname(info.path)) if os.path.dirname(info.path) != root else "",
            "ext": info.ext, "size": _size(info.path), "duration": round(info.duration, 1),
            "bitrate": info.bitrate, "writable": info.writable,
            "title": info.first("title"), "artist": info.first("artist"),
            "albumartist": info.first("albumartist"), "album": info.first("album"),
            "track": trk, "tracktotal": trk_total, "disc": disc, "disctotal": disc_total,
            "date": info.first("date"), "mbid": info.first("musicbrainz_albumid"),
            "rgid": info.first("musicbrainz_releasegroupid"),
        })

    return {
        "root": root,
        "tracks": tracks,
        "playlists": playlists,
        "extras": extras,
        "covers": covers,
        "stats": {"tracks": len(tracks), "playlists": len(playlists), "extras": len(extras),
                  "duration": round(sum(t["duration"] for t in tracks)),
                  "size": sum(t["size"] for t in tracks)},
    }


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def library_tree(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrupa por artista de álbum -> álbum (carpeta) para el listado A."""
    artists: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for t in tracks:
        artist = t["albumartist"] or t["artist"] or "(Sin artista)"
        album = t["album"] or "(Sin álbum)"
        a = artists.setdefault(artist, {})
        key = f'{album}\u0000{t["dir"]}'
        al = a.setdefault(key, {"album": album, "dir": t["dir"], "year": "", "tracks": []})
        if not al["year"] and t["date"]:
            al["year"] = t["date"][:4]
        al["tracks"].append(t)
    out = []
    for artist in sorted(artists, key=str.casefold):
        albums = sorted(artists[artist].values(), key=lambda x: (x["year"] or "9999", x["album"].casefold()))
        for al in albums:
            al["tracks"].sort(key=lambda x: (x["disc"], x["track"], x["path"]))
        out.append({"artist": artist, "albums": albums,
                    "count": sum(len(al["tracks"]) for al in albums)})
    return out
