"""The connection's life: connecting with retries on a thread of its own, the
stats thread, and disconnecting. Events go to pipeline.py."""

import asyncio
import threading
import time

from . import announcer, pipeline, settings, store, tiktok_adapter

client = None
_thread = None
_stats_thread = None
_run_lock = threading.Lock()
_client_loop = None
_stop_event = threading.Event()
_top_thread_started = False
_should_run = False


def apply_settings(new):
	"""Use these settings from now on; sounds still queued stop when sounds are off."""
	if not new.play_sounds:
		announcer.silence()
	pipeline.use_settings(new)
	announcer.sound_manager.set_volume(new.volume)


def update_top_files():
	ticks = 0
	while not _stop_event.is_set():
		if ticks % 10 == 0:
			pipeline.write_top_files()
		pipeline.flush_stats_file()
		ticks += 1
		_stop_event.wait(1)


def _runner(username, on_connect_cb, on_retry_cb, on_fail_cb, max_attempts=3, on_live_end_cb=None):
	global client, _client_loop
	attempts = 0
	connected_once = False
	live_ended = False

	try:
		classes = tiktok_adapter.event_classes()
	except Exception:
		if on_fail_cb:
			on_fail_cb()
		return

	while _should_run:
		ended_cleanly = False
		try:
			current = {}

			def deliver(event):
				if globals().get("client") is not current.get("client"):
					return
				if not _should_run:
					return
				pipeline.handle(event)

			def on_connected():
				nonlocal attempts, connected_once
				attempts = 0
				connected_once = True
				pipeline.connection_time = time.time()
				if on_connect_cb:
					on_connect_cb()

			def on_stream_end():
				nonlocal live_ended
				if globals().get("client") is not current.get("client"):
					return
				live_ended = True

			client = current["client"] = tiktok_adapter.new_client(
				username, classes, deliver, on_connected, on_stream_end
			)
			try:
				_client_loop = asyncio.get_event_loop()
			except RuntimeError:
				_client_loop = asyncio.new_event_loop()
				asyncio.set_event_loop(_client_loop)

			tiktok_adapter.run(client)
			ended_cleanly = True

		except Exception:
			ended_cleanly = False

		if not _should_run:
			break

		# The stream is over either when the library says so, or when run()
		# returned without error after we had been connected. Either signal
		# alone is enough, so a missing LiveEndEvent cannot hide the ending.
		if live_ended or (ended_cleanly and connected_once):
			if on_live_end_cb:
				on_live_end_cb()
			break

		attempts += 1
		if attempts < max_attempts:
			if on_retry_cb:
				on_retry_cb()
			time.sleep(3)
		else:
			if on_fail_cb:
				on_fail_cb()
			break


def connect(username=None, on_connect=None, on_retry=None, on_fail=None, retry_count=3, on_live_end=None):
	global _top_thread_started, _thread, _should_run, _stats_thread

	if _thread and _thread.is_alive():
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

	_stop_event.clear()

	if not _top_thread_started:
		_stats_thread = threading.Thread(target=update_top_files, daemon=True)
		_stats_thread.start()
		_top_thread_started = True

	_should_run = True

	with _run_lock:
		if _thread and _thread.is_alive():
			return
		_thread = threading.Thread(
			target=_runner,
			args=(final_user, on_connect, on_retry, on_fail, retry_count, on_live_end),
			daemon=True,
		)
		_thread.start()


def disconnect():
	global _thread, client, _should_run, _top_thread_started, _stats_thread
	_should_run = False
	# Written before the plugin archives the files: likes still being summed and
	# the top lists, otherwise written only every 10 s (F11, F12).
	pipeline.like_manager.flush_pending()
	pipeline.write_top_files()
	pipeline.flush_stats_file()
	_stop_event.set()

	_stats_thread = None
	_top_thread_started = False

	with _run_lock:
		if client:
			try:
				if _client_loop is not None and getattr(client, "connected", False):
					if _client_loop.is_running():
						_client_loop.call_soon_threadsafe(client.stop)
				else:
					client.stop()
			except Exception:
				pass

		pipeline.like_manager.stop()
		announcer.sound_manager.stop()

		old_thread = _thread
		_thread = None
		client = None

	if old_thread and old_thread.is_alive() and old_thread != threading.current_thread():
		try:
			old_thread.join(timeout=3.0)
		except Exception:
			pass
