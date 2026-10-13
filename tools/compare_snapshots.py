"""What changed between two snapshots of tools/snapshot_addon.py.

    python tools/compare_snapshots.py <before.json> <after.json>

For each run and each file (or speech, sounds, counters): how many entries only
one side has, with a few examples.
"""

import collections
import json
import sys
from pathlib import Path


def parts(run):
	yield from (("file " + name, lines) for name, lines in run["files"].items())
	for key in ("speech", "sounds", "callbacks", "top gifters", "top likes"):
		yield key, [json.dumps(item, ensure_ascii=False) for item in run[key]]
	yield "stats", [f"{key}={value}" for key, value in run["stats"].items()]


def main():
	before = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
	after = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
	for run in sorted(set(before) | set(after)):
		if run not in before or run not in after:
			print(f"{run}: only in {'after' if run in after else 'before'}")
			continue
		old, new = dict(parts(before[run])), dict(parts(after[run]))
		changes = []
		for part in sorted(set(old) | set(new)):
			was, now = collections.Counter(old.get(part, [])), collections.Counter(new.get(part, []))
			gone, added = was - now, now - was
			if gone or added:
				changes.append(
					f"  {part}: {sum(was.values())} -> {sum(now.values())}"
					f" (only before {sum(gone.values())}, only after {sum(added.values())})"
				)
				for item, count in list(gone.items())[:3]:
					changes.append(f"      - {count}x {item}")
				for item, count in list(added.items())[:3]:
					changes.append(f"      + {count}x {item}")
		print(run + (":" if changes else ": no change"))
		print("\n".join(changes)) if changes else None


if __name__ == "__main__":
	main()
