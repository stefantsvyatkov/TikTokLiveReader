"""Ignored users: what the add-on drops and keeps of them, the shortcut, the settings file."""

import unittest

from . import feed as f
from . import support
from .test_plugin import PluginTest, make_plugin

announcer = support.load("announcer")
events = support.load("events")
pipeline = f.pipeline
settings = f.addon_settings
store = f.store
alice, bob = f.user("Alice"), f.user("Bob")


def logged(result, name):
	return f.without_times(result.files[name])


class WhatIsDropped(unittest.TestCase):
	def setUp(self):
		self.r = f.run_session(
			f.comment(bob, "buy followers"),
			f.comment(alice, "hello"),
			f.like(bob, 5, 5),
			f.like(alice, 1, 6),
			f.join(bob),
			f.share(bob),
			f.gift(bob, "Rose", 1, 1),
			f.follow(bob),
			settings={"ignored_users": {"bob": "Bob"}, "events": {"visitors": True}},
		)

	def test_comments_likes_shares_and_visits_are_dropped(self):
		r = self.r
		self.assertEqual(logged(r, "comments.txt"), ["Alice: hello"])
		self.assertEqual(logged(r, "likes.txt"), ["Alice: 1 like"])
		self.assertEqual(logged(r, "visitors.txt"), [])
		self.assertEqual(logged(r, "shares.txt"), [])
		self.assertEqual(logged(r, "top likes.txt"), ["Alice: 1"])
		self.assertNotIn("Bob: buy followers", r.speech)

	def test_gifts_and_follows_still_come(self):
		r = self.r
		self.assertEqual(logged(r, "gifts.txt"), ["Bob: 1 Rose"])
		self.assertEqual(logged(r, "followers.txt"), ["Bob"])
		self.assertIn("Gift: Bob: 1 Rose", r.speech)
		self.assertIn("New follower: Bob", r.speech)

	def test_the_live_totals_still_count_them(self):
		self.assertEqual(self.r.stats["total_likes"], 6)

	def test_handles_are_compared_in_lower_case(self):
		carol = f.user("Carol", "Carol_X")
		r = f.run_session(f.comment(carol, "hi"), settings={"ignored_users": {"carol_x": "Carol"}})
		self.assertEqual(logged(r, "comments.txt"), [])


class WhoALineIsAbout(unittest.TestCase):
	def test_lines_written_know_their_person(self):
		r = f.run_session(f.comment(alice, "hello"), f.gift(bob, "Rose", 1, 1))
		store.set_folder(r.log_dir)
		comment = store.read_entries(store.COMMENTS)[0]
		self.assertEqual(store.author_of(comment), ("alice", "Alice"))
		gift = store.read_entries(store.GIFTS)[0]
		self.assertEqual(store.author_of(gift), ("bob", "Bob"))
		self.assertIsNone(store.author_of(store.read_entries(store.STATS)[0]))

	def test_clearing_forgets_them(self):
		r = f.run_session(f.comment(alice, "hello"))
		store.set_folder(r.log_dir)
		comment = store.read_entries(store.COMMENTS)[0]
		store.clear_all()
		self.assertIsNone(store.author_of(comment))


class SettingsFile(unittest.TestCase):
	def test_kept_with_a_percent_sign(self):
		saved = settings.Settings(ignored_users={"bob": "100% Bob"})
		settings.save(saved)
		self.assertEqual(settings.load().ignored_users, {"bob": "100% Bob"})

	def test_no_section_while_nobody_is_ignored(self):
		settings.save(settings.Settings())
		self.assertNotIn("ignored_users", settings.CONFIG_PATH.read_text(encoding="utf-8"))
		self.assertEqual(settings.load().ignored_users, {})


class Shortcut(PluginTest):
	def setUp(self):
		self.plugin, _ = make_plugin()
		self.start(self.plugin, f.comment(alice, "one"), f.comment(bob, "two"), lines=2)
		support.spoken.clear()

	def test_ignores_and_stops_ignoring_the_person_of_the_current_item(self):
		p = self.plugin
		p.script_lastItem(None)
		p.script_toggleIgnoreUser(None)
		self.assertEqual(support.spoken[-1], "Bob is now ignored")
		self.assertEqual(p.settings.ignored_users, {"bob": "Bob"})
		self.assertEqual(settings.load().ignored_users, {"bob": "Bob"})
		self.assertEqual(pipeline._settings.ignored_users, {"bob": "Bob"})
		p.script_toggleIgnoreUser(None)
		self.assertEqual(support.spoken[-1], "Bob is no longer ignored")
		self.assertEqual(settings.load().ignored_users, {})

	def test_an_item_about_nobody(self):
		p = self.plugin
		while support.spoken[-1:] != ["Stats"]:
			p.script_nextFile(None)
		p.script_nextItem(None)
		p.script_toggleIgnoreUser(None)
		self.assertEqual(support.spoken[-1], "Nobody to ignore in this item")

	def test_before_moving_to_an_item(self):
		self.plugin.script_toggleIgnoreUser(None)
		self.assertEqual(support.spoken[-1], "No entries")


def person(nickname, handle):
	return events.Person(True, abs(hash(handle)), nickname, nickname, handle)


class IgnoredMeanwhile(unittest.TestCase):
	def setUp(self):
		store.set_folder(f.fresh_log_dir())
		store.ensure_files_exist()
		self.addCleanup(pipeline.use_settings, pipeline._settings)
		self.addCleanup(pipeline.like_manager.stop)

	def test_likes_being_summed_are_dropped(self):
		pipeline.use_settings(settings.Settings())
		pipeline._on_like(events.Like(1, person("Bob", "bob"), 10, 4))
		pipeline.use_settings(settings.Settings(ignored_users={"bob": "Bob"}))
		pipeline.like_manager.flush_pending()
		self.assertEqual(store.read_entries(store.LIKES), [])

	def test_announcements_waiting_their_turn_are_dropped(self):
		sounds = announcer.SoundManager(announcer.ADDON_DIR)
		sounds.start()
		self.addCleanup(sounds.stop)
		done = []
		for name, wanted in (("ignored", False), ("kept", True), ("no person", None)):
			sounds.play(
				"comments",
				play_file=False,
				on_complete=lambda name=name: done.append(name),
				post_delay=0.0,
				wanted=None if wanted is None else (lambda wanted=wanted: wanted),
			)
		self.assertTrue(f.wait_until(lambda: sounds._queue.unfinished_tasks == 0, timeout=5))
		self.assertEqual(done, ["kept", "no person"])


if __name__ == "__main__":
	unittest.main()
