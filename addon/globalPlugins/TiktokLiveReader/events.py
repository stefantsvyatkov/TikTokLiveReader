"""The add-on's own events, made from the library's by tiktok_adapter.py: what the
pipeline reads, as plain values. ``message_id`` is TikTok's id of the message an
event came in (0 when unknown): the same message delivered twice has the same id."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
	"""A user object as the library gave it. ``present`` is False for an empty
	one; ``nick_name`` is the name 1.8 remembers people by; ``nickname`` and
	``unique_id`` are None when the object has no such attribute."""

	present: bool
	user_id: object
	nick_name: object
	nickname: object
	unique_id: object


@dataclass(frozen=True)
class Comment:
	message_id: int
	user: Person | None
	text: object


@dataclass(frozen=True)
class Follow:
	message_id: int
	user: Person | None


@dataclass(frozen=True)
class Share:
	"""``repost``: shown to the person's followers rather than sent to someone."""

	message_id: int
	user: Person | None
	repost: bool = False


@dataclass(frozen=True)
class FanClubJoin:
	"""Someone joined the host's fan club; ``number`` is their place in it."""

	message_id: int
	user: Person | None
	number: str


@dataclass(frozen=True)
class LiveState:
	"""The live paused (the host left the app) or went on."""

	message_id: int
	paused: bool


@dataclass(frozen=True)
class Gift:
	"""``streaking``: a streak is under way and this is not its last message."""

	message_id: int
	user: Person | None
	streaking: bool
	repeat_count: object
	name: object
	diamond_count: object


@dataclass(frozen=True)
class Like:
	"""``total`` is the live's like count, None when the message has none."""

	message_id: int
	user: Person | None
	total: object
	count: int


@dataclass(frozen=True)
class Join:
	message_id: int
	user: Person | None


@dataclass(frozen=True)
class ViewerCount:
	"""``total`` is None when the message has no count."""

	message_id: int
	total: object


@dataclass(frozen=True)
class LinkMessage:
	"""A guest request, invitation or link layer change, with the people in it in
	the order 1.8 looks at them."""

	message_id: int
	kind: str
	has_apply: bool
	applicant: Person | None
	has_invite: bool
	invitee: Person | None
	user: Person | None
	inviter_nickname: object
	display_people: tuple
	has_list_change: bool
	list_change_type: object
	applied: tuple
	message_type: str
	m_type: str
	# People named with their nicknames: the queue and the guests in
	# TikTokLive 7's LinkEvent, which the link layer lists by id only.
	named: tuple = ()
