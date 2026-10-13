"""What the add-on plays and says for an event: the event's sound first, then its
text, which goes through the speech buffer to NVDA's speech."""

import array
import io
import json
import queue
import threading
import time
import wave
import winsound
from pathlib import Path

import ui

ADDON_DIR = Path(__file__).resolve().parent
SPEECH_BUFFER_FILE = ADDON_DIR / "speechbuffer.json"
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
		on_complete = None
		if speech_enabled:

			def on_complete():
				queue_speech(text)

		sound_manager.play(event_key, play_file=sound_enabled, on_complete=on_complete)


def queue_speech(text):
	try:
		with open(SPEECH_BUFFER_FILE, "a", encoding="utf-8") as handle:
			handle.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
	except Exception:
		pass


def clear_speech_buffer():
	try:
		with open(SPEECH_BUFFER_FILE, "w", encoding="utf-8"):
			pass
	except Exception:
		pass


def ensure_speech_buffer():
	if not SPEECH_BUFFER_FILE.exists():
		with open(SPEECH_BUFFER_FILE, "w", encoding="utf-8"):
			pass


def remove_speech_buffer():
	if SPEECH_BUFFER_FILE.exists():
		SPEECH_BUFFER_FILE.unlink()


class SpeechReader:
	"""Speaks what is added to the speech buffer while it runs, with ``delay``
	seconds after each text."""

	def __init__(self, delay=1.0):
		self.delay = delay
		self._running = False
		self._thread = None

	def start(self):
		if self._running:
			return
		self._running = True
		self._thread = threading.Thread(target=self._worker, daemon=True)
		self._thread.start()

	def stop(self):
		self._running = False
		if self._thread:
			self._thread.join(timeout=1)
			self._thread = None

	def _worker(self):
		me = threading.current_thread()

		last_pos = 0
		if SPEECH_BUFFER_FILE.exists():
			last_pos = SPEECH_BUFFER_FILE.stat().st_size

		while self._running and self._thread is me:
			if not SPEECH_BUFFER_FILE.exists():
				time.sleep(0.5)
				continue

			try:
				curr_size = SPEECH_BUFFER_FILE.stat().st_size
				if curr_size < last_pos:
					last_pos = 0

				if curr_size > last_pos:
					with open(SPEECH_BUFFER_FILE, "r", encoding="utf-8") as handle:
						handle.seek(last_pos)
						lines = handle.readlines()
						last_pos = handle.tell()

					for line in lines:
						if not self._running or self._thread is not me:
							break
						line = line.strip()
						if not line:
							continue
						try:
							text = json.loads(line).get("text", "")
							if text:
								ui.message(text)
								time.sleep(self.delay)
						except Exception:
							pass

			except Exception:
				pass

			time.sleep(0.5)
