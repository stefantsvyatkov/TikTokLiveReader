"""How long each user has been live, to pick lives near a puzzle time.

    python tools/live_ages.py <user> [...]

Prints minutes since the live started (room info), the viewer count and the
title, or why it could not tell.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_live import vendor_scope  # noqa: E402


async def age(TikTokLiveClient, user):
	client = TikTokLiveClient(unique_id=user)
	try:
		room_id = int(await client.web.fetch_room_id_from_api(user))
		client.web.params["room_id"] = str(room_id)
		info = await client.web.fetch_room_info()
		created = int(info.get("create_time") or 0)
		viewers = (info.get("stats") or {}).get("total_user") or info.get("user_count")
		minutes = (time.time() - created) / 60 if created else None
		return f"{user}: {minutes:.0f} min live, {viewers} viewers, {info.get('title', '')!r}"
	except Exception as error:
		return f"{user}: {type(error).__name__} {error}"
	finally:
		try:
			await client.close()
		except Exception:
			pass


async def main(users):
	from TikTokLive import TikTokLiveClient

	for user in users:
		print(await age(TikTokLiveClient, user), flush=True)
		await asyncio.sleep(1)


if __name__ == "__main__":
	with vendor_scope():
		asyncio.run(main([user.lstrip("@") for user in sys.argv[1:]]))
