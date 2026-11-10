"""What keeps a busy live cheap: text files written in batches and read only where
they grew, one timer for every liker, announcements that fell behind dropped."""

import threading
import time
import unittest

from . import feed as f
from . import support

store = support.load("store")
likes = support.load("likes")
announcer = support.load("announcer")


class TextFiles(unittest.TestCase):
	def setUp(self):
		store.set_folder(f.fresh_log_dir())
		store.ensure_files_exist()

	def test_lines_are_written_at_the_flush(self):
		store.append(store.COMMENTS, "Alice: one  10:00:00")
		self.assertEqual(store.path(store.COMMENTS).read_text(encoding="utf-8"), "")
		store.flush()
		self.assertEqual(store.path(store.COMMENTS).read_text(encoding="utf-8"), "Alice: one  10:00:00\n")

	def test_reading_sees_the_lines_not_written_yet(self):
		store.append(store.COMMENTS, "Alice: one  10:00:00")
		self.assertEqual(store.read_entries(store.COMMENTS), ["Alice: one  10:00:00"])

	def test_a_file_that_grew_is_read_from_where_it_was_left(self):
		store.append(store.COMMENTS, "Alice: one  10:00:00")
		first = store.read_entries(store.COMMENTS)
		with open(store.path(store.COMMENTS), "ab") as handle:
			handle.write(b"Bob: two  10:00:01\n")
		self.assertEqual(store.read_entries(store.COMMENTS), first + ["Bob: two  10:00:01"])

	def test_a_file_that_shrank_is_read_again(self):
		store.append(store.COMMENTS, "Alice: one  10:00:00")
		store.append(store.COMMENTS, "Bob: two  10:00:01")
		store.read_entries(store.COMMENTS)
		store.path(store.COMMENTS).write_text("Carol: three  10:00:02\n", encoding="utf-8")
		self.assertEqual(store.read_entries(store.COMMENTS), ["Carol: three  10:00:02"])

	def test_clearing_drops_the_lines_not_written_yet(self):
		store.append(store.COMMENTS, "Alice: one  10:00:00")
		store.read_entries(store.COMMENTS)
		store.append(store.COMMENTS, "Bob: two  10:00:01")
		store.clear_all()
		store.flush()
		self.assertEqual(store.read_entries(store.COMMENTS), [])
		self.assertEqual(store.path(store.COMMENTS).read_text(encoding="utf-8"), "")

	def test_a_rewritten_file_is_read_again(self):
		store.write(store.STATS, "Viewers: 1\n")
		self.assertEqual(store.read_entries(store.STATS), ["Viewers: 1"])
		store.write(store.STATS, "Viewers: 2\n")
		self.assertEqual(store.read_entries(store.STATS), ["Viewers: 2"])


class Likes(unittest.TestCase):
	def setUp(self):
		self.addCleanup(setattr, likes, "PAUSE", likes.PAUSE)
		likes.PAUSE = 0.3
		self.reports = []
		self.aggregator = likes.LikeAggregator(lambda user, count: self.reports.append((user, count)))
		self.addCleanup(self.aggregator.stop)

	def test_each_person_is_reported_after_their_own_pause(self):
		self.aggregator.add("Alice", 2)
		time.sleep(0.15)
		self.aggregator.add("Bob", 1)
		self.aggregator.add("Alice", 5)
		self.assertTrue(f.wait_until(lambda: len(self.reports) == 2, timeout=5))
		self.assertEqual(self.reports, [("Bob", 1), ("Alice", 5)])
		self.aggregator.add("Alice", 7)
		self.assertTrue(f.wait_until(lambda: len(self.reports) == 3, timeout=5))
		self.assertEqual(self.reports[-1], ("Alice", 2))

	def test_many_likers_wait_on_one_timer(self):
		before = threading.active_count()
		for number in range(200):
			self.aggregator.add(f"user{number}", 1)
		self.assertLessEqual(threading.active_count() - before, 1)
		self.aggregator.flush_pending()
		self.assertEqual(len(self.reports), 200)


class Announcements(unittest.TestCase):
	def test_an_announcement_that_waited_too_long_is_dropped(self):
		self.addCleanup(setattr, announcer, "STALE_AFTER", announcer.STALE_AFTER)
		announcer.STALE_AFTER = 0.3
		sounds = announcer.SoundManager(announcer.ADDON_DIR)
		sounds.start()
		self.addCleanup(sounds.stop)
		done = []
		for name in ("first", "second"):
			sounds.play(
				"comments", play_file=False, on_complete=lambda name=name: done.append(name), post_delay=1.0
			)
		self.assertTrue(f.wait_until(lambda: sounds._queue.unfinished_tasks == 0, timeout=5))
		self.assertEqual(done, ["first"])

	def test_comments_come_before_what_waited_longer(self):
		waiting = announcer.AnnouncementQueue()
		for kind in ("visitors", "likes", "shares", "requests", "followers", "gifts", "comments"):
			waiting.put(kind, kind)
		waiting.put("comments", "second comment")
		taken = [waiting.get(timeout=0) for _ in range(8)]
		self.assertEqual(
			taken,
			[
				"comments",
				"second comment",
				"gifts",
				"followers",
				"requests",
				"shares",
				"likes",
				"visitors",
			],
		)

	def test_only_the_newest_likes_wait(self):
		waiting = announcer.AnnouncementQueue()
		for number in range(10):
			waiting.put("likes", f"like {number}")
		waiting.put("comments", "hi")
		taken = [waiting.get(timeout=0) for _ in range(4)]
		self.assertEqual(taken, ["hi", "like 7", "like 8", "like 9"])
		self.assertRaises(announcer.queue.Empty, waiting.get, timeout=0)
		self.assertEqual(waiting.unfinished_tasks, 4)

	def test_likes_go_stale_before_comments(self):
		self.addCleanup(setattr, announcer, "STALE_AFTER_BY_KIND", announcer.STALE_AFTER_BY_KIND)
		announcer.STALE_AFTER_BY_KIND = {"likes": 0.1}
		waiting = announcer.AnnouncementQueue()
		waiting.put("likes", "like")
		waiting.put("comments", "hi")
		time.sleep(0.2)
		self.assertEqual(waiting.get(timeout=0), "hi")
		self.assertRaises(announcer.queue.Empty, waiting.get, timeout=0)

	def test_a_comment_queued_behind_many_likes_is_played_next(self):
		sounds = announcer.SoundManager(announcer.ADDON_DIR)
		sounds.start()
		self.addCleanup(sounds.stop)
		done = []

		def like(number):
			sounds.play(
				"likes", play_file=False, on_complete=lambda: done.append(f"like {number}"), post_delay=0.3
			)

		like(0)
		self.assertTrue(f.wait_until(lambda: done == ["like 0"], timeout=5))
		for number in range(1, 5):
			like(number)
		sounds.play("comments", play_file=False, on_complete=lambda: done.append("hi"), post_delay=0.0)
		self.assertTrue(f.wait_until(lambda: sounds._queue.unfinished_tasks == 0, timeout=5))
		self.assertEqual(done, ["like 0", "hi", "like 2", "like 3", "like 4"])


if __name__ == "__main__":
	unittest.main()
