# Kodi NFO Fiddler

A small Python utility that takes in messy video file names, extracts MKV metadata, looks up movie details through TMDB, and writes Kodi-compatible `.nfo` files.

## Requirements

- Python 3.12 or newer
- `mkvmerge` from the `mkvtoolnix` package
- A TMDB read access token for live lookups

The repository includes a VS Code dev container that provides Python and `mkvmerge` automatically.

## Requirements

Set `TMDB_READ_TOKEN` in a `.env` file in the project directory:

```dotenv
TMDB_READ_TOKEN=your_tmdb_read_access_token
```

## Run

Process the current directory:

```bash
python3 kodi_nfo_fiddler.py
```

Process a specific directory:

```bash
python3 kodi_nfo_fiddler.py /path/to/movies
```

Upgrade legacy NFO files with `--upgrade-nfo`. This walks the directory recursively and rewrites plain-text NFO files that contain only an IMDB or TMDB link into Kodi movie XML with a TMDB unique id (the IMDB id is kept as a second `uniqueid`). IMDB links are resolved to TMDB through the TMDB API. NFOs that are already XML are left alone, as are files TMDB cannot match. This mode only upgrades NFOs and does not organize or remux videos:

```bash
python3 kodi_nfo_fiddler.py --upgrade-nfo /path/to/movies
```

Warnings are printed in yellow in interactive terminals. Color is disabled when output is redirected or when `NO_COLOR` is set.

Remux MP4 files into MKV with `--remux-mp4` (without it, MP4 files are skipped):

```bash
python3 kodi_nfo_fiddler.py --remux-mp4 /path/to/movies
```

With the flag, MP4 files are remuxed into MKV containers without re-encoding. Matching sidecar subtitles whose filenames contain an English (`en`, `eng`, `english`) or Swedish (`sv`, `swe`, `swedish`, `svenska`) language tag are included; English tracks are ordered first and set as the default when present. The source MP4 is removed only after a successful conversion. Subtitle sidecars remain in place.

## Dev container

Open the repository in VS Code and choose **Reopen in Container**. Once the container is created, run the tests in its terminal with:

```bash
python -m unittest -v
```