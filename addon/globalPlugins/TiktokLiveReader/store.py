"""The session's text files in the folder chosen in the settings: written by the
connection, read by navigation, cleared and archived."""

import datetime
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


def set_folder(directory):
	"""Use ``directory`` when it is an absolute path, the default folder otherwise."""
	global folder
	try:
		path = Path(str(directory).strip()).expanduser()
		if not path.is_absolute():
			raise ValueError("text_files_destination must be an absolute path")
	except Exception:
		path = settings.DEFAULT_LOG_DIR
	folder = path


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
		for file in session_files():
			with open(file, "w", encoding="utf-8"):
				pass


def append(name, line):
	with _lock, open(folder / name, "a", encoding="utf-8") as handle:
		handle.write(line + "\n")


def write(name, text):
	with _lock, open(folder / name, "w", encoding="utf-8") as handle:
		handle.write(text)


def read_text(name):
	"""The file's text; a damaged character reads as U+FFFD instead of failing."""
	with _lock:
		return (folder / name).read_text(encoding="utf-8", errors="replace")


def read_entries(name):
	"""The file's non-empty lines, stripped; none when it cannot be opened."""
	try:
		return [line.strip() for line in read_text(name).split("\n") if line.strip()]
	except OSError:
		return []


def safe_name(name):
	cleaned = "".join(ch for ch in str(name) if ch not in _INVALID_NAME_CHARS and ord(ch) >= 32)
	return cleaned.strip().rstrip(".")


def archive_session(username):
	"""Copy the finished session's text files into Backups/<date time host>/."""
	try:
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
