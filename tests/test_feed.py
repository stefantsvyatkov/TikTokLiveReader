"""Guards for the test feed itself: it must decode messages exactly as a live connection does."""

import unittest

from . import feed, support


class DecodedLikeALiveConnection(unittest.TestCase):
	def decode(self, message):
		with feed.adapter.library_scope():
			whole = feed.frame(message)
			client = feed.TikTokLive.TikTokLiveClient(unique_id="probe")
			events = []

			async def collect():
				async for event in client._parse_webcast_response(whole):
					events.append(event)

			loop = client._asyncio_loop
			try:
				loop.run_until_complete(collect())
			finally:
				loop.close()
		return [event for event in events if type(event).__name__ != "WebsocketResponseEvent"]

	def test_gift_has_the_library_extended_types(self):
		(event,) = self.decode(feed.gift(feed.user("Alice"), "Rose", 1, 5))
		self.assertEqual(type(event.gift).__name__, "ExtendedGift")
		self.assertTrue(event.gift.streakable)
		self.assertEqual(event.user.nickname, "Alice")

	def test_follow_produces_the_social_and_the_follow_event(self):
		names = [type(event).__name__ for event in self.decode(feed.follow(feed.user("Alice")))]
		self.assertEqual(names, ["FollowEvent", "SocialEvent"])

	def test_live_end_produces_the_live_end_event(self):
		names = [type(event).__name__ for event in self.decode(feed.live_ended())]
		self.assertIn("LiveEndEvent", names)


class StaysOutOfTheRealConfiguration(unittest.TestCase):
	def test_runtime_files_are_in_the_temporary_folder(self):
		settings = feed.addon_settings
		for path in (
			settings.CONFIG_PATH,
			settings.POSITIONS_PATH,
			settings.LEGACY_CONFIG_PATH,
			settings.LEGACY_POSITIONS_PATH,
		):
			self.assertTrue(path.is_relative_to(support.ROOT), path)


if __name__ == "__main__":
	unittest.main()
