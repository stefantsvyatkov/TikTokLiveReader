"""Recording a live (recorder.py): the stream address, the file and FFmpeg's process."""

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from . import support

recorder = support.load("recorder")
FAKE_FFMPEG = [sys.executable, str(Path(__file__).with_name("fake_ffmpeg.py"))]


def room_info(qualities=None, flv_pull_url=None):
	"""Room info with the stream data TikTok gives: quality name -> FLV address."""
	data = {name: {"main": {"flv": url}} for name, url in (qualities or {}).items()}
	stream = {"live_core_sdk_data": {"pull_data": {"stream_data": json.dumps({"data": data})}}}
	if flv_pull_url:
		stream["flv_pull_url"] = flv_pull_url
	return {"stream_url": stream}


class StreamAddress(unittest.TestCase):
	def test_video_is_the_hd_stream_and_audio_the_audio_only_one(self):
		info = room_info({"hd": "https://cdn/hd.flv", "ao": "https://cdn/ao.flv"})
		self.assertEqual(recorder.stream_url(info, "video"), "https://cdn/hd.flv")
		self.assertEqual(recorder.stream_url(info, "audio"), "https://cdn/ao.flv")

	def test_video_falls_back_to_another_video_quality(self):
		info = room_info({"sd": "https://cdn/sd.flv", "ao": "https://cdn/ao.flv"})
		self.assertEqual(recorder.stream_url(info, "video"), "https://cdn/sd.flv")

	def test_without_stream_data_video_takes_the_plain_flv_address(self):
		info = {"stream_url": {"flv_pull_url": {"HD1": "https://cdn/plain.flv"}}}
		self.assertEqual(recorder.stream_url(info, "video"), "https://cdn/plain.flv")

	def test_no_address_without_a_stream(self):
		self.assertIsNone(recorder.stream_url({}, "video"))
		self.assertIsNone(recorder.stream_url(room_info({"hd": "https://cdn/hd.flv"}), "audio"))


class FileName(unittest.TestCase):
	def test_named_as_archives_with_the_quality_s_file_type(self):
		now = datetime.datetime(2026, 10, 15, 20, 30, 5)
		folder = Path("C:/Videos/TikTok live")
		self.assertEqual(
			recorder.file_path(folder, "host", "video", now).name, "2026-10-15 20-30-05 host.mp4"
		)
		self.assertEqual(
			recorder.file_path(folder, "ho:st?", "audio", now).name, "2026-10-15 20-30-05 host.m4a"
		)


class Process(unittest.TestCase):
	def setUp(self):
		self.folder = Path(tempfile.mkdtemp(dir=support.ROOT))
		self.path = self.folder / "live.mp4"

	def test_ffmpeg_copies_the_stream_until_stopped(self):
		rec = recorder.Recorder(FAKE_FFMPEG)
		self.assertTrue(rec.start("https://cdn/hd.flv", self.path, settle=0.5))
		self.assertTrue(rec.recording)
		rec.stop()
		self.assertFalse(rec.recording)
		lines = self.path.read_text(encoding="utf-8").splitlines()
		self.assertEqual((lines[0], lines[-1]), ("recording", "done"))
		self.assertIn("-c copy -movflags +frag_keyframe+empty_moov+default_base_moof", lines[1])

	def test_an_ffmpeg_that_ends_at_once_is_a_failure_with_its_error_logged(self):
		del support.logged[:]
		rec = recorder.Recorder(FAKE_FFMPEG)
		self.assertFalse(rec.start("https://cdn/fail.flv", self.path, settle=5))
		self.assertFalse(rec.recording)
		self.assertTrue(any("404 Not Found" in text for level, text in support.logged))

	def test_an_ffmpeg_that_does_not_finish_is_stopped(self):
		os.environ["FAKE_FFMPEG_DEAF"] = "1"
		try:
			rec = recorder.Recorder(FAKE_FFMPEG)
			self.assertTrue(rec.start("https://cdn/hd.flv", self.path, settle=0.5))
			rec.stop(timeout=0.5)
			self.assertFalse(rec.recording)
		finally:
			del os.environ["FAKE_FFMPEG_DEAF"]

	def test_a_missing_ffmpeg_is_a_failure(self):
		rec = recorder.Recorder(self.folder / "no-ffmpeg.exe")
		self.assertFalse(rec.start("https://cdn/hd.flv", self.path, settle=0.5))


if __name__ == "__main__":
	unittest.main()
