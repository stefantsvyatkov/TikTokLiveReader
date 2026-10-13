"""Replay live recordings through the add-on on recorded time and save all it
produced, to compare two versions of the code.

    python tools/snapshot_addon.py <out.json> <recording.jsonl> [...]

Each recording runs with user names cleaned and not, with every event, auto
speak and sound on. Pauses only advance a virtual clock (tests/feed.py), so the
one- and ten-second rules see the recorded timing and every run gives the same
result: two snapshots differ only where the add-on's behaviour does. Likes still
being summed are reported at the end. The stats and top files are written on a
timer and left out; the counters behind them are kept.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EVERYTHING = {
	key: True for key in ("comments", "followers", "gifts", "likes", "requests", "shares", "visitors")
}
CONFIGURATIONS = {
	"clean names": {"behavior": {"clean_usernames": True}},
	"raw names": {"behavior": {"clean_usernames": False}},
}
TIMED_FILES = ("stats.txt", "top gifters.txt", "top likes.txt")


def _addon_value(name):
	"""A module global of the add-on, wherever the current code keeps it."""
	for module_name, module in sorted(sys.modules.items()):
		if module_name.startswith("tiktokAddon.") and hasattr(module, name):
			return getattr(module, name)
	raise LookupError(name)


def snapshot(feed, recording, extra):
	settings = {
		"events": EVERYTHING,
		"auto_speak": dict(EVERYTHING, enabled=True),
		"sound_events": EVERYTHING,
		"sounds": {"play_sounds": True},
		**extra,
	}
	result = feed.run_session(
		*feed.recorded_frames(recording, pace=1.0),
		past_grace_period=False,
		settings=settings,
		clock=feed.VirtualClock(),
		timeout=900,
	)
	return {
		"files": {
			name: feed.without_times(lines or [])
			for name, lines in sorted(result.files.items())
			if name not in TIMED_FILES
		},
		"speech": result.speech,
		"sounds": [list(sound) for sound in result.sounds],
		"callbacks": result.callbacks,
		"stats": result.stats,
		"top gifters": sorted(_addon_value("top_gifters").items()),
		"top likes": sorted(_addon_value("top_likers").items()),
	}


def main():
	out = Path(sys.argv[1])
	from tests import feed

	snapshots = {}
	for recording in map(Path, sys.argv[2:]):
		for configuration, extra in CONFIGURATIONS.items():
			key = f"{recording.stem} / {configuration}"
			snapshots[key] = snapshot(feed, recording, extra)
			counts = {name: len(lines) for name, lines in snapshots[key]["files"].items()}
			print(key, counts, "speech", len(snapshots[key]["speech"]), flush=True)
	out.parent.mkdir(parents=True, exist_ok=True)
	out.write_text(json.dumps(snapshots, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
	main()
