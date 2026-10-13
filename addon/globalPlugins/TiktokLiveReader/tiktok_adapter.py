"""Everything that knows TikTokLive: the bundled copy, the client, and turning the
library's events into the add-on's own (events.py). The listeners are those of
1.8, doubled registrations included: a comment reaches the pipeline twice, a
follow or share once as itself and once as a social message (see findings.md)."""

from pathlib import Path

from . import events
from .vendor_loader import load_runtime, runtime_scope

LIB_DIR = Path(__file__).resolve().parent / "lib"
RUNTIME = load_runtime(str(LIB_DIR))

LINK_EVENTS = ("LinkLayerEvent", "LinkMicMethodEvent", "GuestInviteEvent")
# Listened to by name; TikTokLive emits no events by these names.
LINK_MESSAGE_NAMES = ("WebcastLinkLayerMessage", "WebcastLinkMicMethodMessage", "WebcastGuestInviteMessage")


def _optional(module, *names):
	"""The named classes, or None for all of them when one is missing."""
	try:
		return {name: getattr(module, name) for name in names}
	except AttributeError:
		return dict.fromkeys(names)


def event_classes():
	"""The client class and the event classes the add-on listens to; raises when
	the library cannot be loaded."""
	with runtime_scope(RUNTIME):
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
	"""A client for ``username`` that calls ``deliver`` with each of the add-on's
	events, ``on_connected()`` when connected and ``on_live_end()`` when the live
	ends."""
	with runtime_scope(RUNTIME):
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
	return client


def run(client):
	"""Connect and handle the live until it ends or the connection drops."""
	with runtime_scope(RUNTIME):
		client.run()


def legacy_id(event):
	ident = getattr(event, "msgId", None)
	if not ident:
		ident = getattr(event, "id", None)
	if not ident:
		base = getattr(event, "base_message", None)
		if base:
			ident = getattr(base, "msg_id", None)
	return ident


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


def _comment(event):
	text = (
		getattr(event, "comment", None)
		or getattr(event, "content", None)
		or getattr(event, "text", None)
		or getattr(event, "msg", None)
		or getattr(event, "message", None)
	)
	if not text:
		parts = getattr(event, "comments", None)
		if isinstance(parts, (list, tuple)) and parts:
			text = " ".join(str(part) for part in parts if part is not None).strip()
	if not text:
		display_text = getattr(event, "display_text", None)
		text = getattr(display_text, "default_pattern", None) or getattr(display_text, "key", None)
	return events.Comment(legacy_id(event), _user(event), text)


def _follow(event):
	return events.Follow(legacy_id(event), _user(event))


def _share(event):
	return events.Share(legacy_id(event), _user(event))


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


def _gift(event):
	gift = getattr(event, "gift", None)
	return events.Gift(
		legacy_id=legacy_id(event),
		user=_user(event),
		repeat_end=getattr(event, "repeat_end", True),
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
	return events.Like(_user(event), total, count)


def _join(event):
	return events.Join(_user(event))


def _viewer_count(event):
	if hasattr(event, "m_total"):
		return events.ViewerCount(event.m_total)
	if hasattr(event, "viewer_count"):
		return events.ViewerCount(event.viewer_count)
	return events.ViewerCount(None)


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
