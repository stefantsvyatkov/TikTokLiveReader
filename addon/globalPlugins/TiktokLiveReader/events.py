"""The add-on's own events, made from the library's by tiktok_adapter.py: what the
pipeline reads, as plain values. ``legacy_id`` is what 1.8 deduplicates by (F4:
never set by TikTokLive 6.6.5)."""

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
	legacy_id: object
	user: Person | None
	text: object


@dataclass(frozen=True)
class Follow:
	legacy_id: object
	user: Person | None


@dataclass(frozen=True)
class Share:
	legacy_id: object
	user: Person | None


@dataclass(frozen=True)
class Gift:
	legacy_id: object
	user: Person | None
	repeat_end: object
	repeat_count: object
	name: object
	diamond_count: object


@dataclass(frozen=True)
class Like:
	"""``total`` is the live's like count, None when the message has none."""

	user: Person | None
	total: object
	count: int


@dataclass(frozen=True)
class Join:
	user: Person | None


@dataclass(frozen=True)
class ViewerCount:
	"""``total`` is None when the message has no count."""

	total: object


@dataclass(frozen=True)
class LinkMessage:
	"""A guest request, invitation or link layer change, with the people in it in
	the order 1.8 looks at them."""

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
