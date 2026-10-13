"""What a live session writes, says and plays: behaviour to keep."""

import unittest

from . import feed as f

alice, bob = f.user("Alice"), f.user("Bob")


def logged(result, name):
	return f.without_times(result.files[name])


class Comments(unittest.TestCase):
	def test_logged_in_comments_and_events_and_spoken(self):
		r = f.run_session(f.comment(alice, "hello"))
		self.assertEqual(logged(r, "comments.txt"), ["Alice: hello"])
		self.assertEqual(logged(r, "events.txt"), ["Alice: hello"])
		self.assertEqual(r.speech, ["Alice: hello"])
		self.assertEqual(r.sounds, [("comments", False)])

	def test_same_text_from_different_people(self):
		r = f.run_session(f.comment(alice, "hi"), f.comment(bob, "hi"))
		self.assertEqual(logged(r, "comments.txt"), ["Alice: hi", "Bob: hi"])

	def test_lines_carry_a_time_stamp(self):
		r = f.run_session(f.comment(alice, "hello"))
		self.assertRegex(r.files["comments.txt"][0], r"^Alice: hello  \d\d:\d\d:\d\d$")


class Gifts(unittest.TestCase):
	def test_streak_is_logged_once_when_it_ends(self):
		r = f.run_session(
			f.gift(alice, "Rose", 1, 3, repeat_end=0), f.gift(alice, "Rose", 1, 5, repeat_end=1)
		)
		self.assertEqual(logged(r, "gifts.txt"), ["Alice: 5 Rose"])
		self.assertEqual(logged(r, "events.txt"), ["Gift: Alice: 5 Rose"])
		self.assertEqual(r.speech, ["Gift: Alice: 5 Rose"])
		self.assertEqual(r.stats["total_diamonds"], 5)

	def test_diamonds_are_count_times_value(self):
		r = f.run_session(f.gift(alice, "Galaxy", 1000, 2, repeat_end=1))
		self.assertEqual(r.stats["total_diamonds"], 2000)
		self.assertIn("Diamonds: 2000", r.files["stats.txt"])


class Likes(unittest.TestCase):
	def test_bursts_are_summed_per_person(self):
		r = f.run_session(f.like(alice, 5, 10), f.like(alice, 3, 13), f.like(bob, 2, 15))
		self.assertEqual(logged(r, "likes.txt"), ["Alice: 8 likes", "Bob: 2 likes"])
		self.assertEqual(r.speech, ["Alice: 8 likes", "Bob: 2 likes"])

	def test_total_comes_from_the_stream(self):
		r = f.run_session(f.like(alice, 5, 900))
		self.assertEqual(r.stats["total_likes"], 900)
		self.assertIn("Likes: 900", r.files["stats.txt"])

	def test_single_like_is_singular(self):
		r = f.run_session(f.like(alice, 1, 1))
		self.assertEqual(logged(r, "likes.txt"), ["Alice: 1 like"])


class FollowsSharesVisitors(unittest.TestCase):
	def test_follow_is_logged_once(self):
		r = f.run_session(f.follow(alice))
		self.assertEqual(logged(r, "followers.txt"), ["Alice"])
		self.assertEqual(logged(r, "events.txt"), ["New follower: Alice"])
		self.assertEqual(r.speech, ["New follower: Alice"])
		self.assertEqual(r.stats["total_followers"], 1)

	def test_share_is_logged_once(self):
		r = f.run_session(f.share(alice))
		self.assertEqual(logged(r, "shares.txt"), ["Alice"])
		self.assertEqual(r.speech, ["Alice shared the live"])

	def test_visitors_are_counted_once_each(self):
		r = f.run_session(f.join(alice), f.join(alice), f.join(bob))
		self.assertEqual(logged(r, "visitors.txt"), ["Alice", "Bob"])
		self.assertEqual(r.stats["total_viewers"], 2)

	def test_viewer_count_follows_the_stream(self):
		r = f.run_session(f.viewers(37))
		self.assertEqual(r.stats["viewer_count"], 37)
		self.assertIn("Viewers: 37", r.files["stats.txt"])


class Settings(unittest.TestCase):
	def test_visitors_are_off_by_default_in_events_and_speech(self):
		r = f.run_session(f.join(alice))
		self.assertEqual(r.files["events.txt"], [])
		self.assertEqual(r.speech, [])

	def test_events_setting_only_affects_events_file(self):
		r = f.run_session(f.comment(alice, "quiet"), settings={"events": {"comments": False}})
		self.assertEqual(logged(r, "comments.txt"), ["Alice: quiet"])
		self.assertEqual(r.files["events.txt"], [])
		self.assertEqual(r.speech, ["Alice: quiet"])

	def test_auto_speak_setting_only_affects_speech(self):
		r = f.run_session(f.comment(alice, "x"), settings={"auto_speak": {"comments": False}})
		self.assertEqual(logged(r, "comments.txt"), ["Alice: x"])
		self.assertEqual(r.speech, [])

	def test_sounds_play_when_enabled(self):
		r = f.run_session(f.comment(alice, "x"), settings={"sounds": {"play_sounds": True}})
		self.assertEqual(r.sounds, [("comments", True)])

	def test_names_keep_letters_when_cleaned(self):
		r = f.run_session(f.comment(f.user("Ана ✨"), "здравей"))
		self.assertEqual(logged(r, "comments.txt"), ["Ана: здравей"])

	def test_names_stay_as_they_are_when_not_cleaned(self):
		r = f.run_session(f.comment(f.user("Ана ✨"), "x"), settings={"behavior": {"clean_usernames": False}})
		self.assertEqual(logged(r, "comments.txt"), ["Ана ✨: x"])


class ConnectionLifecycle(unittest.TestCase):
	def test_nothing_is_spoken_in_the_first_ten_seconds(self):
		r = f.run_session(f.comment(alice, "early"), past_grace_period=False)
		self.assertEqual(logged(r, "comments.txt"), ["Alice: early"])
		self.assertEqual(r.speech, [])
		self.assertEqual(r.sounds, [])

	def test_stream_end_reports_live_end(self):
		r = f.run_session(f.comment(alice, "bye"), f.live_ended())
		self.assertEqual(r.callbacks, ["connected", "live_end"])

	def test_clean_return_after_connecting_reports_live_end(self):
		r = f.run_session(f.comment(alice, "bye"))
		self.assertEqual(r.callbacks, ["connected", "live_end"])

	def test_dropped_connection_reports_failure_after_retries(self):
		r = f.run_session(f.comment(alice, "x"), end="error")
		self.assertEqual(r.callbacks, ["connected", "fail"])

	def test_files_are_cleared_on_start(self):
		first = f.run_session(f.comment(alice, "one"))
		second = f.run_session(f.comment(bob, "two"), log_dir=first.log_dir)
		self.assertEqual(logged(second, "comments.txt"), ["Bob: two"])

	def test_files_are_kept_when_clearing_is_off(self):
		off = {"behavior": {"clear_on_start": False}}
		first = f.run_session(f.comment(alice, "one"), settings=off)
		second = f.run_session(f.comment(bob, "two"), settings=off, log_dir=first.log_dir)
		self.assertEqual(logged(second, "comments.txt"), ["Alice: one", "Bob: two"])

	def test_history_already_in_kept_files_is_not_logged_again(self):
		off = {"behavior": {"clear_on_start": False}}
		first = f.run_session(f.comment(alice, "one"), settings=off)
		second = f.run_session(
			f.comment(alice, "one"), f.comment(bob, "two"), settings=off, log_dir=first.log_dir
		)
		self.assertEqual(logged(second, "comments.txt"), ["Alice: one", "Bob: two"])
		self.assertEqual(logged(second, "events.txt"), ["Alice: one", "Bob: two"])

	def test_stats_file_has_five_lines(self):
		r = f.run_session()
		self.assertEqual(
			r.files["stats.txt"], ["Viewers: 0", "Visitors: 0", "Likes: 0", "Followers: 0", "Diamonds: 0"]
		)


class EachMessageOnce(unittest.TestCase):
	"""Duplicates are recognised by TikTok's message id (findings F4, F5, F6, F8,
	F13, F32, F33): a message delivered twice counts once, two messages twice."""

	def test_a_comment_delivered_twice_is_logged_once(self):
		message = f.comment(alice, "hi")
		r = f.run_session(message, message)
		self.assertEqual(logged(r, "comments.txt"), ["Alice: hi"])
		self.assertEqual(r.speech, ["Alice: hi"])

	def test_the_same_comment_written_twice_is_logged_twice(self):
		r = f.run_session(f.comment(alice, "hi"), f.comment(alice, "hi"))
		self.assertEqual(logged(r, "comments.txt"), ["Alice: hi", "Alice: hi"])
		self.assertEqual(logged(r, "events.txt"), ["Alice: hi", "Alice: hi"])

	def test_a_like_delivered_twice_counts_once(self):
		message = f.like(alice, 5, 5)
		r = f.run_session(message, message)
		self.assertEqual(logged(r, "likes.txt"), ["Alice: 5 likes"])

	def test_the_same_gift_sent_twice_is_logged_twice(self):
		r = f.run_session(
			f.gift(alice, "Rose", 1, 1, repeat_end=1), f.gift(alice, "Rose", 1, 1, repeat_end=1)
		)
		self.assertEqual(logged(r, "gifts.txt"), ["Alice: 1 Rose", "Alice: 1 Rose"])
		self.assertEqual(r.stats["total_diamonds"], 2)

	def test_every_share_is_logged(self):
		r = f.run_session(f.share(alice), f.share(alice), f.share(alice))
		self.assertEqual(logged(r, "shares.txt"), ["Alice", "Alice", "Alice"])
		self.assertEqual(logged(r, "events.txt"), ["Alice shared the live"] * 3)

	def test_a_follow_counts_once_although_the_library_reports_it_twice(self):
		r = f.run_session(f.follow(alice))
		self.assertEqual(logged(r, "events.txt"), ["New follower: Alice"])
		self.assertEqual(r.speech, ["New follower: Alice"])


if __name__ == "__main__":
	unittest.main()
