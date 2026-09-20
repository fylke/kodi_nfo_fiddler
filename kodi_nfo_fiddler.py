# /// script
# dependencies = [
#     "requests",
#     "python-dotenv",
# ]
# ///

import os
import sys
import re
import shutil
import json
import subprocess
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# --- CONFIGURATION ---
TMDB_READ_TOKEN = os.getenv("TMDB_READ_TOKEN")
# ---------------------

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_BASE_URL = "https://www.themoviedb.org/movie/"
MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.m4v', '.mov', '.flv', '.wmv')
REMOVE_EXTENSIONS = ('.txt', '.jpg')
SOURCE_KEYWORDS = ["BluRay", "WEB-DL", "WEBRip", "WEB", "HDTV", "DVDRip", "DVD", "BRRip", "BDRip"]
SOURCE_NORMALIZATIONS = {"WEB-DL": "WEBRip", "WEB": "WEBRip", "BRRip": "BluRay", "BDRip": "BluRay", "DVDRip": "DVD"}

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
        data = json.loads(result.stdout)

        resolution = "Unknown Resolution"
        audio_codec = "Unknown Codec"
        audio_channels = "Unknown Channels"

        tracks = data.get("tracks", [])
        for track in tracks:
            track_type = track.get("type")
            properties = track.get("properties", {})

            # Extract Video Info (Direct integer targeting for reliability)
            if track_type == "video" and resolution == "Unknown Resolution":
                # 1. Grab raw integer properties first if available
                display_width = properties.get("pixel_width") or properties.get("display_width")
                display_height = properties.get("pixel_height") or properties.get("display_height")

                # 2. Fallback to string splitting ONLY if integers aren't present
                if not display_width or not display_height:
                    dimensions = properties.get("display_dimensions") or properties.get("pixel_dimensions")
                    if dimensions and 'x' in dimensions:
                        try:
                            w_str, h_str = dimensions.split('x')
                            display_width = int(w_str)
                            display_height = int(h_str)
                        except ValueError:
                            pass

                # 3. Perform safety check. If we successfully found numbers, execute bucketing logic
                if display_width and display_height:
                    display_width = int(display_width)
                    display_height = int(display_height)

                    if display_width >= 3840 or display_height >= 2160:
                        resolution = "2160p"
                    elif display_width >= 1920 or display_height >= 1080:
                        resolution = "1080p"
                    elif display_width >= 1280 or display_height >= 720:
                        resolution = "720p"
                    elif display_width >= 720 or display_height >= 480:
                        resolution = "SD"
                    else:
                        resolution = f"{display_height}p"

            # Extract Audio Info (Codec & Channels)
            elif track_type == "audio" and audio_codec == "Unknown Codec":
                codec_id = track.get("codec", "").upper()

                if "DTS-HD" in codec_id:
                    audio_codec = "DTS-HD"
                elif "DTS" in codec_id:
                    audio_codec = "DTS"
                elif "TRUEHD" in codec_id or "ATMOS" in codec_id:
                    audio_codec = "TrueHD"
                elif "EAC3" in codec_id or "E-AC-3" in codec_id:
                    audio_codec = "E-AC3"
                elif "AC3" in codec_id or "AC-3" in codec_id:
                    audio_codec = "AC3"
                elif "AAC" in codec_id:
                    audio_codec = "AAC"
                elif "OPUS" in codec_id:
                    audio_codec = "Opus"
                elif "FLAC" in codec_id:
                    audio_codec = "FLAC"
                else:
                    audio_codec = codec_id.replace("A_", "")

                channels = properties.get("audio_channels")
                if channels:
                    if channels == 8:
                        audio_channels = "7.1"
                    elif channels == 6:
                        audio_channels = "5.1"
                    elif channels == 2:
                        audio_channels = "2.0"
                    elif channels == 1:
                        audio_channels = "1.0"
                    else:
                        audio_channels = f"{channels}.0"

        return {
            "resolution": resolution,
            "audio_codec": audio_codec,
            "audio_channels": audio_channels
        }

    except Exception:
        return None

def search_tmdb(title, year):
    """
    Searches TMDB for a movie title. If a strict year search fails,
    it falls back to a broad text search to match web behavior.
    """
    API_KEY = "your_tmdb_api_key_here"
    BASE_URL = "https://api.themoviedb.org/3/search/movie"

    headers = {
        "Authorization": f"Bearer {TMDB_READ_TOKEN}",
        "accept": "application/json"
    }

    # Tier 1: Strict API Search (Title + Exact Year Filter)
    params = {
        "api_key": API_KEY,
        "query": title,
        "year": year,
        "include_adult": "false",
        "language": "en-US",
        "page": 1
    }

    if year and year != "Unknown Year":
        params["primary_release_year"] = year

    try:
        response = requests.get(TMDB_SEARCH_URL, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            # If Tier 1 found matches, return the top hit
            if results:
                hit = results[0]
                tmdb_url = f"https://www.themoviedb.org/movie/{hit['id']}"
                return tmdb_url, hit["title"], hit.get("release_date", "####")[:4]

        # Tier 2: Broad Fallback Search (If strict year filter returned 0 hits)
        if year and year != "Unknown Year":
            print(f"[!] Strict year match failed for '{title}' ({year}). Trying broad search...")
            params.pop("year", None)
            params.pop("primary_release_year", None)

            response = requests.get(BASE_URL, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])

                # Scan results manually to find a close match within a 1-year variance window
                for hit in results:
                    release_date = hit.get("release_date", "")
                    if release_date:
                        hit_year = int(release_date[:4])
                        target_year = int(year)

                        # Allow a +/- 1 year tolerance window for international premieres
                        if abs(hit_year - target_year) <= 1:
                            tmdb_url = f"https://www.themoviedb.org/movie/{hit['id']}"
                            return tmdb_url, hit["title"], str(hit_year)

                # Final ultimate safety: if no year is close but it's the only hit, take it
                if results:
                    hit = results[0]
                    tmdb_url = f"https://www.themoviedb.org/movie/{hit['id']}"
                    return tmdb_url, hit["title"], hit.get("release_date", "####")[:4]

    except Exception as e:
        print(f"[-] Network error querying TMDB: {e}")

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

    # Deduce Source out of raw string before returning (fallback for non-MKVs)
    for src in SOURCE_KEYWORDS:
        if re.search(r'\b' + re.escape(src) + r'\b', clean_name, re.IGNORECASE):
            metadata["source"] = SOURCE_NORMALIZATIONS.get(src, src)
            break

    # Some release layouts keep the source tag only in the parent directory name.
    if metadata["source"] == "Unknown Source":
        parent_name = os.path.basename(os.path.dirname(file_path))
        for src in SOURCE_KEYWORDS:
            if re.search(r'\b' + re.escape(src) + r'\b', parent_name, re.IGNORECASE):
                metadata["source"] = SOURCE_NORMALIZATIONS.get(src, src)
                break

    # If the file is an MKV, populate pristine technical parameters directly from the tracks
    if filename.lower().endswith('.mkv'):
        mkv_meta = get_mkv_metadata(file_path)
        if mkv_meta:
            metadata.update(mkv_meta)

    return metadata

def get_video_files(directory):
    """Returns a list of video files in the given directory (non-recursive)."""
    try:
        return [f for f in os.listdir(directory) if f.lower().endswith(MEDIA_EXTENSIONS) and os.path.isfile(os.path.join(directory, f))]
    except Exception:
        return []

def remove_unwanted_files(directory):
    """Removes TXT and JPG files from the given directory (non-recursive)."""
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if filename.lower().endswith(REMOVE_EXTENSIONS) and os.path.isfile(file_path):
                os.remove(file_path)
    except Exception:
        pass

def sanitize_folder_name(name):
    """Sanitizes folder names, keeps spaces/commas, then replaces spaces with underscores."""
    name = name.replace(":", "_-")
    sanitized = re.sub(r'[^\w\s\(\)\.,-]', '', name)
    return sanitized.replace(" ", "_")

def write_metadata_file(path, url, title, year, metadata, original_filename):
    """Helper to write the movie details to an NFO file (with empty rows before formatting)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{url}\n\n")
            f.write(f"Title: {title}\n")
            f.write(f"Year: {year}\n")
            f.write(f"Resolution: {metadata['resolution']}\n")
            f.write(f"Source: {metadata['source']}\n")
            f.write(f"Audio Codec: {metadata['audio_codec']}\n")
            f.write(f"Audio Channels: {metadata['audio_channels']}\n\n")
            f.write(f"Original Filename: {original_filename}\n")
    except Exception as e:
        print(f" -> Failed writing metadata file: {e}")

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

def process_directory(directory_path, is_root=False):
    directory_path = os.path.abspath(directory_path)
    original_directory = os.path.basename(directory_path)
    stored_directory = None
    if original_directory.startswith("no_hit_"):
        stored_directory = get_original_directory(directory_path)
        if stored_directory:
            original_directory = stored_directory
    remove_unwanted_files(directory_path)
    video_files = get_video_files(directory_path)
    if not video_files:
        return None

    num_videos = len(video_files)
    print(f"\nScanning folder: '{os.path.basename(directory_path)}' (Contains {num_videos} video file(s))")

    for filename in video_files:
        # Keep track of the untouched original filename
        original_filename = filename
        file_path = os.path.join(directory_path, filename)
        _, ext = os.path.splitext(filename)
        print(f" -> Processing file: {filename}")

        # Prefer the original directory metadata when retrying a previous no-hit.
        metadata = parse_filename(filename, file_path)
        if stored_directory:
            metadata = parse_filename(stored_directory, file_path)

        # 1. Safely call the TMDB search
        search_result = search_tmdb(metadata['title'], metadata['year'])

        # Initialize flags, folder target names, and pure file title tracks
        is_hit = True
        file_title = metadata['title']
        target_year = metadata['year']
        tmdb_url = ""

        # 2. The No-Hit Fallback Switch
        if search_result is None:
            print(f"[!] No TMDB hit for '{metadata['title']}'. Tagging directory with prefix 'no_hit_'...")
            is_hit = False
            # Folder title gets the prefix flag
            target_title = f"no_hit_{metadata['title']}"
        else:
            # Safe to unpack if it's a valid hit
            tmdb_url, matched_title, release_year = search_result
            # Normalize target names to official TMDB naming conventions
            target_title = matched_title
            file_title = matched_title
            target_year = release_year

        # 3. Construct the clean destination directory name (With no_hit_ prefix if applicable)
        metadata_suffix = sanitize_folder_name(
            f"({metadata['resolution']}_{metadata['source']}_{metadata['audio_codec']}_{metadata['audio_channels']})"
        )
        sanitized_title = sanitize_folder_name(target_title)
        new_name = f"{sanitized_title}_({target_year})_{metadata_suffix}"

        # Determine target layout based on folder context tier
        if is_root:
            # Create a brand new folder inside the landing directory root
            dest_dir = os.path.join(directory_path, new_name)
            os.makedirs(dest_dir, exist_ok=True)
        else:
            # Keep operations local to the current working subdirectory
            dest_dir = directory_path

        new_file_name = f"{new_name}{ext}"
        new_file_path = os.path.join(dest_dir, new_file_name)

        # 4. Move/Rename the movie asset file into position
        print(f"[+] Setting asset to: {new_file_path}")
        os.rename(file_path, new_file_path)

        # 5. Generate the .nfo file sidecar matching the filename pattern
        nfo_file_name = f"{new_name}.nfo"
        nfo_file_path = os.path.join(dest_dir, nfo_file_name)

        with open(nfo_file_path, 'w', encoding='utf-8') as nfo:
            nfo.write("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\" ?>\n")
            nfo.write("<movie>\n")
            nfo.write(f"    <!-- Original Filename: {original_filename} -->\n")
            nfo.write(f"    <original_directory>{escape(original_directory)}</original_directory>\n")
            nfo.write(f"    <title>{metadata['title']}</title>\n")
            nfo.write(f"    <year>{metadata['year']}</year>\n")

            if is_hit:
                nfo.write(f"    <uniqueid type=\"tmdb\" default=\"true\">{tmdb_url.split('/')[-1]}</uniqueid>\n")
                nfo.write(f"    <kodi_nfo_url>{tmdb_url}</kodi_nfo_url>\n")
            else:
                nfo.write("    <kodi_nfo_url></kodi_nfo_url>\n")

            nfo.write("</movie>\n")

        # 7. Final Step: Rename the directory itself if it's an existing subdir
        if not is_root:
            parent_dir = os.path.dirname(directory_path)
            final_subdir_path = os.path.join(parent_dir, new_name)

            # Guard against overwriting if name is already perfectly normalized
            if directory_path != final_subdir_path:
                print(f"[+] Renaming directory from '{os.path.basename(directory_path)}' to '{new_name}'")
                try:
                    os.rename(directory_path, final_subdir_path)
                    # Break out early since the tracking directory path just moved locations
                    return final_subdir_path
                except Exception as e:
                    print(f"[-] Directory rename failed: {e}")
            return directory_path

    return directory_path if not is_root else None

def main():
    if not TMDB_READ_TOKEN:
        print("Error: TMDB_READ_TOKEN not found. Check your .env file.")
        sys.exit(1)

    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = "."

    if not os.path.isdir(target_dir):
        print(f"Error: The directory '{target_dir}' does not exist.")
        sys.exit(1)

    target_dir = os.path.abspath(target_dir)
    print(f"Scanning directory: {target_dir}")

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
    process_directory(target_dir, is_root=True)

    # 3. Process nested files in existing subdirectories (Renames the subdirs)
    for subdir in existing_subdirs:
        process_directory(subdir, is_root=False)

if __name__ == "__main__":
    main()
