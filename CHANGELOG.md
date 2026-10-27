# Changelog

## 1.0.1
- Distribución: ejecutables para macOS (arm64 e Intel), Linux y Windows publicados automáticamente en cada Release
  (GitHub Actions + PyInstaller, con `SHA256SUMS.txt`), e instalación con `pipx`.
- README: instrucciones de instalación completas con URL del repositorio.
- Interfaz: mensajes claros cuando no hay conexión con el servidor o se abre el HTML como fichero.
- La versión mostrada en el pie y en la ayuda se toma del servidor.

## 1.0.0
Primera versión.
- Interfaz web local multiplataforma (macOS, Linux, Windows) con selector de carpetas propio.
- A · listado por artista/álbum · B · borrado de listas de reproducción · C · carátulas desde Cover Art Archive o incrustadas
  · D · detección y borrado de ficheros sobrantes · E · normalización de tags y nombres según Navidrome con MusicBrainz.
- Ayuda integrada, papelera por defecto, registro de cambios en `~/.navimusic/changes.jsonl`.
