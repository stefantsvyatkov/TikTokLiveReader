"""The session's text files in the folder chosen in the settings: written by the
connection, read by navigation, cleared and archived.

Appended lines wait in memory until ``flush``, which the session calls every
half second and before anything reads, archives or clears the files. Read
entries are kept with the lines written since; a file is read again only from
where something else appended to it."""

import collections
import datetime
import os
import shutil
import threading
from pathlib import Path

from logHandler import log

from . import settings

COMMENTS = "comments.txt"
EVENTS = "events.txt"
FOLLOWERS = "followers.txt"
GIFTS = "gifts.txt"
LIKES = "likes.txt"
REQUESTS = "requests.txt"
SHARES = "shares.txt"
STATS = "stats.txt"
TOP_GIFTERS = "top gifters.txt"
TOP_LIKES = "top likes.txt"
VISITORS = "visitors.txt"
SESSION_FILES = (
	COMMENTS,
	EVENTS,
	FOLLOWERS,
	GIFTS,
	LIKES,
	REQUESTS,
	SHARES,
	STATS,
	TOP_GIFTERS,
	TOP_LIKES,
	VISITORS,
)
BACKUPS_DIR_NAME = "Backups"
_INVALID_NAME_CHARS = '<>:"/\\|?*'

folder = settings.DEFAULT_LOG_DIR
# The connection thread, the like timers and NVDA's main thread all write here;
# Windows appends by seeking to the end, so unguarded writes overwrite each
# other (F30), and clearing raced with writing (F22).
_lock = threading.Lock()
# Lines appended and not written yet, by file name.
_pending = {}
# Entries read by file name: (the file's size in bytes, its entries).
_entries = {}
# Who the lines written while NVDA runs are about, by line: (handle, name). The
# line alone cannot tell, a name may contain ": ".
_authors = collections.OrderedDict()
MAX_AUTHORS = 50000


def set_folder(directory):
	"""Use ``directory`` when it is an absolute path, the default folder otherwise."""
	global folder
	try:
		path = Path(str(directory).strip()).expanduser()
		if not path.is_absolute():
			raise ValueError("text_files_destination must be an absolute path")
	except Exception:
		path = settings.DEFAULT_LOG_DIR
	flush()
	with _lock:
		folder = path
		_entries.clear()


def path(name):
	return folder / name


def session_files():
	return [folder / name for name in SESSION_FILES]


def usable_folder(directory):
	"""``directory`` if it can be created, else the default folder."""
	for candidate in (directory, settings.DEFAULT_LOG_DIR):
		try:
			path = Path(str(candidate).strip()).expanduser()
			if not path.is_absolute():
				continue
			path.mkdir(parents=True, exist_ok=True)
			return path
		except Exception:
			continue
	return settings.DEFAULT_LOG_DIR


def ensure_files_exist():
	set_folder(usable_folder(folder))
	for file in session_files():
		if not file.exists():
			with open(file, "w", encoding="utf-8"):
				pass


def clear_all():
	with _lock:
		_pending.clear()
		_entries.clear()
		_authors.clear()
		for file in session_files():
			with open(file, "w", encoding="utf-8"):
				pass


def append(name, line, author=None):
	"""Add ``line`` to the file at the next ``flush``; ``author`` is (handle, name)
	of the person it is about, for ``author_of``."""
	with _lock:
		_pending.setdefault(name, []).append(line + "\n")
		if author is not None:
			_authors[line.strip()] = author
			while len(_authors) > MAX_AUTHORS:
				_authors.popitem(last=False)


def author_of(entry):
	"""(handle, name) of the person an entry read by navigation is about; None
	when it is about nobody or was written before NVDA started."""
	with _lock:
		return _authors.get(entry)


def _write_pending(names):
	"""Write the waiting lines of ``names``; with ``_lock`` held. Lines that cannot
	be written (the folder is gone) are dropped, as a failed append was."""
	for name in names:
		lines = _pending.pop(name, None)
		if not lines:
			continue
		text = "".join(lines)
		# As text mode writes them, so the files stay what they were.
		data = text.replace("\n", os.linesep).encode("utf-8")
		try:
			with open(folder / name, "ab") as handle:
				start = handle.tell()
				handle.write(data)
		except OSError:
			log.debugWarning(f"TikTok Live Reader: writing {name}", exc_info=True)
			continue
		# Opening a file just written is slow (the antivirus looks at it again);
		# the lines are known.
		known = _entries.get(name)
		if known is not None and known[0] == start:
			_entries[name] = (start + len(data), known[1] + _split(text))


def flush(name=None):
	"""Write the lines appended since the last flush, of ``name`` or of every file."""
	with _lock:
		_write_pending(list(_pending) if name is None else [name])


def write(name, text):
	with _lock:
		_pending.pop(name, None)
		_entries.pop(name, None)
		with open(folder / name, "w", encoding="utf-8") as handle:
			handle.write(text)


def read_text(name):
	"""The file's text; a damaged character reads as U+FFFD instead of failing."""
	with _lock:
		_write_pending([name])
		return (folder / name).read_text(encoding="utf-8", errors="replace")


def _split(text):
	return [line.strip() for line in text.split("\n") if line.strip()]


def read_entries(name):
	"""The file's non-empty lines, stripped; none when it cannot be opened. Read
	on each navigation key, so a file that only grew is read from where the last
	read stopped. The list returned is not to be changed."""
	with _lock:
		_write_pending([name])
		try:
			size = os.stat(folder / name).st_size
			known = _entries.get(name)
			if known is not None and known[0] == size:
				return known[1]
			# Grown: only the end is new. Otherwise (cleared, replaced) read it all.
			offset, entries = known if known is not None and size > known[0] else (0, [])
			with open(folder / name, "rb") as handle:
				handle.seek(offset)
				added = handle.read()
		except OSError:
			_entries.pop(name, None)
			return []
		entries = entries + _split(added.decode("utf-8", errors="replace"))
		_entries[name] = (offset + len(added), entries)
		return entries


def safe_name(name):
	cleaned = "".join(ch for ch in str(name) if ch not in _INVALID_NAME_CHARS and ord(ch) >= 32)
	return cleaned.strip().rstrip(".")


def archive_session(username):
	"""Copy the finished session's text files into Backups/<date time host>/."""
	try:
		flush()
		sources = [file for file in session_files() if file.is_file()]
		if not sources or not any(file.stat().st_size > 0 for file in sources):
			return None

		host = safe_name(username) or "unknown"
		stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
		base = folder / BACKUPS_DIR_NAME / f"{stamp} {host}"

		target = base
		suffix = 2
		while target.exists():
			target = base.with_name(f"{base.name} ({suffix})")
			suffix += 1

		target.mkdir(parents=True, exist_ok=True)
		for file in sources:
			shutil.copy2(str(file), str(target / file.name))
		return target
	except Exception:
		log.debugWarning("TikTok Live Reader: archiving the session", exc_info=True)
		return None
