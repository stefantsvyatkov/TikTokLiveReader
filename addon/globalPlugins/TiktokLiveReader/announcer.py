"""What the add-on plays and says for an event: the event's sound first, then its
text, which the speech reader passes to NVDA's speech while auto speak is on."""

import array
import functools
import io
import queue
import threading
import time
import wave
import winsound
from pathlib import Path

import ui
import wx

ADDON_DIR = Path(__file__).resolve().parent
# winsound has no name for it: playing synchronously is the absence of SND_ASYNC.
SND_SYNC = 0x0000

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
		self._queue = queue.Queue()
		self._running = True
		self._thread = threading.Thread(target=self._worker, daemon=True)
		self._thread.start()

	def set_volume(self, volume):
		self.volume = max(0, min(100, int(volume)))

	def stop(self):
		self._running = False
		with self._queue.mutex:
			self._queue.queue.clear()

	def clear(self):
		with self._queue.mutex:
			self._queue.queue.clear()

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
					pass

			if post_delay > 0:
				time.sleep(post_delay)

			self._queue.task_done()

	def _play_actual(self, fname):
		fpath = self.sounds_dir / fname
		if not fpath.exists():
			return

		try:
			with wave.open(str(fpath), "rb") as wav_in:
				params = wav_in.getparams()

				if self.volume == 100 or params.sampwidth != 2:
					winsound.PlaySound(str(fpath), winsound.SND_FILENAME | SND_SYNC)
					return

				frames = wav_in.readframes(params.nframes)

				try:
					factor = self.volume / 100.0
					samples = array.array("h", frames)
					for i in range(len(samples)):
						samples[i] = max(-32768, min(32767, int(samples[i] * factor)))

					mem_file = io.BytesIO()
					with wave.open(mem_file, "wb") as wav_out:
						wav_out.setparams(params)
						wav_out.writeframes(samples.tobytes())

					winsound.PlaySound(mem_file.getvalue(), winsound.SND_MEMORY | SND_SYNC)
				except Exception:
					winsound.PlaySound(str(fpath), winsound.SND_FILENAME | SND_SYNC)

		except Exception:
			try:
				winsound.PlaySound(str(fpath), winsound.SND_FILENAME | SND_SYNC)
			except Exception:
				pass


sound_manager = SoundManager(ADDON_DIR)
settings_open = False


def set_settings_open(is_open):
	global settings_open
	settings_open = is_open


def silence():
	"""Drop the queued sounds and stop the one playing."""
	try:
		sound_manager.clear()
		winsound.PlaySound(None, winsound.SND_PURGE)
	except Exception:
		pass


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
