"""The connection's life: connecting with retries on a thread of its own, the
stats thread, and disconnecting. Events go to pipeline.py.

Each switch-on is a run of its own. Switching off ends the current run at once;
its threads finish by themselves, and nothing they still report reaches the
pipeline or the plugin (1.8 waited for them for 3 s (F27) and let an old
connection end the next session (F2))."""

import threading
import time

from . import announcer, pipeline, settings, store, tiktok_adapter

RETRY_PAUSE = 3
_current = None
_lock = threading.Lock()


class _Run:
	def __init__(self):
		self.active = True
		self.stopped = threading.Event()
		self.connection = None

	def end(self):
		self.active = False
		self.stopped.set()
		if self.connection is not None:
			self.connection.stop()


def apply_settings(new):
	"""Use these settings from now on; sounds still queued stop when sounds are off."""
	if not new.play_sounds:
		announcer.silence()
	pipeline.use_settings(new)
	announcer.sound_manager.set_volume(new.volume)


def _write_files_regularly(run):
	"""The stats file when it changed, the top lists every 10 s, until the run
	ends (one such thread per run; 1.8 could leave two running, F23)."""
	ticks = 0
	while not run.stopped.is_set():
		if ticks % 10 == 0:
			pipeline.write_top_files()
		pipeline.flush_stats_file()
		ticks += 1
		run.stopped.wait(1)


def _runner(run, username, on_connect_cb, on_retry_cb, on_fail_cb, max_attempts=3, on_live_end_cb=None):
	attempts = 0
	connected_once = False
	live_ended = False

	def report(callback):
		if callback and run.active:
			callback()

	try:
		classes = tiktok_adapter.event_classes()
	except Exception:
		report(on_fail_cb)
		return

	def deliver(event):
		if run.active:
			pipeline.handle(event)

	def on_connected():
		nonlocal attempts, connected_once
		if not run.active:
			return
		attempts = 0
		connected_once = True
		pipeline.connection_time = time.time()
		report(on_connect_cb)

	def on_stream_end():
		nonlocal live_ended
		live_ended = True

	while run.active:
		ended_cleanly = False
		try:
			run.connection = tiktok_adapter.new_client(
				username, classes, deliver, on_connected, on_stream_end
			)
			if not run.active:
				break
			run.connection.run()
			ended_cleanly = True
		except Exception:
			ended_cleanly = False

		if not run.active:
			break

		# The stream is over either when the library says so, or when the
		# connection ended without error after we had been connected. Either
		# signal alone is enough, so a missing LiveEndEvent cannot hide the ending.
		if live_ended or (ended_cleanly and connected_once):
			report(on_live_end_cb)
			break

		attempts += 1
		if attempts < max_attempts:
			report(on_retry_cb)
			run.stopped.wait(RETRY_PAUSE)
		else:
			report(on_fail_cb)
			break


def connect(username=None, on_connect=None, on_retry=None, on_fail=None, retry_count=3, on_live_end=None):
	global _current
	if _current is not None:
		return

	loaded = settings.load()
	pipeline.use_settings(loaded)
	announcer.sound_manager.set_volume(loaded.volume)
	announcer.sound_manager.start()
	announcer.sound_manager.clear()
	announcer.forget_pending_speech()
	pipeline.forget_seen()
	if not loaded.clear_on_start:
		pipeline.remember_logged()
	final_user = username if username else loaded.username

	if not final_user:
		return

	store.ensure_files_exist()
	if loaded.clear_on_start:
		store.clear_all()
		pipeline.reset_accumulators()
		pipeline.update_stats_file(force=True)

	with _lock:
		if _current is not None:
			return
		run = _current = _Run()
	threading.Thread(target=_write_files_regularly, args=(run,), daemon=True).start()
	threading.Thread(
		target=_runner,
		args=(run, final_user, on_connect, on_retry, on_fail, retry_count, on_live_end),
		daemon=True,
	).start()


def disconnect():
	"""End the current run; returns at once."""
	global _current
	with _lock:
		run, _current = _current, None
	if run is not None:
		run.end()
	# Written before the plugin archives the files: likes still being summed and
	# the top lists, otherwise written only every 10 s (F11, F12).
	pipeline.like_manager.flush_pending()
	pipeline.write_top_files()
	pipeline.flush_stats_file()
	pipeline.like_manager.stop()
	announcer.sound_manager.stop()
