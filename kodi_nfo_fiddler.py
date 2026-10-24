# /// script
# dependencies = [
#     "requests",
#     "python-dotenv",
# ]
# ///

import argparse
import os
import sys
import re
import shutil
import json
import subprocess
import uuid
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

TMDB_READ_TOKEN = os.getenv("TMDB_READ_TOKEN")
TMDB_MOVIE_BASE_URL = "https://www.themoviedb.org/movie/"
TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
IMDB_ID_PATTERN = re.compile(r"\b(tt\d{7,})\b", re.IGNORECASE)
TMDB_MOVIE_URL_PATTERN = re.compile(r"themoviedb\.org/movie/(\d+)", re.IGNORECASE)
TMDB_TV_URL_PATTERN = re.compile(r"themoviedb\.org/tv/(\d+)", re.IGNORECASE)
TVDB_ID_PATTERN = re.compile(r"thetvdb\.com/\S*?(?:[?&](?:amp;)?(?:series)?id=|dereferrer/series/)(\d+)", re.IGNORECASE)
MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.m4v', '.mov', '.flv', '.wmv')
REMOVE_EXTENSIONS = ('.txt', '.jpg')
SOURCE_KEYWORDS = ["BluRay", "WEB-DL", "WEBRip", "WEB", "HDTV", "DVDRip", "DVD", "BRRip", "BDRip"]
SOURCE_NORMALIZATIONS = {"WEB-DL": "WEBRip", "WEB": "WEBRip", "BRRip": "BluRay", "BDRip": "BluRay", "DVDRip": "DVD"}
SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup")
SUBTITLE_LANGUAGES = {
    "en": ("en", "eng", "english"),
    "sv": ("sv", "swe", "swedish", "svenska"),
}
# Ordered: the first entry with a matching needle wins (e.g. DTS-HD before DTS, EAC3 before AC3).
AUDIO_CODEC_NAMES = [
    (("DTS-HD",), "DTS-HD"),
    (("DTS",), "DTS"),
    (("TRUEHD", "ATMOS"), "TrueHD"),
    (("EAC3", "E-AC-3"), "E-AC3"),
    (("AC3", "AC-3"), "AC3"),
    (("AAC",), "AAC"),
    (("OPUS",), "Opus"),
    (("FLAC",), "FLAC"),
]
AUDIO_CHANNEL_LAYOUTS = {8: "7.1", 6: "5.1", 2: "2.0", 1: "1.0"}


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_warning(message):
    """Print a "[!]"-prefixed warning, in yellow when stdout is an interactive terminal."""
    message = f"[!] {message}"
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        message = f"\033[33m{message}\033[0m"
    print(message)



# ---------------------------------------------------------------------------
# Subtitles and MP4 remuxing
# ---------------------------------------------------------------------------

def is_language(language_tag, language):
    """True if a language tag (e.g. "eng", "en-US", "english") is one of the aliases for the language key."""
    primary_subtag = language_tag.casefold().split("-")[0]
    return primary_subtag in SUBTITLE_LANGUAGES[language]


def find_sidecar_subtitles(video_path):
    """Find language-tagged subtitle files whose names match the video basename."""
    directory = os.path.dirname(video_path)
    video_stem = os.path.splitext(os.path.basename(video_path))[0]
    subtitles = {"en": [], "sv": []}

    for filename in os.listdir(directory):
        stem, extension = os.path.splitext(filename)
        if extension.lower() not in SUBTITLE_EXTENSIONS or not os.path.isfile(os.path.join(directory, filename)):
            continue
        if not stem.casefold().startswith(video_stem.casefold()):
            continue

        suffix = stem[len(video_stem):]
        if not suffix or suffix[0] not in " ._-":
            continue
        tokens = {token.casefold() for token in re.split(r"[ ._-]+", suffix) if token}
        for language, aliases in SUBTITLE_LANGUAGES.items():
            if tokens.intersection(aliases):
                subtitles[language].append(os.path.join(directory, filename))
                break

    for language in subtitles:
        subtitles[language].sort(key=str.casefold)
    return subtitles


def remux_mp4_to_mkv(mp4_path):
    """Remux an MP4 and matching English/Swedish subtitles, then remove the MP4."""
    subtitles = find_sidecar_subtitles(mp4_path)
    output_path = os.path.join(os.path.dirname(mp4_path), f".kodi_nfo_fiddler_{uuid.uuid4().hex}.mkv")

    command = ["mkvmerge", "-o", output_path, mp4_path]
    # English first; the first subtitle track overall is the default
    ordered_subtitles = [(path, "eng") for path in subtitles["en"]] + [(path, "swe") for path in subtitles["sv"]]
    for index, (subtitle_path, language) in enumerate(ordered_subtitles):
        command.extend([
            "--language", f"0:{language}",
            "--default-track-flag", f"0:{'yes' if index == 0 else 'no'}",
            subtitle_path,
        ])

    try:
        subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        if os.path.isfile(output_path):
            os.remove(mp4_path)
            return output_path
        error_details = "mkvmerge completed without creating an output file"
    except (OSError, subprocess.CalledProcessError) as error:
        error_details = getattr(error, "stderr", None) or error

    print_warning(f"Failed to convert '{os.path.basename(mp4_path)}' to MKV: {error_details}")
    if os.path.exists(output_path):
        os.remove(output_path)
    return None



# ---------------------------------------------------------------------------
# MKV metadata
# ---------------------------------------------------------------------------

def classify_resolution(width, height):
    """Buckets pixel dimensions into a resolution label (tolerant of cropped widescreen encodes)."""
    if width >= 3840 or height >= 2160:
        return "2160p"
    if width >= 1900 or height >= 1030:
        return "1080p"
    if width >= 1280 or height >= 720:
        return "720p"
    if width >= 720 or height >= 480:
        return "SD"
    return f"{height}p"

def get_video_dimensions(properties):
    """Returns (width, height) from mkvmerge video track properties, or None if unavailable."""
    width = properties.get("pixel_width") or properties.get("display_width")
    height = properties.get("pixel_height") or properties.get("display_height")
    if width and height:
        return int(width), int(height)

    dimensions = properties.get("display_dimensions") or properties.get("pixel_dimensions")
    if dimensions and 'x' in dimensions:
        try:
            width, height = dimensions.split('x')
            return int(width), int(height)
        except ValueError:
            pass
    return None

def describe_audio(track):
    """Returns (codec, channel layout) labels for an mkvmerge audio track."""
    codec_id = track.get("codec", "").upper()
    codec = next(
        (name for needles, name in AUDIO_CODEC_NAMES if any(needle in codec_id for needle in needles)),
        codec_id.replace("A_", "")
    )

    channels = track.get("properties", {}).get("audio_channels")
    if not channels:
        return codec, "Unknown Channels"
    return codec, AUDIO_CHANNEL_LAYOUTS.get(channels, f"{channels}.0")

def get_mkv_metadata(filepath):
    """Attempts to read MKV technical metadata using mkvmerge -J."""
    try:
        result = subprocess.run(
            ["mkvmerge", "-J", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        tracks = json.loads(result.stdout).get("tracks", [])
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        print_warning(f"Could not read MKV metadata for '{os.path.basename(filepath)}': {e}")
        return None

    resolution = "Unknown Resolution"
    audio_codec = "Unknown Codec"
    audio_channels = "Unknown Channels"
    english_subtitles = False

    for track in tracks:
        track_type = track.get("type")
        properties = track.get("properties", {})

        if track_type == "subtitles":
            language_tag = properties.get("language_ietf") or properties.get("language", "")
            english_subtitles = english_subtitles or is_language(language_tag, "en")
        elif track_type == "video" and resolution == "Unknown Resolution":
            dimensions = get_video_dimensions(properties)
            if dimensions:
                resolution = classify_resolution(*dimensions)
        elif track_type == "audio" and audio_codec == "Unknown Codec":
            audio_codec, audio_channels = describe_audio(track)

    return {
        "resolution": resolution,
        "audio_codec": audio_codec,
        "audio_channels": audio_channels,
        "english_subtitles": english_subtitles
    }


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

def detect_source(text):
    """Returns the normalized source (e.g. BluRay, WEBRip) named in the text, or None."""
    for source in SOURCE_KEYWORDS:
        if re.search(r'\b' + re.escape(source) + r'\b', text, re.IGNORECASE):
            return SOURCE_NORMALIZATIONS.get(source, source)
    return None

def parse_filename(filename, file_path):
    """
    Cleans up complex release group filenames to extract a pristine
    Title and Year for TMDB API optimization.
    """
    # Technical metadata defaults (Will be overwritten if it's an MKV)
    metadata = {
        "title": "Unknown Title",
        "year": "Unknown Year",
        "resolution": "Unknown Resolution",
        "source": "Unknown Source",
        "audio_codec": "Unknown Codec",
        "audio_channels": "Unknown Channels"
    }

    # Strip extension
    base_name, _ = os.path.splitext(filename)
    base_name = re.sub(r'^no_hit_', '', base_name, count=1, flags=re.IGNORECASE)

    # Remove site URLs commonly prepended to release names.
    base_name = re.sub(r'(?:https?://|www\.)[^_\s]+', ' ', base_name, flags=re.IGNORECASE)

    # Replace common separators with spaces to standardize tokenization
    clean_name = base_name.replace('_', ' ').replace('.', ' ')

    # Extract Year: allow it to immediately follow a title, but not another digit.
    year_match = re.search(r'(?<!\d)(19\d{2}|2\d{3})\b', clean_name)

    if year_match:
        metadata["year"] = year_match.group(1)
        # The title is everything before the year
        title_part = clean_name[:year_match.start()]
    else:
        # Fallback if no year is found: try to cut off at common tag indicators
        title_part = re.split(r'\b(1080p|720p|2160p|480p|BluRay|WEB|DVD)\b', clean_name, flags=re.IGNORECASE)[0]

    # Clean up the extracted title string
    title_part = re.sub(r'[\(\)\[\]\-\+]', ' ', title_part) # Strip parentheses/brackets
    title_part = re.sub(r'\s+', ' ', title_part).strip()     # Normalize spaces
    metadata["title"] = title_part

    # Deduce Source out of raw string before returning (fallback for non-MKVs).
    # Some release layouts keep the source tag only in the parent directory name.
    parent_name = os.path.basename(os.path.dirname(file_path))
    metadata["source"] = detect_source(clean_name) or detect_source(parent_name) or "Unknown Source"

    # If the file is an MKV, populate pristine technical parameters directly from the tracks
    if filename.lower().endswith('.mkv'):
        mkv_meta = get_mkv_metadata(file_path)
        if mkv_meta:
            metadata.update(mkv_meta)

    return metadata


# ---------------------------------------------------------------------------
# Folder cleanup and naming helpers
# ---------------------------------------------------------------------------

def get_video_files(directory):
    """Returns a list of video files in the given directory (non-recursive)."""
    try:
        return [f for f in os.listdir(directory) if f.lower().endswith(MEDIA_EXTENSIONS) and os.path.isfile(os.path.join(directory, f))]
    except OSError as e:
        print_warning(f"Could not list '{directory}': {e}")
        return []

def remove_smaller_video_files(directory):
    """Removes smaller video files when the largest is at least twice as large."""
    video_files = [filename for filename in get_video_files(directory) if filename.lower().endswith('.mkv')]
    if len(video_files) < 2:
        return

    files_by_size = sorted(
        video_files,
        key=lambda filename: os.path.getsize(os.path.join(directory, filename)),
        reverse=True
    )
    largest_size = os.path.getsize(os.path.join(directory, files_by_size[0]))
    second_largest_size = os.path.getsize(os.path.join(directory, files_by_size[1]))
    if largest_size < 2 * second_largest_size:
        return

    for filename in files_by_size[1:]:
        file_path = os.path.join(directory, filename)
        print(f"[+] Removing smaller video file: {filename}")
        os.remove(file_path)

def remove_unwanted_files(directory):
    """Removes TXT and JPG files from the given directory (non-recursive)."""
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if filename.lower().endswith(REMOVE_EXTENSIONS) and os.path.isfile(file_path):
                os.remove(file_path)
    except OSError as e:
        print_warning(f"Could not remove unwanted files in '{directory}': {e}")

def remove_featurettes_folder(directory):
    """Removes a Featurettes folder from the given movie directory."""
    featurettes_path = os.path.join(directory, "Featurettes")
    try:
        if os.path.isdir(featurettes_path):
            shutil.rmtree(featurettes_path)
    except OSError as e:
        print_warning(f"Could not remove '{featurettes_path}': {e}")

def remove_sample_entries(directory):
    """Removes files or folders starting with sample from the given movie directory."""
    try:
        for filename in os.listdir(directory):
            if not filename.lower().startswith("sample"):
                continue

            sample_path = os.path.join(directory, filename)
            if os.path.isdir(sample_path):
                shutil.rmtree(sample_path)
            elif os.path.isfile(sample_path):
                os.remove(sample_path)
    except OSError as e:
        print_warning(f"Could not remove sample files in '{directory}': {e}")

def sanitize_folder_name(name):
    """Sanitizes folder names, keeps spaces/commas, then replaces spaces with underscores."""
    name = name.replace(":", "_-")
    sanitized = re.sub(r"[^\w\s().,!'-]", '', name)
    return sanitized.replace(" ", "_")

def get_original_directory(directory_path):
    """Reads the original directory name from an existing NFO, if available."""
    for filename in os.listdir(directory_path):
        if not filename.lower().endswith('.nfo'):
            continue

        try:
            root = ET.parse(os.path.join(directory_path, filename)).getroot()
            original_directory = root.findtext('original_directory')
            if original_directory:
                return original_directory
        except (OSError, ET.ParseError):
            continue

    return None


# ---------------------------------------------------------------------------
# Organizing videos
# ---------------------------------------------------------------------------

def clean_directory(directory_path, is_root):
    """Removes junk files, featurettes, samples and (outside the root) smaller duplicate videos."""
    remove_unwanted_files(directory_path)
    remove_featurettes_folder(directory_path)
    remove_sample_entries(directory_path)
    if not is_root:
        remove_smaller_video_files(directory_path)

def prepare_mkv(directory_path, filename, remux_mp4):
    """
    Returns (file_path, mkv_filename) for a video, remuxing an MP4 first if allowed.
    Returns None when the file should be skipped.
    """
    file_path = os.path.join(directory_path, filename)
    if remux_mp4 and filename.lower().endswith('.mp4'):
        file_path = remux_mp4_to_mkv(file_path)
        if file_path is None:
            return None
        return file_path, f"{os.path.splitext(filename)[0]}.mkv"
    if not filename.lower().endswith('.mkv'):
        print_warning(f"Skipping non-MKV media file: {filename}")
        return None
    return file_path, filename

def resolve_naming(metadata):
    """
    Looks the movie up on TMDB and returns (tmdb_id, nfo_title, folder_title, year).
    A miss keeps the parsed title and prefixes the folder title with no_hit_.
    """
    search_result = search_tmdb(metadata['title'], metadata['year'])
    if search_result is None:
        print_warning(f"No TMDB hit for '{metadata['title']}'. Tagging directory with prefix 'no_hit_'...")
        return None, metadata['title'], f"no_hit_{metadata['title']}", metadata['year']

    # Use the official TMDB title and release year for naming
    tmdb_url, title, year = search_result
    return tmdb_url.split('/')[-1], title, title, year

def build_new_name(metadata, folder_title, year):
    """Builds the clean Title_(Year)_(resolution_source_codec_channels) name."""
    metadata_suffix = sanitize_folder_name(
        f"({metadata['resolution']}_{metadata['source']}_{metadata['audio_codec']}_{metadata['audio_channels']})"
    )
    return f"{sanitize_folder_name(folder_title)}_({year})_{metadata_suffix}"

def rename_directory(directory_path, new_name):
    """Renames a directory to new_name and returns its resulting path."""
    final_path = os.path.join(os.path.dirname(directory_path), new_name)

    # Guard against overwriting if name is already perfectly normalized
    if directory_path != final_path:
        print(f"[+] Renaming directory from '{os.path.basename(directory_path)}' to '{new_name}'")
        try:
            os.rename(directory_path, final_path)
            return final_path
        except OSError as e:
            print(f"[-] Directory rename failed: {e}")
    return directory_path

def process_directory(directory_path, is_root=False, remux_mp4=False):
    directory_path = os.path.abspath(directory_path)
    original_directory = os.path.basename(directory_path)
    stored_directory = None
    if original_directory.startswith("no_hit_"):
        stored_directory = get_original_directory(directory_path)
        if stored_directory:
            original_directory = stored_directory

    clean_directory(directory_path, is_root)
    video_files = get_video_files(directory_path)
    if not video_files:
        return None

    print(f"\nScanning folder: '{os.path.basename(directory_path)}' (Contains {len(video_files)} video file(s))")

    for original_filename in video_files:
        prepared = prepare_mkv(directory_path, original_filename, remux_mp4)
        if prepared is None:
            continue
        file_path, filename = prepared
        print(f" -> Processing file: {filename}")

        # Prefer the original directory metadata when retrying a previous no-hit.
        metadata = parse_filename(stored_directory or filename, file_path)
        if not metadata.get("english_subtitles", False):
            print_warning(f"No English subtitles found in '{filename}'.")

        tmdb_id, nfo_title, folder_title, year = resolve_naming(metadata)
        new_name = build_new_name(metadata, folder_title, year)

        # Loose files in the root get a new folder; files in an existing subdirectory stay put
        if is_root:
            dest_dir = os.path.join(directory_path, new_name)
            os.makedirs(dest_dir, exist_ok=True)
        else:
            dest_dir = directory_path

        new_file_path = os.path.join(dest_dir, f"{new_name}{os.path.splitext(filename)[1]}")
        print(f"[+] Setting asset to: {new_file_path}")
        os.rename(file_path, new_file_path)

        write_kodi_nfo(
            os.path.join(dest_dir, f"{new_name}.nfo"),
            nfo_title,
            metadata['year'],
            tmdb_id=tmdb_id,
            original_filename=original_filename,
            original_directory=original_directory,
        )

        # A subdirectory is renamed to match its first video and then we're done
        if not is_root:
            return rename_directory(directory_path, new_name)

    return None if is_root else directory_path


# ---------------------------------------------------------------------------
# TMDB client
# ---------------------------------------------------------------------------

def tmdb_get(path, params=None):
    """Performs an authenticated TMDB API GET request and returns the decoded JSON."""
    response = requests.get(
        f"{TMDB_API_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {TMDB_READ_TOKEN}", "accept": "application/json"},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

def _movie_details(data, imdb_id=None):
    return {
        "tmdb_id": data["id"],
        "title": data["title"],
        "year": (data.get("release_date") or "")[:4],
        "imdb_id": imdb_id or data.get("imdb_id"),
    }

def lookup_tmdb_by_imdb_id(imdb_id):
    """Returns a movie details dict (tmdb_id, title, year, imdb_id) for an IMDB id, or None if TMDB has no match."""
    results = tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"}).get("movie_results", [])
    return _movie_details(results[0], imdb_id) if results else None

def lookup_tmdb_by_id(tmdb_id):
    """Returns a movie details dict (tmdb_id, title, year, imdb_id) for a TMDB movie id."""
    return _movie_details(tmdb_get(f"/movie/{tmdb_id}"))

def _as_result(hit):
    """Converts a TMDB search hit into (tmdb_url, title, year)."""
    return f"{TMDB_MOVIE_BASE_URL}{hit['id']}", hit["title"], (hit.get("release_date") or "####")[:4]

def search_tmdb(title, year):
    """
    Searches TMDB for a movie title. If a strict year search fails,
    it falls back to a broad text search to match web behavior.
    """
    has_year = bool(year) and year != "Unknown Year"

    # Tier 1: Strict API Search (Title + Exact Year Filter)
    params = {
        "query": title,
        "include_adult": "false",
        "language": "en-US",
        "page": 1
    }

    if has_year:
        params["year"] = year
        params["primary_release_year"] = year

    try:
        results = tmdb_get("/search/movie", params).get("results", [])

        # If Tier 1 found matches, return the top hit
        if results:
            return _as_result(results[0])

        # Tier 2: Broad Fallback Search (If strict year filter returned 0 hits)
        if has_year:
            print_warning(f"Strict year match failed for '{title}' ({year}). Trying broad search...")
            broad_params = {k: v for k, v in params.items() if k not in ("year", "primary_release_year")}
            results = tmdb_get("/search/movie", broad_params).get("results", [])

            # Scan results manually to find a close match within a 1-year variance window
            for hit in results:
                release_date = hit.get("release_date", "")
                if release_date:
                    hit_year = int(release_date[:4])
                    target_year = int(year)

                    # Allow a +/- 1 year tolerance window for international premieres
                    if abs(hit_year - target_year) <= 1:
                        return _as_result(hit)

            # Last resort: no hit was within a year of the target, so take the top result
            if results:
                return _as_result(results[0])

    except Exception as e:
        print(f"[-] Network error querying TMDB: {e}")

    return None

def lookup_tmdb_tv_by_external_id(external_id, source):
    """Returns the TMDB tv id for an IMDB or TVDB id (source: imdb_id or tvdb_id), or None."""
    results = tmdb_get(f"/find/{external_id}", {"external_source": source}).get("tv_results", [])
    return results[0]["id"] if results else None

def lookup_tmdb_tv(tmdb_id):
    """Returns TV show details including TVDB/IMDB ids from TMDB."""
    data = tmdb_get(f"/tv/{tmdb_id}", {"append_to_response": "external_ids"})
    external_ids = data.get("external_ids") or {}
    return {
        "tmdb_id": data["id"],
        "title": data["name"],
        "year": (data.get("first_air_date") or "")[:4],
        "tvdb_id": external_ids.get("tvdb_id"),
        "imdb_id": external_ids.get("imdb_id"),
    }


# ---------------------------------------------------------------------------
# NFO writing
# ---------------------------------------------------------------------------

def write_nfo_xml(path, root_tag, fields):
    """Writes an NFO whose root has one child per (tag, text, attributes) field."""
    root = ET.Element(root_tag)
    for tag, text, attributes in fields:
        ET.SubElement(root, tag, attributes).text = str(text)
    ET.indent(root, space="    ")
    with open(path, "w", encoding="utf-8") as nfo:
        nfo.write("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\" ?>\n")
        nfo.write(ET.tostring(root, encoding="unicode", short_empty_elements=False) + "\n")

def write_kodi_nfo(path, title, year, tmdb_id=None, imdb_id=None, original_filename=None, original_directory=None):
    """
    Writes a Kodi movie NFO. Without a tmdb_id (a no-hit) the unique ids are omitted
    and kodi_nfo_url is left empty. The original_* fields let a no-hit be retried later.
    """
    fields = []
    if original_filename:
        fields.append(("original_filename", original_filename, {}))
    if original_directory:
        fields.append(("original_directory", original_directory, {}))
    fields.append(("title", title, {}))
    if year:
        fields.append(("year", year, {}))
    if tmdb_id:
        fields.append(("uniqueid", tmdb_id, {"type": "tmdb", "default": "true"}))
    if imdb_id:
        fields.append(("uniqueid", imdb_id, {"type": "imdb"}))
    fields.append(("kodi_nfo_url", f"{TMDB_MOVIE_BASE_URL}{tmdb_id}" if tmdb_id else "", {}))
    write_nfo_xml(path, "movie", fields)

def write_kodi_tvshow_nfo(path, show):
    """Writes a Kodi tvshow NFO. TVDB is the default id (Kodi's default TV scraper) when known."""
    fields = []
    if show.get("title"):
        fields.append(("title", show["title"], {}))
    if show.get("year"):
        fields.append(("year", show["year"], {}))
    unique_ids = [(id_type, show[key]) for id_type, key in (("tvdb", "tvdb_id"), ("tmdb", "tmdb_id"), ("imdb", "imdb_id")) if show.get(key)]
    for index, (id_type, value) in enumerate(unique_ids):
        attributes = {"type": id_type, **({"default": "true"} if index == 0 else {})}
        fields.append(("uniqueid", value, attributes))
    write_nfo_xml(path, "tvshow", fields)


# ---------------------------------------------------------------------------
# Legacy NFO upgrade (--upgrade-nfo)
# ---------------------------------------------------------------------------

def upgrade_tvshow_nfo(path, text):
    """Upgrades a plain-text tvshow.nfo link. Returns "upgraded", "skipped" or "failed"."""
    imdb_match = IMDB_ID_PATTERN.search(text)
    tmdb_match = TMDB_TV_URL_PATTERN.search(text)
    tvdb_match = TVDB_ID_PATTERN.search(text)
    if not (imdb_match or tmdb_match or tvdb_match):
        print_warning(f"No IMDB, TMDB or TVDB series id found in '{path}'. Leaving it unchanged.")
        return "skipped"

    linked_ids = {
        "tvdb_id": tvdb_match.group(1) if tvdb_match else None,
        "imdb_id": imdb_match.group(1) if imdb_match else None,
    }

    try:
        tmdb_id = tmdb_match.group(1) if tmdb_match else None
        if tmdb_id is None and linked_ids["tvdb_id"]:
            tmdb_id = lookup_tmdb_tv_by_external_id(linked_ids["tvdb_id"], "tvdb_id")
        if tmdb_id is None and linked_ids["imdb_id"]:
            tmdb_id = lookup_tmdb_tv_by_external_id(linked_ids["imdb_id"], "imdb_id")

        show = lookup_tmdb_tv(tmdb_id) if tmdb_id else None
        if show is None:
            if not linked_ids["tvdb_id"]:
                print_warning(f"No TMDB TV show found for '{path}'. Leaving it unchanged.")
                return "failed"
            # TVDB id is already what Kodi wants; write it without TMDB enrichment.
            show = {}

        # Ids from the original link fill any gaps TMDB left
        for key, value in linked_ids.items():
            show[key] = show.get(key) or value
        write_kodi_tvshow_nfo(path, show)
    except (requests.RequestException, KeyError, ValueError, OSError) as e:
        print_warning(f"Failed to upgrade '{path}': {e}")
        return "failed"

    print(f"[+] Upgraded TV show NFO: {path} -> TVDB {show.get('tvdb_id') or 'n/a'}, TMDB {show.get('tmdb_id') or 'n/a'}")
    return "upgraded"

def upgrade_nfo_file(path):
    """
    Upgrades a plain-text NFO (a bare IMDB/TMDB link, or for tvshow.nfo also TVDB) to Kodi XML format.
    Returns "upgraded", "skipped" (already XML or no recognizable link) or "failed".
    """
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as nfo:
            text = nfo.read()
    except OSError as e:
        print_warning(f"Could not read '{path}': {e}")
        return "failed"

    # Anything XML-like is left alone, including malformed or non-movie NFOs.
    if text.lstrip().startswith("<"):
        return "skipped"

    if os.path.basename(path).lower() == "tvshow.nfo":
        return upgrade_tvshow_nfo(path, text)

    imdb_match = IMDB_ID_PATTERN.search(text)
    tmdb_match = TMDB_MOVIE_URL_PATTERN.search(text)
    if not imdb_match and not tmdb_match:
        print_warning(f"No IMDB or TMDB link found in '{path}'. Leaving it unchanged.")
        return "skipped"

    try:
        if tmdb_match:
            movie = lookup_tmdb_by_id(tmdb_match.group(1))
            movie["imdb_id"] = movie["imdb_id"] or (imdb_match.group(1) if imdb_match else None)
        else:
            movie = lookup_tmdb_by_imdb_id(imdb_match.group(1))
            if movie is None:
                print_warning(f"No TMDB movie found for {imdb_match.group(1)} in '{path}'. Leaving it unchanged.")
                return "failed"
        write_kodi_nfo(path, movie["title"], movie["year"], tmdb_id=movie["tmdb_id"], imdb_id=movie["imdb_id"])
    except (requests.RequestException, KeyError, ValueError, OSError) as e:
        print_warning(f"Failed to upgrade '{path}': {e}")
        return "failed"

    print(f"[+] Upgraded NFO: {path} -> TMDB {movie['tmdb_id']} ({movie['title']})")
    return "upgraded"

def upgrade_nfo_files(directory):
    """Recursively upgrades legacy plain-text NFO files under the given directory."""
    counts = {"upgraded": 0, "skipped": 0, "failed": 0}
    for current_dir, _, filenames in os.walk(directory):
        for filename in sorted(filenames):
            if filename.lower().endswith(".nfo"):
                counts[upgrade_nfo_file(os.path.join(current_dir, filename))] += 1

    print(f"NFO upgrade complete: {counts['upgraded']} upgraded, {counts['skipped']} skipped, {counts['failed']} failed")
    return counts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main():
    if not TMDB_READ_TOKEN:
        print("Error: TMDB_READ_TOKEN not found. Check your .env file.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Organize movie files and write Kodi NFO files.")
    parser.add_argument("directory", nargs="?", default=".", help="directory to process (default: current directory)")
    parser.add_argument(
        "--remux-mp4",
        action="store_true",
        help="remux MP4 files (plus English/Swedish sidecar subtitles) into MKV and remove the MP4",
    )
    parser.add_argument(
        "--upgrade-nfo",
        action="store_true",
        help="recursively upgrade plain-text NFO files to Kodi XML (movie NFOs get a TMDB id, tvshow.nfo gets a TVDB id), then exit",
    )
    args = parser.parse_args()
    target_dir = args.directory

    if not os.path.isdir(target_dir):
        print(f"Error: The directory '{target_dir}' does not exist.")
        sys.exit(1)

    target_dir = os.path.abspath(target_dir)
    print(f"Scanning directory: {target_dir}")

    if args.upgrade_nfo:
        upgrade_nfo_files(target_dir)
        return

    # 1. Snapshot the pre-existing subdirectories BEFORE processing loose files
    try:
        existing_subdirs = [
            os.path.join(target_dir, d)
            for d in os.listdir(target_dir)
            if os.path.isdir(os.path.join(target_dir, d)) and not d.startswith('.')
        ]
    except Exception as e:
        print(f"Error scanning initial subdirectories: {e}")
        existing_subdirs = []

    # 2. Process loose video files sitting directly in the root directory (Creates subdirs)
    process_directory(target_dir, is_root=True, remux_mp4=args.remux_mp4)

    # 3. Process nested files in existing subdirectories (Renames the subdirs)
    for subdir in existing_subdirs:
        process_directory(subdir, is_root=False, remux_mp4=args.remux_mp4)

if __name__ == "__main__":
    main()
