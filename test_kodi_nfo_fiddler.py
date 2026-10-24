import os
import json
import shutil
import tempfile
import unittest
import requests
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

from kodi_nfo_fiddler import (
    get_mkv_metadata,
    collect_metadata,
    parse_filename,
    sanitize_folder_name,
    build_new_name,
    search_tmdb,
    process_directory,
    print_warning,
    find_sidecar_subtitles,
    is_language,
    detect_source,
    classify_resolution,
    describe_audio,
    remux_mp4_to_mkv,
    upgrade_nfo_file,
    upgrade_nfo_files,
)

def _movie(tmdb_id, title, year):
    return {"tmdb_id": tmdb_id, "title": title, "year": year, "imdb_id": None}

class TempDirTestCase(unittest.TestCase):

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


class NfoUpgradeTests(TempDirTestCase):

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


class ConsoleOutputTests(TempDirTestCase):

    @patch.dict(os.environ, {}, clear=True)
    @patch('sys.stdout')
    def test_print_warning_colors_interactive_output(self, mock_stdout):
        mock_stdout.isatty.return_value = True

        print_warning("A warning")

        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        self.assertIn("\033[33m[!] A warning\033[0m", output)

    @patch.dict(os.environ, {"NO_COLOR": ""}, clear=True)
    @patch('sys.stdout')
    def test_print_warning_respects_no_color(self, mock_stdout):
        mock_stdout.isatty.return_value = True

        print_warning("A warning")

        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        self.assertNotIn("\033[", output)


class SubtitleAndRemuxTests(TempDirTestCase):

    def test_is_language_matches_tags_and_regional_variants(self):
        for tag in ("en", "eng", "English", "en-US", "EN-gb"):
            self.assertTrue(is_language(tag, "en"), tag)
        for tag in ("sv", "swe", "sv-SE"):
            self.assertTrue(is_language(tag, "sv"), tag)
        for tag in ("", "fra", "und", "enm"):
            self.assertFalse(is_language(tag, "en"), tag)

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
            return MagicMock(returncode=0)

        mock_run.side_effect = create_output

        output_path = remux_mp4_to_mkv(mp4_path)

        self.assertIsNotNone(output_path)
        self.assertFalse(os.path.exists(mp4_path))
        self.assertFalse(os.path.exists(english_path))
        self.assertFalse(os.path.exists(swedish_path))
        command = mock_run.call_args.args[0]
        self.assertLess(command.index(english_path), command.index(swedish_path))
        self.assertIn("0:eng", command)
        self.assertIn("0:swe", command)
        self.assertEqual(command[command.index("--default-track-flag") + 1], "0:yes")
        self.assertEqual(command[command.index("--default-track-flag", command.index("--default-track-flag") + 1) + 1], "0:no")

    @patch("kodi_nfo_fiddler.subprocess.run")
    def test_remux_mp4_failure_keeps_source_and_subtitles(self, mock_run):
        mock_run.return_value = MagicMock(returncode=2, stdout="Error: boom", stderr="")
        mp4_path = os.path.join(self.test_dir, "Movie.mp4")
        subtitle_path = os.path.join(self.test_dir, "Movie.en.srt")
        for path in (mp4_path, subtitle_path):
            with open(path, "w") as file:
                file.write("video")

        self.assertIsNone(remux_mp4_to_mkv(mp4_path))
        self.assertTrue(os.path.exists(mp4_path))
        self.assertTrue(os.path.exists(subtitle_path))

    @patch("kodi_nfo_fiddler.subprocess.run")
    def test_remux_mp4_accepts_mkvmerge_warnings(self, mock_run):
        mp4_path = os.path.join(self.test_dir, "Movie.mp4")
        with open(mp4_path, "w") as file:
            file.write("video")

        def create_output(command, **kwargs):
            with open(command[command.index("-o") + 1], "w") as output:
                output.write("mkv")
            return MagicMock(returncode=1, stdout="Warning: odd timestamps", stderr="")

        mock_run.side_effect = create_output

        with patch("builtins.print") as mock_print:
            output_path = remux_mp4_to_mkv(mp4_path)

        self.assertIsNotNone(output_path)
        self.assertFalse(os.path.exists(mp4_path))
        self.assertTrue(any("warnings" in call.args[0] for call in mock_print.call_args_list))


class MkvMetadataTests(TempDirTestCase):

    def test_classify_resolution_buckets(self):
        self.assertEqual(classify_resolution(3840, 1600), "2160p")
        self.assertEqual(classify_resolution(1920, 800), "1080p")
        self.assertEqual(classify_resolution(1280, 536), "720p")
        self.assertEqual(classify_resolution(720, 400), "SD")
        self.assertEqual(classify_resolution(640, 360), "360p")

    def test_describe_audio_names_codec_and_channels(self):
        cases = (
            ("A_DTS", 6, ("DTS", "5.1", False)),
            ("A_EAC3", 8, ("E-AC3", "7.1", False)),
            ("A_AC3", 2, ("AC3", "2.0", False)),
            ("A_TRUEHD", 10, ("TrueHD", "10.0", False)),
            ("A_VORBIS", 2, ("Vorbis", "2.0", False)),
            ("MP3", 2, ("MP3", "2.0", False)),
            ("MP2", 2, ("MP2", "2.0", False)),
            ("PCM", 2, ("PCM", "2.0", False)),
            ("E-AC-3 Atmos", 6, ("E-AC3", "5.1", True)),
            ("TrueHD Atmos", 8, ("TrueHD", "7.1", True)),
            ("A_WAVPACK4", None, ("WAVPACK4", None, False)),
        )
        for codec, channels, expected in cases:
            with self.subTest(codec=codec):
                track = {"codec": codec, "properties": {"audio_channels": channels}}
                self.assertEqual(describe_audio(track), expected)

    @patch('subprocess.run', side_effect=FileNotFoundError("mkvmerge"))
    def test_get_mkv_metadata_warns_and_returns_none_when_mkvmerge_fails(self, mock_run):
        with patch('builtins.print') as mock_print:
            self.assertIsNone(get_mkv_metadata("dummy_path.mkv"))

        self.assertTrue(any("Could not read MKV metadata" in call.args[0] for call in mock_print.call_args_list))

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
        self.assertFalse(metadata["audio_atmos"])
        self.assertTrue(metadata["english_subtitles"])

    @patch('subprocess.run')
    def test_get_mkv_metadata_flags_atmos(self, mock_run):
        mock_run.return_value = MagicMock(stdout=json.dumps({
            "tracks": [{
                "type": "audio",
                "codec": "TrueHD Atmos",
                "properties": {"audio_channels": 8}
            }]
        }), returncode=0)

        metadata = get_mkv_metadata("dummy_path.mkv")

        self.assertEqual(metadata["audio_codec"], "TrueHD")
        self.assertTrue(metadata["audio_atmos"])

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

    @patch('subprocess.run')
    def test_get_mkv_metadata_widescreen_1080p_at_1920x802(self, mock_run):
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


class FilenameParsingTests(TempDirTestCase):

    def test_detect_source_normalizes_and_returns_none_when_missing(self):
        self.assertEqual(detect_source("Movie 2024 1080p WEB-DL"), "WEBRip")
        self.assertEqual(detect_source("movie bdrip x264"), "BluRay")
        self.assertIsNone(detect_source("Movie 2024 1080p"))

    def test_detect_source_handles_spelling_variants(self):
        expected = {
            "Movie 2024 Blu Ray": "BluRay",
            "Movie 2024 Blu-Ray": "BluRay",
            "Movie 2024 1080p BDRemux": "BluRay",
            "Movie 2024 2160p UHD BluRay REMUX": "BluRay",
            "Movie 2024 WEBDL": "WEBRip",
            "Movie 2024 HDRip": "WEBRip",
            "Movie 2024 DVDR": "DVD",
            "Show 2024 PDTV": "PDTV",
            "Movie.2024.1080p.Blu.Ray": "BluRay",
            "Movie_2024_WEB_DL": "WEBRip",
        }
        for text, source in expected.items():
            with self.subTest(text=text):
                self.assertEqual(detect_source(text), source)

    def test_parse_filename_cuts_title_at_any_source_or_resolution_tag_without_year(self):
        for name in ("Some Movie 720p.mkv", "Some Movie HDTV x264.mkv", "Some Movie.WEB-DL.mkv", "Some.Movie.Blu-Ray.mkv"):
            with self.subTest(name=name):
                self.assertEqual(parse_filename(name, name)["title"], "Some Movie")

    def test_parse_filename_uses_none_for_unknown_year_and_source(self):
        metadata = parse_filename("Some Movie.mkv", "Some Movie.mkv")
        self.assertIsNone(metadata["year"])
        self.assertIsNone(metadata["source"])

    def test_build_new_name_appends_atmos_after_channels(self):
        metadata = {
            "resolution": "2160p", "source": "BluRay",
            "audio_codec": "TrueHD", "audio_channels": "7.1", "audio_atmos": True,
        }
        self.assertEqual(
            build_new_name(metadata, "Inception", "2010"),
            "Inception_(2010)_(2160p_BluRay_TrueHD_7.1_Atmos)",
        )
        metadata["audio_atmos"] = False
        self.assertEqual(
            build_new_name(metadata, "Inception", "2010"),
            "Inception_(2010)_(2160p_BluRay_TrueHD_7.1)",
        )

    def test_sanitize_folder_name(self):
        raw_name = "The Movie: Director's! Cut (2024) (1080p, BluRay, DTS, 5.1)"
        expected = "The_Movie_-_Director's!_Cut_(2024)_(1080p,_BluRay,_DTS,_5.1)"

        sanitized = sanitize_folder_name(raw_name)
        self.assertEqual(sanitized, expected)

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_collect_metadata_strict_fallback_when_not_mkv(self, mock_mkv):
        """Ensure non-MKV files only parse Title, Year, and Source, defaulting technical meta."""
        metadata = collect_metadata("Inception.2010.1080p.BluRay.DTS.5.1.mp4", "dummy_path.mp4")

        mock_mkv.assert_not_called()
        self.assertEqual(metadata["title"], "Inception")
        self.assertEqual(metadata["year"], "2010")
        self.assertEqual(metadata["source"], "BluRay")
        # Technical metadata must be unknown (None) because it's not an MKV
        self.assertIsNone(metadata["resolution"])
        self.assertIsNone(metadata["audio_codec"])
        self.assertIsNone(metadata["audio_channels"])

    def test_parse_filename_ignores_no_hit_prefix(self):
        metadata = parse_filename(
            "no_hit_Inception.2010.1080p.BluRay.mp4",
            "no_hit_Inception.2010.1080p.BluRay.mp4"
        )

        self.assertEqual(metadata["title"], "Inception")
        self.assertEqual(metadata["year"], "2010")

    def test_parse_filename_normalizes_web_sources(self):
        for source in ("WEB-DL", "WEB", "WEBRip"):
            with self.subTest(source=source):
                metadata = parse_filename(
                    f"Movie.2024.1080p.{source}.mkv",
                    "Movie.2024.1080p.{0}.mkv".format(source)
                )
                self.assertEqual(metadata["source"], "WEBRip")

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_collect_metadata_reads_tracks_for_mkv_path_even_with_directory_name(self, mock_mkv):
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}

        metadata = collect_metadata("Mystery Movie (2024) BluRay", "folder/no_hit_x.mkv")

        mock_mkv.assert_called_once_with("folder/no_hit_x.mkv")
        self.assertEqual(metadata["resolution"], "1080p")
        self.assertEqual(metadata["title"], "Mystery Movie")

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


class ProcessDirectoryTests(TempDirTestCase):

    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_removes_txt_and_jpg_files(self, mock_tmdb):
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")

        video_path = os.path.join(self.test_dir, "inception.BluRay.mp4")
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
        video_path = os.path.join(self.test_dir, "inception.BluRay.mp4")
        with open(video_path, "w") as video_file:
            video_file.write("test")

        process_directory(self.test_dir, is_root=True)

        mock_remux.assert_not_called()
        self.assertTrue(os.path.exists(video_path))

    @patch("kodi_nfo_fiddler.search_tmdb")
    @patch("kodi_nfo_fiddler.get_mkv_metadata")
    @patch("kodi_nfo_fiddler.subprocess.run")
    def test_process_directory_remuxes_mp4_before_organizing(self, mock_run, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "AAC",
            "audio_channels": "2.0",
            "english_subtitles": True,
        }
        video_path = os.path.join(self.test_dir, "Inception.2010.BluRay.mp4")
        subtitle_path = os.path.join(self.test_dir, "Inception.2010.BluRay.en.srt")
        for path in (video_path, subtitle_path):
            with open(path, "w") as file:
                file.write("test")

        def create_output(command, **kwargs):
            with open(command[command.index("-o") + 1], "w") as output:
                output.write("mkv")
            return MagicMock(returncode=0)

        mock_run.side_effect = create_output

        process_directory(self.test_dir, is_root=True, remux_mp4=True)

        self.assertFalse(os.path.exists(video_path))
        self.assertFalse(os.path.exists(subtitle_path))
        organized_files = [
            filename for _, _, filenames in os.walk(self.test_dir)
            for filename in filenames
        ]
        self.assertTrue(any(filename.endswith(".mkv") for filename in organized_files))
        self.assertTrue(any(filename.endswith(".nfo") for filename in organized_files))
        mock_mkv.assert_called_once()

    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    @patch('kodi_nfo_fiddler.search_tmdb')
    def test_process_directory_removes_smaller_videos_in_subdirectory(self, mock_tmdb, mock_mkv):
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        movie_dir = os.path.join(self.test_dir, "movie")
        os.makedirs(movie_dir)
        large_path = os.path.join(movie_dir, "inception.BluRay.mkv")
        small_path = os.path.join(movie_dir, "inception.BluRay-trailer.mkv")
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
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }
        large_path = os.path.join(self.test_dir, "inception.BluRay.mp4")
        small_path = os.path.join(self.test_dir, "inception.BluRay.mkv")
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
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")

        video_path = os.path.join(self.test_dir, "inception.BluRay.mp4")
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
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")

        video_path = os.path.join(self.test_dir, "inception.BluRay.mp4")
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
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1",
            "english_subtitles": False
        }

        video_path = os.path.join(self.test_dir, "inception.BluRay.mkv")
        with open(video_path, "w") as video_file:
            video_file.write("test")

        with patch('builtins.print') as mock_print:
            process_directory(self.test_dir, is_root=True)

        self.assertTrue(any("No English subtitles found" in call.args[0] for call in mock_print.call_args_list))

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_single_file_renames_parent_folder(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Inception_Raw_Folder")
        os.makedirs(movie_folder)
        video_file_path = os.path.join(movie_folder, "inception.BluRay.mkv")

        with open(video_file_path, "w") as f:
            f.write("fake video data")

        new_folder_path = process_directory(movie_folder)

        expected_folder_name = "Inception_(2010)_(1080p_BluRay_DTS_5.1)"
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
        with open(os.path.join(movie_folder, "mystery.2024.mkv"), "w") as video_file:
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
            "<original_filename>mystery.2024.mkv</original_filename>",
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
            _movie("123", "Mystery Movie", "2024")
        ]
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Mystery Movie (2024) BluRay")
        os.makedirs(movie_folder)
        with open(os.path.join(movie_folder, "mystery.2024.mkv"), "w") as video_file:
            video_file.write("fake video data")

        no_hit_path = process_directory(movie_folder)
        recovered_path = process_directory(no_hit_path)

        self.assertEqual(mock_tmdb.call_args_list[1].args[:2], ("Mystery Movie", "2024"))
        self.assertEqual(os.path.basename(recovered_path).startswith("no_hit_"), False)
        self.assertIn("Mystery_Movie_(2024)", os.path.basename(recovered_path))
        self.assertIn("1080p_BluRay_DTS_5.1", os.path.basename(recovered_path))

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_skips_file_when_destination_exists(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}

        for name, content in (("first.2010.BluRay.mkv", "first"), ("second.2010.BluRay.mkv", "second")):
            with open(os.path.join(self.test_dir, name), "w") as video_file:
                video_file.write(content)

        process_directory(self.test_dir, is_root=True)

        organized_name = "Inception_(2010)_(1080p_BluRay_DTS_5.1)"
        organized_file = os.path.join(self.test_dir, organized_name, f"{organized_name}.mkv")
        with open(organized_file) as video_file:
            winner = video_file.read()
        loser = "second" if winner == "first" else "first"
        self.assertIn(winner, ("first", "second"))
        with open(os.path.join(self.test_dir, f"{loser}.2010.BluRay.mkv")) as video_file:
            self.assertEqual(video_file.read(), loser)

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_uses_largest_video_in_subdirectory(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        movie_dir = os.path.join(self.test_dir, "Inception")
        os.makedirs(movie_dir)
        for name, size in (("a.2010.BluRay.mp4", 60), ("z.2010.BluRay.mkv", 150)):
            with open(os.path.join(movie_dir, name), "wb") as video_file:
                video_file.write(b"x" * size)

        new_dir = process_directory(movie_dir)

        organized = os.path.join(new_dir, f"{os.path.basename(new_dir)}.mkv")
        self.assertEqual(os.path.getsize(organized), 150)
        self.assertTrue(os.path.exists(os.path.join(new_dir, "a.2010.BluRay.mp4")))

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_skips_folder_with_similar_sized_videos(self, mock_mkv, mock_tmdb):
        movie_dir = os.path.join(self.test_dir, "Inception")
        os.makedirs(movie_dir)
        for name, size in (("a.2010.BluRay.mkv", 100), ("b.2010.BluRay.mkv", 150)):
            with open(os.path.join(movie_dir, name), "wb") as video_file:
                video_file.write(b"x" * size)

        self.assertEqual(process_directory(movie_dir), movie_dir)

        self.assertEqual(sorted(os.listdir(movie_dir)), ["a.2010.BluRay.mkv", "b.2010.BluRay.mkv"])
        mock_tmdb.assert_not_called()

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_skips_rename_when_a_tag_is_unknown(self, mock_mkv, mock_tmdb):
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        movie_dir = os.path.join(self.test_dir, "Inception 2010")
        os.makedirs(movie_dir)
        video_path = os.path.join(movie_dir, "inception.mkv")
        with open(video_path, "w") as video_file:
            video_file.write("x")

        result = process_directory(movie_dir)

        self.assertEqual(result, movie_dir)
        self.assertTrue(os.path.exists(video_path))
        self.assertEqual(os.listdir(movie_dir), ["inception.mkv"])
        mock_tmdb.assert_not_called()

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_nfo_and_folder_use_tmdb_year_not_filename_year(self, mock_mkv, mock_tmdb):
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        movie_dir = os.path.join(self.test_dir, "Inception 2009 BluRay")
        os.makedirs(movie_dir)
        with open(os.path.join(movie_dir, "inception.2009.BluRay.mkv"), "w") as video_file:
            video_file.write("x")

        new_dir = process_directory(movie_dir)

        self.assertEqual(os.path.basename(new_dir), "Inception_(2010)_(1080p_BluRay_DTS_5.1)")
        nfo_files = [name for name in os.listdir(new_dir) if name.endswith(".nfo")]
        self.assertEqual(len(nfo_files), 1)
        self.assertEqual(ET.parse(os.path.join(new_dir, nfo_files[0])).getroot().findtext("year"), "2010")

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_skips_no_hit_without_year(self, mock_mkv, mock_tmdb):
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        mock_tmdb.return_value = None
        movie_dir = os.path.join(self.test_dir, "Obscure Film")
        os.makedirs(movie_dir)
        with open(os.path.join(movie_dir, "obscure.BluRay.mkv"), "w") as video_file:
            video_file.write("y")

        self.assertEqual(process_directory(movie_dir), movie_dir)

        self.assertEqual(os.listdir(movie_dir), ["obscure.BluRay.mkv"])

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_skips_hit_when_tmdb_has_no_release_year(self, mock_mkv, mock_tmdb):
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        mock_tmdb.return_value = _movie("27205", "Inception", "")
        movie_dir = os.path.join(self.test_dir, "Inception 2010")
        os.makedirs(movie_dir)
        with open(os.path.join(movie_dir, "inception.2010.BluRay.mkv"), "w") as video_file:
            video_file.write("x")

        self.assertEqual(process_directory(movie_dir), movie_dir)

        self.assertEqual(os.listdir(movie_dir), ["inception.2010.BluRay.mkv"])

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_preserves_apostrophes_and_exclamation_marks(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = _movie("568", "Mission's: Impossible!", "1996")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "DTS",
            "audio_channels": "5.1"
        }

        movie_folder = os.path.join(self.test_dir, "Mission_Raw_Folder")
        os.makedirs(movie_folder)
        with open(os.path.join(movie_folder, "mission.BluRay.mkv"), "w") as video_file:
            video_file.write("fake video data")

        new_folder_path = process_directory(movie_folder)

        expected_folder_name = "Mission's_-_Impossible!_(1996)_(1080p_BluRay_DTS_5.1)"
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
        mock_tmdb.return_value = _movie("278", "The Chronicles of Riddick", "2004")
        mock_mkv.return_value = {
            "resolution": "1080p",
            "audio_codec": "AAC",
            "audio_channels": "5.1"
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

    @patch('kodi_nfo_fiddler.search_tmdb')
    @patch('kodi_nfo_fiddler.get_mkv_metadata')
    def test_process_directory_warns_and_continues_when_rename_fails(self, mock_mkv, mock_tmdb):
        mock_tmdb.return_value = _movie("27205", "Inception", "2010")
        mock_mkv.return_value = {"resolution": "1080p", "audio_codec": "DTS", "audio_channels": "5.1"}
        video_path = os.path.join(self.test_dir, "inception.2010.BluRay.mkv")
        with open(video_path, "w") as video_file:
            video_file.write("x")

        with patch("kodi_nfo_fiddler.os.rename", side_effect=OSError("denied")):
            process_directory(self.test_dir, is_root=True)

        self.assertTrue(os.path.exists(video_path))


class TmdbSearchTests(TempDirTestCase):

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

        self.assertEqual(result, _movie(683127, "Earwig and the Witch", "2021"))
        fallback_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertNotIn("year", fallback_params)
        self.assertNotIn("primary_release_year", fallback_params)

    @patch('kodi_nfo_fiddler.requests.get')
    def test_search_tmdb_omits_year_filters_for_unknown_year(self, mock_get):
        mock_get.return_value = self._tmdb_response({
            "results": [{"id": 27205, "title": "Inception", "release_date": "2010-07-15"}]
        })

        result = search_tmdb("Inception", None)

        self.assertEqual(result, _movie(27205, "Inception", "2010"))
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("year", params)
        self.assertNotIn("primary_release_year", params)
        self.assertNotIn("api_key", params)

    @patch('kodi_nfo_fiddler.requests.get', side_effect=requests.ConnectionError("down"))
    def test_search_tmdb_warns_and_returns_none_on_network_error(self, mock_get):
        with patch("builtins.print") as mock_print:
            self.assertIsNone(search_tmdb("Inception", "2010"))
        self.assertTrue(any("TMDB search failed" in call.args[0] for call in mock_print.call_args_list))


if __name__ == '__main__':
    unittest.main()
