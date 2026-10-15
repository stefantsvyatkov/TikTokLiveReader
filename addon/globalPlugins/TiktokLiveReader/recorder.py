"""Recording a live with FFmpeg: the stream TikTok sends viewers (the host's
camera and microphone, without comments or gift animations) copied into a file
by FFmpeg in its own process; NVDA only starts and stops it (docs/dev/plan.md)."""

import datetime
import json
import subprocess
import threading
from pathlib import Path

from logHandler import log

from . import ffmpeg_setup, settings, store

# The settings' quality names, TikTok's for them in the stream data, and the file type.
TIKTOK_QUALITIES = {"video": "hd", "audio": "ao"}
EXTENSIONS = {"video": ".mp4", "audio": ".m4a"}
# Fragmented MP4, so that a file cut short (NVDA closing, a crash) still plays.
COPY = ["-c", "copy", "-movflags", "+frag_keyframe+empty_moov+default_base_moof"]
CREATE_NO_WINDOW = 0x08000000
# How long FFmpeg is watched after starting: a wrong address ends it at once.
SETTLE = 2.0
LOG_PATH = settings.CONFIG_DIR / "tiktokLiveReader-ffmpeg.log"


def stream_url(room_info, quality):
	"""The FLV address of the live's stream in ``quality`` ("video" or "audio"),
	from the room info; None when it has none."""
	stream = (room_info or {}).get("stream_url") or {}
	try:
		data = json.loads(stream["live_core_sdk_data"]["pull_data"]["stream_data"])["data"]
	except (KeyError, TypeError, ValueError):
		data = {}
	wanted = TIKTOK_QUALITIES.get(quality, TIKTOK_QUALITIES["video"])
	names = [wanted]
	if wanted != "ao":
		names += [name for name in data if name not in (wanted, "ao")]
	for name in names:
		url = ((data.get(name) or {}).get("main") or {}).get("flv")
		if url:
			return url
	if wanted != "ao":
		for url in (stream.get("flv_pull_url") or {}).values():
			if url:
				return url
	return None


def file_path(folder, username, quality, now=None):
	"""``folder``/<date time host>.mp4 (.m4a for audio), named as archives are."""
	stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H-%M-%S")
	host = store.safe_name(username) or "unknown"
	return Path(folder) / f"{stamp} {host}{EXTENSIONS.get(quality, EXTENSIONS['video'])}"


class Recorder:
	"""One FFmpeg process copying a stream into a file. ``command`` is FFmpeg's
	path, or a list that starts FFmpeg (the tests' stand-in)."""

	def __init__(self, command):
		self._command = [str(command)] if isinstance(command, (str, Path)) else list(command)
		self._process = None
		self._lock = threading.Lock()
		self.path = None

	@property
	def recording(self):
		process = self._process
		return process is not None and process.poll() is None

	def start(self, url, path, settle=None):
		"""Copy ``url`` into ``path``; False when FFmpeg could not start or ended
		within ``settle`` seconds (its error is in NVDA's log)."""
		path = Path(path)
		settle = SETTLE if settle is None else settle
		with self._lock:
			if self.recording:
				return True
			try:
				path.parent.mkdir(parents=True, exist_ok=True)
				with open(LOG_PATH, "wb") as errors:
					self._process = subprocess.Popen(
						[
							*self._command,
							"-hide_banner",
							"-loglevel",
							"error",
							"-y",
							"-i",
							url,
							*COPY,
							str(path),
						],
						stdin=subprocess.PIPE,
						stdout=subprocess.DEVNULL,
						stderr=errors,
						creationflags=CREATE_NO_WINDOW,
					)
			except OSError:
				log.warning("TikTok Live Reader: FFmpeg could not start", exc_info=True)
				self._process = None
				return False
			self.path = path
		try:
			self._process.wait(settle)
		except subprocess.TimeoutExpired:
			return True
		log.warning(f"TikTok Live Reader: FFmpeg ended at once: {_errors()}")
		return False

	def stop(self, timeout=5.0):
		"""End the recording: FFmpeg is asked to finish ("q"), then stopped."""
		with self._lock:
			process, self._process = self._process, None
		if process is None:
			return
		if process.poll() is None:
			try:
				process.stdin.write(b"q")
				process.stdin.flush()
				process.stdin.close()
			except OSError:
				pass
			try:
				process.wait(timeout)
			except subprocess.TimeoutExpired:
				process.kill()
				process.wait()
		elif process.returncode:
			log.warning(f"TikTok Live Reader: FFmpeg stopped with {process.returncode}: {_errors()}")


class LiveRecording:
	"""The plugin's recording: started with the live's room info in a worker
	thread, so the room request and FFmpeg's start never hold NVDA; one at a time.
	``room_info(username)`` is tiktok_adapter's (the tests' stand-in)."""

	def __init__(self, room_info=None):
		self._room_info = room_info
		self._recorder = None
		self._starting = None
		self._lock = threading.Lock()

	@property
	def active(self):
		"""Recording, or starting to."""
		recorder = self._recorder
		return self._starting is not None or (recorder is not None and recorder.recording)

	def start(self, username, quality, folder, done):
		"""Start recording; ``done(started)`` is called from the worker thread."""
		with self._lock:
			if self.active:
				return
			attempt = self._starting = object()
		threading.Thread(
			target=self._start, args=(attempt, username, quality, folder, done), daemon=True
		).start()

	def _start(self, attempt, username, quality, folder, done):
		started = False
		try:
			if self._room_info is None:
				from . import tiktok_adapter

				self._room_info = tiktok_adapter.room_info
			url = stream_url(self._room_info(username), quality)
			ffmpeg = ffmpeg_setup.executable()
			if url and ffmpeg:
				recorder = Recorder(ffmpeg)
				started = recorder.start(url, file_path(folder, username, quality))
				with self._lock:
					if self._starting is attempt and started:
						self._recorder = recorder
						recorder = None
				if recorder is not None:
					recorder.stop()
					started = started and self._starting is attempt
			else:
				log.warning(f"TikTok Live Reader: no recording (stream address {bool(url)}, FFmpeg {ffmpeg})")
		except Exception:
			log.warning("TikTok Live Reader: the recording could not start", exc_info=True)
		finally:
			with self._lock:
				if self._starting is attempt:
					self._starting = None
		done(started)

	def stop(self):
		"""Stop recording (and a start under way); True when something was stopped."""
		with self._lock:
			recorder, self._recorder = self._recorder, None
			was_starting, self._starting = self._starting is not None, None
		if recorder is not None:
			recorder.stop()
		return recorder is not None or was_starting


def _errors():
	try:
		return LOG_PATH.read_text(encoding="utf-8", errors="replace").strip()[-500:]
	except OSError:
		return ""
