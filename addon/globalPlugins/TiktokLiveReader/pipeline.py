"""What the add-on does with each event (events.py): the duplicate checks, the
lines in the text files, the counters, the stats and top files, and what is
announced. Runs on the connection thread; holds the state of the session."""

import datetime
import re
import threading
import time
import unicodedata

from . import announcer, events, likes, store
from .i18n import _
from .settings import Settings

MAX_TRACKED_ITEMS = 50000
# Message ids remembered to recognise a message delivered again; repeats come
# within seconds, the history repeated in the first frames.
MAX_MESSAGE_IDS = 10000
MAX_TIMESTAMP_ITEMS = 5000
STATS_MIN_INTERVAL = 1.0
# Announcements wait this long after connecting: the first seconds bring the
# live's history.
GRACE_PERIOD = 10.0


class BoundedSet:
	"""Set that forgets the oldest entries instead of dropping everything at once."""

	def __init__(self, limit):
		self._limit = limit
		self._items = {}

	def add(self, item):
		self._items[item] = None
		while len(self._items) > self._limit:
			del self._items[next(iter(self._items))]

	def clear(self):
		self._items.clear()

	def __contains__(self, item):
		return item in self._items

	def __len__(self):
		return len(self._items)


_settings = Settings()
connection_time = 0

top_gifters = {}
top_likers = {}
total_likes = 0
total_followers = 0
total_diamonds = 0
visitors = set()
viewer_count = 0
total_viewers = 0
# Lines of earlier sessions in kept text files: the history TikTok sends on
# connecting is not logged again.
_comments_logged_before = BoundedSet(MAX_TRACKED_ITEMS)
_events_logged_before = BoundedSet(MAX_TRACKED_ITEMS)
_known_followers = BoundedSet(MAX_TRACKED_ITEMS)
_known_users = {}
_requests_log = {}
_seen_messages = BoundedSet(MAX_MESSAGE_IDS)

_stats_lock = threading.Lock()
_stats_dirty = False
_stats_last_write = 0.0


def use_settings(new):
	global _settings
	_settings = new


def _now():
	return datetime.datetime.now().strftime("%H:%M:%S")


def _prune_timestamps(mapping, max_age):
	if len(mapping) <= MAX_TIMESTAMP_ITEMS:
		return
	cutoff = time.time() - max_age
	for key in [k for k, v in mapping.items() if v < cutoff]:
		del mapping[key]


def _remember_user(uid, name):
	if not uid or not name:
		return
	_known_users[str(uid)] = name
	while len(_known_users) > MAX_TRACKED_ITEMS:
		del _known_users[next(iter(_known_users))]


def _sanitize_name(name):
	if not _settings.clean_usernames or not isinstance(name, str):
		return name
	out = []
	for ch in name:
		cat = unicodedata.category(ch)
		if ch.isspace() or cat.startswith("P"):
			out.append(ch)
		elif cat == "Nd":
			out.append(ch)
		elif cat[0] == "L":
			uname = unicodedata.name(ch, "")
			if "LATIN" in uname or "CYRILLIC" in uname:
				out.append(ch)
	return "".join(out).strip()


def _display_name(person):
	"""The person's nickname, else their handle, else "someone"."""
	if person is not None:
		for value in (person.nickname, person.unique_id):
			if value:
				return value
	return "someone"


def _clean_name(name, person=None):
	"""``name`` as the user names setting wants it. A name cleaning would leave
	without a letter or digit (emoji, Arabic script) becomes the person's handle,
	or stays as it is (F10)."""
	cleaned = _sanitize_name(name)
	if not name or not isinstance(cleaned, str) or any(ch.isalnum() for ch in cleaned):
		return cleaned
	handle = _sanitize_name(person.unique_id) if person is not None and person.unique_id else ""
	return handle or name


LINE_BREAKS = re.compile(r"[\r\n\u2028\u2029]+")


def _one_line(text):
	"""Each entry is one line of its file (F9)."""
	return LINE_BREAKS.sub(" ", str(text)).strip()


def _nickname(person, default):
	"""The person's ``nickname``, ``default`` when there is no such attribute."""
	if person is None or person.nickname is None:
		return default
	return person.nickname


def forget_seen():
	"""Start a connection: nothing has been seen yet."""
	global connection_time
	_comments_logged_before.clear()
	_events_logged_before.clear()
	_seen_messages.clear()
	connection_time = 0
	_known_followers.clear()


def remember_logged():
	"""Treat what the text files already hold as seen, when they are kept."""
	try:
		for line in store.read_text(store.COMMENTS).split("\n"):
			line = line.strip()
			if line:
				_comments_logged_before.add(line.rsplit("  ", 1)[0])
		if store.path(store.EVENTS).exists():
			for line in store.read_text(store.EVENTS).split("\n"):
				line = line.strip()
				if line:
					_events_logged_before.add(line.rsplit("  ", 1)[0])
	except Exception:
		pass


def reset_accumulators():
	global top_gifters, top_likers, total_likes, total_followers, total_diamonds, visitors, viewer_count
	global total_viewers
	top_gifters = {}
	top_likers = {}
	total_likes = 0
	total_followers = 0
	total_diamonds = 0
	visitors = set()
	viewer_count = 0
	total_viewers = 0

	_comments_logged_before.clear()
	_events_logged_before.clear()
	_known_followers.clear()
	_requests_log.clear()
	_seen_messages.clear()


def _write_stats_file():
	try:
		lines = [
			# Translators: Stats file lines. {count} represents the respective count.
			_("Viewers: {count}").format(count=viewer_count),
			_("Visitors: {count}").format(count=total_viewers),
			_("Likes: {count}").format(count=total_likes),
			_("Followers: {count}").format(count=total_followers),
			_("Diamonds: {count}").format(count=total_diamonds),
		]
		store.write(store.STATS, "".join(line + "\n" for line in lines))
	except Exception:
		pass


def update_stats_file(force=False):
	global _stats_dirty, _stats_last_write
	with _stats_lock:
		now = time.time()
		if not force and (now - _stats_last_write) < STATS_MIN_INTERVAL:
			_stats_dirty = True
			return
		_stats_dirty = False
		_stats_last_write = now
		_write_stats_file()


def flush_stats_file():
	with _stats_lock:
		if not _stats_dirty:
			return
	update_stats_file(force=True)


def write_top_files():
	try:
		if top_gifters:
			sorted_gifters = sorted(top_gifters.items(), key=lambda x: x[1], reverse=True)
			store.write(
				store.TOP_GIFTERS,
				"".join(f"{user}: {diamonds} diamonds\n" for user, diamonds in sorted_gifters),
			)
		if top_likers:
			sorted_likers = sorted(top_likers.items(), key=lambda x: x[1], reverse=True)
			store.write(store.TOP_LIKES, "".join(f"{user}: {count}\n" for user, count in sorted_likers))
	except Exception:
		pass


def _log_to_events(log_text):
	if log_text.rsplit("  ", 1)[0] in _events_logged_before:
		return
	try:
		store.append(store.EVENTS, log_text)
	except Exception:
		pass


def _announce(event_key, speak_text):
	if connection_time == 0 or (time.time() - connection_time) < GRACE_PERIOD:
		return
	announcer.announce(event_key, speak_text, _settings)


def _track_user(person):
	if person is not None and person.present:
		uid = person.user_id
		nick_name = person.nick_name
		if uid and nick_name:
			_remember_user(uid, _clean_name(nick_name, person))


def _report_likes(user, count):
	# Translators: Singular and plural forms for likes in the logs.
	likes_word = _("like") if count == 1 else _("likes")
	log_line = f"{user}: {count} {likes_word}  {_now()}"
	try:
		store.append(store.LIKES, log_line)
	except Exception:
		pass
	if _settings.events.get("likes", False):
		_log_to_events(log_line)
	_announce("likes", f"{user}: {count} {likes_word}")


like_manager = likes.LikeAggregator(_report_likes)


def _on_comment(event):
	_track_user(event.user)

	nickname = _clean_name(_display_name(event.user), event.user)
	_remember_user(event.user.user_id if event.user else None, nickname)
	text = _one_line(event.text) if event.text else ""
	if not text:
		return
	user_comment = f"{nickname}: {text}"
	if user_comment in _comments_logged_before:
		return
	log_line = f"{user_comment}  {_now()}"
	store.append(store.COMMENTS, log_line)
	if _settings.events.get("comments", True):
		_log_to_events(log_line)
	_announce("comments", user_comment)


def _on_follow(event):
	global total_followers
	_track_user(event.user)

	unique_id = event.user.unique_id if event.user.unique_id is not None else event.user.nickname
	if unique_id in _known_followers:
		return
	_known_followers.add(unique_id)

	total_followers += 1
	name = _clean_name(event.user.nickname, event.user)
	store.append(store.FOLLOWERS, f"{name}  {_now()}")
	# Translators: Announced when a new user follows the streamer. {name} is the user's name.
	speak_msg = _("New follower: {name}").format(name=name)
	if _settings.events.get("followers", False):
		_log_to_events(f"{speak_msg}  {_now()}")
	_announce("followers", speak_msg)
	update_stats_file()


def _on_gift(event):
	global total_diamonds
	_track_user(event.user)

	if event.streaking:
		return
	count = event.repeat_count or 1
	name = event.name
	diamonds = count * event.diamond_count
	display_name = _clean_name(_nickname(event.user, "someone"), event.user)

	if diamonds > 0:
		total_diamonds += diamonds
		top_gifters[display_name] = top_gifters.get(display_name, 0) + diamonds

	speak_msg = f"Gift: {display_name}: {count} {name}"
	log_msg = f"{speak_msg}  {_now()}"
	store.append(store.GIFTS, f"{display_name}: {count} {name}  {_now()}")
	if _settings.events.get("gifts", False):
		_log_to_events(log_msg)
	_announce("gifts", speak_msg)
	update_stats_file()


def _on_like(event):
	global total_likes
	_track_user(event.user)
	if event.total is not None:
		total_likes = event.total
	update_stats_file()

	user = event.user
	if user is None or not user.present:
		return
	raw_name = user.nickname if user.nickname else user.unique_id
	if not raw_name:
		return
	user_name = _clean_name(raw_name, user)
	if not user_name:
		return

	top_likers[user_name] = top_likers.get(user_name, 0) + event.count
	like_manager.add(user_name, top_likers[user_name])


def _on_share(event):
	_track_user(event.user)

	display_name = _clean_name(event.user.nickname, event.user)
	store.append(store.SHARES, f"{display_name}  {_now()}")
	if _settings.events.get("shares", False):
		# Translators: Announced when a user shares the live stream. {name} is the user's name.
		msg = _("{name} shared the live").format(name=display_name)
		_log_to_events(f"{msg}  {_now()}")
	msg = _("{name} shared the live").format(name=display_name)
	_announce("shares", msg)


def _on_join(event):
	global total_viewers
	_track_user(event.user)

	display_name = _clean_name(_nickname(event.user, "someone"), event.user)
	if display_name in visitors:
		return
	visitors.add(display_name)

	total_viewers = len(visitors)
	store.append(store.VISITORS, f"{display_name}  {_now()}")
	if _settings.events.get("visitors", False):
		# Translators: Announced when a user joins the live stream. {name} is the user's name.
		msg = _("{name} joined").format(name=display_name)
		_log_to_events(f"{msg}  {_now()}")
	msg = _("{name} joined").format(name=display_name)
	_announce("visitors", msg)
	update_stats_file()


def _on_viewer_count(event):
	global viewer_count
	if event.total is not None:
		viewer_count = event.total
	update_stats_file()


def _name_of(person):
	"""A name for the person: theirs, cleaned, or the one remembered for their id."""
	if not person or not person.present:
		return None
	uid = person.user_id
	if person.nick_name:
		sanitized = _clean_name(person.nick_name, person)
		if sanitized:
			_remember_user(uid, sanitized)
			return sanitized
	if uid and str(uid) in _known_users:
		return _known_users[str(uid)]
	return None


REQUEST_KINDS = (
	"LinkMicMethodEvent",
	"GuestInviteEvent",
	"LinkLayerEvent",
	"WebcastLinkLayerMessage",
	"WebcastLinkMicMethodMessage",
	"WebcastGuestInviteMessage",
)


def _on_link(event):
	try:
		user_name = None
		is_request = False

		if event.has_apply:
			is_request = True
			user_name = _name_of(event.applicant) or user_name

		if not user_name and event.has_invite:
			is_request = True
			user_name = _name_of(event.invitee) or user_name

		if not user_name and event.user is not None:
			user_name = _name_of(event.user) or user_name

		if not user_name and event.inviter_nickname:
			sanitized = _sanitize_name(event.inviter_nickname)
			if sanitized:
				user_name = sanitized
			is_request = True

		if not user_name:
			for person in event.display_people:
				name = _name_of(person)
				if name:
					user_name = name
					break

		if not user_name and event.has_list_change:
			if event.list_change_type is not None and event.list_change_type not in (1, 2):
				return
			for person in event.applied:
				name = _name_of(person)
				if name:
					user_name = name
					is_request = True
					break

		if "Apply" in event.message_type or "APPLY" in event.message_type:
			is_request = True
		if event.m_type in ("1", "2"):
			is_request = True
		elif event.m_type == "8":
			return
		if event.kind in REQUEST_KINDS:
			is_request = True

		if not is_request or not user_name:
			return

		now = time.time()
		if now - _requests_log.get(user_name, 0) < 10.0:
			return
		_requests_log[user_name] = now
		_prune_timestamps(_requests_log, 10.0)

		# Translators: Announced when someone requests to join the live stream. {name} is the user's name.
		speak_msg = _("Guest request: {name}").format(name=user_name)
		store.append(store.REQUESTS, f"{user_name}  {_now()}")
		if _settings.events.get("requests", True):
			_log_to_events(f"{speak_msg}  {_now()}")
		_announce("requests", speak_msg)
	except Exception:
		pass


_HANDLERS = {
	events.Comment: _on_comment,
	events.Follow: _on_follow,
	events.Share: _on_share,
	events.Gift: _on_gift,
	events.Like: _on_like,
	events.Join: _on_join,
	events.ViewerCount: _on_viewer_count,
	events.LinkMessage: _on_link,
}


def handle(event):
	"""Handle an event once: TikTok sends some messages twice, and the library
	turns one message into more than one event of a kind (findings F4, F13)."""
	if event.message_id:
		key = (type(event), event.message_id)
		if key in _seen_messages:
			return
		_seen_messages.add(key)
	_HANDLERS[type(event)](event)
