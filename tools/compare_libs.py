"""Compare two decodings of the same recording (from tools/decode_recording.py).

    python tools/compare_libs.py <a.jsonl> <b.jsonl>

Events are matched by message id and event class. Reports the events each
library emits, events only one of them emits, and fields that differ.
"""

import collections
import json
import sys
from pathlib import Path


def load(path):
	header, events, errors = None, {}, 0
	for line in Path(path).read_text(encoding="utf-8").splitlines():
		row = json.loads(line)
		if row.get("header"):
			header = row
		elif "error" in row:
			errors += 1
		else:
			events[(row["msg_id"], row["event"])] = row
	return header, events, errors


def main():
	(a_head, a, a_errors), (b_head, b, b_errors) = load(sys.argv[1]), load(sys.argv[2])
	a_name, b_name = a_head["library"], b_head["library"]
	print(f"recording: {a_head['recording']}")
	print(f"frame errors: {a_name} {a_errors}, {b_name} {b_errors}\n")

	counts = collections.defaultdict(lambda: [0, 0])
	for _, event in a:
		counts[event][0] += 1
	for _, event in b:
		counts[event][1] += 1
	print(f"{'event':34} {a_name:>8} {b_name:>8}")
	for event, (in_a, in_b) in sorted(counts.items(), key=lambda item: -max(item[1])):
		mark = "" if in_a == in_b else "   <-"
		print(f"{event:34} {in_a:>8} {in_b:>8}{mark}")

	differences = collections.defaultdict(list)
	for key in a.keys() & b.keys():
		fa, fb = a[key]["fields"], b[key]["fields"]
		for field in fa.keys() | fb.keys():
			if fa.get(field) != fb.get(field):
				differences[(key[1], field)].append((fa.get(field), fb.get(field)))
	print("\nfield differences" + ("" if differences else ": none"))
	for (event, field), values in sorted(differences.items()):
		examples = "; ".join(f"{x!r} -> {y!r}" for x, y in values[:3])
		print(f"  {event}.{field}: {len(values)}x  e.g. {examples}")


if __name__ == "__main__":
	main()
