"""Decode a raw recording with a given copy of TikTokLive.

    python tools/decode_recording.py <recording.jsonl> <lib folder> <output.jsonl>

Run once per library, each in its own interpreter (both are the package
"TikTokLive"). Messages are regrouped into their recorded frames and decoded
the way the websocket loop does. Each output line is one event the library
emits, with the fields the add-on reads; ``tools/compare_libs.py`` compares
two outputs.
"""

import asyncio
import base64
import inspect
import json
import sys
import traceback
from itertools import groupby
from pathlib import Path

# Meaning -> attribute paths, first that exists wins (6.6.5 names first, then
# 7.x renames), optionally limited to some event classes.
FIELDS = [
	("message_id", ["base_message.message_id", "common.msg_id"], None),
	("display_key", ["base_message.display_text.key", "common.display_text.key"], None),
	("user.nickname", ["user.nickname", "user.nick_name"], None),
	("user.unique_id", ["user.unique_id", "user.username"], None),
	("user.id", ["user.id"], None),
	("comment", ["comment", "content"], None),
	("gift.name", ["gift.name"], None),
	("gift.diamond_count", ["gift.diamond_count"], None),
	("gift.type", ["gift.type"], None),
	("gift.streakable", ["gift.streakable"], None),
	("streaking", ["streaking"], None),
	("repeat_count", ["repeat_count"], None),
	("repeat_end", ["repeat_end"], None),
	("like.count", ["count"], {"LikeEvent"}),
	("like.total", ["total"], {"LikeEvent"}),
	("action", ["action"], None),
	("viewers", ["m_total", "total"], {"RoomUserSeqEvent"}),
	("total_user", ["total_user"], {"RoomUserSeqEvent"}),
	("member_count", ["count", "member_count"], {"JoinEvent"}),
	("link_type", ["m_type", "message_type"], {"LinkMicMethodEvent", "LinkLayerEvent"}),
]


def read(event, path):
	value = event
	for part in path.split("."):
		value = getattr(value, part)
	return value


def plain(value):
	if value is None or isinstance(value, (bool, int, float, str)):
		return value
	name = getattr(value, "name", None)
	if isinstance(name, str) and hasattr(value, "value"):
		return name
	return repr(value)


def fields_of(event):
	result = {}
	kind = type(event).__name__
	for name, paths, kinds in FIELDS:
		if kinds and kind not in kinds:
			continue
		for path in paths:
			try:
				value = read(event, path)
			except Exception:
				continue
			if value in (None, "", 0) and name not in ("repeat_end", "action"):
				break
			result[name] = plain(value)
			break
	return result


def parse(cls, data):
	try:
		return cls().parse(data)
	except TypeError:
		return cls.parse(data)


async def decode(rows, out):
	from TikTokLive import TikTokLiveClient
	from TikTokLive.proto import ProtoMessageFetchResult, ProtoMessageFetchResultBaseProtoMessage

	client = TikTokLiveClient(unique_id="decoder")
	takes_frame = "webcast_response" in inspect.signature(client._parse_webcast_response_message).parameters
	counts = {"frames": 0, "messages": 0, "events": 0, "errors": 0}
	for frame_number, group in groupby(rows, key=lambda row: row["frame"]):
		group = list(group)
		counts["frames"] += 1
		counts["messages"] += len(group)
		messages = [
			ProtoMessageFetchResultBaseProtoMessage(
				method=row["method"],
				payload=base64.b64decode(row["payload"]),
				msg_id=row["msg_id"],
				is_history=row["is_history"],
			)
			for row in group
		]
		by_id = {row["msg_id"]: row for row in group}
		try:
			frame = parse(ProtoMessageFetchResult, bytes(ProtoMessageFetchResult(messages=messages, is_first=group[0]["is_first"])))
			for message in frame.messages:
				if takes_frame:
					events = await client._parse_webcast_response_message(
						webcast_response=frame, webcast_response_message=message
					)
				else:
					events = await client._parse_webcast_response_message(message)
				for event in events or []:
					if event is None or type(event).__name__ == "WebsocketResponseEvent":
						continue
					counts["events"] += 1
					out.write(json.dumps({
						"frame": frame_number,
						"msg_id": message.msg_id,
						"method": message.method,
						"is_history": by_id.get(message.msg_id, {}).get("is_history"),
						"event": type(event).__name__,
						"fields": fields_of(event),
					}, ensure_ascii=False) + "\n")
		except Exception:
			counts["errors"] += 1
			out.write(json.dumps({"frame": frame_number, "error": traceback.format_exc(limit=3)}) + "\n")
	return counts


def main():
	recording, lib, output = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
	sys.path.insert(0, str(lib.resolve()))
	from TikTokLive.__version__ import PACKAGE_VERSION

	rows = [json.loads(line) for line in recording.read_text(encoding="utf-8").splitlines()]
	rows = [row for row in rows if not row.get("header")]
	output.parent.mkdir(parents=True, exist_ok=True)
	with output.open("w", encoding="utf-8") as out:
		out.write(json.dumps({"header": True, "library": PACKAGE_VERSION, "recording": recording.name}) + "\n")
		counts = asyncio.run(decode(rows, out))
	print(f"TikTokLive {PACKAGE_VERSION}: {counts}")


if __name__ == "__main__":
	main()
