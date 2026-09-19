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

## Run tests

Run the full unittest suite from the project root:

```bash
python3 -m unittest -v
```

Run the test module directly:

```bash
python3 -m unittest -v test_kodi_nfo_fiddler.py
```

## Dev container

Open the repository in VS Code and choose **Reopen in Container**. Once the container is created, run the tests in its terminal with:

```bash
python -m unittest -v
```