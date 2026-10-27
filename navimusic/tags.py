"""Lectura y escritura de tags en todos los formatos de audio habituales."""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import mutagen
import mutagen.flac
import mutagen.mp3
import mutagen.mp4
import mutagen.oggopus
import mutagen.oggvorbis
from mutagen._vorbis import VCommentDict
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4Tags

AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".m4b", ".mp4", ".aac", ".ogg", ".oga", ".opus",
    ".wav", ".wma", ".aif", ".aiff", ".ape", ".wv", ".mpc", ".dsf", ".dff",
}

KEYS = [
    "title", "artist", "album", "albumartist", "tracknumber", "discnumber",
    "date", "genre", "compilation", "artists", "albumartists",
    "musicbrainz_albumid", "musicbrainz_trackid", "musicbrainz_artistid",
    "musicbrainz_albumartistid", "musicbrainz_releasegroupid",
]

_MP4_FREEFORM = {
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_trackid": "MusicBrainz Track Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "artists": "ARTISTS",
    "albumartists": "ALBUMARTISTS",
    "compilation": "COMPILATION",
}

# Formatos cuyo tag no es "easy": nombres alternativos para lectura.
_ALT = {
    "title": ["Title", "Title"], "artist": ["Author", "Artist"],
    "album": ["WM/AlbumTitle", "Album"], "albumartist": ["WM/AlbumArtist", "Album Artist"],
    "tracknumber": ["WM/TrackNumber", "Track"], "discnumber": ["WM/PartOfSet", "Disc"],
    "date": ["WM/Year", "Year"], "genre": ["WM/Genre", "Genre"],
}


def _register() -> None:
    EasyID3.RegisterTXXXKey("artists", "ARTISTS")
    EasyID3.RegisterTXXXKey("albumartists", "ALBUMARTISTS")
    for k, name in _MP4_FREEFORM.items():
        EasyMP4Tags.RegisterFreeformKey(k, name)


_register()


@dataclass
class AudioInfo:
    path: str
    ext: str
    tags: Dict[str, List[str]] = field(default_factory=dict)
    duration: float = 0.0
    bitrate: int = 0
    writable: bool = False
    error: Optional[str] = None

    def first(self, key: str) -> str:
        v = self.tags.get(key)
        return str(v[0]).strip() if v else ""


def parse_num(value: str) -> Tuple[int, int]:
    """'3/12' -> (3, 12); '' -> (0, 0)."""
    m = re.match(r"\s*(\d+)\s*(?:/\s*(\d+))?", value or "")
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2) or 0)


def read(path: str) -> AudioInfo:
    ext = os.path.splitext(path)[1].lower()
    info = AudioInfo(path=path, ext=ext)
    try:
        f = mutagen.File(path, easy=True)
    except Exception as e:  # archivo corrupto / formato raro
        info.error = f"{type(e).__name__}: {e}"
        return info
    if f is None:
        info.error = "Formato no reconocido"
        return info
    if f.info is not None:
        info.duration = float(getattr(f.info, "length", 0) or 0)
        info.bitrate = int(getattr(f.info, "bitrate", 0) or 0)
    t = f.tags
    if t is None:
        info.writable = isinstance(f, (mutagen.mp3.MP3, mutagen.flac.FLAC, mutagen.mp4.MP4,
                                       mutagen.oggvorbis.OggVorbis, mutagen.oggopus.OggOpus))
        return info
    easy = isinstance(t, (EasyID3, EasyMP4Tags, VCommentDict))
    info.writable = easy
    for k in KEYS:
        vals = None
        try:
            if easy:
                vals = t.get(k)
            elif k in _ALT:
                for alt in _ALT[k]:
                    for tk in t.keys():
                        if tk.lower() == alt.lower():
                            vals = t[tk]
                            break
                    if vals:
                        break
        except Exception:
            vals = None
        if vals:
            vals = [str(v) for v in (vals if isinstance(vals, (list, tuple)) else [vals])]
            vals = [v for v in vals if v.strip()]
            if vals:
                info.tags[k] = vals
    return info


def write(path: str, changes: Dict[str, Optional[List[str]]]) -> None:
    """Aplica cambios; valor None/[] elimina la clave."""
    f = mutagen.File(path, easy=True)
    if f is None:
        raise ValueError("Formato no reconocido")
    if f.tags is None:
        f.add_tags()
    for k, v in changes.items():
        try:
            if not v:
                if k in f.tags:
                    del f.tags[k]
            else:
                f.tags[k] = v
        except KeyError:
            continue  # clave no soportada por este formato
    f.save()


# --- Carátulas incrustadas -------------------------------------------------

def extract_embedded_art(path: str) -> Optional[Tuple[bytes, str]]:
    """Devuelve (bytes, mime) de la primera imagen incrustada, si la hay."""
    try:
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None:
        return None
    try:
        if isinstance(f, mutagen.mp3.MP3) and f.tags:
            for k in f.tags.keys():
                if k.startswith("APIC"):
                    fr = f.tags[k]
                    return fr.data, fr.mime
        elif isinstance(f, mutagen.flac.FLAC) and f.pictures:
            p = f.pictures[0]
            return p.data, p.mime
        elif isinstance(f, mutagen.mp4.MP4) and f.tags and "covr" in f.tags:
            c = f.tags["covr"][0]
            mime = "image/png" if getattr(c, "imageformat", 13) == 14 else "image/jpeg"
            return bytes(c), mime
        elif f.tags and "metadata_block_picture" in f.tags:
            from mutagen.flac import Picture
            p = Picture(base64.b64decode(f.tags["metadata_block_picture"][0]))
            return p.data, p.mime
    except Exception:
        return None
    return None
