"""Version 1.8 behaviour believed to be wrong, pinned as it is today.

Each test names its finding in docs/dev/findings.md. A fix makes the test
fail on purpose; it then moves to test_pipeline.py with the new expectation.
Findings marked "needs live data" are only fixed once recordings confirm them.
"""

import time
import unittest

from . import feed as f
from . import support
from .test_plugin import make_plugin, said

alice, bob = f.user("Alice"), f.user("Bob")


def logged(result, name):
	return f.without_times(result.files[name])


class KnownIssues(unittest.TestCase):
	def test_F4_message_id_is_never_read(self):
		event = type("Event", (), {"base_message": type("Common", (), {"message_id": 7})()})()
		self.assertFalse(f.pipeline._is_processed(f.adapter.legacy_id(event)))
		self.assertFalse(f.pipeline._is_processed(f.adapter.legacy_id(event)))

	def test_F5_same_comment_from_same_person_is_dropped(self):
		r = f.run_session(f.comment(alice, "hi"), f.comment(alice, "hi"))
		self.assertEqual(logged(r, "comments.txt"), ["Alice: hi"])

	def test_F6_repeated_event_line_is_dropped_from_events_file(self):
		r = f.run_session(f.share(alice), 1.2, f.share(alice))
		self.assertEqual(logged(r, "shares.txt"), ["Alice", "Alice"])
		self.assertEqual(logged(r, "events.txt"), ["Alice shared the live"])

	def test_F7_gift_that_cannot_streak_is_dropped_when_repeat_end_is_zero(self):
		# Needs live data: what repeat_end TikTok really sends for such gifts.
		r = f.run_session(f.gift(alice, "Lion", 29999, 1, repeat_end=0, streakable=False))
		self.assertEqual(r.files["gifts.txt"], [])
		self.assertEqual(r.stats["total_diamonds"], 0)

	def test_F8_same_gift_twice_within_a_second_is_one(self):
		r = f.run_session(
			f.gift(alice, "Rose", 1, 1, repeat_end=1), f.gift(alice, "Rose", 1, 1, repeat_end=1)
		)
		self.assertEqual(logged(r, "gifts.txt"), ["Alice: 1 Rose"])

	def test_F9_new_line_in_a_comment_splits_the_entry(self):
		r = f.run_session(f.comment(alice, "line1\nline2"))
		self.assertEqual(logged(r, "comments.txt"), ["Alice: line1", "line2"])

	def test_F10_name_cleaned_to_nothing_leaves_empty_entries(self):
		emoji = f.user("✨🌸", "flowers")
		r = f.run_session(f.comment(emoji, "hey"), f.follow(emoji))
		self.assertEqual(logged(r, "comments.txt"), [": hey"])
		self.assertEqual(logged(r, "followers.txt"), [""])

	def test_F11_likes_still_being_summed_are_lost_at_the_end(self):
		r = f.run_session(f.like(alice, 5, 5), settle_likes=False)
		self.assertEqual(r.files["likes.txt"], [])
		self.assertEqual(r.stats["total_likes"], 5)

	def test_F12_top_lists_are_not_written_at_the_end(self):
		r = f.run_session(f.gift(alice, "Rose", 1, 1), f.like(bob, 5, 5))
		self.assertEqual(r.files["top gifters.txt"], [])
		self.assertEqual(r.files["top likes.txt"], [])

	def test_F29_settings_saved_with_a_byte_order_mark_are_ignored(self):
		plugin, _ = make_plugin(main={"username": "someone"})
		text = f.addon_settings.CONFIG_PATH.read_text(encoding="utf-8")
		f.addon_settings.CONFIG_PATH.write_text("﻿" + text, encoding="utf-8")
		again = type(plugin)()
		self.assertEqual(again.settings.username, "")


class ConnectionIssues(unittest.TestCase):
	def test_F1_F27_switching_off_leaves_the_connection_open_and_blocks_three_seconds(self):
		plugin, _ = make_plugin()
		with f.replaying(end="hold") as session:
			plugin.script_toggleActive(None)
			self.assertTrue(f.wait_until(said("Connected to user: host")))
			started = time.perf_counter()
			plugin.script_toggleActive(None)
			self.assertGreaterEqual(time.perf_counter() - started, 2.9)
			self.assertTrue(session.threads[0].is_alive())

	def test_F2_old_connection_ending_switches_off_the_new_session(self):
		plugin, _ = make_plugin()
		with f.replaying(end="hold") as old:
			plugin.script_toggleActive(None)
			self.assertTrue(f.wait_until(said("Connected to user: host")))
			plugin.script_toggleActive(None)
			support.spoken.clear()
			with f.replaying(end="hold") as new:
				plugin.script_toggleActive(None)
				self.assertTrue(f.wait_until(said("Connected to user: host")))
				old.release.set()
				self.assertTrue(f.wait_until(said("The live has ended")), support.spoken)
				self.assertFalse(plugin.active)
				new.release.set()


if __name__ == "__main__":
	unittest.main()
