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
    search_tmdb,
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
        expected = "The_Movie_-_Directors_Cut_(2024)_(1080p,_BluRay,_DTS,_5.1)"

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

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_parse_filename_ignores_no_hit_prefix(self, mock_mkv):
        metadata = parse_filename(
            "no_hit_Inception.2010.1080p.BluRay.mp4",
            "no_hit_Inception.2010.1080p.BluRay.mp4"
        )

        self.assertEqual(metadata["title"], "Inception")
        self.assertEqual(metadata["year"], "2010")

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_parse_filename_normalizes_web_sources(self, mock_mkv):
        for source in ("WEB-DL", "WEB", "WEBRip"):
            with self.subTest(source=source):
                metadata = parse_filename(
                    f"Movie.2024.1080p.{source}.mkv",
                    "Movie.2024.1080p.{0}.mkv".format(source)
                )
                self.assertEqual(metadata["source"], "WEBRip")

        mock_mkv.assert_called()

    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_removes_txt_and_jpg_files(self, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")

        video_path = os.path.join(self.test_dir, "inception.mp4")
        txt_path = os.path.join(self.test_dir, "notes.TXT")
        jpg_path = os.path.join(self.test_dir, "poster.JPG")
        keep_path = os.path.join(self.test_dir, "keep.png")
        for path in (video_path, txt_path, jpg_path, keep_path):
            with open(path, "w") as file:
                file.write("test")

        process_directory(self.test_dir, is_root=True)

        self.assertFalse(os.path.exists(txt_path))
        self.assertFalse(os.path.exists(jpg_path))
        self.assertTrue(os.path.exists(keep_path))

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

        expected_folder_name = "Inception_(2010)_(1080p_Unknown_Source_DTS_5.1)"
        expected_folder_path = os.path.join(self.test_dir, expected_folder_name)

        self.assertEqual(new_folder_path, expected_folder_path)
        self.assertTrue(os.path.isdir(expected_folder_path))

        expected_video_file = os.path.join(expected_folder_path, f"{expected_folder_name}.mkv")
        expected_nfo_file = os.path.join(expected_folder_path, f"{expected_folder_name}.nfo")

        self.assertTrue(os.path.exists(expected_video_file))
        self.assertTrue(os.path.exists(expected_nfo_file))

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_stores_original_directory_for_no_hit_retry(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = None
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Mystery Movie (2024) BluRay")
        os.makedirs(movie_folder)
        with open(os.path.join(movie_folder, "mystery.mkv"), "w") as video_file:
            video_file.write("fake video data")

        no_hit_path = process_directory(movie_folder)
        nfo_path = next(
            os.path.join(no_hit_path, filename)
            for filename in os.listdir(no_hit_path)
            if filename.endswith('.nfo')
        )

        with open(nfo_path, encoding="utf-8") as nfo_file:
            nfo_contents = nfo_file.read()

        self.assertTrue(os.path.basename(no_hit_path).startswith("no_hit_"))
        self.assertIn(
            "<original_directory>Mystery Movie (2024) BluRay</original_directory>",
            nfo_contents
        )

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_retries_no_hit_using_original_directory(self, mock_mkv, mock_tmdb):
        mock_tmdb.side_effect = [
            None,
            ("https://www.themoviedb.org/movie/123", "Mystery Movie", "2024")
        ]
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Mystery Movie (2024) BluRay")
        os.makedirs(movie_folder)
        with open(os.path.join(movie_folder, "mystery.mkv"), "w") as video_file:
            video_file.write("fake video data")

        no_hit_path = process_directory(movie_folder)
        recovered_path = process_directory(no_hit_path)

        self.assertEqual(mock_tmdb.call_args_list[1].args[:2], ("Mystery Movie", "2024"))
        self.assertEqual(os.path.basename(recovered_path).startswith("no_hit_"), False)
        self.assertIn("Mystery_Movie_(2024)", os.path.basename(recovered_path))

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_sanitizes_colons_in_title(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = (
            "https://www.themoviedb.org/movie/568",
            "Mission: Impossible",
            "1996"
        )
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Mission_Raw_Folder")
        os.makedirs(movie_folder)
        with open(os.path.join(movie_folder, "mission.mkv"), "w") as video_file:
            video_file.write("fake video data")

        new_folder_path = process_directory(movie_folder)

        expected_folder_name = "Mission_-_Impossible_(1996)_(1080p_Unknown_Source_DTS_5.1)"
        expected_folder_path = os.path.join(self.test_dir, expected_folder_name)
        expected_video_file = os.path.join(expected_folder_path, f"{expected_folder_name}.mkv")

        self.assertEqual(new_folder_path, expected_folder_path)
        self.assertTrue(os.path.exists(expected_video_file))

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_uses_source_from_movie_folder(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/278", "The Chronicles of Riddick", "2004")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "Unknown Codec",
            "audio_channels": "Unknown Channels"
        }

        movie_folder = os.path.join(
            self.test_dir,
            "The Chronicles of Riddick (2004) DC (1080p BluRay x265 HEVC 10bit AAC 5.1 Tigole)"
        )
        os.makedirs(movie_folder)
        with open(
            os.path.join(movie_folder, "The Chronicles of Riddick (2004) DC (1080p x265 10bit Tigole).mkv"),
            "w"
        ) as video_file:
            video_file.write("fake video data")

        new_folder_path = process_directory(movie_folder)

        self.assertIn("BluRay", os.path.basename(new_folder_path))

    @patch('subprocess.run')
    def test_get_mkv_metadata_widescreen_1080p(self, mock_run):
        """Verify that a widescreen 1920x802 file correctly maps to 1080p."""
        mock_stdout = json.dumps({
            "tracks": [
                {
                    "type": "video",
                    "properties": {
                        "display_dimensions": "1920x802"
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

    def test_parse_filename_with_heavy_metadata(self):
        filename = "Toy Story (1995) (1080p DS4K BluRay x265 10-bit HDR AAC 7.1).mkv"
        metadata = parse_filename(filename, "dummy_path.mkv")

        self.assertEqual(metadata["title"], "Toy Story")
        self.assertEqual(metadata["year"], "1995")

    def test_parse_filename_with_year_attached_to_title(self):
        metadata = parse_filename(
            "Eddie.Izzard.Sexie2003.x264.aac.mkv",
            "dummy_path.mkv"
        )

        self.assertEqual(metadata["title"], "Eddie Izzard Sexie")
        self.assertEqual(metadata["year"], "2003")

    def test_parse_filename_removes_prepended_url(self):
        metadata = parse_filename(
            "WwW.SeeHD.WS__Free Solo 2018 1080p WEB-DL X264 AC3-SeeHD.mkv",
            "dummy_path.mkv"
        )

        self.assertEqual(metadata["title"], "Free Solo")
        self.assertEqual(metadata["year"], "2018")

    @patch('kodi_nfo_fiddler.requests.get')
    def test_search_tmdb_fallback_removes_all_year_filters(self, mock_get):
        strict_response = MagicMock(status_code=200)
        strict_response.json.return_value = {"results": []}
        fallback_response = MagicMock(status_code=200)
        fallback_response.json.return_value = {
            "results": [{
                "id": 683127,
                "title": "Earwig and the Witch",
                "release_date": "2021-02-03"
            }]
        }
        mock_get.side_effect = [strict_response, fallback_response]

        result = search_tmdb("Earwig and the Witch", "2020")

        self.assertEqual(
            result,
            ("https://www.themoviedb.org/movie/683127", "Earwig and the Witch", "2021")
        )
        fallback_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertNotIn("year", fallback_params)
        self.assertNotIn("primary_release_year", fallback_params)
        
if __name__ == '__main__':
    unittest.main()
