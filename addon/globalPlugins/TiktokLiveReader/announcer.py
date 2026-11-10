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
# Between two announcements: speech waits until NVDA has spoken the text (F45).
GAP = 0.3
# After a text NVDA did not report spoken (speech off, beeps or on demand, a
# synthesizer that does not report where it is) or cancelled (a key: what the
# key brings is heard first), the pause every text had before.
UNCONFIRMED_PAUSE = 1.0
# After this many texts in a row not reported spoken, only that pause is waited.
UNCONFIRMED_LIMIT = 2


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

	def play(self, event_name, play_file=True, on_complete=None, post_delay=GAP, wanted=None):
		"""``wanted``, when given, is asked again when the sound's turn comes: the
		person may have been ignored since. ``on_complete`` may return a longer pause
		than ``post_delay`` to leave before the next."""
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

				pause = post_delay
				if callback:
					try:
						asked = callback()
					except Exception:
						log.exception("TikTok Live Reader: after a sound")
					else:
						if isinstance(asked, (int, float)):
							pause = max(pause, asked)

				if pause > 0:
					time.sleep(pause)

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
		then_speak = functools.partial(speak_and_wait, text) if speech_enabled else None
		sound_manager.play(event_key, play_file=sound_enabled, on_complete=then_speak, wanted=wanted)


def say(text):
	"""Speak ``text`` now, whatever the auto speak setting, as "The live has
	ended" is."""
	wx.CallAfter(ui.message, text)


# Auto speak is on. 1.8 passed the texts through a file polled every 0.5 s,
# written from several threads (F19, F30), and waited a second after each.
_listening = False
# The text NVDA is speaking for the sound worker; only touched on NVDA's main
# thread but by forget_pending_speech.
_speaking = None
_speaking_lock = threading.Lock()
# Texts in a row NVDA did not report spoken.
_unconfirmed = 0


class _Utterance:
	def __init__(self):
		self.done = threading.Event()
		self.spoken = False


def _longest_wait(text):
	"""How long NVDA may take to speak ``text`` at a slow rate."""
	return min(30.0, 2.0 + len(text) / 8)


def _speech_module():
	"""NVDA's speech when it reports what it spoke; None otherwise (speech off,
	beeps or on demand, or outside NVDA)."""
	try:
		import speech
	except ImportError:
		return None
	try:
		if speech.getState().speechMode != speech.SpeechMode.talk:
			return None
	except Exception:
		return None
	return speech


def speak_and_wait(text):
	"""Speak ``text`` while auto speak is on and wait until NVDA has spoken it, or
	cancelled speech; the pause to leave before the next announcement. Without
	word from NVDA, the wait is cut short: at first after a time that fits the
	text, after ``UNCONFIRMED_LIMIT`` such texts after ``UNCONFIRMED_PAUSE``."""
	global _unconfirmed
	if not _listening:
		return None
	speech = _speech_module()
	if speech is None:
		# Spoken on NVDA's main thread (F3).
		wx.CallAfter(ui.message, text)
		return UNCONFIRMED_PAUSE
	utterance = _Utterance()
	wx.CallAfter(_speak, speech, text, utterance)
	trusted = _unconfirmed < UNCONFIRMED_LIMIT
	wait = _longest_wait(text) if trusted else UNCONFIRMED_PAUSE
	while not utterance.done.wait(wait):
		# Paused with shift: the text is still to come.
		if not _is_paused(speech):
			break
		wait = UNCONFIRMED_PAUSE
	if not utterance.done.is_set():
		_unconfirmed += 1
		_finish(utterance, spoken=False)
		return None
	return GAP if utterance.spoken else UNCONFIRMED_PAUSE


def _is_paused(speech):
	try:
		return speech.getState().isPaused
	except Exception:
		return False


def _speak(speech, text, utterance):
	"""On NVDA's main thread: ``text`` in speech with a callback after it, and in
	braille, as ui.message shows it."""
	global _speaking
	from speech.commands import CallbackCommand

	try:
		speech.speak([text, CallbackCommand(lambda: _reported(utterance), name="TikTok Live Reader")])
	except Exception:
		log.debugWarning("TikTok Live Reader: speaking an announcement", exc_info=True)
		_finish(utterance, spoken=False)
	# Only now: speaking cancels paused speech, which is not this text's.
	with _speaking_lock:
		if not utterance.done.is_set():
			_speaking = utterance
	try:
		import braille

		braille.handler.message(text)
	except Exception:
		log.debugWarning("TikTok Live Reader: showing an announcement in braille", exc_info=True)


def _reported(utterance):
	"""NVDA spoke the text: its callback, on NVDA's main thread."""
	global _unconfirmed
	_unconfirmed = 0
	_finish(utterance, spoken=True)


def _finish(utterance, spoken):
	global _speaking
	with _speaking_lock:
		if utterance.done.is_set():
			return
		utterance.spoken = spoken
		utterance.done.set()
		if _speaking is utterance:
			_speaking = None


def forget_pending_speech():
	"""Stop waiting for the text being spoken."""
	with _speaking_lock:
		utterance = _speaking
	if utterance is not None:
		_finish(utterance, spoken=False)


def _on_speech_canceled():
	"""NVDA cancelled speech (a key, a focus change): the text being spoken will not
	report it was, so the sound worker goes on."""
	forget_pending_speech()


class SpeechReader:
	"""Auto speak: while it runs, the sound worker speaks each announcement after
	its sound and waits until NVDA has spoken it."""

	def __init__(self):
		self._running = False

	def start(self):
		global _listening
		if self._running:
			return
		_listening = True
		self._running = True
		try:
			import speech

			speech.speechCanceled.register(_on_speech_canceled)
		except Exception:
			pass

	def stop(self):
		global _listening
		_listening = False
		self._running = False
		try:
			import speech

			speech.speechCanceled.unregister(_on_speech_canceled)
		except Exception:
			pass
		forget_pending_speech()
