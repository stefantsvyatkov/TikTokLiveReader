"""The add-on's settings: one Settings object, read from and written to
tiktokLiveReader.ini in NVDA's configuration folder."""

import configparser
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from logHandler import log

ADDON_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = Path.home() / "Documents" / "TikTok live"

DEFAULT_EVENT_PREFS = {
	"comments": True,
	"followers": True,
	"gifts": True,
	"likes": True,
	"requests": True,
	"shares": True,
	"visitors": False,
}
DEFAULT_BEHAVIOR = {
	"clear_on_start": True,
	"clean_usernames": True,
	"retry_count": 3,
	"backup_sessions": False,
}
DEFAULT_SOUNDS = {
	"play_sounds": False,
	"volume": 70,
}
EVENT_SECTIONS = ("events", "auto_speak", "sound_events")


def user_config_dir():
	"""NVDA's own configuration folder, which survives add-on updates; the add-on
	folder when NVDA is not there."""
	try:
		import NVDAState

		path = Path(NVDAState.WritePaths.configDir)
		if path.is_dir():
			return path
	except Exception:
		pass
	try:
		import globalVars

		path = Path(globalVars.appArgs.configPath)
		if path.is_dir():
			return path
	except Exception:
		pass
	return ADDON_DIR


CONFIG_DIR = user_config_dir()
CONFIG_PATH = CONFIG_DIR / "tiktokLiveReader.ini"
POSITIONS_PATH = CONFIG_DIR / "tiktokLiveReader-positions.json"
# Where these files lived up to version 1.7, inside the add-on folder.
LEGACY_CONFIG_PATH = ADDON_DIR / "config.ini"
LEGACY_POSITIONS_PATH = ADDON_DIR / "positions.json"


def migrate_user_files():
	"""Copy settings left in the add-on folder to their new home, once."""
	for new_path, old_path in ((CONFIG_PATH, LEGACY_CONFIG_PATH), (POSITIONS_PATH, LEGACY_POSITIONS_PATH)):
		try:
			if new_path == old_path or new_path.exists() or not old_path.is_file():
				continue
			new_path.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(str(old_path), str(new_path))
		except Exception:
			log.debugWarning(f"TikTok Live Reader: moving {old_path}", exc_info=True)


def resolve_destination(raw):
	"""An absolute folder for the text files; the default one for anything else."""
	try:
		path = Path(str(raw).strip()).expanduser()
		if not path.is_absolute():
			raise ValueError("text_files_destination must be an absolute path")
		return str(path)
	except Exception:
		return str(DEFAULT_LOG_DIR)


@dataclass
class Settings:
	username: str = ""
	text_files_destination: str = str(DEFAULT_LOG_DIR)
	events: dict = field(default_factory=lambda: dict(DEFAULT_EVENT_PREFS))
	auto_speak: dict = field(default_factory=lambda: dict(DEFAULT_EVENT_PREFS))
	sounds: dict = field(default_factory=lambda: dict(DEFAULT_EVENT_PREFS))
	auto_speak_enabled: bool = False
	clear_on_start: bool = DEFAULT_BEHAVIOR["clear_on_start"]
	clean_usernames: bool = DEFAULT_BEHAVIOR["clean_usernames"]
	retry_count: int = DEFAULT_BEHAVIOR["retry_count"]
	backup_sessions: bool = DEFAULT_BEHAVIOR["backup_sessions"]
	play_sounds: bool = DEFAULT_SOUNDS["play_sounds"]
	volume: int = DEFAULT_SOUNDS["volume"]


def _as_ini(value):
	if isinstance(value, bool):
		return "true" if value else "false"
	return str(value)


def read_config_file():
	config = configparser.ConfigParser()
	if CONFIG_PATH.exists():
		# utf-8-sig: a byte order mark (old Notepad, PowerShell 5) is not part of
		# the first section header (F29).
		config.read(CONFIG_PATH, encoding="utf-8-sig")
	if "events" not in config and "auto_read" in config:
		config["events"] = config["auto_read"]
	return config


def apply_config_defaults(config):
	"""Add every missing section and key with its default value."""
	if "main" not in config:
		config["main"] = {"username": ""}
	if "text_files_destination" not in config["main"]:
		config["main"]["text_files_destination"] = str(DEFAULT_LOG_DIR)
	for section in EVENT_SECTIONS:
		if section not in config:
			config[section] = {}
		for key, value in DEFAULT_EVENT_PREFS.items():
			if key not in config[section]:
				config[section][key] = _as_ini(value)
	for section, defaults in (("behavior", DEFAULT_BEHAVIOR), ("sounds", DEFAULT_SOUNDS)):
		if section not in config:
			config[section] = {}
		for key, value in defaults.items():
			if key not in config[section]:
				config[section][key] = _as_ini(value)
	return config


def _section(config, section):
	return {
		key: config.getboolean(section, key, fallback=value) for key, value in DEFAULT_EVENT_PREFS.items()
	}


def from_config(config):
	return Settings(
		username=config.get("main", "username", fallback=""),
		text_files_destination=config.get("main", "text_files_destination", fallback=str(DEFAULT_LOG_DIR)),
		events=_section(config, "events"),
		auto_speak=_section(config, "auto_speak"),
		sounds=_section(config, "sound_events"),
		auto_speak_enabled=config.getboolean("auto_speak", "enabled", fallback=False),
		clear_on_start=config.getboolean(
			"behavior", "clear_on_start", fallback=DEFAULT_BEHAVIOR["clear_on_start"]
		),
		clean_usernames=config.getboolean(
			"behavior", "clean_usernames", fallback=DEFAULT_BEHAVIOR["clean_usernames"]
		),
		retry_count=config.getint("behavior", "retry_count", fallback=DEFAULT_BEHAVIOR["retry_count"]),
		backup_sessions=config.getboolean(
			"behavior", "backup_sessions", fallback=DEFAULT_BEHAVIOR["backup_sessions"]
		),
		play_sounds=config.getboolean("sounds", "play_sounds", fallback=DEFAULT_SOUNDS["play_sounds"]),
		volume=config.getint("sounds", "volume", fallback=DEFAULT_SOUNDS["volume"]),
	)


def load():
	"""The settings in the file, defaults for missing keys; raises when the file
	cannot be read."""
	return from_config(read_config_file())


def load_and_complete():
	"""The settings in the file, which is written back with every missing key filled
	in; all defaults when that fails."""
	try:
		config = apply_config_defaults(read_config_file())
		with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
			config.write(handle)
		loaded = from_config(config)
	except Exception:
		log.warning("TikTok Live Reader: the settings file cannot be read; using the defaults", exc_info=True)
		return Settings()
	loaded.text_files_destination = resolve_destination(loaded.text_files_destination)
	return loaded


def save(settings):
	"""Write the settings; the text files folder is made absolute first."""
	settings.text_files_destination = resolve_destination(settings.text_files_destination)
	config = configparser.ConfigParser()
	config["main"] = {
		"username": settings.username,
		"text_files_destination": settings.text_files_destination,
	}
	config["events"] = {key: _as_ini(value) for key, value in settings.events.items()}
	config["auto_speak"] = {key: _as_ini(value) for key, value in settings.auto_speak.items()}
	config["auto_speak"]["enabled"] = _as_ini(settings.auto_speak_enabled)
	config["sound_events"] = {key: _as_ini(value) for key, value in settings.sounds.items()}
	config["behavior"] = {
		"clear_on_start": _as_ini(settings.clear_on_start),
		"clean_usernames": _as_ini(settings.clean_usernames),
		"retry_count": str(settings.retry_count),
		"backup_sessions": _as_ini(settings.backup_sessions),
	}
	config["sounds"] = {
		"play_sounds": _as_ini(settings.play_sounds),
		"volume": str(settings.volume),
	}
	with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
		config.write(handle)
