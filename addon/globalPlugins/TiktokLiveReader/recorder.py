"""Recording a live with FFmpeg: the stream TikTok sends viewers (the host's
camera and microphone, without comments or gift animations) copied into a file
by FFmpeg in its own process; NVDA only starts and stops it (docs/dev/plan.md)."""

import datetime
import json
import os
import subprocess
import threading
from pathlib import Path

from logHandler import log

from . import ffmpeg_setup, settings, store

# The settings' quality names, TikTok's for them in the stream data, and the file type.
TIKTOK_QUALITIES = {"video": "hd", "audio": "ao"}
EXTENSIONS = {"video": ".mp4", "audio": ".mp3"}
# What FFmpeg makes of the stream for each file type, written to disk as it comes, so that a file cut short
# (a crash) still plays: MP4 in fragments until FFmpeg finishes it as a standard one, MP3 at a constant rate.
OUTPUT = {
	".mp4": ["-c", "copy", "-movflags", "+hybrid_fragmented"],
	".mp3": ["-c:a", "libmp3lame", "-b:a", "192k", "-write_xing", "0"],
}
FLUSH = ["-flush_packets", "1"]
CREATE_NO_WINDOW = 0x08000000
# How long FFmpeg is watched after starting: a wrong address ends it at once.
SETTLE = 2.0
# How often a recording's FFmpeg is looked at, and how it is started again when it
# ended by itself (TikTok cut the stream, F45): tries, and the pause between them.
WATCH = 1.0
RESTART_TRIES = 6
RESTART_PAUSE = 10.0
# The longest joining a recording's parts may take.
JOIN_TIMEOUT = 600
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
	"""``folder``/<date time host>.mp4 (.mp3 for audio), named as archives are."""
	stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H-%M-%S")
	host = store.safe_name(username) or "unknown"
	return Path(folder) / f"{stamp} {host}{EXTENSIONS.get(quality, EXTENSIONS['video'])}"


def part_path(first, number):
	"""The file of a recording's part ``number`` (2 on), beside its first."""
	return first.with_name(f"{first.stem} ({number}){first.suffix}")


def _command_list(command):
	return [str(command)] if isinstance(command, (str, Path)) else list(command)


def _concat_line(path):
	# The concat demuxer's quoting: a quote inside single quotes is written '\''.
	return "file '{}'\n".format(path.as_posix().replace("'", "'\\''"))


def join(command, files):
	"""Join a recording's ``files`` into the first, copied (not encoded) by FFmpeg's
	concat demuxer, and remove the others; True when done. When FFmpeg fails, every
	part stays as it is."""
	if len(files) < 2:
		return True
	first = files[0]
	listing = first.with_name(f"{first.stem} (parts).txt")
	joined = first.with_name(f"{first.stem} (joined){first.suffix}")
	try:
		listing.write_text("".join(_concat_line(path) for path in files), encoding="utf-8")
		result = subprocess.run(
			[
				*_command_list(command),
				"-hide_banner",
				"-loglevel",
				"error",
				"-y",
				*("-f", "concat", "-safe", "0", "-i", str(listing)),
				*("-c", "copy", str(joined)),
			],
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE,
			creationflags=CREATE_NO_WINDOW,
			timeout=JOIN_TIMEOUT,
		)
		if result.returncode or not joined.is_file():
			errors = result.stderr.decode("utf-8", "replace").strip()[-500:]
			log.warning(f"TikTok Live Reader: the recording's parts were not joined: {errors}")
			_remove(joined)
			return False
		os.replace(joined, first)
		for path in files[1:]:
			_remove(path)
		return True
	except (OSError, subprocess.SubprocessError):
		log.warning("TikTok Live Reader: the recording's parts were not joined", exc_info=True)
		_remove(joined)
		return False
	finally:
		_remove(listing)


def _remove(path):
	try:
		path.unlink(missing_ok=True)
	except OSError:
		log.debugWarning(f"TikTok Live Reader: {path} stays", exc_info=True)


class Recorder:
	"""One FFmpeg process copying a stream into a file. ``command`` is FFmpeg's
	path, or a list that starts FFmpeg (the tests' stand-in)."""

	def __init__(self, command):
		self._command = _command_list(command)
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
							*OUTPUT.get(path.suffix, OUTPUT[".mp4"]),
							*FLUSH,
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
		else:
			if process.returncode:
				log.warning(f"TikTok Live Reader: FFmpeg stopped with {process.returncode}: {_errors()}")
			try:
				process.stdin.close()
			except OSError:
				pass


class _Parts:
	"""A recording under way: its files, one more each time FFmpeg had to start again."""

	def __init__(self, username, quality, first, lost):
		self.username = username
		self.quality = quality
		self.files = [first]
		self.lost = lost
		self.stopped = threading.Event()


class LiveRecording:
	"""The plugin's recording: started with the live's room info in a worker
	thread, so the room request and FFmpeg's start never hold NVDA; one at a time.
	When FFmpeg ends by itself it is started again on a fresh stream address, into a
	part of its own, and the parts are joined into one file when the recording stops
	(F45). ``room_info(username)`` is tiktok_adapter's (the tests' stand-in)."""

	def __init__(self, room_info=None):
		self._room_info = room_info
		self._recorder = None
		self._parts = None
		self._starting = None
		self._lock = threading.Lock()

	@property
	def active(self):
		"""Recording, or starting to (again)."""
		return self._starting is not None or self._parts is not None

	def start(self, username, quality, folder, done, lost=None):
		"""Start recording; ``done(started)`` is called from the worker thread, and
		``lost()`` from another when FFmpeg ended and could not be started again."""
		with self._lock:
			if self.active:
				return
			attempt = self._starting = object()
		threading.Thread(
			target=self._start, args=(attempt, username, quality, folder, done, lost), daemon=True
		).start()

	def _start(self, attempt, username, quality, folder, done, lost):
		started = False
		parts = None
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
						parts = self._parts = _Parts(username, quality, recorder.path, lost)
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
		if parts is not None:
			threading.Thread(target=self._watch, args=(parts,), daemon=True).start()
		done(started)

	def _watch(self, parts):
		"""Start FFmpeg again whenever it ends by itself; when it cannot be, the
		recording ends and ``lost`` is told."""
		while not parts.stopped.wait(WATCH):
			recorder = self._recorder
			if recorder is not None and recorder.recording:
				continue
			if parts.stopped.is_set():
				return
			log.warning(f"TikTok Live Reader: FFmpeg ended during the recording: {_errors()}")
			if recorder is not None:
				recorder.stop()
			if self._restart(parts):
				continue
			with self._lock:
				gave_up = self._parts is parts and not parts.stopped.is_set()
				if gave_up:
					self._parts = self._recorder = None
			if gave_up:
				parts.stopped.set()
				self._join(parts)
				if parts.lost:
					parts.lost()
			return

	def _restart(self, parts):
		for attempt in range(RESTART_TRIES):
			if parts.stopped.wait(RESTART_PAUSE if attempt else 0):
				return False
			try:
				url = stream_url(self._room_info(parts.username), parts.quality)
			except Exception:
				log.debugWarning("TikTok Live Reader: no room info to record again", exc_info=True)
				continue
			ffmpeg = ffmpeg_setup.executable()
			if not (url and ffmpeg):
				continue
			path = part_path(parts.files[0], len(parts.files) + 1)
			recorder = Recorder(ffmpeg)
			started = recorder.start(url, path)
			with self._lock:
				if started and not parts.stopped.is_set():
					self._recorder = recorder
					parts.files.append(path)
					return True
			recorder.stop()
			_remove(path)
		return False

	def _join(self, parts):
		"""Join the parts in a thread of its own: copying a long recording takes a while."""
		ffmpeg = ffmpeg_setup.executable()
		if len(parts.files) > 1 and ffmpeg:
			threading.Thread(target=join, args=(ffmpeg, list(parts.files)), daemon=True).start()

	def stop(self):
		"""Stop recording (and a start under way); True when something was stopped."""
		with self._lock:
			recorder, self._recorder = self._recorder, None
			parts, self._parts = self._parts, None
			was_starting, self._starting = self._starting is not None, None
		if parts is not None:
			parts.stopped.set()
		if recorder is not None:
			recorder.stop()
		if parts is not None:
			self._join(parts)
		return parts is not None or was_starting


def _errors():
	try:
		return LOG_PATH.read_text(encoding="utf-8", errors="replace").strip()[-500:]
	except OSError:
		return ""
