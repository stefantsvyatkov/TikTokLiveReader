"""Record a public TikTok LIVE as raw websocket messages.

    python tools/record_live.py <user> <minutes> [output.jsonl]

Uses the add-on's vendored TikTokLive through its vendor loader, so the
recording goes through exactly the code the add-on runs. Each line is one
message: its method, raw payload (base64), message id and history flag, with
the frame it came in. Recordings hold real people's names: they stay in
artifacts/ (gitignored); fixtures committed to the repository are anonymized.
"""

import asyncio
import base64
import datetime
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADDON = REPO / "addon" / "globalPlugins" / "TiktokLiveReader"


def load_vendor_runtime():
	spec = importlib.util.spec_from_file_location("vendor_loader", ADDON / "vendor_loader.py")
	loader = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(loader)
	return loader, loader.load_runtime(str(ADDON / "lib"))


async def record(TikTokLiveClient, user, seconds, output):
	frames = 0
	messages = 0

	original = TikTokLiveClient._parse_webcast_response

	async def recording(client, response):
		nonlocal frames, messages
		frames += 1
		for message in response.messages:
			messages += 1
			output.write(json.dumps({
				"t": round(time.time(), 3),
				"frame": frames,
				"is_first": bool(response.is_first),
				"method": message.method,
				"msg_id": message.msg_id,
				"is_history": bool(message.is_history),
				"payload": base64.b64encode(message.payload).decode("ascii"),
			}) + "\n")
		output.flush()
		async for event in original(client, response):
			yield event

	TikTokLiveClient._parse_webcast_response = recording
	client = TikTokLiveClient(unique_id=user)
	task = await client.start()
	try:
		await asyncio.wait_for(asyncio.shield(task), timeout=seconds)
		ended = "stream ended"
	except asyncio.TimeoutError:
		ended = "time limit"
	finally:
		await client.disconnect()
	return frames, messages, ended


def main():
	user = sys.argv[1].lstrip("@")
	minutes = float(sys.argv[2])
	stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
	path = Path(sys.argv[3]) if len(sys.argv) > 3 else REPO / "artifacts" / "recordings" / f"{stamp} {user}.jsonl"
	path.parent.mkdir(parents=True, exist_ok=True)

	loader, runtime = load_vendor_runtime()
	with loader.runtime_scope(runtime):
		from TikTokLive import TikTokLiveClient
		from TikTokLive.__version__ import PACKAGE_VERSION

		with path.open("w", encoding="utf-8") as output:
			output.write(json.dumps({"header": True, "user": user, "started": stamp, "library": PACKAGE_VERSION}) + "\n")
			frames, messages, ended = asyncio.run(record(TikTokLiveClient, user, minutes * 60, output))
	print(f"{path.name}: {frames} frames, {messages} messages, {ended}")


if __name__ == "__main__":
	main()
