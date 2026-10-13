"""The add-on's scripts: switching on and off, navigation, clearing, archiving, settings."""

import json
import re
import unittest

from . import feed as f
from . import support

G = support.load("globalPlugin")
settings = f.addon_settings
store = f.store
alice, bob = f.user("Alice"), f.user("Bob")
BASE_GESTURES = {"kb:NVDA+control+shift+t", "kb:NVDA+control+shift+l"}


class Gesture:
	sent = False

	def send(self):
		self.sent = True


def make_plugin(**sections):
	log_dir = f.fresh_log_dir()
	main = {"username": "host", "text_files_destination": str(log_dir)}
	main.update(sections.pop("main", {}))
	for path in (settings.CONFIG_PATH, settings.POSITIONS_PATH):
		if path.exists():
			path.unlink()
	f.write_settings(main=main, **sections)
	support.spoken.clear()
	support.dialogs.clear()
	return G.GlobalPlugin(), log_dir


def said(text):
	return lambda: text in support.spoken


class PluginTest(unittest.TestCase):
	def start(self, plugin, *frames, lines=None):
		"""Switch on with a held replay; wait until connected and ``lines`` comments are logged."""
		self.replay = f.replaying(*frames, end="hold")
		self.replay.__enter__()
		self.addCleanup(self.stop, plugin)
		plugin.script_toggleActive(None)
		self.assertTrue(f.wait_until(said("Connected to user: host")), support.spoken)
		if lines is not None:
			self.assertTrue(f.wait_until(lambda: len(self.read(plugin, "comments.txt")) >= lines))

	def stop(self, plugin):
		if plugin.active:
			plugin.script_toggleActive(None)
		self.replay.__exit__(None, None, None)

	def read(self, plugin, name):
		path = store.path(name)
		return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


class SwitchingOnAndOff(PluginTest):
	def test_refuses_without_a_user_name(self):
		plugin, _ = make_plugin(main={"username": ""})
		plugin.script_toggleActive(None)
		self.assertEqual(support.spoken, ["Please enter a valid username"])
		self.assertFalse(plugin.active)

	def test_on_and_off(self):
		plugin, _ = make_plugin()
		self.start(plugin)
		self.assertTrue(plugin.active)
		self.assertIn("kb:control+shift+downArrow", plugin.boundGestures)
		plugin.script_toggleActive(None)
		self.assertEqual(
			support.spoken, ["TikTok Live Reader On", "Connected to user: host", "TikTok Live Reader Off"]
		)
		self.assertEqual(set(plugin.boundGestures), BASE_GESTURES)

	def test_stream_end_switches_off(self):
		plugin, _ = make_plugin()
		with f.replaying(f.comment(alice, "bye")):
			plugin.script_toggleActive(None)
			self.assertTrue(f.wait_until(said("The live has ended")), support.spoken)
		self.assertEqual(
			support.spoken, ["TikTok Live Reader On", "Connected to user: host", "The live has ended"]
		)
		self.assertFalse(plugin.active)
		self.assertEqual(set(plugin.boundGestures), BASE_GESTURES)

	def test_failed_connection_switches_off(self):
		plugin, _ = make_plugin(behavior={"retry_count": 1})
		with f.replaying(end="error"):
			plugin.script_toggleActive(None)
			self.assertTrue(f.wait_until(said("Connection unsuccessful.")), support.spoken)
		self.assertFalse(plugin.active)

	def test_report_viewers(self):
		plugin, _ = make_plugin()
		self.start(plugin, f.viewers(37))
		self.assertTrue(f.wait_until(lambda: f.pipeline.viewer_count == 37))
		plugin.script_reportViewers(None)
		self.assertEqual(support.spoken[-1], "37 viewers")


class Navigation(PluginTest):
	def setUp(self):
		self.plugin, _ = make_plugin()
		self.start(
			self.plugin, f.comment(alice, "one"), f.comment(bob, "two"), f.comment(alice, "three"), lines=3
		)
		support.spoken.clear()

	def assertSaid(self, pattern):
		self.assertRegex(support.spoken[-1], pattern)

	def test_items(self):
		p = self.plugin
		p.script_nextItem(None)
		self.assertSaid(r"^Alice: one  \d\d:\d\d:\d\d \(1 of 3\)$")
		p.script_nextItem(None)
		self.assertSaid(r"^Bob: two  .* \(2 of 3\)$")
		p.script_lastItem(None)
		self.assertSaid(r"\(3 of 3\)$")
		p.script_nextItem(None)
		self.assertSaid(r"\(3 of 3\)$")
		p.script_firstItem(None)
		self.assertSaid(r"\(1 of 3\)$")
		p.script_prevItem(None)
		self.assertSaid(r"\(1 of 3\)$")

	def test_files_wrap_around(self):
		p = self.plugin
		p.script_nextFile(None)
		self.assertEqual(support.spoken[-1], "Events")
		p.script_prevFile(None)
		p.script_prevFile(None)
		self.assertEqual(support.spoken[-1], "Visitors")

	def test_empty_file(self):
		p = self.plugin
		p.script_nextFile(None)
		p.script_nextFile(None)
		self.assertEqual(support.spoken[-1], "Followers")
		p.script_nextItem(None)
		self.assertEqual(support.spoken[-1], "No entries")

	def test_stats_lines_have_no_position(self):
		p = self.plugin
		while support.spoken[-1:] != ["Stats"]:
			p.script_nextFile(None)
		p.script_nextItem(None)
		self.assertEqual(support.spoken[-1], "Viewers: 0")

	def test_each_file_keeps_its_own_position(self):
		p = self.plugin
		p.script_nextItem(None)
		p.script_nextItem(None)
		p.script_nextFile(None)
		p.script_prevFile(None)
		p.script_nextItem(None)
		self.assertSaid(r"\(3 of 3\)$")


class Positions(PluginTest):
	def test_kept_across_sessions_when_clearing_is_off(self):
		off = {"behavior": {"clear_on_start": False}}
		plugin, log_dir = make_plugin(**off)
		self.start(plugin, f.comment(alice, "one"), f.comment(bob, "two"), f.comment(alice, "three"), lines=3)
		plugin.script_nextItem(None)
		plugin.script_nextItem(None)
		self.stop(plugin)
		saved = json.loads(settings.POSITIONS_PATH.read_text(encoding="utf-8"))
		self.assertEqual(saved["files"]["comments"], {"line": 1})

		f.write_settings(main={"username": "host", "text_files_destination": str(log_dir)}, **off)
		again = G.GlobalPlugin()
		self.start(again, lines=3)
		support.spoken.clear()
		again.script_nextItem(None)
		self.assertRegex(support.spoken[-1], r"\(3 of 3\)$")


class Clearing(PluginTest):
	def setUp(self):
		self.plugin, _ = make_plugin()
		self.start(self.plugin, f.comment(alice, "one"), lines=1)

	def test_asks_first(self):
		self.plugin.script_clearTextFiles(None)
		(dialog,) = support.dialogs
		self.assertEqual(dialog.message, "Are you sure you want to delete the contents of all text files?")
		dialog.press("no")
		self.assertEqual(len(self.read(self.plugin, "comments.txt")), 1)

	def test_yes_clears_every_file(self):
		self.plugin.script_clearTextFiles(None)
		support.dialogs[0].press("yes")
		self.assertEqual(support.spoken[-1], "All files cleared.")
		for path in store.session_files():
			self.assertEqual(path.read_text(encoding="utf-8"), "", path.name)


class Toggles(PluginTest):
	def test_auto_speak_and_sounds_are_saved(self):
		plugin, _ = make_plugin()
		self.start(plugin)
		plugin.script_toggleAutoSpeak(None)
		plugin.script_togglePlaySounds(None)
		self.assertEqual(support.spoken[-2:], ["Auto speak On", "Sounds On"])
		saved = settings.load()
		self.assertTrue(saved.auto_speak_enabled)
		self.assertTrue(saved.play_sounds)
		plugin.script_toggleAutoSpeak(None)
		self.assertEqual(support.spoken[-1], "Auto speak Off")

	def test_toggles_pass_the_key_through_when_off(self):
		plugin, _ = make_plugin()
		gesture = Gesture()
		plugin.script_toggleAutoSpeak(gesture)
		self.assertTrue(gesture.sent)
		self.assertEqual(support.spoken, [])

	def test_auto_speak_reads_new_events_aloud(self):
		plugin, _ = make_plugin(auto_speak={"enabled": True})
		self.start(plugin, 0.3, f.comment(alice, "hello"))
		self.assertTrue(f.wait_until(said("Alice: hello"), timeout=5), support.spoken)


class Archiving(PluginTest):
	def archives(self, log_dir):
		backups = log_dir / "Backups"
		return sorted(backups.iterdir()) if backups.exists() else []

	def test_switching_off_archives_the_session(self):
		plugin, log_dir = make_plugin(behavior={"backup_sessions": True})
		self.start(plugin, f.comment(alice, "keep me"), lines=1)
		plugin.script_toggleActive(None)
		(folder,) = self.archives(log_dir)
		self.assertRegex(folder.name, r"^\d{4}-\d\d-\d\d \d\d-\d\d-\d\d host$")
		self.assertIn("keep me", (folder / "comments.txt").read_text(encoding="utf-8"))

	def test_stream_end_archives_the_session(self):
		plugin, log_dir = make_plugin(behavior={"backup_sessions": True})
		with f.replaying(f.comment(alice, "bye")):
			plugin.script_toggleActive(None)
			self.assertTrue(f.wait_until(said("The live has ended")))
		self.assertEqual(len(self.archives(log_dir)), 1)

	def test_nothing_is_archived_when_off(self):
		plugin, log_dir = make_plugin()
		self.start(plugin, f.comment(alice, "x"), lines=1)
		plugin.script_toggleActive(None)
		self.assertEqual(self.archives(log_dir), [])

	def test_failed_connection_is_not_archived(self):
		plugin, log_dir = make_plugin(behavior={"backup_sessions": True, "retry_count": 1})
		with f.replaying(end="error"):
			plugin.script_toggleActive(None)
			self.assertTrue(f.wait_until(said("Connection unsuccessful.")))
		self.assertEqual(self.archives(log_dir), [])

	def test_closing_nvda_archives_an_active_session(self):
		plugin, log_dir = make_plugin(behavior={"backup_sessions": True})
		self.start(plugin, f.comment(alice, "x"), lines=1)
		plugin.terminate()
		self.assertEqual(len(self.archives(log_dir)), 1)


class SettingsFile(unittest.TestCase):
	def test_saved_settings_are_read_back(self):
		plugin, log_dir = make_plugin()
		prefs = dict(settings.DEFAULT_EVENT_PREFS, likes=False)
		speak = dict(settings.DEFAULT_EVENT_PREFS, gifts=False)
		sounds = dict(settings.DEFAULT_EVENT_PREFS, visitors=True)
		plugin._apply_settings(
			settings.Settings(
				username="someone",
				text_files_destination=str(log_dir),
				events=prefs,
				auto_speak=speak,
				sounds=sounds,
				clear_on_start=False,
				clean_usernames=False,
				retry_count=7,
				backup_sessions=True,
				play_sounds=True,
				volume=40,
			)
		)
		again = G.GlobalPlugin().settings
		self.assertEqual(again.username, "someone")
		self.assertEqual((again.events, again.auto_speak, again.sounds), (prefs, speak, sounds))
		self.assertEqual(
			(again.clear_on_start, again.clean_usernames, again.retry_count, again.play_sounds, again.volume),
			(False, False, 7, True, 40),
		)
		self.assertEqual(again.text_files_destination, str(log_dir))
		self.assertTrue(again.backup_sessions)

	def test_missing_file_gives_the_defaults(self):
		for path in (settings.CONFIG_PATH, settings.POSITIONS_PATH):
			if path.exists():
				path.unlink()
		loaded = G.GlobalPlugin().settings
		self.assertEqual(loaded.username, "")
		self.assertEqual(loaded.events, settings.DEFAULT_EVENT_PREFS)
		self.assertEqual(loaded.volume, 70)
		self.assertTrue(re.search(r"Documents[\\/]TikTok live$", loaded.text_files_destination))


if __name__ == "__main__":
	unittest.main()
