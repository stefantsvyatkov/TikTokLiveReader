"""Everything that knows TikTokLive: the bundled copy, the client, and turning the
library's events into the add-on's own (events.py). The listeners are those of
1.8: a comment reaches the pipeline twice, a follow or share once as itself and
once as a social message; the pipeline handles each message once by its id."""

import asyncio
import contextlib
import threading
from pathlib import Path

from . import events, vendor

LIB_DIR = Path(__file__).resolve().parent / "lib"
_runtime = None
_runtime_lock = threading.Lock()

LINK_EVENTS = ("LinkLayerEvent", "LinkMicMethodEvent", "GuestInviteEvent")
# Listened to by name; TikTokLive emits no events by these names.
LINK_MESSAGE_NAMES = ("WebcastLinkLayerMessage", "WebcastLinkMicMethodMessage", "WebcastGuestInviteMessage")


def runtime():
	"""The bundled library, loaded on first use: it takes 0.7 s or more, which
	NVDA's start should not pay when the add-on is not used (F18)."""
	global _runtime
	with _runtime_lock:
		if _runtime is None:
			_runtime = vendor.load(
				LIB_DIR, "TikTokLive", "httpx", "websockets", optional=("google.protobuf",)
			)
		return _runtime


def library_scope():
	"""The bundled TikTokLive and its dependencies importable by their names."""
	return vendor.scope(runtime())


def _optional(module, *names):
	"""The named classes, or None for all of them when one is missing."""
	try:
		return {name: getattr(module, name) for name in names}
	except AttributeError:
		return dict.fromkeys(names)


def event_classes():
	"""The client class and the event classes the add-on listens to; raises when
	the library cannot be loaded."""
	with library_scope():
		import TikTokLive.events as module
		from TikTokLive import TikTokLiveClient
		from TikTokLive.events import (
			CommentEvent,
			ConnectEvent,
			DiggEvent,
			FollowEvent,
			GiftEvent,
			JoinEvent,
			LikeEvent,
		)

		classes = {
			"TikTokLiveClient": TikTokLiveClient,
			"CommentEvent": CommentEvent,
			"ConnectEvent": ConnectEvent,
			"DiggEvent": DiggEvent,
			"FollowEvent": FollowEvent,
			"GiftEvent": GiftEvent,
			"JoinEvent": JoinEvent,
			"LikeEvent": LikeEvent,
		}
		classes.update(_optional(module, "CommentsEvent"))
		classes.update(_optional(module, "EmoteChatEvent", "ScreenChatEvent"))
		classes.update(_optional(module, "ViewerUpdateEvent", "RoomUserSeqEvent"))
		if classes["ViewerUpdateEvent"] is None:
			classes.update(_optional(module, "RoomUserSeqEvent"))
		for name in ("ShareEvent", "SocialEvent", "LiveEndEvent") + LINK_EVENTS:
			classes.update(_optional(module, name))
	return classes


def new_client(username, classes, deliver, on_connected, on_live_end):
	"""A connection to ``username``'s live that calls ``deliver`` with each of the
	add-on's events, ``on_connected()`` when connected and ``on_live_end()`` when
	the live ends."""
	with library_scope():
		client = classes["TikTokLiveClient"](unique_id=username)

		def listen(event, convert):
			async def listener(library_event):
				converted = convert(library_event)
				if converted is not None:
					deliver(converted)

			client.add_listener(event, listener)

		for name in ("CommentEvent", "CommentsEvent", "EmoteChatEvent", "ScreenChatEvent"):
			if classes[name]:
				listen(classes[name], _comment)
				listen(name, _comment)
		listen(classes["FollowEvent"], _follow)
		listen(classes["GiftEvent"], _gift)
		listen(classes["LikeEvent"], _like)
		listen(classes["DiggEvent"], _like)
		listen(classes["JoinEvent"], _join)
		for name, convert in (("ShareEvent", _share), ("SocialEvent", _social)):
			if classes[name]:
				try:
					listen(classes[name], convert)
				except Exception:
					pass
		for name in ("ViewerUpdateEvent", "RoomUserSeqEvent"):
			if classes[name]:
				listen(classes[name], _viewer_count)
		for name in LINK_EVENTS:
			if classes[name]:
				listen(classes[name], _link)
				listen(name, _link)
		for name in LINK_MESSAGE_NAMES:
			listen(name, _link)

		async def connected(library_event):
			on_connected()

		async def live_ended(library_event):
			on_live_end()

		client.add_listener(classes["ConnectEvent"], connected)
		if classes["LiveEndEvent"]:
			client.add_listener(classes["LiveEndEvent"], live_ended)
		client.add_listener("LiveEndEvent", live_ended)
	return Connection(client)


class Connection:
	"""One connection: the library's client and the event loop it runs on, in the
	thread that calls ``run``. 1.8 ran it in a loop nobody kept, so switching off
	could not close it (F1) and waited 3 s for it (F27)."""

	def __init__(self, client):
		self.client = client
		self._loop = None
		self._task = None
		self._stopping = False

	def run(self):
		"""Connect and handle the live until it ends, the connection drops or
		``stop`` is called; raises when connecting fails."""
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		try:
			with library_scope():
				self._task = loop.create_task(self._connect())
				self._loop = loop
				try:
					loop.run_until_complete(self._task)
				except asyncio.CancelledError:
					pass
				finally:
					_close_loop(loop, self.client)
		finally:
			asyncio.set_event_loop(None)

	async def _connect(self):
		if not self._stopping:
			await self.client.connect()

	def stop(self):
		"""Close the connection, from any thread; returns at once."""
		self._stopping = True
		loop = self._loop
		if loop is not None and loop.is_running():
			with contextlib.suppress(RuntimeError):
				asyncio.run_coroutine_threadsafe(self._shut_down(), loop)

	async def _shut_down(self):
		with contextlib.suppress(Exception):
			await self.client.disconnect()
		if self._task is not None:
			self._task.cancel()


def _close_loop(loop, client):
	"""Leave nothing running on the loop and close it (F15)."""
	with contextlib.suppress(Exception):
		loop.run_until_complete(client.close())
	pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
	for task in pending:
		task.cancel()
	with contextlib.suppress(Exception):
		loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
	with contextlib.suppress(Exception):
		loop.run_until_complete(loop.shutdown_asyncgens())
	loop.close()


def message_id(event):
	return getattr(getattr(event, "base_message", None), "message_id", 0) or 0


def _person(user):
	if user is None:
		return None
	return events.Person(
		present=bool(user),
		user_id=getattr(user, "id", getattr(user, "uid", None)),
		nick_name=getattr(user, "nick_name", getattr(user, "nickname", None)),
		nickname=getattr(user, "nickname", None),
		unique_id=getattr(user, "unique_id", None),
	)


def _user(event):
	return _person(getattr(event, "user", None))


COMMENT_TEXT_ATTRIBUTES = ("comment", "content", "text", "msg", "message")


def _comment_text(event):
	"""The text however the comment-like event carries it, a falsy value without."""
	for name in COMMENT_TEXT_ATTRIBUTES:
		value = getattr(event, name, None)
		if value:
			return value
	parts = getattr(event, "comments", None)
	if isinstance(parts, (list, tuple)) and parts:
		joined = " ".join(str(part) for part in parts if part is not None).strip()
		if joined:
			return joined
	display_text = getattr(event, "display_text", None)
	return getattr(display_text, "default_pattern", None) or getattr(display_text, "key", None)


def _comment(event):
	return events.Comment(message_id(event), _user(event), _comment_text(event))


def _follow(event):
	return events.Follow(message_id(event), _user(event))


def _share(event):
	return events.Share(message_id(event), _user(event))


def _social(event):
	action = getattr(event, "action", None)
	display_text = getattr(event, "display_text", None)
	key = getattr(display_text, "key", "").lower()
	pattern = getattr(display_text, "default_pattern", "").lower()
	if action == 3 or "share" in key or "share" in pattern:
		return _share(event)
	if action == 1 or "follow" in key or "follow" in pattern:
		return _follow(event)
	return None


def _streaking(event, gift):
	try:
		return bool(event.streaking)
	except Exception:
		# A plain Gift has no ``streakable``; the library's rule: type 1 can streak.
		return getattr(gift, "type", 1) == 1 and not getattr(event, "repeat_end", True)


def _gift(event):
	gift = getattr(event, "gift", None)
	return events.Gift(
		message_id=message_id(event),
		user=_user(event),
		streaking=_streaking(event, gift),
		repeat_count=getattr(event, "repeat_count", 1),
		name=getattr(gift, "name", "Gift"),
		diamond_count=getattr(gift, "diamond_count", 0),
	)


def _like(event):
	total = None
	for name in ("totalLikeCount", "total", "totalDiggCount"):
		if hasattr(event, name):
			total = getattr(event, name)
			break
	increment = next(
		(
			getattr(event, name)
			for name in ("likeCount", "count", "diggCount", "increment", "delta")
			if hasattr(event, name)
		),
		0,
	)
	count = increment if isinstance(increment, int) and increment > 0 else 1
	return events.Like(message_id(event), _user(event), total, count)


def _join(event):
	return events.Join(message_id(event), _user(event))


def _viewer_count(event):
	if hasattr(event, "m_total"):
		return events.ViewerCount(message_id(event), event.m_total)
	if hasattr(event, "viewer_count"):
		return events.ViewerCount(message_id(event), event.viewer_count)
	return events.ViewerCount(message_id(event), None)


def _as_int(value):
	try:
		return int(value)
	except (TypeError, ValueError):
		return value


def _link(event):
	try:
		has_apply = hasattr(event, "apply_content") and event.apply_content is not None
		has_invite = hasattr(event, "invite_content") and event.invite_content is not None
		display_people = []
		if hasattr(event, "base_message") and event.base_message:
			display_text = getattr(event.base_message, "display_text", None)
			if display_text and hasattr(display_text, "pieces") and display_text.pieces:
				for piece in display_text.pieces:
					value = getattr(piece, "user_value", None)
					if value and hasattr(value, "user"):
						display_people.append(_person(value.user))
		has_list_change = bool(hasattr(event, "list_content") and event.list_content)
		change_type = None
		applied = []
		if has_list_change:
			content = event.list_content
			change_type = getattr(content, "list_change_type", None)
			if hasattr(content, "user_list") and content.user_list:
				user_list = content.user_list
				if hasattr(user_list, "applied_list") and user_list.applied_list:
					for application in user_list.applied_list:
						if hasattr(application, "link_user") and application.link_user:
							applied.append(_person(application.link_user))
		return events.LinkMessage(
			message_id=message_id(event),
			kind=type(event).__name__,
			has_apply=has_apply,
			applicant=_person(getattr(event.apply_content, "applicant", None)) if has_apply else None,
			has_invite=has_invite,
			invitee=_person(getattr(event.invite_content, "invitee", None)) if has_invite else None,
			user=_person(event.user) if hasattr(event, "user") else None,
			inviter_nickname=getattr(event, "inviter_nickname", None),
			display_people=tuple(display_people),
			has_list_change=has_list_change,
			list_change_type=None if change_type is None else _as_int(change_type),
			applied=tuple(applied),
			message_type=str(getattr(event, "message_type", "")),
			m_type=str(getattr(event, "m_type", getattr(event, "mType", ""))),
		)
	except Exception:
		return None
