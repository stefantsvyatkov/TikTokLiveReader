"""TikTokLiveClient that replays a recording, for the add-on copy inside the sandbox only.

The sandbox agent copies this file into the staged add-on as
lib/TikTokLive/_sandbox_replay.py and makes TikTokLive export it when the
environment variable TIKTOK_REPLAY names a recording (tools/record_live.py
format). TIKTOK_REPLAY_PACE scales the recorded pauses. After the last frame
the stream stays open until the file TIKTOK_REPLAY_CONTROL holds "end"
(stream over) or "drop" (connection lost), or the add-on disconnects.
"""

import asyncio
import base64
import itertools
import json
import os
from pathlib import Path

from .client.client import TikTokLiveClient as _LiveClient
from .events import ConnectEvent
from .proto import ProtoMessageFetchResult, ProtoMessageFetchResultBaseProtoMessage


def _frames(path, pace):
	rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
	rows = [row for row in rows if "method" in row]
	frames, previous = [], None
	for _number, group in itertools.groupby(rows, key=lambda row: row["frame"]):
		group = list(group)
		if previous is not None and pace:
			gap = (group[0]["t"] - previous) * pace
			if gap > 0:
				frames.append(gap)
		previous = group[0]["t"]
		messages = [
			ProtoMessageFetchResultBaseProtoMessage(
				method=row["method"],
				payload=base64.b64decode(row["payload"]),
				msg_id=row["msg_id"],
				is_history=row["is_history"],
			)
			for row in group
		]
		whole = ProtoMessageFetchResult(messages=messages, is_first=group[0]["is_first"])
		frames.append(ProtoMessageFetchResult().parse(bytes(whole)))
	return frames


def _control():
	path = os.environ.get("TIKTOK_REPLAY_CONTROL")
	try:
		return Path(path).read_text(encoding="utf-8").strip() if path else ""
	except OSError:
		return ""


class TikTokLiveClient(_LiveClient):
	async def connect(self, **kwargs):
		# TikTokLive 7 parses frames only with a room id.
		self._room_id = 1
		self._replay_stopped = False

		async def room_info(*args, **kwargs):
			return {}

		self._web.fetch_room_info = room_info
		await self._replay()

	async def disconnect(self, *args, **kwargs):
		# As the real client: connect() returns once disconnected.
		self._replay_stopped = True
		await super().disconnect(*args, **kwargs)

	async def _replay(self):
		frames = _frames(os.environ["TIKTOK_REPLAY"], float(os.environ.get("TIKTOK_REPLAY_PACE", "1")))
		if not any(getattr(item, "is_first", False) for item in frames):
			self.emit(ConnectEvent.get_type(), ConnectEvent(unique_id=self._unique_id, room_id=1))
			await self.wait_for_complete()
		for item in frames:
			if self._replay_stopped:
				return
			if isinstance(item, float):
				await asyncio.sleep(item)
				continue
			async for event in self._parse_webcast_response(item):
				self.emit(event.get_type(), event)
			await self.wait_for_complete()
		while _control() not in ("end", "drop"):
			if self._replay_stopped:
				return
			await asyncio.sleep(0.1)
		if _control() == "drop":
			raise ConnectionError("replay: connection dropped")
