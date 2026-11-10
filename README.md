# Kodi NFO Fiddler

A small Python utility that takes in messy video file names, extracts MKV metadata, looks up movie details through TMDB, and writes Kodi-compatible `.nfo` files.

## Requirements

- Python 3.12 or newer
- `mkvmerge` from the `mkvtoolnix` package
- A TMDB read access token for movie and TV show lookups

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
Title[_-_Director's_Cut]_(Year)_(resolution_source_audioCodec_channels[_Atmos])
```

For example `Inception_(2010)_(1080p_BluRay_DTS-HD_7.1_Atmos)`. When the source name contains `Director's Cut` or `Directors Cut`, the video name includes `_-_Director's_Cut` before the year; the movie title used for TMDB and the NFO is unchanged. Loose videos in the target directory get their own folder; videos in an existing subfolder keep their place and the folder is renamed to match. A matching `.nfo` is written next to the video.

- **Technical tags:** resolution, audio codec, channel layout and the optional `Atmos` tag (always last) are read from the MKV with `mkvmerge`. The source comes from the file name or, failing that, its parent folder name.
- **Sources:** `LaserDisc`, `BluRay`, `WEBRip`, `HDTV`, `PDTV` and `DVD`. `Laserdisc` is normalized to `LaserDisc`. Other variants are normalized: `Blu-Ray`, `Blu Ray`, `BR`, `BDRemux`, `BRRip` and `BDRip` become `BluRay`; `WEB-DL`, `WEBDL`, `HDRip` and `WEB` become `WEBRip`; `DVDRip` and `DVDR` become `DVD`. A bare `REMUX` is not recognized.
- **Unknown values:** if the resolution, source, audio codec, channel count or year cannot be determined, the file is left untouched and a warning is printed. Nothing is renamed and no NFO is written for it.
- **No TMDB match:** a warning is printed and the parsed title and year are used for naming. The year must still be known for the rename to happen; running the tool again retries the TMDB lookup.
- **Several videos in one folder:** the largest video is treated as the movie. Smaller `.mkv` files are deleted when the largest is at least twice the size of the next one, and other smaller videos are left alone with a warning. If the two largest videos are within a factor of two of each other, the whole folder is skipped.
- **Name collisions:** an existing file or folder with the target name is never overwritten; the item is skipped with a warning.
- **Cleanup:** after a video is successfully organized, `.txt` and `.jpg` files, `Featurettes` folders and entries starting with `sample` are removed from its folder. Folders skipped as ambiguous or lacking required metadata are left untouched.
- **Subtitles:** an MKV without an English subtitle track gets English subtitle files added with `mkvmerge` (the file is rewritten in place and the subtitle files are removed afterwards). For a loose video in the target directory only files named after the video count (`Movie.en.srt`); for a video in an existing folder any subtitle file in that folder ending in `en`, `eng` or `english` counts (`name.en.srt`). If the muxing fails, the files are left untouched with a warning. Without any English subtitles a warning is printed.
- **Non-MKV videos:** MP4 files are remuxed into MKV (below); other formats are skipped.

Warnings are printed in yellow in interactive terminals. Color is disabled when output is redirected or when `NO_COLOR` is set.

## Organizing TV shows

When the current working directory or the selected target directory is named exactly `TV-Shows`, the script visits the target directory recursively, creates missing `tvshow.nfo` files and renames episodes:

```bash
python3 kodi_nfo_fiddler.py /path/to/TV-Shows
```

Episode filenames must contain `S01E01`, for example `Breaking_Bad_-_S01E01.mkv` or `Breaking Bad [2008] S01E01 Part1.mkv`. The text before that marker is the show name (underscores and dots become spaces); if it is empty, the folder name is used. A year in brackets, parentheses or at the end (e.g. `[2022]`) is removed from the search and used to narrow the TMDB match. Video files without `S01E01` produce a warning. Multi-episode files per the Kodi naming rules (`S01E01E02`, `S01E01-E04`, `S01E01-S01E02`, `S01E01-02-03`) are supported; each episode's title is looked up and the file is renamed `Show_-_S01E01E02_-_Title1_-_Title2_(...)`. Ambiguous series matches are skipped with a warning. New `tvshow.nfo` files use the TMDB series ID. Existing NFOs with a TMDB ID are used directly; legacy NFOs containing only a TVDB ID are resolved to TMDB when possible. Each show directory is renamed to the TMDB title; if multiple series share that title, the first-air year is added (`Title_(Year)`). Episode filenames never include the year.

Episodes are named `Show_-_S01E01_-_Episode_(resolution_source_audioCodec_channels[_Atmos]).mkv`, using the show's TMDB episode details and the same technical metadata rules as movies. Matching English and Swedish subtitle sidecars are embedded in MKV or MP4 episodes, with English tracks first; they are removed only after successful remuxing and organization. Other matching sidecars, including untagged and other-language subtitles, are renamed alongside the episode. MP4 episodes are remuxed into MKV without re-encoding; other formats are skipped. Missing episode titles or required metadata, conflicting destination names, and shows without a usable TMDB ID cause the affected files to be skipped with a warning.

## Remuxing MP4 files

When processing movies, MP4 files are always remuxed into MKV. For example:

```bash
python3 kodi_nfo_fiddler.py /path/to/movies
```

MP4 files are remuxed into MKV containers without re-encoding. Matching sidecar subtitles whose filenames contain an English (`en`, `eng`, `english`) or Swedish (`sv`, `swe`, `swedish`, `svenska`) language tag are included; English tracks are ordered first and set as the default when present. The source MP4 and the subtitle sidecars that were included are removed only after a successful conversion; mkvmerge warnings (exit code 1) still count as success.

## Dev container

Open the repository in VS Code and choose **Reopen in Container**. Once the container is created, run the tests in its terminal with:

```bash
.venv/bin/python -m unittest -v
```

Lint with [ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`):

```bash
.venv/bin/ruff check .
```