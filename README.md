# NaviMusic

[Español](README.es.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A music-library organiser made for [Navidrome](https://www.navidrome.org/), with
[MusicBrainz](https://musicbrainz.org/) as its data source. It is a Python program with a local web interface that
works the same on **macOS, Linux and Windows**. Your files never leave your machine: only MusicBrainz and the
Cover Art Archive are queried.

- Author: **Miguel González Oreiro** · License: [MIT](LICENSE) · Version: 1.1.0 ([changelog](CHANGELOG.md))

## Install

Pick whichever suits you. In all of them, open `http://127.0.0.1:8765` in your browser: press **Choose folder…**,
browse to your music and scan. The **? Help** button in the interface explains each tab.

### 1. Executable (no Python needed), recommended

Download the file for your system from the [latest Release](https://github.com/mgoreiro/navimusic/releases/latest):

| System | File |
|---|---|
| macOS Apple Silicon (M1/M2/M3/M4) | `navimusic-vX.Y.Z-macos-arm64.tar.gz` |
| macOS Intel | `navimusic-vX.Y.Z-macos-x64.tar.gz` |
| Windows 10/11 | `navimusic-vX.Y.Z-windows-x64.zip` |
| Linux x86-64 | `navimusic-vX.Y.Z-linux-x64.tar.gz` |

Unpack it and run `navimusic` (`navimusic.exe` on Windows). The browser will open; to quit, close the terminal window
or press Ctrl+C. The executables are not signed, so your system will warn you the first time:

- **macOS:** if it says it cannot verify the developer, remove the quarantine flag and run it again:
  ```bash
  xattr -d com.apple.quarantine navimusic && ./navimusic
  ```
- **Windows:** in the SmartScreen warning press **More info → Run anyway**.
- **Linux:** `chmod +x navimusic && ./navimusic`.

Each Release includes `SHA256SUMS.txt` to verify the download.

### 2. With Python (pipx)

Needs Python 3.9 or later and [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/mgoreiro/navimusic.git
navimusic
```

Upgrade: `pipx upgrade navimusic`. Uninstall: `pipx uninstall navimusic`.

### 3. From source

```bash
git clone https://github.com/mgoreiro/navimusic.git && cd navimusic
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m navimusic
```

### Options

| Option | Effect |
|---|---|
| `--no-browser` | Do not open the browser automatically |
| `NAVIMUSIC_PORT=9000` | Change the port (if it is busy, a free one is used) |

## Features

| Tab | What it does |
|---|---|
| **A · Library** | Artist → Album → tracks tree, with a filter by artist, album or title |
| **B · Playlists** | Finds `.m3u`, `.m3u8`, `.pls`, `.wpl`, `.zpl`, `.xspf`, `.asx`… and lets you delete them |
| **C · Covers** | Detects albums without a `cover.*`; searches MusicBrainz + Cover Art Archive (or extracts the embedded one); preview and saves `cover.jpg` |
| **D · Leftovers** | Lists `.nfo`, `.log`, `.sfv`, `Thumbs.db`, `.DS_Store`, `._*`, empty files and empty folders, with checkboxes to delete |
| **E · Tags and names** | Proposes tags and names following Navidrome's recommendations, with a comparison first and per-album apply |

### E · Normalisation following Navidrome

Based on Navidrome's [tagging guide](https://www.navidrome.org/docs/usage/library/tagging/).

Tags written: `title`, `artist`, `album`, `albumartist`, `tracknumber`; `discnumber` only for multi-disc; `date`;
`compilation=1` when the album artist is "Various Artists"; multi-value `ARTISTS` and `ALBUMARTISTS` when there are
several artists; and MBIDs (`musicbrainz_albumid`, `trackid`, `artistid`, `albumartistid`, `releasegroupid`).

Names: `NN - Title.ext` (`D-NN - Title.ext` for multi-disc); optionally `Artist/Album/`, also moving covers and
loose files and removing empty folders.

How it decides: it looks up the release by the MBID in the tags or by artist + album, prefers the one with the same
number of tracks, and matches files to tracks by title (similarity) and number. Albums with ≥ 80 % of tracks matched
are preselected; if there is no reliable match it only does basic cleanup (spaces, title and track number from the file
name, `albumartist`). You can change the chosen release in a drop-down.

## Formats

Tag read and write: MP3 (ID3v2.4), FLAC, OGG Vorbis, Opus, M4A/MP4.
Read only: WMA, WAV, AIFF, APE, WavPack, Musepack, DSF/DFF.

## Security and privacy

- The server listens only on `127.0.0.1`, requires a per-session token and validates the `Host` header.
- Every path is checked against the chosen folder; nothing outside it can be touched.
- Nothing is modified without review and confirmation. Deletions go to the trash unless you turn that off in Settings.
- Every change made in E is logged in `~/.navimusic/changes.jsonl`; settings are in `~/.navimusic/settings.json`.
- Only artist/album names and MBIDs are sent to MusicBrainz. It respects 1 request per second and identifies itself with a
  User-Agent that you can complete with your contact in Settings.
- **Back up before writing tags in bulk.**

## Architecture

```
navimusic/
  server.py       HTTP server (stdlib) + JSON API + tasks
  scanner.py      walking, tag reading (cached) and file classification
  tags.py         multi-format read/write with mutagen, embedded covers
  musicbrainz.py  MusicBrainz / Cover Art Archive client with rate limiting
  covers.py       cover search and saving
  organizer.py    change plan (tags + names) and its application
  jobs.py         background tasks with progress and cancellation
  static/index.html  interface (HTML + JS, no dependencies)
```

API (all with an `X-Token` header): `GET /api/fs|state|job|library|playlists|extras|covers`,
`POST /api/scan|delete|covers/search|covers/save|organize/plan|organize/replan|organize/apply|cancel|settings`.

## Building the executables

They are built by the [`release.yml`](.github/workflows/release.yml) action when a `vX.Y.Z` tag is pushed:
it compiles with PyInstaller on macOS (arm64 and Intel), Linux and Windows, checks that each binary starts and serves
the interface, and publishes the packages and `SHA256SUMS.txt` in the Release. To publish a new version:

```bash
# update the version in navimusic/__init__.py, pyproject.toml and CHANGELOG.md; commit and push
git tag -a v1.1.0 -m "NaviMusic 1.1.0" && git push origin v1.1.0
```

To build one by hand on your machine (PyInstaller does not cross-compile):

```bash
pip install pyinstaller
pyinstaller --onefile --name navimusic --add-data "navimusic/static:navimusic/static" --collect-submodules send2trash run.py
# Windows: --add-data "navimusic\static;navimusic\static"
```

## Limitations

- WMA, WAV and AIFF do not support tag writing.
- Special editions (deluxe, reissues) may be picked wrongly automatically: check the release drop-down.
- It does not detect audio duplicates, and it does not recompress or embed covers.
- The interface is in Spanish for now.

## License

[MIT](LICENSE) © 2026 mgoreiro
