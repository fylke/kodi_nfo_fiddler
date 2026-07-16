import os
import re
import requests
from dotenv import load_load_env  # Import dotenv

# Load environment variables from the .env file
load_dotenv()

# --- CONFIGURATION ---
# It will look for "TMDB_API_KEY" in your environment/system.
# If not found, it defaults to None.
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TARGET_DIR = "."
# ---------------------

# Keep the rest of your script exactly the same, but add a quick safety check:
if not TMDB_API_KEY:
    print("Error: TMDB_API_KEY not found. Please ensure it is set in your .env file.")
    exit(1)
# ---------------------

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_BASE_URL = "https://www.themoviedb.org/movie/"

# Supported media extensions to filter out non-video files
MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.m4v', '.mov', '.flv', '.wmv')

def parse_filename(filename):
    """
    Parses a typical movie filename to extract metadata.
    Example: "The.Matrix.1999.1080p.BluRay.x264.DTS-5.1.mkv"
    """
    # Remove extension
    name, _ = os.path.splitext(filename)
    # Replace dots, dashes, and underscores with spaces for cleaner regex parsing
    clean_name = re.sub(r'[\._\-]', ' ', name)
    
    # Common regex patterns for extraction
    year_match = re.search(r'\b(19|20)\d{2}\b', clean_name)
    resolution_match = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', clean_name, re.IGNORECASE)
    source_match = re.search(r'\b(BluRay|BRRip|BDRip|WEBRip|WEB-DL|HDRip|DVDRip|HDTV)\b', clean_name, re.IGNORECASE)
    
    # Audio Codec patterns (DTS, AAC, AC3, EAC3, TrueHD, FLAC, DD+, etc.)
    audio_codec_match = re.search(r'\b(DTS-HD|DTS|AAC|AC3|EAC3|TrueHD|FLAC|DD\+|DD|Atmos)\b', clean_name, re.IGNORECASE)
    
    # Audio Channels (e.g., 7.1, 5.1, 2.0)
    audio_channels_match = re.search(r'\b([257]\.[01])\b', clean_name)

    # Extract Title: Everything before the year, or before the resolution if no year exists
    title = clean_name
    split_points = [m.start() for m in [year_match, resolution_match, source_match] if m]
    if split_points:
        title = clean_name[:min(split_points)].strip()
    else:
        # Fallback: just clean up excessive spacing
        title = ' '.join(title.split())

    return {
        "title": title,
        "year": year_match.group(0) if year_match else None,
        "resolution": resolution_match.group(0) if resolution_match else "Unknown Resolution",
        "source": source_match.group(0) if source_match else "Unknown Source",
        "audio_codec": audio_codec_match.group(0) if audio_codec_match else "Unknown Codec",
        "audio_channels": audio_channels_match.group(0) if audio_channels_match else "Unknown Channels"
    }

def search_tmdb(title, year=None):
    """
    Searches TMDB for a movie. Returns the TMDB movie URL if an unequivocal hit is found.
    """
    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
    }
    if year:
        params["primary_release_year"] = year

    try:
        response = requests.get(TMDB_SEARCH_URL, params=params)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])

        # Define "unequivocal hit": 
        # Either there is exactly 1 result, OR the first result is a very high popularity/exact match.
        if len(results) == 1:
            movie = results[0]
            return f"{TMDB_MOVIE_BASE_URL}{movie['id']}", movie['title'], movie.get('release_date', '0000-00-00')[:4]
        elif len(results) > 1:
            # Check if the top result's title is an exact match (case-insensitive) to be sure
            first_match = results[0]
            if first_match['title'].lower() == title.lower():
                return f"{TMDB_MOVIE_BASE_URL}{first_match['id']}", first_match['title'], first_match.get('release_date', '0000-00-00')[:4]
            
        return None, None, None
    except Exception as e:
        print(f"Error searching TMDB for '{title}': {e}")
        return None, None, None

def main():
    if TMDB_API_KEY == "YOUR_TMDB_API_KEY_HERE":
        print("Please configure your TMDB API Key in the script before running.")
        return

    print(f"Scanning directory: {os.path.abspath(TARGET_DIR)}")
    
    for filename in os.listdir(TARGET_DIR):
        # Scan only media files
        if not filename.lower().endswith(MEDIA_EXTENSIONS):
            continue
            
        print(f"\nProcessing file: {filename}")
        metadata = parse_filename(filename)
        
        print(f" -> Parsed: '{metadata['title']}' | Year: {metadata['year']}")
        
        # Look up on TMDB
        tmdb_url, matched_title, release_year = search_tmdb(metadata['title'], metadata['year'])
        
        if tmdb_url:
            print(f" -> Found unequivocal TMDB match: {matched_title} ({release_year})")
            
            # Format the output text file name (replace spaces with underscores)
            # Standardized name: Movie_Title_(Year).txt
            output_filename = f"{matched_title}_{release_year}.txt"
            output_filename = re.sub(r'[^\w\s\(\)\.-]', '', output_filename) # Strip illegal characters
            output_filename = output_filename.replace(" ", "_")
            
            output_path = os.path.join(TARGET_DIR, output_filename)
            
            # Write metadata contents to file
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"TMDB URL: {tmdb_url}\n")
                    f.write(f"Title: {matched_title}\n")
                    f.write(f"Year: {release_year}\n")
                    f.write(f"Resolution: {metadata['resolution']}\n")
                    f.write(f"Source: {metadata['source']}\n")
                    f.write(f"Audio Codec: {metadata['audio_codec']}\n")
                    f.write(f"Audio Channels: {metadata['audio_channels']}\n")
                print(f" -> Successfully wrote details to: {output_filename}")
            except Exception as e:
                print(f" -> Failed writing to file {output_filename}: {e}")
        else:
            print(" -> No unequivocal hit found on TMDB. Skipping...")

if __name__ == "__main__":
    main()
