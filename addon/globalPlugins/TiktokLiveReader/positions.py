"""Where navigation stopped in each text file, kept across sessions while the files
are not cleared on start (tiktokLiveReader-positions.json)."""

import json

from logHandler import log

from . import settings

EMPTY = {"version": 1, "files": {}}


def read():
	"""The line per file key; nothing when the file is missing or unreadable."""
	try:
		return json.loads(settings.POSITIONS_PATH.read_text(encoding="utf-8")).get("files", {})
	except Exception:
		return {}


def write(lines):
	try:
		data = {"version": 1, "files": {key: {"line": int(line)} for key, line in lines.items()}}
		settings.POSITIONS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
	except Exception:
		log.debugWarning("TikTok Live Reader: saving the positions", exc_info=True)


def create_if_missing():
	if not settings.POSITIONS_PATH.exists():
		with open(settings.POSITIONS_PATH, "w", encoding="utf-8") as handle:
			json.dump(EMPTY, handle)


def remove():
	if settings.POSITIONS_PATH.exists():
		settings.POSITIONS_PATH.unlink()


def reset():
	try:
		settings.POSITIONS_PATH.write_text(json.dumps(EMPTY, ensure_ascii=False), encoding="utf-8")
	except Exception:
		log.debugWarning("TikTok Live Reader: resetting the positions", exc_info=True)
