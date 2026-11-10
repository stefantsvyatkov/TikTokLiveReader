"""What the add-on plays and says for an event: the event's sound first, then its
text, which the speech reader passes to NVDA's speech while auto speak is on."""

import collections
import contextlib
import functools
import queue
import threading
import time
import wave
from pathlib import Path

import ui
import wx
from logHandler import log

ADDON_DIR = Path(__file__).resolve().parent

SOUND_FILES = {
	"comments": "comment.wav",
	"fan_club": "fan_club.wav",
	"followers": "follower.wav",
	"gifts": "gift.wav",
	"likes": "like.wav",
	"shares": "share.wav",
	"visitors": "visitor.wav",
	"requests": "request.wav",
}
# Announced first to last, each kind in the order it came: in a busy live
# likes and visitors outnumber comments, which waited behind them (F44).
PRIORITY = ("comments", "gifts", "followers", "requests", "shares", "likes", "visitors")
# An event announced at least a second apart falls behind in a busy live;
# what waited longer than this is dropped (it is in the text files), so that
# what is heard is what happens now.
STALE_AFTER = 60.0
# Who liked or came in a while ago is no news.
STALE_AFTER_BY_KIND = {"likes": 10.0, "visitors": 10.0}
# Only the newest of these wait; a newer one pushes out the oldest.
WAITING_AT_MOST = {"likes": 3, "visitors": 3}


def _rank(kind):
	try:
		return PRIORITY.index(kind)
	except ValueError:
		return len(PRIORITY)


class AnnouncementQueue:
	"""What waits to be announced, handed out by ``PRIORITY``; what waited too long
	is dropped on the way."""

	def __init__(self):
		# Kind: (time queued, item), oldest first.
		self._waiting = {}
		self._ready = threading.Condition()
		# Items put and not dropped nor done, as queue.Queue counts them.
		self.unfinished_tasks = 0

	def put(self, kind, item):
		with self._ready:
			waiting = self._waiting.setdefault(kind, collections.deque())
			waiting.append((time.monotonic(), item))
			self.unfinished_tasks += 1
			if len(waiting) > WAITING_AT_MOST.get(kind, len(waiting)):
				waiting.popleft()
				self.unfinished_tasks -= 1
			self._ready.notify()

	def get(self, timeout):
		"""The next item; queue.Empty when none came within ``timeout`` seconds."""
		deadline = time.monotonic() + timeout
		with self._ready:
			while True:
				found, item = self._next()
				if found:
					return item
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					raise queue.Empty
				self._ready.wait(remaining)

	def _next(self):
		now = time.monotonic()
		for kind in sorted(self._waiting, key=_rank):
			waiting = self._waiting[kind]
			limit = STALE_AFTER_BY_KIND.get(kind, STALE_AFTER)
			while waiting:
				queued, item = waiting.popleft()
				if now - queued <= limit:
					return True, item
				self.unfinished_tasks -= 1
		return False, None

	def task_done(self):
		with self._ready:
			self.unfinished_tasks -= 1

	def clear(self):
		with self._ready:
			for waiting in self._waiting.values():
				self.unfinished_tasks -= len(waiting)
			self._waiting.clear()


class SoundManager:
	"""Plays queued sounds one at a time on its own thread, the most important
	first, each followed by its callback and a pause."""

	def __init__(self, base_dir):
		self.base_dir = base_dir
		self.sounds_dir = base_dir.parent.parent / "sounds"
		self.volume = 100
		self._player = None
		# File name: (wave parameters, frames), None when it cannot be read.
		self._sounds = {}
		self._queue = AnnouncementQueue()
		# The worker starts with the first session or the settings dialog (F18).
		self._running = False
		self._thread = None

	def set_volume(self, volume):
		self.volume = max(0, min(100, int(volume)))

	def stop(self):
		self._running = False
		self._queue.clear()

	def clear(self):
		self._queue.clear()

	def stop_playing(self):
		player = self._player
		if player is not None:
			player.stop()

	def start(self):
		if not self._running:
			self._queue = AnnouncementQueue()
			self._running = True
			self._thread = threading.Thread(target=self._worker, daemon=True)
			self._thread.start()

	def play(self, event_name, play_file=True, on_complete=None, post_delay=1.0, wanted=None):
		"""``wanted``, when given, is asked again when the sound's turn comes: the
		person may have been ignored since."""
		fname = SOUND_FILES.get(event_name, f"{event_name}.wav")
		self._queue.put(event_name, (fname, play_file, on_complete, post_delay, wanted))

	def _worker(self):
		me = threading.current_thread()
		# This thread's players by format and device: opening the audio device
		# for every sound is slow on a slow computer.
		players = {}
		try:
			while self._running and self._thread is me:
				try:
					fname, play_file, callback, post_delay, wanted = self._queue.get(timeout=1.0)
				except queue.Empty:
					continue

				if wanted is not None and not wanted():
					self._queue.task_done()
					continue

				if fname and play_file:
					self._play_actual(fname, players)

				if callback:
					try:
						callback()
					except Exception:
						log.exception("TikTok Live Reader: after a sound")

				if post_delay > 0:
					time.sleep(post_delay)

				self._queue.task_done()
		finally:
			for player in players.values():
				with contextlib.suppress(Exception):
					player.close()

	def _sound(self, fname):
		"""The file's wave parameters and frames, read once; None when it cannot be read."""
		if fname not in self._sounds:
			try:
				with wave.open(str(self.sounds_dir / fname), "rb") as wav:
					params = wav.getparams()
					self._sounds[fname] = (params, wav.readframes(params.nframes))
			except (OSError, EOFError, wave.Error):
				self._sounds[fname] = None
		return self._sounds[fname]

	def _play_actual(self, fname, players):
		"""Play on the output device chosen in NVDA's settings at the add-on's own
		volume (1.8 used winsound: the Windows default device, the volume applied
		sample by sample in Python, F17)."""
		sound = self._sound(fname)
		if sound is None:
			return
		try:
			import config
			import nvwave
		except ImportError:
			return
		params, frames = sound
		device = config.conf["audio"]["outputDevice"]
		key = (params.nchannels, params.framerate, params.sampwidth, device)
		player = players.get(key)
		if player is None:
			try:
				# A speech player: NVDA applies its sound volume only to sounds players.
				player = players[key] = nvwave.WavePlayer(
					channels=params.nchannels,
					samplesPerSec=params.framerate,
					bitsPerSample=params.sampwidth * 8,
					outputDevice=device,
					wantDucking=False,
				)
			except Exception:
				log.debugWarning(f"TikTok Live Reader: cannot play {fname}", exc_info=True)
				return
		self._player = player
		try:
			player.setVolume(all=self.volume / 100)
			player.feed(frames)
			player.sync()
		except Exception:
			log.debugWarning(f"TikTok Live Reader: playing {fname} failed", exc_info=True)
			del players[key]
			with contextlib.suppress(Exception):
				player.close()
		finally:
			self._player = None


sound_manager = SoundManager(ADDON_DIR)
settings_open = False


def set_settings_open(is_open):
	global settings_open
	settings_open = is_open


def silence():
	"""Drop the queued sounds and stop the one playing."""
	try:
		sound_manager.clear()
		sound_manager.stop_playing()
	except Exception:
		log.debugWarning("TikTok Live Reader: stopping the sound failed", exc_info=True)


def announce(event_key, text, settings, wanted=None):
	"""The event's sound, then ``text`` for speech, each as the settings ask;
	nothing while the settings dialog is open, nor when ``wanted()`` says no by
	the time it is its turn."""
	if settings_open:
		return
	sound_enabled = settings.play_sounds and settings.sounds.get(event_key, False)
	speech_enabled = settings.auto_speak.get(event_key, False)
	if sound_enabled or speech_enabled:
		then_speak = functools.partial(queue_speech, text, event_key) if speech_enabled else None
		sound_manager.play(event_key, play_file=sound_enabled, on_complete=then_speak, wanted=wanted)


def say(text):
	"""Speak ``text`` now, whatever the auto speak setting, as "The live has
	ended" is."""
	wx.CallAfter(ui.message, text)


# Texts waiting for the speech reader. 1.8 used a file polled every 0.5 s,
# written from several threads (F19, F30).
_speech = AnnouncementQueue()
_listening = False


def queue_speech(text, kind=None):
	"""Speak ``text`` when the speech reader runs; without it the text is dropped,
	as the reader starts with what comes after it. ``kind``: the event's, for its
	place in ``PRIORITY``."""
	if _listening:
		_speech.put(kind, text)


def forget_pending_speech():
	_speech.clear()


class SpeechReader:
	"""Speaks the texts queued for speech while it runs, with ``delay`` seconds
	after each."""

	def __init__(self, delay=1.0):
		self.delay = delay
		self._running = False
		self._thread = None

	def start(self):
		global _listening
		if self._running:
			return
		forget_pending_speech()
		_listening = True
		self._running = True
		self._thread = threading.Thread(target=self._worker, daemon=True)
		self._thread.start()

	def stop(self):
		global _listening
		_listening = False
		self._running = False
		if self._thread:
			self._thread.join(timeout=1)
			self._thread = None

	def _worker(self):
		me = threading.current_thread()
		while self._running and self._thread is me:
			try:
				text = _speech.get(timeout=0.5)
			except queue.Empty:
				continue
			_speech.task_done()
			if not self._running or self._thread is not me:
				break
			# Spoken on NVDA's main thread (F3).
			wx.CallAfter(ui.message, text)
			time.sleep(self.delay)
