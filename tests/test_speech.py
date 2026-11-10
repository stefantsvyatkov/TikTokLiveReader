"""Auto speak waits until NVDA has spoken each announcement, and copes when NVDA
never says so: speech cancelled, paused, off, or a synthesizer that does not
report where it is."""

import sys
import threading
import time
import types
import unittest
from types import SimpleNamespace as NS

from . import feed as f
from . import support

announcer = support.load("announcer")


class FakeSpeech:
	"""NVDA's speech and braille as the add-on uses them. ``answer``: "spoken"
	runs the callback after ``after`` seconds, "silent" never runs it."""

	def __init__(self):
		self.mode = "talk"
		self.paused = False
		self.answer = "spoken"
		self.after = 0.0
		self.spoken = []
		self.braille = []
		self.callbacks = []
		self.cancel_handlers = []
		speech = types.ModuleType("speech")
		speech.SpeechMode = NS(talk="talk", off="off", beeps="beeps", onDemand="onDemand")
		speech.getState = lambda: NS(speechMode=self.mode, isPaused=self.paused)
		speech.speak = self._speak
		speech.speechCanceled = NS(register=self.cancel_handlers.append, unregister=self._unregister)
		commands = types.ModuleType("speech.commands")
		commands.CallbackCommand = _CallbackCommand
		speech.commands = commands
		braille = types.ModuleType("braille")
		braille.handler = NS(message=self.braille.append)
		self.modules = {"speech": speech, "speech.commands": commands, "braille": braille}

	def _unregister(self, handler):
		if handler in self.cancel_handlers:
			self.cancel_handlers.remove(handler)

	def _speak(self, sequence):
		text, command = sequence
		self.spoken.append(text)
		self.callbacks.append(command)
		if self.answer == "spoken":
			threading.Timer(self.after, command.run).start()

	def cancel(self):
		for handler in list(self.cancel_handlers):
			handler()


class _CallbackCommand:
	def __init__(self, callback, name=None):
		self._callback = callback

	def run(self):
		return self._callback()


class SpeakAndWait(unittest.TestCase):
	def setUp(self):
		self.speech = FakeSpeech()
		for name, module in self.speech.modules.items():
			self.addCleanup(sys.modules.pop, name, None)
			sys.modules[name] = module
		announcer._unconfirmed = 0
		self.reader = announcer.SpeechReader()
		self.reader.start()
		self.addCleanup(self.reader.stop)
		support.spoken.clear()

	def timed(self, text):
		started = time.monotonic()
		pause = announcer.speak_and_wait(text)
		return pause, time.monotonic() - started

	def test_it_waits_until_the_text_is_spoken(self):
		self.speech.after = 0.3
		pause, took = self.timed("Alice: hello")
		self.assertGreaterEqual(took, 0.25)
		self.assertEqual(pause, announcer.GAP)
		self.assertEqual(self.speech.spoken, ["Alice: hello"])
		self.assertEqual(self.speech.braille, ["Alice: hello"])

	def test_cancelled_speech_ends_the_wait_with_the_longer_pause(self):
		self.speech.answer = "silent"
		threading.Timer(0.2, self.speech.cancel).start()
		pause, took = self.timed("Alice: a long comment that would take a while to speak")
		self.assertLess(took, 1.5)
		self.assertEqual(pause, announcer.UNCONFIRMED_PAUSE)

	def test_without_word_from_nvda_it_soon_waits_only_the_old_pause(self):
		self.addCleanup(setattr, announcer, "UNCONFIRMED_PAUSE", announcer.UNCONFIRMED_PAUSE)
		self.addCleanup(setattr, announcer, "_longest_wait", announcer._longest_wait)
		announcer._longest_wait = lambda text: 0.4
		announcer.UNCONFIRMED_PAUSE = 0.05
		self.speech.answer = "silent"
		took = [self.timed(f"text {number}")[1] for number in range(announcer.UNCONFIRMED_LIMIT + 1)]
		self.assertTrue(all(each >= 0.35 for each in took[:-1]), took)
		self.assertLess(took[-1], 0.3)
		# A text reported spoken, however late, makes NVDA trusted again.
		self.speech.callbacks[0].run()
		self.assertEqual(announcer._unconfirmed, 0)

	def test_paused_speech_is_waited_for(self):
		self.addCleanup(setattr, announcer, "UNCONFIRMED_PAUSE", announcer.UNCONFIRMED_PAUSE)
		self.addCleanup(setattr, announcer, "_longest_wait", announcer._longest_wait)
		announcer._longest_wait = lambda text: 0.1
		announcer.UNCONFIRMED_PAUSE = 0.05
		self.speech.paused = True
		self.speech.after = 0.5
		pause, took = self.timed("Alice: hello")
		self.assertGreaterEqual(took, 0.45)
		self.assertEqual(pause, announcer.GAP)

	def test_with_speech_off_the_message_is_shown_as_before(self):
		self.speech.mode = "off"
		pause, took = self.timed("Alice: hello")
		self.assertEqual(support.spoken, ["Alice: hello"])
		self.assertEqual(self.speech.spoken, [])
		self.assertEqual(pause, announcer.UNCONFIRMED_PAUSE)
		self.assertLess(took, 0.2)

	def test_nothing_is_spoken_while_auto_speak_is_off(self):
		self.reader.stop()
		self.assertIsNone(announcer.speak_and_wait("Alice: hello"))
		self.assertEqual(self.speech.spoken, [])
		self.assertEqual(self.speech.cancel_handlers, [])

	def test_switching_auto_speak_off_ends_the_wait(self):
		self.speech.answer = "silent"
		threading.Timer(0.2, self.reader.stop).start()
		pause, took = self.timed("Alice: a long comment that would take a while to speak")
		self.assertLess(took, 1.5)


class SoundWorker(unittest.TestCase):
	def test_the_next_announcement_waits_the_pause_asked_for(self):
		sounds = announcer.SoundManager(announcer.ADDON_DIR)
		sounds.start()
		self.addCleanup(sounds.stop)
		times = []

		def first():
			times.append(time.monotonic())
			return 0.4

		sounds.play("comments", play_file=False, on_complete=first, post_delay=0.0)
		sounds.play(
			"comments", play_file=False, on_complete=lambda: times.append(time.monotonic()), post_delay=0.0
		)
		self.assertTrue(f.wait_until(lambda: sounds._queue.unfinished_tasks == 0, timeout=5))
		self.assertGreaterEqual(times[1] - times[0], 0.35)


if __name__ == "__main__":
	unittest.main()
