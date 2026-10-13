"""What the add-on plays and says for an event: the event's sound first, then its
text, which the speech reader passes to NVDA's speech while auto speak is on."""

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
	"followers": "follower.wav",
	"gifts": "gift.wav",
	"likes": "like.wav",
	"shares": "share.wav",
	"visitors": "visitor.wav",
	"requests": "request.wav",
}


class SoundManager:
	"""Plays queued sounds one at a time on its own thread, each followed by its
	callback and a pause."""

	def __init__(self, base_dir):
		self.base_dir = base_dir
		self.sounds_dir = base_dir.parent.parent / "sounds"
		self.volume = 100
		self._player = None
		self._queue = queue.Queue()
		# The worker starts with the first session or the settings dialog (F18).
		self._running = False
		self._thread = None

	def set_volume(self, volume):
		self.volume = max(0, min(100, int(volume)))

	def stop(self):
		self._running = False
		with self._queue.mutex:
			self._queue.queue.clear()

	def clear(self):
		with self._queue.mutex:
			self._queue.queue.clear()

	def stop_playing(self):
		player = self._player
		if player is not None:
			player.stop()

	def start(self):
		if not self._running:
			self._queue = queue.Queue()
			self._running = True
			self._thread = threading.Thread(target=self._worker, daemon=True)
			self._thread.start()

	def play(self, event_name, play_file=True, on_complete=None, post_delay=1.0):
		fname = SOUND_FILES.get(event_name, f"{event_name}.wav")
		self._queue.put((fname, play_file, on_complete, post_delay))

	def _worker(self):
		me = threading.current_thread()
		while self._running and self._thread is me:
			try:
				fname, play_file, callback, post_delay = self._queue.get(timeout=1.0)
			except queue.Empty:
				continue

			if fname and play_file:
				self._play_actual(fname)

			if callback:
				try:
					callback()
				except Exception:
					log.exception("TikTok Live Reader: after a sound")

			if post_delay > 0:
				time.sleep(post_delay)

			self._queue.task_done()

	def _play_actual(self, fname):
		"""Play on the output device chosen in NVDA's settings at the add-on's own
		volume (1.8 used winsound: the Windows default device, the volume applied
		sample by sample in Python, F17)."""
		fpath = self.sounds_dir / fname
		if not fpath.exists():
			return
		try:
			import config
			import nvwave
		except ImportError:
			return
		try:
			with wave.open(str(fpath), "rb") as wav:
				params = wav.getparams()
				frames = wav.readframes(params.nframes)
			# A speech player: NVDA applies its sound volume only to sounds players.
			player = nvwave.WavePlayer(
				channels=params.nchannels,
				samplesPerSec=params.framerate,
				bitsPerSample=params.sampwidth * 8,
				outputDevice=config.conf["audio"]["outputDevice"],
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
		finally:
			self._player = None
			player.close()


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


def announce(event_key, text, settings):
	"""The event's sound, then ``text`` for speech, each as the settings ask;
	nothing while the settings dialog is open."""
	if settings_open:
		return
	sound_enabled = settings.play_sounds and settings.sounds.get(event_key, False)
	speech_enabled = settings.auto_speak.get(event_key, False)
	if sound_enabled or speech_enabled:
		then_speak = functools.partial(queue_speech, text) if speech_enabled else None
		sound_manager.play(event_key, play_file=sound_enabled, on_complete=then_speak)


# Texts waiting for the speech reader. 1.8 used a file polled every 0.5 s,
# written from several threads (F19, F30).
_speech = queue.Queue()
_listening = False


def queue_speech(text):
	"""Speak ``text`` when the speech reader runs; without it the text is dropped,
	as the reader starts with what comes after it."""
	if _listening:
		_speech.put(text)


def forget_pending_speech():
	while True:
		try:
			_speech.get_nowait()
		except queue.Empty:
			return


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
			if not self._running or self._thread is not me:
				break
			# Spoken on NVDA's main thread (F3).
			wx.CallAfter(ui.message, text)
			time.sleep(self.delay)
