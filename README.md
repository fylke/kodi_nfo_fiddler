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

Upgrade legacy NFO files with `--upgrade-nfo`. This walks the directory recursively and rewrites plain-text NFO files into Kodi XML. It runs on its own and does not organize or remux videos:

```bash
python3 kodi_nfo_fiddler.py --upgrade-nfo /path/to/movies
```

- **Movies:** an NFO containing only an IMDB or TMDB movie link becomes a Kodi `<movie>` NFO with a TMDB `uniqueid` (the IMDB id is kept as a second `uniqueid`). IMDB links are resolved through the TMDB API.
- **TV shows:** a plain-text `tvshow.nfo` containing an IMDB, TMDB (`/tv/`) or TVDB (`?tab=series&id=` / `dereferrer/series/`) link becomes a Kodi `<tvshow>` NFO. TheTVDB is Kodi's default TV scraper, so the TVDB id is written as the default `uniqueid`, with TMDB and IMDB ids alongside. The TVDB id is looked up through the TMDB API. Per-episode NFOs are not touched.
- NFOs that are already XML are left alone, as are files TMDB cannot match.

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