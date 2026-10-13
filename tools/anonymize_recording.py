"""Anonymize a live recording so it can be committed as a test fixture.

    python tools/anonymize_recording.py <recording.jsonl> <output.jsonl> [method ...]

Every payload is decoded with the vendored TikTokLive, every person-related
text (names, handles, comments, bios, links) and user id is replaced with a
stable stand-in (the same person keeps the same stand-in across messages, so
deduplication and guest-request queues behave as recorded), and the message is
encoded again. Messages of methods not listed are left out (all are kept when
none is listed). Message ids, timing and structure are kept.
"""

import base64
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "addon" / "globalPlugins" / "TiktokLiveReader" / "lib"))

from TikTokLive.proto import ProtoMessageFetchResult  # noqa: E402

ProtoMessageFetchResult().parse(bytes(ProtoMessageFetchResult()))  # see docs/dev/library.md

import betterproto  # noqa: E402
from TikTokLive.events.proto_events import EVENT_MAPPINGS  # noqa: E402

NAME_FIELDS = {"nick_name", "nickname", "username", "display_id", "unique_id", "inviter_nickname"}
TEXT_FIELDS = {
	"content",
	"signature",
	"bio_description",
	"describe",
	"pop_str",
	"share_target",
	"default_pattern",
}
DROP_FIELDS = {
	"sec_uid",
	"id_str",
	"url_list",
	"uri",
	"avatar_thumb",
	"avatar_medium",
	"avatar_large",
	"web_url",
}
ID_FIELDS = {"id", "uid", "user_id", "invite_uid", "target_user_id", "anchor_id", "to_user_id"}


class Anonymizer:
	def __init__(self):
		self.names, self.ids, self.texts = {}, {}, {}

	def name(self, value):
		return self.names.setdefault(value, f"Person {len(self.names) + 1}")

	def user_id(self, value):
		return self.ids.setdefault(value, 900_000_000 + len(self.ids) + 1)

	def text(self, value):
		digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]
		# keep what matters to the add-on's handling: line breaks and doubled spaces
		marks = ("\n" if "\n" in value else "") + ("  " if "  " in value else "")
		return self.texts.setdefault(value, f"text {digest}{marks}")

	def walk(self, message):
		if not isinstance(message, betterproto.Message):
			return message
		for field in dataclasses.fields(message):
			name = field.name
			try:
				value = getattr(message, name)
			except AttributeError:
				continue
			if isinstance(value, str) and value:
				if name in NAME_FIELDS:
					setattr(message, name, self.name(value))
				elif name in TEXT_FIELDS:
					setattr(message, name, self.text(value))
				elif name in DROP_FIELDS:
					setattr(message, name, "")
			elif isinstance(value, int) and not isinstance(value, bool) and value and name in ID_FIELDS:
				setattr(message, name, self.user_id(value))
			elif isinstance(value, list):
				if name in DROP_FIELDS:
					setattr(message, name, [])
				else:
					for item in value:
						self.walk(item)
			elif isinstance(value, dict):
				for item in value.values():
					self.walk(item)
			elif isinstance(value, betterproto.Message):
				if name in DROP_FIELDS:
					setattr(message, name, type(value)())
				else:
					self.walk(value)
		return message


def main():
	source, target = Path(sys.argv[1]), Path(sys.argv[2])
	keep = set(sys.argv[3:])
	anonymizer = Anonymizer()
	kept = skipped = 0
	with target.open("w", encoding="utf-8") as out:
		for line in source.read_text(encoding="utf-8").splitlines():
			row = json.loads(line)
			if row.get("header"):
				row["user"] = "host"
				out.write(json.dumps(row) + "\n")
				continue
			if keep and row["method"] not in keep:
				skipped += 1
				continue
			event_class = EVENT_MAPPINGS.get(row["method"])
			if event_class is None:
				skipped += 1
				continue
			message = event_class().parse(base64.b64decode(row["payload"]))
			row["payload"] = base64.b64encode(bytes(anonymizer.walk(message))).decode("ascii")
			out.write(json.dumps(row) + "\n")
			kept += 1
	print(f"{target.name}: {kept} messages kept, {skipped} left out, {len(anonymizer.names)} people")


if __name__ == "__main__":
	main()
