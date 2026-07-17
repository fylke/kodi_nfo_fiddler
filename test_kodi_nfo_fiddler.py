import os
import json
import shutil
import tempfile
import unittest
import subprocess
from unittest.mock import patch, MagicMock

from kodi_nfo_fiddler import (
    get_mkv_metadata,
    parse_filename,
    sanitize_folder_name,
    process_directory,
    write_metadata_file
)

class TestMovieOrganizer(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch('subprocess.run')
    def test_get_mkv_metadata_widescreen_1080p(self, mock_run):
        """Verify that a widescreen 1920x800 file correctly maps to 1080p."""
        mock_stdout = json.dumps({
            "tracks": [
                {
                    "type": "video",
                    "properties": {
                        "display_dimensions": "1920x800"
                    }
                },
                {
                    "type": "audio",
                    "codec": "A_DTS",
                    "properties": {
                        "audio_channels": 6
                    }
                }
            ]
        })

        mock_run.return_value = MagicMock(stdout=mock_stdout, returncode=0)
        metadata = get_mkv_metadata("dummy_path.mkv")

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["resolution"], "1080p")
        self.assertEqual(metadata["audio_codec"], "DTS")
        self.assertEqual(metadata["audio_channels"], "5.1")

    def test_sanitize_folder_name(self):
        raw_name = "The Movie: Director's Cut (2024) (1080p, BluRay, DTS, 5.1)"
        expected = "The_Movie_Directors_Cut_(2024)_(1080p,_BluRay,_DTS,_5.1)"

        sanitized = sanitize_folder_name(raw_name)
        self.assertEqual(sanitized, expected)

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_parse_filename_strict_fallback_when_not_mkv(self, mock_mkv):
        """Ensure non-MKV files only parse Title, Year, and Source, defaulting technical meta."""
        metadata = parse_filename("Inception.2010.1080p.BluRay.DTS.5.1.mp4", "dummy_path.mp4")

        mock_mkv.assert_not_called()
        self.assertEqual(metadata["title"], "Inception")
        self.assertEqual(metadata["year"], "2010")
        self.assertEqual(metadata["source"], "BluRay")
        # Technical metadata must default to Unknown because it's not an MKV
        self.assertEqual(metadata["resolution"], "Unknown Resolution")
        self.assertEqual(metadata["audio_codec"], "Unknown Codec")
        self.assertEqual(metadata["audio_channels"], "Unknown Channels")

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_single_file_renames_parent_folder(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Inception_Raw_Folder")
        os.makedirs(movie_folder)
        video_file_path = os.path.join(movie_folder, "inception.mkv")

        with open(video_file_path, "w") as f:
            f.write("fake video data")

        new_folder_path = process_directory(movie_folder)

        expected_folder_name = "Inception_(2010)_(1080p,_Unknown_Source,_DTS,_5.1)"
        expected_folder_path = os.path.join(self.test_dir, expected_folder_name)

        self.assertEqual(new_folder_path, expected_folder_path)
        self.assertTrue(os.path.isdir(expected_folder_path))

        expected_video_file = os.path.join(expected_folder_path, f"{expected_folder_name}.mkv")
        expected_nfo_file = os.path.join(expected_folder_path, f"{expected_folder_name}.nfo")

        self.assertTrue(os.path.exists(expected_video_file))
        self.assertTrue(os.path.exists(expected_nfo_file))

if __name__ == '__main__':
    unittest.main()
