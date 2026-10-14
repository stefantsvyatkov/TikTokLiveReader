"""Record a public TikTok LIVE as raw websocket messages.

    python tools/record_live.py <user> <minutes> [output.jsonl] [lib folder]

Uses the add-on's vendored TikTokLive through its vendor.py, so the
recording goes through exactly the code the add-on runs. Each line is one
message: its method, raw payload (base64), message id and history flag, with
the frame it came in. Recordings hold real people's names: they stay in
artifacts/ (gitignored); fixtures committed to the repository are anonymized.

For long watches it connects again after a drop until the time is up or the
user is no longer live, notes when the live started, and prints the first
message of each method and every message of the WATCHED ones as they come.
"""

import asyncio
import base64
import contextlib
import datetime
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADDON = REPO / "addon" / "globalPlugins" / "TiktokLiveReader"


def vendor_scope():
	spec = importlib.util.spec_from_file_location("vendor", ADDON / "vendor.py")
	vendor = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(vendor)
	return vendor.scope(vendor.load(ADDON / "lib", "TikTokLive"))


# Printed as they arrive, with every method's first message: what a host's
# verification (the puzzle) might come as.
WATCHED = {
	"WebcastAccessControlMessage",
	"WebcastRoomVerifyMessage",
	"WebcastControlMessage",
	"WebcastStreamStatusMessage",
}
RECONNECT_PAUSE = 15


def note(user, text):
	print(f"{datetime.datetime.now():%H:%M:%S} {user}: {text}", flush=True)


async def record(TikTokLiveClient, user, seconds, output):
	"""Record until the time is up, connecting again after a drop; the stream
	ending is reported and stops the recording."""
	frames = 0
	messages = 0
	seen = set()

	original = TikTokLiveClient._parse_webcast_response

	async def recording(client, response):
		nonlocal frames, messages
		frames += 1
		for message in response.messages:
			messages += 1
			if message.method in WATCHED or message.method not in seen:
				note(user, f"{message.method}{' (history)' if message.is_history else ''}")
			seen.add(message.method)
			output.write(
				json.dumps(
					{
						"t": round(time.time(), 3),
						"frame": frames,
						"is_first": bool(response.is_first),
						"method": message.method,
						"msg_id": message.msg_id,
						"is_history": bool(message.is_history),
						"payload": base64.b64encode(message.payload).decode("ascii"),
					}
				)
				+ "\n"
			)
		output.flush()
		async for event in original(client, response):
			yield event

	TikTokLiveClient._parse_webcast_response = recording
	deadline = time.monotonic() + seconds
	ended = "time limit"
	while time.monotonic() < deadline:
		client = TikTokLiveClient(unique_id=user)
		try:
			task = await client.start(fetch_room_info=True)
			created = (client.room_info or {}).get("create_time")
			output.write(json.dumps({"connected": round(time.time(), 3), "room_created": created}) + "\n")
			if created:
				note(user, f"live for {(time.time() - int(created)) / 60:.0f} min")
			await asyncio.wait_for(asyncio.shield(task), timeout=max(1, deadline - time.monotonic()))
			note(user, f"connection ended, checking again in {RECONNECT_PAUSE} s")
		except asyncio.TimeoutError:
			break
		except Exception as error:
			if type(error).__name__ in ("UserOfflineError", "UserNotFoundError"):
				note(user, "not live")
				ended = "not live"
				break
			if type(error).__name__ == "AgeRestrictedError":
				note(user, "age restricted, only for logged-in viewers")
				ended = "age restricted"
				break
			# The signing server allows a few new connections a minute per key.
			pause = 65 if "RateLimit" in type(error).__name__ else RECONNECT_PAUSE
			note(user, f"connection lost ({type(error).__name__}: {error}), again in {pause} s")
			await asyncio.sleep(pause - RECONNECT_PAUSE)
		finally:
			with contextlib.suppress(Exception):
				await client.disconnect()
		await asyncio.sleep(RECONNECT_PAUSE)
	return frames, messages, ended


def main():
	user = sys.argv[1].lstrip("@")
	minutes = float(sys.argv[2])
	stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
	path = (
		Path(sys.argv[3])
		if len(sys.argv) > 3
		else REPO / "artifacts" / "recordings" / f"{stamp} {user}.jsonl"
	)
	path.parent.mkdir(parents=True, exist_ok=True)

	if len(sys.argv) > 4:
		# Another copy of TikTokLive (e.g. artifacts/lib-7.0.1), imported directly.
		sys.path.insert(0, str(Path(sys.argv[4]).resolve()))
		scope = contextlib.nullcontext()
	else:
		scope = vendor_scope()
	with scope:
		from TikTokLive import TikTokLiveClient
		from TikTokLive.__version__ import PACKAGE_VERSION

		with path.open("w", encoding="utf-8") as output:
			output.write(
				json.dumps({"header": True, "user": user, "started": stamp, "library": PACKAGE_VERSION})
				+ "\n"
			)
			frames, messages, ended = asyncio.run(record(TikTokLiveClient, user, minutes * 60, output))
	print(f"{path.name}: TikTokLive {PACKAGE_VERSION}, {frames} frames, {messages} messages, {ended}")


if __name__ == "__main__":
	main()
