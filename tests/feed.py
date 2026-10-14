"""TikTok messages for tests, decoded by the add-on's own copy of TikTokLive.

Each builder returns one websocket message (method, payload bytes, id), the
same shape the recorder stores. Payloads are encoded with the library's event
classes and decoded inside whole ProtoMessageFetchResult frames, as the
websocket loop does: anything else changes the decoded types (see
docs/dev/library.md).

``run_session`` drives the add-on's real connection thread with a
TikTokLiveClient subclass that replays messages instead of connecting.
"""

import asyncio
import base64
import contextlib
import functools
import itertools
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import support

addon_session = support.load("session")
pipeline = support.load("pipeline")
adapter = support.load("tiktok_adapter")
addon_settings = support.load("settings")
store = support.load("store")
announcer = support.load("announcer")

with adapter.library_scope():
	import TikTokLive
	from TikTokLive import proto
	from TikTokLive.events import ConnectEvent, proto_events
	from TikTokLive.proto.custom_proto import ControlAction
	from TikTokLiveProto.v3.webcast.model.message import linkcore
	from TikTokLiveProto.v3.webcast.model.message.common import Text as DisplayText

_ids = itertools.count(1_000_001)


def _in_runtime(function):
	"""betterproto resolves type hints through sys.modules, which only holds the
	add-on's TikTokLive inside its library scope; the add-on runs the connection there too."""

	@functools.wraps(function)
	def wrapper(*args, **kwargs):
		with adapter.library_scope():
			return function(*args, **kwargs)

	return wrapper


METHODS = {event: method for method, event in proto_events.EVENT_MAPPINGS.items()}


@_in_runtime
def user(nickname, unique_id=None, user_id=None):
	return proto.User(
		id=user_id if user_id is not None else abs(hash(unique_id or nickname)) % 10**12,
		nickname=nickname,
		display_id=unique_id or nickname.lower().replace(" ", "_"),
	)


@_in_runtime
def _message(event, display_key=""):
	event.common = proto.CommonMessageData(
		msg_id=next(_ids),
		create_time=int(time.time() * 1000),
		display_text=DisplayText(key=display_key),
	)
	return proto.ProtoMessageFetchResultBaseProtoMessage(
		method=METHODS[type(event)],
		payload=bytes(event),
		msg_id=event.common.msg_id,
	)


@_in_runtime
def comment(who, text):
	return _message(proto_events.CommentEvent(user=who, content=text))


@_in_runtime
def gift(who, name, diamonds=1, count=1, repeat_end=1, streakable=True):
	return _message(
		proto_events.GiftEvent(
			user=who,
			repeat_count=count,
			repeat_end=repeat_end,
			gift=proto.Gift(name=name, diamond_count=diamonds, type=1 if streakable else 2),
		)
	)


@_in_runtime
def like(who, count, total):
	return _message(proto_events.LikeEvent(user=who, count=count, total=total))


@_in_runtime
def follow(who):
	return _message(proto_events.SocialEvent(user=who, action=1), "pm_main_follow_message_viewer_2")


@_in_runtime
def share(who):
	return _message(proto_events.SocialEvent(user=who, action=3), "pm_mt_guidance_share")


@_in_runtime
def join(who):
	return _message(proto_events.JoinEvent(user=who, action=1), "live_room_enter_toast")


@_in_runtime
def viewers(total):
	return _message(proto_events.RoomUserSeqEvent(total=total))


@_in_runtime
def guest_request(who):
	return _message(proto_events.LinkMicMethodEvent(message_type=1, user_id=who.id))


@_in_runtime
def applicant_queue(*people):
	"""A link layer list change with these people waiting to join, as user ids."""
	queue = [linkcore.LinkLayerListUser(user=linkcore.Player(room_id=1, user_id=person.id)) for person in people]
	return _message(
		proto_events.LinkLayerEvent(
			list_change_content=linkcore.LinkListChangeContent(type=2, list=linkcore.AllListUser(applied_list=queue))
		)
	)


@_in_runtime
def live_ended():
	return _message(proto_events.ControlEvent(action=ControlAction.STREAM_ENDED))


@_in_runtime
def frame(*messages):
	"""Messages as one websocket frame, decoded the way the websocket loop decodes it."""
	whole = proto.ProtoMessageFetchResult(messages=list(messages))
	return proto.ProtoMessageFetchResult.parse(bytes(whole))


@_in_runtime
def recorded_frames(path, pace=1.0):
	"""A recording from tools/record_live.py as frames, with its pauses scaled by ``pace``
	(0 replays without pauses)."""
	rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
	rows = [row for row in rows if "method" in row]
	frames, previous_time = [], None
	for number, group in itertools.groupby(rows, key=lambda row: row["frame"]):
		group = list(group)
		if previous_time is not None and pace:
			gap = (group[0]["t"] - previous_time) * pace
			if gap > 0:
				frames.append(gap)
		previous_time = group[0]["t"]
		messages = [
			proto.ProtoMessageFetchResultBaseProtoMessage(
				method=row["method"],
				payload=base64.b64decode(row["payload"]),
				msg_id=row["msg_id"],
				is_history=row["is_history"],
			)
			for row in group
		]
		whole = proto.ProtoMessageFetchResult(messages=messages, is_first=group[0]["is_first"])
		frames.append(proto.ProtoMessageFetchResult.parse(bytes(whole)))
	return frames


def write_recording(path, *items, user="host", start=None):
	"""Write messages (and pauses in seconds) in the recorder's format, one frame per message."""
	clock = start if start is not None else time.time()
	with Path(path).open("w", encoding="utf-8") as out:
		out.write(
			json.dumps({"header": True, "user": user, "started": "synthetic", "library": "7.0.1"}) + "\n"
		)
		number = 0
		for item in items:
			if isinstance(item, (int, float)):
				clock += item
				continue
			number += 1
			out.write(
				json.dumps(
					{
						"t": round(clock, 3),
						"frame": number,
						"is_first": number == 1,
						"method": item.method,
						"msg_id": item.msg_id,
						"is_history": False,
						"payload": base64.b64encode(item.payload).decode("ascii"),
					}
				)
				+ "\n"
			)


class _ReplayClient(TikTokLive.TikTokLiveClient):
	"""Replays the current session's frames instead of connecting."""

	session = None

	async def connect(self, **kwargs):
		session = self.session
		session.threads.append(threading.current_thread())
		self._room_id = 1
		await self._replay(session)

	async def _replay(self, session):
		recorded_connect = any(getattr(item, "is_first", False) for item in session.frames)
		if not recorded_connect:
			self.emit(ConnectEvent.get_type(), ConnectEvent(unique_id="host", room_id=1))
			await self.wait_for_complete()
		if session.past_grace_period:
			pipeline.connection_time = (session.clock or time).time() - 60
		for item in session.frames:
			if isinstance(item, (int, float)):
				if session.clock:
					session.clock.advance(item)
				else:
					await asyncio.sleep(item)
				continue
			async for event in self._parse_webcast_response(item):
				self.emit(event.get_type(), event)
			await self.wait_for_complete()
		if session.end == "hold":
			while not session.release.is_set():
				await asyncio.sleep(0.02)
		if session.end == "error":
			raise ConnectionError("replay ended with a dropped connection")


class _RecordingSounds:
	"""Stands in for announcer.sound_manager: records instead of playing, no delays."""

	def __init__(self):
		self.played = []
		self._queue = queue.Queue()

	def play(self, event_name, play_file=True, on_complete=None, post_delay=1.0):
		self.played.append((event_name, play_file))
		if on_complete:
			on_complete()

	def set_volume(self, volume):
		pass

	def start(self):
		pass

	def stop(self):
		pass

	def clear(self):
		pass


@dataclass
class Session:
	"""``end``: "clean" (the stream is over), "error" (dropped connection) or
	"hold" (stays connected until ``release`` is set)."""

	frames: list
	end: str = "clean"
	past_grace_period: bool = True
	release: threading.Event = field(default_factory=threading.Event)
	sounds: object = None
	threads: list = field(default_factory=list)
	clock: object = None
	speech: list = field(default_factory=list)


class VirtualClock:
	"""Stands in for the ``time`` module in the add-on's modules during a replay:
	``time()`` is the recorded time, which the replay's pauses advance at once.
	The add-on's ``threading.Timer`` runs on it too, firing in the replay thread
	when a pause passes its time."""

	def __init__(self, start=1_000_000.0):
		self.now = start
		self._timers = []

	def time(self):
		return self.now

	def advance(self, seconds):
		target = self.now + seconds
		while True:
			due = [timer for timer in self._timers if timer.deadline <= target]
			if not due:
				break
			timer = min(due, key=lambda timer: timer.deadline)
			self._timers.remove(timer)
			self.now = max(self.now, timer.deadline)
			timer.function(*timer.args)
		self.now = target

	def __getattr__(self, name):
		return getattr(time, name)


class _VirtualTimer:
	def __init__(self, clock, interval, function, args=None):
		self.clock, self.interval, self.function, self.args = clock, interval, function, args or []
		self.daemon = True

	def start(self):
		self.deadline = self.clock.now + self.interval
		self.clock._timers.append(self)

	def cancel(self):
		if self in self.clock._timers:
			self.clock._timers.remove(self)


class _VirtualThreading:
	def __init__(self, clock):
		self._clock = clock

	def Timer(self, interval, function, args=None):
		return _VirtualTimer(self._clock, interval, function, args)

	def __getattr__(self, name):
		return getattr(threading, name)


@contextlib.contextmanager
def _clock_in_addon(clock):
	stand_ins = {"time": (time, clock), "threading": (threading, _VirtualThreading(clock))}
	patched = []
	for name, module in list(sys.modules.items()):
		if name.startswith(f"{support.PACKAGE}."):
			for attribute, (real, stand_in) in stand_ins.items():
				if getattr(module, attribute, None) is real:
					setattr(module, attribute, stand_in)
					patched.append((module, attribute, real))
	try:
		yield
	finally:
		for module, attribute, real in patched:
			setattr(module, attribute, real)


@dataclass
class Result:
	files: dict
	speech: list
	sounds: list
	callbacks: list
	log_dir: Path
	stats: dict = field(default_factory=dict)


def write_settings(**sections):
	"""Write the settings file the add-on reads on connect.

	Keyword arguments are sections, e.g. ``events={"likes": False}``.
	"""
	config = addon_settings.apply_config_defaults(addon_settings.read_config_file())
	for section, values in sections.items():
		for key, value in values.items():
			config[section][key] = addon_settings._as_ini(value)
	with open(addon_settings.CONFIG_PATH, "w", encoding="utf-8") as handle:
		config.write(handle)


_session_numbers = itertools.count(1)


def fresh_log_dir():
	return support.ROOT / f"session{next(_session_numbers)}"


def wait_until(condition, timeout=10):
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		if condition():
			return True
		time.sleep(0.01)
	return False


@contextlib.contextmanager
def replaying(*frames, end="clean", past_grace_period=True, clock=None):
	"""While active, the add-on's connections replay ``frames`` instead of connecting.

	A number among the frames is a pause in seconds; with a ``VirtualClock`` the
	pauses only advance the clock the add-on reads.
	"""
	frames = [
		item if isinstance(item, (int, float, proto.ProtoMessageFetchResult)) else frame(item)
		for item in frames
	]
	session = Session(frames, end, past_grace_period, clock=clock)
	real_sounds = announcer.sound_manager
	session.sounds = announcer.sound_manager = _RecordingSounds()
	real_queue_speech = announcer.queue_speech

	def queue_speech(text):
		session.speech.append(text)
		real_queue_speech(text)

	announcer.queue_speech = queue_speech
	runtime = adapter.runtime().modules["TikTokLive"]
	real_client_class = runtime.TikTokLiveClient
	runtime.TikTokLiveClient = _ReplayClient
	_ReplayClient.session = session
	with _clock_in_addon(clock) if clock else contextlib.nullcontext():
		try:
			yield session
		finally:
			session.release.set()
			for thread in session.threads:
				thread.join(10)
			runtime.TikTokLiveClient = real_client_class
			announcer.sound_manager = real_sounds
			announcer.queue_speech = real_queue_speech


def run_session(
	*frames,
	end="clean",
	past_grace_period=True,
	settle_likes=True,
	settings=None,
	log_dir=None,
	timeout=60,
	clock=None,
):
	"""Run one connection through the add-on's real thread, replaying ``frames``.

	``settle_likes`` lets the like aggregator's 10 second timers fire before
	the session closes, as they would in a session that stays open.
	"""
	if addon_settings.CONFIG_PATH.exists():
		addon_settings.CONFIG_PATH.unlink()
	write_settings(**(settings or {}))
	log_dir = log_dir or fresh_log_dir()
	store.set_folder(log_dir)

	callbacks = []
	finished = threading.Event()
	logged_before = len(support.logged)

	def record(name, last=False):
		def callback():
			callbacks.append(name)
			if last:
				finished.set()

		return callback

	with replaying(*frames, end=end, past_grace_period=past_grace_period, clock=clock) as session:
		addon_session.connect(
			username="host",
			on_connect=record("connected"),
			on_retry=record("retry"),
			on_fail=record("fail", last=True),
			on_live_end=record("live_end", last=True),
			retry_count=1,
		)
		pauses = 0 if clock else sum(item for item in frames if isinstance(item, (int, float)))
		if not finished.wait(timeout + pauses):
			raise TimeoutError("the replayed session did not finish")
		if settle_likes:
			settle_like_timers()
		stats = {
			"viewer_count": pipeline.viewer_count,
			"total_viewers": pipeline.total_viewers,
			"total_likes": pipeline.total_likes,
			"total_followers": pipeline.total_followers,
			"total_diamonds": pipeline.total_diamonds,
		}
		addon_session.disconnect()

	files = {}
	for path in store.session_files():
		files[path.name] = (
			path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else None
		)
	errors = [message for level, message in support.logged[logged_before:] if level == "error"]
	if errors:
		raise AssertionError(f"the add-on logged errors: {errors}")
	return Result(files, session.speech, session.sounds.played, callbacks, log_dir, stats)


def settle_like_timers():
	"""Fire the like aggregator's pending timers now instead of after 10 seconds."""
	pipeline.like_manager.flush_pending()


def without_times(lines):
	"""Log lines without their trailing "  HH:MM:SS" time stamp."""
	return [line.rsplit("  ", 1)[0] for line in lines or []]
