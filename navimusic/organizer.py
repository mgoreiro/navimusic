"""Normalización de tags y nombres según las recomendaciones de Navidrome (E).

Navidrome exige/recomienda: title, artist, album, albumartist y tracknumber en
todas las pistas; discnumber solo en multi-disco; date; compilation=1 con
albumartist "Various Artists"; ARTISTS/ALBUMARTISTS multivalor; MBIDs.
Estructura de ficheros sugerida: Artista/Álbum/NN - Título.ext
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from . import musicbrainz as mb
from . import tags

PLACEHOLDERS = {"unknown artist", "unknown album", "unknown", "desconocido", "track", "various", "va"}
_ILLEGAL = re.compile(r'[<>"|?*\x00-\x1f]')


def clean(s: str) -> str:
    return " ".join((s or "").split())


def sanitize(name: str, fallback: str = "_") -> str:
    name = clean(name).replace("/", "-").replace("\\", "-").replace(":", " -")
    name = _ILLEGAL.sub("", name)
    name = clean(name).strip(" .")
    return name[:120].strip(" .") or fallback


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def _title_from_filename(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return clean(re.sub(r"^\s*(\d{1,3}\s*[-._)]+\s*|\d{1,3}\s+)", "", stem).replace("_", " "))


def _num_from_filename(path: str) -> int:
    m = re.match(r"\s*(\d{1,3})(?=[\s._)-]|$)", os.path.basename(path))
    return int(m.group(1)) if m else 0


# --- emparejado con MusicBrainz ---------------------------------------------

def _mb_tracks(release: Dict[str, Any]) -> List[Dict[str, Any]]:
    media = release.get("media", [])
    out = []
    for m in media:
        for t in m.get("tracks", []):
            rec = t.get("recording", {})
            out.append({
                "disc": m.get("position", 1), "pos": t.get("position", 0), "title": t.get("title") or rec.get("title", ""),
                "recording": rec.get("id", ""), "credit": t.get("artist-credit") or rec.get("artist-credit") or [],
                "multi": len(media) > 1,
            })
    return out


def match_tracks(infos: List[tags.AudioInfo], mbt: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    pairs = []
    for i, info in enumerate(infos):
        title = info.first("title") or _title_from_filename(info.path)
        num = tags.parse_num(info.first("tracknumber"))[0] or _num_from_filename(info.path)
        disc = tags.parse_num(info.first("discnumber"))[0]
        for j, t in enumerate(mbt):
            sim = difflib.SequenceMatcher(None, _norm(title), _norm(t["title"])).ratio()
            same_num = num == t["pos"] and (not t["multi"] or not disc or disc == t["disc"])
            score = 0.7 * sim + (0.3 if same_num else 0)
            if score >= 0.5:
                pairs.append((score, i, j))
    pairs.sort(reverse=True)
    used_i, used_j, res = set(), set(), {}
    for _, i, j in pairs:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            res[i] = mbt[j]
    return res


# --- tags deseados ------------------------------------------------------------

def _credit_names(credit: List[Dict[str, Any]]) -> List[str]:
    return [(c.get("name") or c["artist"]["name"]) for c in credit]


def _credit_ids(credit: List[Dict[str, Any]]) -> List[str]:
    return [c["artist"]["id"] for c in credit]


def _differs(key: str, cur: List[str], new: Optional[List[str]]) -> bool:
    if new is None:
        return False
    if key in ("tracknumber", "discnumber"):
        return not cur or tags.parse_num(cur[0])[0] != tags.parse_num(new[0])[0]
    if key == "date":
        return not cur or not cur[0].strip().startswith(new[0])
    return list(cur) != list(new)


def desired_for_file(info: tags.AudioInfo, mbt: Optional[Dict[str, Any]], release: Optional[Dict[str, Any]],
                     album_ctx: Dict[str, Any]) -> Dict[str, List[str]]:
    d: Dict[str, List[str]] = {}
    cur = info.tags

    def setv(k: str, v: Any) -> None:
        if v is None or v == "" or v == []:
            return
        d[k] = v if isinstance(v, list) else [str(v)]

    if release and mbt:
        rc = release.get("artist-credit", [])
        setv("album", release.get("title"))
        setv("albumartist", mb.credit_string(rc))
        if len(rc) > 1:
            setv("albumartists", _credit_names(rc))
        setv("title", mbt["title"])
        setv("artist", mb.credit_string(mbt["credit"]))
        if len(mbt["credit"]) > 1:
            setv("artists", _credit_names(mbt["credit"]))
        setv("tracknumber", mbt["pos"])
        if mbt["multi"]:
            setv("discnumber", mbt["disc"])
        setv("date", release.get("date"))
        setv("musicbrainz_albumid", release.get("id"))
        setv("musicbrainz_releasegroupid", (release.get("release-group") or {}).get("id"))
        setv("musicbrainz_trackid", mbt["recording"])
        setv("musicbrainz_artistid", _credit_ids(mbt["credit"]))
        setv("musicbrainz_albumartistid", _credit_ids(rc))
        if rc and rc[0]["artist"]["id"] == mb.VARIOUS_ARTISTS_ID:
            setv("compilation", "1")
    else:
        # Limpieza offline: solo rellena lo imprescindible y recorta espacios.
        for k in ("title", "artist", "album", "albumartist"):
            v = cur.get(k)
            if v and [clean(x) for x in v] != v:
                d[k] = [clean(x) for x in v]
        if not cur.get("title"):
            setv("title", _title_from_filename(info.path))
        if not cur.get("tracknumber"):
            n = _num_from_filename(info.path)
            if n:
                setv("tracknumber", n)
        if not cur.get("albumartist") and album_ctx.get("albumartist"):
            setv("albumartist", album_ctx["albumartist"])
            if album_ctx.get("compilation"):
                setv("compilation", "1")
        if not cur.get("album") and album_ctx.get("album"):
            setv("album", album_ctx["album"])
    return d


def _fmt_new_path(root_dir: str, info: tags.AudioInfo, final: Dict[str, List[str]], width: int,
                  multi_disc: bool) -> str:
    def g(k: str) -> str:
        return (final.get(k) or [""])[0]
    title = sanitize(g("title") or _title_from_filename(info.path), "Sin título")
    num = tags.parse_num(g("tracknumber"))[0]
    disc = tags.parse_num(g("discnumber"))[0]
    prefix = ""
    if num:
        prefix = f"{disc}-" if (multi_disc and disc) else ""
        prefix += f"{num:0{width}d} - "
    return f"{prefix}{title}{info.ext}"


def build_plan(root: str, d: str, track_paths: List[str], cands: List[Dict[str, Any]],
               release: Optional[Dict[str, Any]], note: str = "") -> Dict[str, Any]:
    infos = [tags.read(os.path.join(root, *p.split("/"))) for p in track_paths]
    infos = [i for i in infos if not i.error]
    mbt = _mb_tracks(release) if release else []
    matches = match_tracks(infos, mbt) if release else {}

    artists = {i.first("artist") for i in infos if i.first("artist")}
    album_ctx: Dict[str, Any] = {"album": next((i.first("album") for i in infos if i.first("album")), "")}
    if len(artists) == 1:
        album_ctx["albumartist"] = next(iter(artists))
    elif len(artists) > 1:
        album_ctx["albumartist"], album_ctx["compilation"] = "Various Artists", True

    desired = []
    finals = []
    for i, info in enumerate(infos):
        want = desired_for_file(info, matches.get(i), release if i in matches else None, album_ctx)
        changes = {k: v for k, v in want.items() if _differs(k, info.tags.get(k, []), v)}
        desired.append(changes)
        final = dict(info.tags)
        final.update(want)
        finals.append(final)

    multi_disc = (len(release.get("media", [])) > 1) if release else \
        max([tags.parse_num(i.first("discnumber"))[0] for i in infos] + [0]) > 1
    maxnum = max([tags.parse_num((f.get("tracknumber") or [""])[0])[0] for f in finals] + [0])
    width = max(2, len(str(maxnum)))

    # Carpeta destino "Artista/Álbum" para la opción de reorganizar
    f0 = finals[0] if finals else {}
    aa = (f0.get("albumartist") or f0.get("artist") or ["Unknown Artist"])[0]
    al = (f0.get("album") or ["Unknown Album"])[0]
    reorg_dir = f"{sanitize(aa, 'Unknown Artist')}/{sanitize(al, 'Unknown Album')}"

    tracks_out = []
    used_inplace, used_reorg = set(), set()
    for info, changes, final in zip(infos, desired, finals):
        fname = _fmt_new_path(d, info, final, width, multi_disc)
        cur_rel = os.path.relpath(info.path, root).replace(os.sep, "/")
        inplace = f"{d}/{fname}" if d else fname
        reorg = f"{reorg_dir}/{fname}"
        # evita colisiones dentro del mismo álbum: conserva el nombre actual
        if inplace.lower() in used_inplace:
            inplace = cur_rel
        if reorg.lower() in used_reorg:
            reorg = f"{reorg_dir}/{os.path.basename(cur_rel)}"
        used_inplace.add(inplace.lower())
        used_reorg.add(reorg.lower())
        tracks_out.append({
            "path": cur_rel, "new_inplace": inplace, "new_reorg": reorg,
            "changes": {k: [info.tags.get(k, []), v] for k, v in changes.items()},
            "matched": bool(release) and any(info is infos[i] for i in matches),
            "writable": info.writable,
        })

    coverage = (len(matches) / len(infos)) if (infos and release) else 0.0
    if release and not matches:
        note = note or "La release elegida no coincide con ninguna pista: solo limpieza básica"
    return {
        "dir": d, "count": len(infos), "artist": aa, "album": al,
        "mode": "musicbrainz" if matches else "offline",
        "release": ({"id": release["id"], "title": release.get("title", ""),
                     "artist": mb.credit_string(release.get("artist-credit", [])),
                     "date": release.get("date", "")} if release else None),
        "candidates": cands, "coverage": round(coverage, 2), "note": note, "tracks": tracks_out,
        "n_tag_changes": sum(1 for t in tracks_out if t["changes"]),
        "n_renames": sum(1 for t in tracks_out if t["new_inplace"] != t["path"]),
        "n_moves": sum(1 for t in tracks_out if t["new_reorg"] != t["path"]),
    }


# --- aplicar -------------------------------------------------------------------

def _safe_join(root: str, rel: str) -> str:
    p = os.path.abspath(os.path.join(root, *rel.split("/")))
    if os.path.commonpath([root, p]) != root:
        raise ValueError(f"Ruta fuera de la biblioteca: {rel}")
    return p


def _move(src: str, dst: str) -> None:
    if src == dst:
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        if os.path.samefile(src, dst):  # cambio solo de mayúsculas en FS insensible
            tmp = dst + f".navimusic-{os.getpid()}"
            os.replace(src, tmp)
            os.replace(tmp, dst)
            return
        raise FileExistsError(f"Ya existe: {os.path.basename(dst)}")
    shutil.move(src, dst)


def _log(entry: Dict[str, Any]) -> None:
    d = os.path.join(os.path.expanduser("~"), ".navimusic")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "changes.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def apply_plan(root: str, plan: Dict[str, Any], reorganize: bool, do_tags: bool, do_rename: bool) -> Dict[str, Any]:
    done, errors = 0, []
    moved_dirs: Dict[str, str] = {}
    for t in plan["tracks"]:
        try:
            src = _safe_join(root, t["path"])
            if do_tags and t["changes"]:
                if not t["writable"]:
                    raise PermissionError("Formato de solo lectura para tags")
                tags.write(src, {k: v[1] for k, v in t["changes"].items()})
            dst_rel = (t["new_reorg"] if reorganize else t["new_inplace"]) if do_rename else t["path"]
            dst = _safe_join(root, dst_rel)
            if dst != src:
                _move(src, dst)
                moved_dirs.setdefault(os.path.dirname(src), os.path.dirname(dst))
            _log({"ts": int(time.time()), "from": t["path"], "to": dst_rel, "tags": t["changes"]})
            done += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"path": t["path"], "error": f"{type(e).__name__}: {e}"})

    # Si cambió de carpeta, arrastra carátulas y demás ficheros sueltos y limpia las vacías.
    for old, new in moved_dirs.items():
        if old == new or not os.path.isdir(old):
            continue
        for fn in os.listdir(old):
            p = os.path.join(old, fn)
            if os.path.isfile(p) and os.path.splitext(fn)[1].lower() not in tags.AUDIO_EXTS:
                try:
                    _move(p, os.path.join(new, fn))
                except Exception:  # noqa: BLE001
                    pass
        cur = old
        while cur != root and os.path.isdir(cur) and not os.listdir(cur):
            os.rmdir(cur)
            cur = os.path.dirname(cur)
    return {"dir": plan["dir"], "done": done, "errors": errors}
