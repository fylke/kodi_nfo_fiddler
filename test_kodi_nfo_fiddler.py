import os
import json
import shutil
import tempfile
import unittest
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

from kodi_nfo_fiddler import (
    get_mkv_metadata,
    parse_filename,
    sanitize_folder_name,
    search_tmdb,
    process_directory,
    write_metadata_file,
    print_warning,
    find_sidecar_subtitles,
    remux_mp4_to_mkv,
    upgrade_nfo_file,
    upgrade_nfo_files,
)

class TestMovieOrganizer(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @staticmethod
    def _tmdb_response(payload):
        response = MagicMock()
        response.json.return_value = payload
        return response

    def _write_nfo(self, relative_path, contents):
        path = os.path.join(self.test_dir, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as nfo:
            nfo.write(contents)
        return path

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_nfo_file_converts_imdb_link_to_tmdb_kodi_nfo(self, mock_get):
        mock_get.return_value = self._tmdb_response({
            "movie_results": [{"id": 27205, "title": "Inception", "release_date": "2010-07-15"}]
        })
        path = self._write_nfo("Inception/movie.nfo", "https://www.imdb.com/title/tt1375666/\n")

        self.assertEqual(upgrade_nfo_file(path), "upgraded")

        root = ET.parse(path).getroot()
        self.assertEqual(root.tag, "movie")
        self.assertEqual(root.findtext("title"), "Inception")
        self.assertEqual(root.findtext("year"), "2010")
        unique_ids = {uid.get("type"): uid.text for uid in root.findall("uniqueid")}
        self.assertEqual(unique_ids, {"tmdb": "27205", "imdb": "tt1375666"})
        self.assertEqual(root.findtext("kodi_nfo_url"), "https://www.themoviedb.org/movie/27205")
        self.assertIn("/find/tt1375666", mock_get.call_args.args[0])

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_nfo_file_converts_tmdb_link(self, mock_get):
        mock_get.return_value = self._tmdb_response({
            "id": 27205, "title": "Inception", "release_date": "2010-07-15", "imdb_id": "tt1375666"
        })
        path = self._write_nfo("movie.nfo", "https://www.themoviedb.org/movie/27205-inception\n")

        self.assertEqual(upgrade_nfo_file(path), "upgraded")

        root = ET.parse(path).getroot()
        self.assertEqual(root.find("uniqueid[@type='tmdb']").text, "27205")
        self.assertEqual(root.find("uniqueid[@type='imdb']").text, "tt1375666")

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_nfo_file_leaves_xml_nfo_untouched(self, mock_get):
        original = "<movie><title>Keep Me</title></movie>\nhttps://www.imdb.com/title/tt1375666/\n"
        path = self._write_nfo("movie.nfo", original)

        self.assertEqual(upgrade_nfo_file(path), "skipped")

        mock_get.assert_not_called()
        with open(path, encoding="utf-8") as nfo:
            self.assertEqual(nfo.read(), original)

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_nfo_file_leaves_file_unchanged_when_tmdb_has_no_match(self, mock_get):
        mock_get.return_value = self._tmdb_response({"movie_results": []})
        original = "https://www.imdb.com/title/tt0000001/\n"
        path = self._write_nfo("movie.nfo", original)

        self.assertEqual(upgrade_nfo_file(path), "failed")

        with open(path, encoding="utf-8") as nfo:
            self.assertEqual(nfo.read(), original)

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_nfo_files_walks_recursively(self, mock_get):
        mock_get.return_value = self._tmdb_response({
            "movie_results": [{"id": 27205, "title": "Inception", "release_date": "2010-07-15"}]
        })
        self._write_nfo("a/b/legacy.NFO", "tt1375666")
        self._write_nfo("c/modern.nfo", "<movie><title>Done</title></movie>")
        self._write_nfo("c/notes.txt", "tt1375666")

        counts = upgrade_nfo_files(self.test_dir)

        self.assertEqual(counts, {"upgraded": 1, "skipped": 1, "failed": 0})

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_tvshow_nfo_converts_imdb_link_to_tvdb_default(self, mock_get):
        mock_get.side_effect = [
            self._tmdb_response({"tv_results": [{"id": 1396}]}),
            self._tmdb_response({
                "id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20",
                "external_ids": {"tvdb_id": 81189, "imdb_id": "tt0903747"},
            }),
        ]
        path = self._write_nfo("Breaking Bad/tvshow.nfo", "https://www.imdb.com/title/tt0903747/\n")

        self.assertEqual(upgrade_nfo_file(path), "upgraded")

        root = ET.parse(path).getroot()
        self.assertEqual(root.tag, "tvshow")
        self.assertEqual(root.findtext("title"), "Breaking Bad")
        self.assertEqual(root.findtext("year"), "2008")
        unique_ids = [(uid.get("type"), uid.text, uid.get("default")) for uid in root.findall("uniqueid")]
        self.assertEqual(unique_ids, [
            ("tvdb", "81189", "true"),
            ("tmdb", "1396", None),
            ("imdb", "tt0903747", None),
        ])
        self.assertIn("/find/tt0903747", mock_get.call_args_list[0].args[0])
        self.assertEqual(mock_get.call_args_list[0].kwargs["params"], {"external_source": "imdb_id"})

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_tvshow_nfo_converts_tmdb_tv_link(self, mock_get):
        mock_get.return_value = self._tmdb_response({
            "id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20",
            "external_ids": {"tvdb_id": 81189, "imdb_id": "tt0903747"},
        })
        path = self._write_nfo("tvshow.nfo", "https://www.themoviedb.org/tv/1396-breaking-bad\n")

        self.assertEqual(upgrade_nfo_file(path), "upgraded")

        self.assertEqual(ET.parse(path).getroot().find("uniqueid[@type='tvdb']").text, "81189")

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_tvshow_nfo_uses_tvdb_link_id(self, mock_get):
        mock_get.side_effect = [
            self._tmdb_response({"tv_results": []}),
        ]
        path = self._write_nfo("tvshow.nfo", "https://thetvdb.com/?tab=series&id=81189\n")

        self.assertEqual(upgrade_nfo_file(path), "upgraded")

        root = ET.parse(path).getroot()
        self.assertEqual(root.tag, "tvshow")
        self.assertEqual(root.find("uniqueid[@type='tvdb']").get("default"), "true")
        self.assertEqual(root.find("uniqueid[@type='tvdb']").text, "81189")

    @patch("kodi_nfo_fiddler.requests.get")
    def test_upgrade_tvshow_nfo_leaves_file_unchanged_when_tmdb_has_no_match(self, mock_get):
        mock_get.return_value = self._tmdb_response({"tv_results": []})
        original = "https://www.imdb.com/title/tt0000001/\n"
        path = self._write_nfo("tvshow.nfo", original)

        self.assertEqual(upgrade_nfo_file(path), "failed")

        with open(path, encoding="utf-8") as nfo:
            self.assertEqual(nfo.read(), original)

    @patch.dict(os.environ, {}, clear=True)
    @patch('sys.stdout')
    def test_print_warning_colors_interactive_output(self, mock_stdout):
        mock_stdout.isatty.return_value = True

        print_warning("[!] A warning")

        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        self.assertIn("\033[33m[!] A warning\033[0m", output)

    @patch.dict(os.environ, {"NO_COLOR": ""}, clear=True)
    @patch('sys.stdout')
    def test_print_warning_respects_no_color(self, mock_stdout):
        mock_stdout.isatty.return_value = True

        print_warning("[!] A warning")

        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        self.assertNotIn("\033[", output)

    def test_find_sidecar_subtitles_matches_video_basename_and_languages(self):
        video_path = os.path.join(self.test_dir, "Movie.2024.mp4")
        sidecars = (
            "Movie.2024.en.srt",
            "Movie.2024.English.forced.ass",
            "Movie.2024.sv.srt",
            "Movie.2024.svenska.srt",
            "Other.Movie.en.srt",
            "Movie.2024.fr.srt",
        )
        for filename in sidecars:
            with open(os.path.join(self.test_dir, filename), "w") as subtitle:
                subtitle.write("subtitle")

        found = find_sidecar_subtitles(video_path)

        self.assertEqual(
            [os.path.basename(path) for path in found["en"]],
            ["Movie.2024.en.srt", "Movie.2024.English.forced.ass"],
        )
        self.assertEqual(
            [os.path.basename(path) for path in found["sv"]],
            ["Movie.2024.sv.srt", "Movie.2024.svenska.srt"],
        )

    @patch("kodi_nfo_fiddler.subprocess.run")
    def test_remux_mp4_prioritizes_english_subtitles_and_removes_source(self, mock_run):
        mp4_path = os.path.join(self.test_dir, "Movie.mp4")
        english_path = os.path.join(self.test_dir, "Movie.en.srt")
        swedish_path = os.path.join(self.test_dir, "Movie.sv.srt")
        for path in (mp4_path, english_path, swedish_path):
            with open(path, "w") as file:
                file.write("test")

        def create_output(command, **kwargs):
            output_index = command.index("-o") + 1
            with open(command[output_index], "w") as output:
                output.write("mkv")
            return MagicMock()

        mock_run.side_effect = create_output

        output_path = remux_mp4_to_mkv(mp4_path)

        self.assertIsNotNone(output_path)
        self.assertFalse(os.path.exists(mp4_path))
        self.assertTrue(os.path.exists(english_path))
        self.assertTrue(os.path.exists(swedish_path))
        command = mock_run.call_args.args[0]
        self.assertLess(command.index(english_path), command.index(swedish_path))
        self.assertIn("0:eng", command)
        self.assertIn("0:swe", command)
        self.assertEqual(command[command.index("--default-track-flag") + 1], "0:yes")
        self.assertEqual(command[command.index("--default-track-flag", command.index("--default-track-flag") + 1) + 1], "0:no")

    @patch("kodi_nfo_fiddler.subprocess.run", side_effect=subprocess.CalledProcessError(1, "mkvmerge"))
    def test_remux_mp4_failure_keeps_source(self, mock_run):
        mp4_path = os.path.join(self.test_dir, "Movie.mp4")
        with open(mp4_path, "w") as file:
            file.write("video")

        self.assertIsNone(remux_mp4_to_mkv(mp4_path))
        self.assertTrue(os.path.exists(mp4_path))

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
                },
                {
                    "type": "subtitles",
                    "properties": {
                        "language_ietf": "en-US"
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
        self.assertTrue(metadata["english_subtitles"])

    @patch('subprocess.run')
    def test_get_mkv_metadata_reports_missing_english_subtitles(self, mock_run):
        mock_run.return_value = MagicMock(stdout=json.dumps({
            "tracks": [{
                "type": "subtitles",
                "properties": {"language": "fra"}
            }]
        }), returncode=0)

        metadata = get_mkv_metadata("dummy_path.mkv")

        self.assertFalse(metadata["english_subtitles"])

    def test_sanitize_folder_name(self):
        raw_name = "The Movie: Director's! Cut (2024) (1080p, BluRay, DTS, 5.1)"
        expected = "The_Movie_-_Director's!_Cut_(2024)_(1080p,_BluRay,_DTS,_5.1)"

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
    def test_process_directory_skips_non_mkv_media(self, mock_tmdb):
        video_path = os.path.join(self.test_dir, "inception.avi")
        with open(video_path, "w") as video_file:
            video_file.write("test")

        with patch('builtins.print') as mock_print:
            process_directory(self.test_dir, is_root=True)

        self.assertTrue(os.path.exists(video_path))
        mock_tmdb.assert_not_called()
        self.assertTrue(any("Skipping non-MKV media file" in call.args[0] for call in mock_print.call_args_list))

    @patch("kodi_nfo_fiddler.search_tmdb")
    @patch("kodi_nfo_fiddler.remux_mp4_to_mkv")
    def test_process_directory_does_not_remux_mp4_without_flag(self, mock_remux, mock_tmdb):
        video_path = os.path.join(self.test_dir, "inception.mp4")
        with open(video_path, "w") as video_file:
            video_file.write("test")

        process_directory(self.test_dir, is_root=True)

        mock_remux.assert_not_called()
        self.assertTrue(os.path.exists(video_path))

    @patch("kodi_nfo_fiddler.search_tmdb")
    @patch("kodi_nfo_fiddler.get_mkv_metadata")
    @patch("kodi_nfo_fiddler.subprocess.run")
    def test_process_directory_remuxes_mp4_before_organizing(self, mock_run, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "AAC",
            "audio_channels": "2.0",
            "english_subtitles": True,
        }
        video_path = os.path.join(self.test_dir, "Inception.2010.mp4")
        subtitle_path = os.path.join(self.test_dir, "Inception.2010.en.srt")
        for path in (video_path, subtitle_path):
            with open(path, "w") as file:
                file.write("test")

        def create_output(command, **kwargs):
            with open(command[command.index("-o") + 1], "w") as output:
                output.write("mkv")
            return MagicMock()

        mock_run.side_effect = create_output

        process_directory(self.test_dir, is_root=True, remux_mp4=True)

        self.assertFalse(os.path.exists(video_path))
        self.assertTrue(os.path.exists(subtitle_path))
        organized_files = [
            filename for _, _, filenames in os.walk(self.test_dir)
            for filename in filenames
        ]
        self.assertTrue(any(filename.endswith(".mkv") for filename in organized_files))
        self.assertTrue(any(filename.endswith(".nfo") for filename in organized_files))
        mock_mkv.assert_called_once()

    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_removes_smaller_videos_in_subdirectory(self, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")
        movie_dir = os.path.join(self.test_dir, "movie")
        os.makedirs(movie_dir)
        large_path = os.path.join(movie_dir, "inception.mkv")
        small_path = os.path.join(movie_dir, "inception-trailer.mkv")
        with open(large_path, "wb") as video_file:
            video_file.write(b"a" * 200)
        with open(small_path, "wb") as video_file:
            video_file.write(b"a" * 50)

        processed_dir = process_directory(movie_dir)

        self.assertFalse(os.path.exists(small_path))
        self.assertEqual(
            [name for name in os.listdir(processed_dir) if name.lower().endswith((".mp4", ".mkv", ".avi", ".m4v", ".mov", ".flv", ".wmv"))],
            [os.path.basename(processed_dir) + ".mkv"]
        )

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_keeps_smaller_videos_in_input_root(self, mock_tmdb, mock_mkv):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }
        large_path = os.path.join(self.test_dir, "inception.mp4")
        small_path = os.path.join(self.test_dir, "inception.mkv")
        with open(large_path, "wb") as video_file:
            video_file.write(b"a" * 200)
        with open(small_path, "wb") as video_file:
            video_file.write(b"a" * 50)

        process_directory(self.test_dir, is_root=True)

        self.assertEqual(mock_tmdb.call_count, 1)
        self.assertEqual(
            sum(
                1 for _, _, filenames in os.walk(self.test_dir)
                for filename in filenames
                if filename.lower().endswith((".mp4", ".mkv"))
            ),
            2
        )

    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_removes_featurettes_folder(self, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")

        video_path = os.path.join(self.test_dir, "inception.mp4")
        featurettes_path = os.path.join(self.test_dir, "Featurettes")
        os.makedirs(featurettes_path)
        with open(video_path, "w") as video_file:
            video_file.write("test")
        with open(os.path.join(featurettes_path, "behind_the_scenes.mp4"), "w") as featurette:
            featurette.write("test")

        process_directory(self.test_dir, is_root=True)

        self.assertFalse(os.path.exists(featurettes_path))

    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_removes_sample_file_and_folder(self, mock_tmdb):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")

        video_path = os.path.join(self.test_dir, "inception.mp4")
        sample_file_path = os.path.join(self.test_dir, "Sample Trailer.mp4")
        sample_folder_path = os.path.join(self.test_dir, "sample-footage")
        with open(video_path, "w") as video_file:
            video_file.write("test")
        with open(sample_file_path, "w") as sample_file:
            sample_file.write("test")
        os.makedirs(sample_folder_path)
        with open(os.path.join(sample_folder_path, "clip.mp4"), "w") as sample_clip:
            sample_clip.write("test")

        process_directory(self.test_dir, is_root=True)

        self.assertFalse(os.path.exists(sample_file_path))
        self.assertFalse(os.path.exists(sample_folder_path))

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_warns_when_mkv_has_no_english_subtitles(self, mock_tmdb, mock_mkv):
        mock_tmdb.return_value = ("https://www.themoviedb.org/movie/27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1",
            "english_subtitles": False
        }

        video_path = os.path.join(self.test_dir, "inception.mkv")
        with open(video_path, "w") as video_file:
            video_file.write("test")

        with patch('builtins.print') as mock_print:
            process_directory(self.test_dir, is_root=True)

        self.assertTrue(any("No English subtitles found" in call.args[0] for call in mock_print.call_args_list))

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
            "<original_filename>mystery.mkv</original_filename>",
            nfo_contents
        )
        self.assertIn(
            "<original_directory>Mystery Movie (2024) BluRay</original_directory>",
            nfo_contents
        )
        self.assertNotIn("<!-- Original Filename:", nfo_contents)

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
    def test_process_directory_preserves_apostrophes_and_exclamation_marks(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = (
            "https://www.themoviedb.org/movie/568",
            "Mission's: Impossible!",
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

        expected_folder_name = "Mission's_-_Impossible!_(1996)_(1080p_Unknown_Source_DTS_5.1)"
        expected_folder_path = os.path.join(self.test_dir, expected_folder_name)
        expected_video_file = os.path.join(expected_folder_path, f"{expected_folder_name}.mkv")

        self.assertEqual(new_folder_path, expected_folder_path)
        self.assertTrue(os.path.exists(expected_video_file))

        nfo_path = os.path.join(expected_folder_path, f"{expected_folder_name}.nfo")
        with open(nfo_path, encoding="utf-8") as nfo_file:
            nfo_contents = nfo_file.read()

        self.assertIn("<title>Mission's: Impossible!</title>", nfo_contents)

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

    @patch('subprocess.run')
    def test_get_mkv_metadata_cropped_1080p(self, mock_run):
        """Verify that a slightly cropped 1916x1034 file maps to 1080p."""
        mock_stdout = json.dumps({
            "tracks": [{
                "type": "video",
                "properties": {
                    "display_dimensions": "1916x1034"
                }
            }]
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
