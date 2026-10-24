# Kodi NFO Fiddler

A small Python utility that takes in messy video file names, extracts MKV metadata, looks up movie details through TMDB, and writes Kodi-compatible `.nfo` files.

## Requirements

- Python 3.12 or newer
- `mkvmerge` from the `mkvtoolnix` package
- A TMDB read access token for live lookups

The repository includes a VS Code dev container that provides Python and `mkvmerge` automatically.

## Configuration

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

## How videos are organized

Each MKV is looked up on TMDB and renamed to:

```text
Title_(Year)_(resolution_source_audioCodec_channels[_Atmos])
```

For example `Inception_(2010)_(1080p_BluRay_DTS-HD_7.1_Atmos)`. Loose videos in the target directory get their own folder; videos in an existing subfolder keep their place and the folder is renamed to match. A matching `.nfo` is written next to the video.

- **Technical tags:** resolution, audio codec, channel layout and the optional `Atmos` tag (always last) are read from the MKV with `mkvmerge`. The source comes from the file name or, failing that, its parent folder name.
- **Sources:** `BluRay`, `WEBRip`, `HDTV`, `PDTV` and `DVD`. Variants are normalized: `Blu-Ray`, `Blu Ray`, `BDRemux`, `BRRip` and `BDRip` become `BluRay`; `WEB-DL`, `WEBDL`, `HDRip` and `WEB` become `WEBRip`; `DVDRip` and `DVDR` become `DVD`. A bare `REMUX` is not recognized.
- **Unknown values:** if the resolution, source, audio codec, channel count or year cannot be determined, the file is left untouched and a warning is printed. Nothing is renamed and no NFO is written for it.
- **No TMDB match:** the folder is prefixed with `no_hit_` and the NFO remembers the original names, so running the tool again retries the lookup. The year must still be known for the rename to happen.
- **Several videos in one folder:** the largest video is treated as the movie. Smaller `.mkv` files are deleted when the largest is at least twice the size of the next one, and other smaller videos are left alone with a warning. If the two largest videos are within a factor of two of each other, the whole folder is skipped.
- **Name collisions:** an existing file or folder with the target name is never overwritten; the item is skipped with a warning.
- **Cleanup:** `.txt` and `.jpg` files, `Featurettes` folders and entries starting with `sample` are removed from the folders being processed.
- **Non-MKV videos:** skipped unless you use `--remux-mp4` (below).

Warnings are printed in yellow in interactive terminals. Color is disabled when output is redirected or when `NO_COLOR` is set.

## Upgrading legacy NFO files

Upgrade legacy NFO files with `--upgrade-nfo`. This walks the directory recursively and rewrites plain-text NFO files into Kodi XML. It runs on its own and does not organize or remux videos:

```bash
python3 kodi_nfo_fiddler.py --upgrade-nfo /path/to/movies
```

- **Movies:** an NFO containing only an IMDB or TMDB movie link becomes a Kodi `<movie>` NFO with a TMDB `uniqueid` (the IMDB id is kept as a second `uniqueid`). IMDB links are resolved through the TMDB API.
- **TV shows:** a plain-text `tvshow.nfo` containing an IMDB, TMDB (`/tv/`) or TVDB (`?tab=series&id=` / `dereferrer/series/`) link becomes a Kodi `<tvshow>` NFO. TheTVDB is Kodi's default TV scraper, so the TVDB id is written as the default `uniqueid`, with TMDB and IMDB ids alongside. The TVDB id is looked up through the TMDB API. Per-episode NFOs are not touched.
- NFOs that are already XML are left alone, as are files TMDB cannot match.

## Remuxing MP4 files

Remux MP4 files into MKV with `--remux-mp4` (without it, MP4 files are skipped):

```bash
python3 kodi_nfo_fiddler.py --remux-mp4 /path/to/movies
```

With the flag, MP4 files are remuxed into MKV containers without re-encoding. Matching sidecar subtitles whose filenames contain an English (`en`, `eng`, `english`) or Swedish (`sv`, `swe`, `swedish`, `svenska`) language tag are included; English tracks are ordered first and set as the default when present. The source MP4 and the subtitle sidecars that were included are removed only after a successful conversion; mkvmerge warnings (exit code 1) still count as success.

## Dev container

Open the repository in VS Code and choose **Reopen in Container**. Once the container is created, run the tests in its terminal with:

```bash
python -m unittest -v
```

Lint with [ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`):

```bash
ruff check .
```