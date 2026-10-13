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
