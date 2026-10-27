# NaviMusic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Organizador de bibliotecas de audio pensado para [Navidrome](https://www.navidrome.org/), con
[MusicBrainz](https://musicbrainz.org/) como fuente de datos. Es un programa Python con interfaz web local que
funciona igual en **macOS, Linux y Windows**. Tus ficheros no salen de tu equipo: solo se consultan MusicBrainz y
Cover Art Archive.

- Autor: **mgoreiro** · Licencia: [MIT](LICENSE) · Versión: 1.0.0 ([changelog](CHANGELOG.md))

## Instalación y uso

Requiere Python 3.9 o superior.

```bash
git clone <url-del-repositorio> && cd <carpeta>
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m navimusic
```

También puedes instalarlo con `pip install .`, que crea el comando `navimusic`.
Se abre `http://127.0.0.1:8765` en tu navegador. Pulsa **Elegir carpeta…**, navega a tu música y escanea.
El botón **? Ayuda** de la interfaz explica cada pestaña.

| Opción | Efecto |
|---|---|
| `--no-browser` | No abre el navegador automáticamente |
| `NAVIMUSIC_PORT=9000` | Cambia el puerto (si está ocupado usa uno libre) |

## Funciones

| Pestaña | Qué hace |
|---|---|
| **A · Biblioteca** | Árbol Artista → Álbum → pistas, con filtro por artista, álbum o título |
| **B · Listas** | Localiza `.m3u`, `.m3u8`, `.pls`, `.wpl`, `.zpl`, `.xspf`, `.asx`… y permite borrarlas |
| **C · Carátulas** | Detecta álbumes sin `cover.*`; busca en MusicBrainz + Cover Art Archive (o extrae la incrustada); vista previa y guarda `cover.jpg` |
| **D · Sobrantes** | Lista `.nfo`, `.log`, `.sfv`, `Thumbs.db`, `.DS_Store`, `._*`, ficheros vacíos y carpetas vacías, con casillas para borrar |
| **E · Tags y nombres** | Propone tags y nombres según las recomendaciones de Navidrome, con comparación previa y aplicación por álbum |

### E · Normalización según Navidrome

Basada en la [guía de etiquetado de Navidrome](https://www.navidrome.org/docs/usage/library/tagging/).

Tags escritos: `title`, `artist`, `album`, `albumartist`, `tracknumber`; `discnumber` solo en multi-disco; `date`;
`compilation=1` cuando el artista del álbum es «Various Artists»; `ARTISTS` y `ALBUMARTISTS` multivalor cuando hay
varios artistas; y MBIDs (`musicbrainz_albumid`, `trackid`, `artistid`, `albumartistid`, `releasegroupid`).

Nombres: `NN - Título.ext` (`D-NN - Título.ext` en multi-disco); opcionalmente `Artista/Álbum/` moviendo también
carátulas y ficheros sueltos y retirando carpetas vacías.

Cómo decide: busca la release por MBID de los tags o por artista+álbum, prefiere la de mismo número de pistas, y
empareja ficheros con pistas por título (similitud) y número. Se preseleccionan los álbumes con ≥ 80 % de pistas
emparejadas; si no hay coincidencia fiable solo hace limpieza básica (espacios, título y nº de pista desde el nombre
de fichero, `albumartist`). Puedes cambiar la release elegida en un desplegable.

## Formatos

Lectura y escritura de tags: MP3 (ID3v2.4), FLAC, OGG Vorbis, Opus, M4A/MP4.
Solo lectura: WMA, WAV, AIFF, APE, WavPack, Musepack, DSF/DFF.

## Seguridad y privacidad

- El servidor escucha solo en `127.0.0.1`, exige un token por sesión y valida la cabecera `Host`.
- Cualquier ruta se comprueba contra la carpeta elegida; no se puede operar fuera de ella.
- Nada se modifica sin revisión y confirmación. Los borrados van a la papelera salvo que se desactive en Ajustes.
- Cada cambio de E se registra en `~/.navimusic/changes.jsonl`; los ajustes en `~/.navimusic/settings.json`.
- A MusicBrainz solo se envían nombres de artista/álbum y MBIDs. Se respeta 1 petición/s y se identifica con un
  User-Agent que puedes completar con tu contacto en Ajustes.
- **Haz copia de seguridad antes de escribir tags en masa.**

## Arquitectura

```
navimusic/
  server.py       servidor HTTP (stdlib) + API JSON + tareas
  scanner.py      recorrido, lectura de tags (con caché) y clasificación de ficheros
  tags.py         lectura/escritura multi-formato con mutagen, carátulas incrustadas
  musicbrainz.py  cliente MusicBrainz / Cover Art Archive con límite de ritmo
  covers.py       búsqueda y guardado de carátulas
  organizer.py    plan de cambios (tags + nombres) y su aplicación
  jobs.py         tareas en segundo plano con progreso y cancelación
  static/index.html  interfaz (HTML + JS, sin dependencias)
```

API (todas con cabecera `X-Token`): `GET /api/fs|state|job|library|playlists|extras|covers`,
`POST /api/scan|delete|covers/search|covers/save|organize/plan|organize/replan|organize/apply|cancel|settings`.

## Binario único (opcional)

```bash
pip install pyinstaller
pyinstaller --onefile --name NaviMusic --add-data "navimusic/static:navimusic/static" run.py
# Windows: --add-data "navimusic\static;navimusic\static"
```

PyInstaller no hace compilación cruzada: ejecútalo en cada sistema operativo.

## Limitaciones

- WMA, WAV y AIFF no admiten escritura de tags.
- Las ediciones especiales (deluxe, reediciones) pueden elegirse mal automáticamente: revisa el desplegable de release.
- No detecta duplicados de audio ni recomprime ni incrusta carátulas.

## Licencia

[MIT](LICENSE) © 2026 mgoreiro
