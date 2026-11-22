"""Recording a live (recorder.py): the stream address, the file and FFmpeg's process."""

import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from . import support

recorder = support.load("recorder")
FAKE_FFMPEG = [sys.executable, str(Path(__file__).with_name("fake_ffmpeg.py"))]


def wait_until(condition, timeout=10):
	end = time.monotonic() + timeout
	while time.monotonic() < end:
		if condition():
			return True
		time.sleep(0.02)
	return False


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
			recorder.file_path(folder, "ho:st?", "audio", now).name, "2026-10-15 20-30-05 host.mp3"
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
		self.assertIn("-c copy -movflags +hybrid_fragmented -flush_packets 1", lines[1])

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


class Joining(unittest.TestCase):
	def setUp(self):
		self.folder = Path(tempfile.mkdtemp(dir=support.ROOT))
		self.first = self.folder / "2026-11-22 00-56-09 it's me.mp4"
		self.files = [self.first, recorder.part_path(self.first, 2), recorder.part_path(self.first, 3)]
		for number, path in enumerate(self.files, 1):
			path.write_text(f"part {number}\n", encoding="utf-8")

	def test_the_parts_are_joined_into_the_first(self):
		self.assertTrue(recorder.join(FAKE_FFMPEG, self.files))
		self.assertEqual([path.name for path in self.folder.iterdir()], [self.first.name])
		self.assertEqual(self.first.read_text(encoding="utf-8"), "part 1\npart 2\npart 3\n")

	def test_parts_ffmpeg_cannot_join_stay(self):
		os.environ["FAKE_FFMPEG_JOIN_FAILS"] = "1"
		try:
			self.assertFalse(recorder.join(FAKE_FFMPEG, self.files))
		finally:
			del os.environ["FAKE_FFMPEG_JOIN_FAILS"]
		self.assertEqual(sorted(self.folder.iterdir()), sorted(self.files))
		self.assertEqual(self.first.read_text(encoding="utf-8"), "part 1\n")


class StartingAgain(unittest.TestCase):
	# F45: on 2026-11-22 TikTok cut the stream after 27 minutes; FFmpeg ended and the
	# rest of the live, 2 h 13 min, was not recorded.
	def setUp(self):
		self.folder = Path(tempfile.mkdtemp(dir=support.ROOT))
		ffmpeg = support.load("ffmpeg_setup")
		self.addCleanup(setattr, ffmpeg, "executable", ffmpeg.executable)
		ffmpeg.executable = lambda: FAKE_FFMPEG
		for name, value in (("SETTLE", 0.3), ("WATCH", 0.05), ("RESTART_PAUSE", 0.05), ("RESTART_TRIES", 3)):
			self.addCleanup(setattr, recorder, name, getattr(recorder, name))
			setattr(recorder, name, value)

	def recording(self, *addresses):
		"""A recording whose room info gives these stream addresses in turn, the last from then on."""
		answers = list(addresses)

		def info(username):
			address = answers.pop(0) if len(answers) > 1 else answers[0]
			return room_info({"hd": address})

		self.started, self.lost = [], []
		live = recorder.LiveRecording(room_info=info)
		live.start("host", "video", self.folder, self.started.append, lambda: self.lost.append(True))
		self.assertTrue(wait_until(lambda: self.started), "not started")
		return live

	def test_ffmpeg_ending_by_itself_is_started_again_and_the_parts_joined(self):
		live = self.recording("https://cdn/cut.flv", "https://cdn/hd.flv")
		# The second part counts once FFmpeg has settled; one stopped before is dropped.
		self.assertTrue(wait_until(lambda: len(live._parts.files) == 2), "no second part")
		self.assertTrue(live.active)
		self.assertTrue(live.stop())
		self.assertTrue(wait_until(lambda: len(list(self.folder.iterdir())) == 1), "not joined")
		(recording,) = self.folder.iterdir()
		self.assertRegex(recording.name, r"^\d{4}-\d\d-\d\d \d\d-\d\d-\d\d host\.mp4$")
		lines = recording.read_text(encoding="utf-8").splitlines()
		self.assertEqual(
			[line for line in lines if line in ("recording", "cut", "done")],
			["recording", "cut", "recording", "done"],
		)
		self.assertIn("https://cdn/cut.flv", lines[1])
		self.assertIn("https://cdn/hd.flv", lines[4])
		self.assertEqual(self.lost, [])

	def test_a_stream_that_cannot_be_opened_again_ends_the_recording(self):
		live = self.recording("https://cdn/cut.flv", "https://cdn/fail.flv")
		self.assertTrue(wait_until(lambda: self.lost), "not given up")
		self.assertFalse(live.active)
		self.assertFalse(live.stop())
		(recording,) = self.folder.iterdir()
		self.assertEqual(recording.read_text(encoding="utf-8").splitlines()[-1], "cut")


if __name__ == "__main__":
	unittest.main()
