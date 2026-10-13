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
import functools
import itertools
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import support

client = support.load("client")

with client.runtime_scope(client._RUNTIME):
	import TikTokLive
	from TikTokLive.events import ConnectEvent
	from TikTokLive.events import proto_events
	from TikTokLive.proto import tiktok_proto as proto
	from TikTokLive.proto.custom_proto import ControlAction

_ids = itertools.count(1_000_001)


def _in_runtime(function):
	"""betterproto resolves type hints through sys.modules, which only holds the
	add-on's TikTokLive inside runtime_scope; the add-on runs the connection there too."""

	@functools.wraps(function)
	def wrapper(*args, **kwargs):
		with client.runtime_scope(client._RUNTIME):
			return function(*args, **kwargs)

	return wrapper
METHODS = {event: method for method, event in proto_events.EVENT_MAPPINGS.items()}


@_in_runtime
def user(nickname, unique_id=None, user_id=None):
	return proto.User(
		id=user_id if user_id is not None else abs(hash(unique_id or nickname)) % 10**12,
		nick_name=nickname,
		username=unique_id or nickname.lower().replace(" ", "_"),
	)


@_in_runtime
def _message(event, display_key=""):
	event.base_message = proto.CommonMessageData(
		message_id=next(_ids),
		create_time=int(time.time() * 1000),
		display_text=proto.Text(key=display_key),
	)
	return proto.ProtoMessageFetchResultBaseProtoMessage(
		method=METHODS[type(event)],
		payload=bytes(event),
		msg_id=event.base_message.message_id,
	)


@_in_runtime
def comment(who, text):
	return _message(proto_events.CommentEvent(user_info=who, content=text))


@_in_runtime
def gift(who, name, diamonds=1, count=1, repeat_end=1, streakable=True):
	return _message(proto_events.GiftEvent(
		from_user=who,
		repeat_count=count,
		repeat_end=repeat_end,
		m_gift=proto.Gift(name=name, diamond_count=diamonds, type=1 if streakable else 2),
	))


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
	return _message(proto_events.RoomUserSeqEvent(m_total=total))


@_in_runtime
def guest_request(who):
	return _message(proto_events.LinkMicMethodEvent(m_type=1, user_id=who.id))


@_in_runtime
def live_ended():
	return _message(proto_events.ControlEvent(action=ControlAction.CONTROL_ACTION_STREAM_ENDED))


@_in_runtime
def frame(*messages):
	"""Messages as one websocket frame, decoded the way the websocket loop decodes it."""
	whole = proto.ProtoMessageFetchResult(messages=list(messages))
	return proto.ProtoMessageFetchResult().parse(bytes(whole))


class _ReplayClient(TikTokLive.TikTokLiveClient):
	"""Replays the current session's frames instead of connecting."""

	session = None

	def run(self, **kwargs):
		return self._asyncio_loop.run_until_complete(self._replay(self.session))

	async def _replay(self, session):
		self.emit(ConnectEvent.get_type(), ConnectEvent(unique_id="host", room_id=1))
		await self.wait_for_complete()
		if session.past_grace_period:
			client._connection_time = time.time() - 60
		for item in session.frames:
			if isinstance(item, (int, float)):
				await asyncio.sleep(item)
				continue
			async for event in self._parse_webcast_response(item):
				self.emit(event.type, event)
			await self.wait_for_complete()
		if session.end == "error":
			raise ConnectionError("replay ended with a dropped connection")


class _RecordingSounds:
	"""Stands in for client.sound_manager: records instead of playing, no delays."""

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
	frames: list
	end: str = "clean"
	past_grace_period: bool = True


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
	config = client.apply_config_defaults(client.read_config_file())
	for section, values in sections.items():
		for key, value in values.items():
			config[section][key] = client._as_ini(value)
	with open(client.CONFIG_PATH, "w", encoding="utf-8") as handle:
		config.write(handle)


_session_numbers = itertools.count(1)


def run_session(*frames, end="clean", past_grace_period=True, settle_likes=True, settings=None, log_dir=None):
	"""Run one connection through the add-on's real thread, replaying ``frames``.

	A number among the frames is a pause in seconds.

	``settle_likes`` lets the like aggregator's 10 second timers fire before
	the session closes, as they would in a session that stays open.
	"""
	if client.CONFIG_PATH.exists():
		client.CONFIG_PATH.unlink()
	write_settings(**(settings or {}))
	log_dir = log_dir or support.ROOT / f"session{next(_session_numbers)}"
	client.set_log_directory(log_dir)

	real_sounds = client.sound_manager
	sounds = client.sound_manager = _RecordingSounds()
	real_client_class = client._RUNTIME.modules["TikTokLive"].TikTokLiveClient
	client._RUNTIME.modules["TikTokLive"].TikTokLiveClient = _ReplayClient
	frames = [
		item if isinstance(item, (int, float, proto.ProtoMessageFetchResult)) else frame(item)
		for item in frames
	]
	_ReplayClient.session = Session(frames, end, past_grace_period)

	callbacks = []
	finished = threading.Event()

	def record(name, last=False):
		def callback():
			callbacks.append(name)
			if last:
				finished.set()
		return callback

	try:
		client.connect(
			username="host",
			on_connect=record("connected"),
			on_retry=record("retry"),
			on_fail=record("fail", last=True),
			on_live_end=record("live_end", last=True),
			retry_count=1,
		)
		if not finished.wait(60):
			raise TimeoutError("the replayed session did not finish")
		if client._thread is not None:
			client._thread.join(10)
		if settle_likes:
			for name in list(client.like_manager._timers):
				client.like_manager._timers[name].cancel()
				client.like_manager._flush(name)
		stats = {
			"viewer_count": client.viewer_count,
			"total_viewers": client.total_viewers,
			"total_likes": client.total_likes,
			"total_followers": client.total_followers,
			"total_diamonds": client.total_diamonds,
		}
		client.disconnect()
	finally:
		client._RUNTIME.modules["TikTokLive"].TikTokLiveClient = real_client_class
		client.sound_manager = real_sounds

	files = {}
	for path in client._session_files():
		files[path.name] = path.read_text(encoding="utf-8").splitlines() if path.exists() else None
	speech = []
	if client.SPEECH_BUFFER_FILE.exists():
		for line in client.SPEECH_BUFFER_FILE.read_text(encoding="utf-8").splitlines():
			if line.strip():
				speech.append(json.loads(line)["text"])
	return Result(files, speech, sounds.played, callbacks, log_dir, stats)


def without_times(lines):
	"""Log lines without their trailing "  HH:MM:SS" time stamp."""
	return [line.rsplit("  ", 1)[0] for line in lines or []]
