"""Decode the messages of chosen methods in recordings.

    python tools/peek_recording.py <method,method> <recording> [...]

Prints each message's time since the recording started and its fields, decoded
by the vendored TikTokLive's protobuf classes.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_live import vendor_scope  # noqa: E402


def main():
	methods = set(sys.argv[1].split(","))
	with vendor_scope():
		from TikTokLive.proto import tiktok_proto as proto

		for path in sys.argv[2:]:
			start = None
			for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
				try:
					row = json.loads(line)
				except ValueError:
					continue
				if "method" not in row:
					continue
				start = start or row["t"]
				if row["method"] not in methods:
					continue
				kind = getattr(proto, row["method"], None)
				fields = kind().parse(base64.b64decode(row["payload"])).to_dict() if kind else "?"
				print(
					Path(path).stem,
					f"+{row['t'] - start:.0f}s",
					row["method"],
					json.dumps(fields, ensure_ascii=False),
				)


if __name__ == "__main__":
	main()
