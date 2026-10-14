"""Replay a live recording through the add-on and compare with what happened.

    python tools/check_addon.py <recording.jsonl> [pace]

What happened is counted from the raw messages (decoded by the vendored
library with tools/decode_recording.py); what the add-on did is its text
files and speech after replaying the recording through its real connection
thread. Without ``pace`` it runs on recorded time (tests/feed.py's virtual
clock: the timing the add-on's rules depend on, without waiting for it); with
one it waits the recorded pauses scaled by ``pace``. Output and report go to
artifacts/checks/.
"""

import collections
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EVERYTHING = {
	key: True for key in ("comments", "followers", "gifts", "likes", "requests", "shares", "visitors")
}
SETTINGS = {
	"events": EVERYTHING,
	"auto_speak": dict(EVERYTHING, enabled=True),
	"sound_events": EVERYTHING,
	"behavior": {"clean_usernames": False},
}


def decode(recording, out_dir):
	decoded = out_dir / "decoded-6.6.5.jsonl"
	subprocess.run(
		[
			sys.executable,
			"-X",
			"utf8",
			"-W",
			"ignore",
			str(REPO / "tools" / "decode_recording.py"),
			str(recording),
			str(REPO / "addon" / "globalPlugins" / "TiktokLiveReader" / "lib"),
			str(decoded),
		],
		check=True,
	)
	rows = [json.loads(line) for line in decoded.read_text(encoding="utf-8").split("\n") if line]
	return [row for row in rows if "method" in row and "error" not in row]


def expected_from(events):
	"""What happened, one entry per message id: TikTok sends the history (messages
	from before connecting) more than once."""
	expected = collections.defaultdict(list)
	likes = collections.Counter()
	unique = {}
	for row in events:
		unique.setdefault((row["msg_id"], row["event"]), row)
	history = collections.Counter(row["event"] for row in unique.values() if row.get("is_history"))
	expected["(history, already in the live before connecting)"] = [
		f"{count} {kind}" for kind, count in sorted(history.items())
	]
	for row in unique.values():
		kind, fields = row["event"], row["fields"]
		name = fields.get("user.nickname") or fields.get("user.unique_id") or ""
		if kind == "CommentEvent":
			expected["comments"].append(f"{name}: {fields.get('comment', '')}")
		elif kind == "GiftEvent":
			streakable = fields.get("gift.streakable")
			if not streakable or not fields.get("streaking"):
				expected["gifts"].append(
					f"{name}: {fields.get('repeat_count', 1) or 1} {fields.get('gift.name', '')}"
				)
		elif kind == "FollowEvent":
			expected["followers"].append(name)
		elif kind == "ShareEvent":
			expected["shares"].append(name)
		elif kind == "JoinEvent":
			expected["visitors"].append(name)
		elif kind == "LikeEvent":
			likes[name] += fields.get("like.count", 0)
		elif kind in ("LinkMicMethodEvent", "LinkLayerEvent"):
			expected["link messages"].append(f"{kind} type {fields.get('link_type')}")
			if kind == "LinkLayerEvent" and fields.get("list_change_type") == 2:
				expected["(applications: link layer list changes of type 2)"].append("applied")
	expected["followers"] = list(dict.fromkeys(expected["followers"]))
	expected["visitors"] = list(dict.fromkeys(expected["visitors"]))
	expected["likes (sum per person)"] = [f"{name}: {count}" for name, count in sorted(likes.items())]
	return expected


def logged_from(result, feed):
	logged = {
		"comments": feed.without_times(result.files["comments.txt"]),
		"gifts": feed.without_times(result.files["gifts.txt"]),
		"followers": feed.without_times(result.files["followers.txt"]),
		"shares": feed.without_times(result.files["shares.txt"]),
		"visitors": feed.without_times(result.files["visitors.txt"]),
		"requests": feed.without_times(result.files["requests.txt"]),
	}
	likes = collections.Counter()
	broken = []
	for line in feed.without_times(result.files["likes.txt"]):
		name, _, rest = line.rpartition(": ")
		try:
			likes[name] += int(rest.split()[0])
		except (ValueError, IndexError):
			broken.append(line)
	logged["likes (sum per person)"] = [f"{name}: {count}" for name, count in sorted(likes.items())]
	corrupted = [
		f"{name}: {line}" for name, lines in result.files.items() for line in lines or [] if "�" in line
	]
	logged["(lines with broken characters, F30)"] = corrupted + [
		f"unreadable like line: {line}" for line in broken
	]
	return logged


INFORMATION = ("(", "link messages")


def compare(expected, logged):
	lines = []
	for category in sorted(set(expected) | set(logged)):
		if category.startswith(INFORMATION):
			items = expected.get(category, []) + logged.get(category, [])
			lines.append(f"{category} (for information): {len(items)}")
			for item, count in list(collections.Counter(items).items())[:12]:
				lines.append(f"    {count}x  {item!r}")
			continue
		want = collections.Counter(expected.get(category, []))
		got = collections.Counter(logged.get(category, []))
		missing = want - got
		extra = got - want
		lines.append(
			f"{category}: happened {sum(want.values())}, add-on {sum(got.values())}, "
			f"missing {sum(missing.values())}, extra {sum(extra.values())}"
		)
		for item, count in list(missing.items())[:12]:
			lines.append(f"    missing {count}x  {item!r}")
		for item, count in list(extra.items())[:12]:
			lines.append(f"    extra   {count}x  {item!r}")
	return lines


def main():
	recording = Path(sys.argv[1])
	pace = float(sys.argv[2]) if len(sys.argv) > 2 else None
	out_dir = REPO / "artifacts" / "checks" / recording.stem
	if out_dir.exists():
		shutil.rmtree(out_dir)
	out_dir.mkdir(parents=True)

	events = decode(recording, out_dir)
	from tests import feed

	result = feed.run_session(
		*feed.recorded_frames(recording, pace or 1.0),
		past_grace_period=False,
		settings=SETTINGS,
		log_dir=out_dir / "addon",
		clock=None if pace else feed.VirtualClock(),
		timeout=900,
	)
	(out_dir / "speech.txt").write_text("\n".join(result.speech), encoding="utf-8")

	timing = f"pace {pace}" if pace else "recorded time"
	report = [f"recording {recording.name}, {timing}, {len(events)} events decoded (with repeats)"]
	report += compare(expected_from(events), logged_from(result, feed))
	report.append(f"stats: {result.stats}")
	report.append(f"callbacks: {result.callbacks}")
	(out_dir / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
	print("\n".join(report))


if __name__ == "__main__":
	main()
