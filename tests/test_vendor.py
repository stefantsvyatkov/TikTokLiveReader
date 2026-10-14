"""The bundled libraries stay private to the add-on (vendor.py)."""

import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from . import support

vendor = support.load("vendor")


def make_lib():
	lib = Path(tempfile.mkdtemp(dir=support.ROOT))
	(lib / "vt_alpha").mkdir()
	(lib / "vt_alpha" / "__init__.py").write_text("import vt_single\n", encoding="utf-8")
	(lib / "vt_ns" / "inner").mkdir(parents=True)
	(lib / "vt_ns" / "inner" / "mod.py").write_text("", encoding="utf-8")
	(lib / "vt_single.py").write_text("WHO = 'bundled'\n", encoding="utf-8")
	(lib / "vt_lazy.py").write_text("", encoding="utf-8")
	(lib / "secrets.py").write_text("", encoding="utf-8")
	(lib / "bin").mkdir()
	(lib / "bin" / "tool.exe").write_bytes(b"")
	(lib / "vt_alpha-1.0.dist-info").mkdir()
	(lib / "__pycache__").mkdir()
	return lib


class Isolation(unittest.TestCase):
	def setUp(self):
		self.lib = make_lib()
		self.runtime = vendor.load(self.lib, "vt_alpha")

	def tearDown(self):
		for name in [name for name in sys.modules if name.startswith("vt_")]:
			del sys.modules[name]

	def test_private_names_come_from_the_folder(self):
		self.assertEqual(self.runtime.names, {"vt_alpha", "vt_ns", "vt_single", "vt_lazy"})

	def test_modules_exist_only_inside_the_scope(self):
		self.assertNotIn("vt_alpha", sys.modules)
		self.assertNotIn("vt_single", sys.modules)
		self.assertNotIn(self.runtime.lib_dir, sys.path)
		with vendor.scope(self.runtime):
			import vt_alpha

			self.assertIs(vt_alpha, self.runtime.modules["vt_alpha"])
			self.assertIn(self.runtime.lib_dir, sys.path)
		self.assertNotIn("vt_alpha", sys.modules)
		self.assertNotIn(self.runtime.lib_dir, sys.path)

	def test_another_copy_is_put_back(self):
		theirs = types.ModuleType("vt_single")
		sys.modules["vt_single"] = theirs
		with vendor.scope(self.runtime):
			self.assertEqual(sys.modules["vt_single"].WHO, "bundled")
		self.assertIs(sys.modules["vt_single"], theirs)

	def test_modules_imported_later_are_kept_private(self):
		with vendor.scope(self.runtime):
			import vt_lazy
		self.assertNotIn("vt_lazy", sys.modules)
		with vendor.scope(self.runtime):
			self.assertIs(sys.modules["vt_lazy"], vt_lazy)

	def test_overlapping_scopes_keep_the_modules_until_the_last_ends(self):
		first, second = vendor.scope(self.runtime), vendor.scope(self.runtime)
		first.__enter__()
		second.__enter__()
		first.__exit__(None, None, None)
		self.assertIn("vt_alpha", sys.modules)
		self.assertIn(self.runtime.lib_dir, sys.path)
		second.__exit__(None, None, None)
		self.assertNotIn("vt_alpha", sys.modules)
		self.assertNotIn(self.runtime.lib_dir, sys.path)


class StandardCopies(unittest.TestCase):
	# grp is Unix only; colorsys is in every Python.
	def setUp(self):
		self.lib = make_lib()
		for name in ("grp", "colorsys"):
			(self.lib / f"{name}.py").write_text("WHO = 'bundled'\n", encoding="utf-8")
			sys.modules.pop(name, None)

	def tearDown(self):
		for name in ("grp", "colorsys"):
			sys.modules.pop(name, None)

	@unittest.skipUnless(sys.platform == "win32", "grp is part of Python on Unix")
	def test_a_copy_stands_in_for_a_module_python_lacks(self):
		runtime = vendor.load(self.lib, "vt_alpha")
		self.assertEqual(sys.modules["grp"].WHO, "bundled")
		self.assertNotIn("grp", runtime.names)

	def test_pythons_own_module_wins_over_the_copy(self):
		runtime = vendor.load(self.lib, "vt_alpha")
		with vendor.scope(runtime):
			import colorsys
		self.assertFalse(hasattr(colorsys, "WHO"))


STARTING = """
import sys, threading
sys.path.insert(0, sys.argv[1])
from tests import support
before = threading.active_count()
plugin = support.load("globalPlugin").GlobalPlugin()
adapter = sys.modules["tiktokAddon.tiktok_adapter"]
print(adapter._runtime is None, "TikTokLive" in sys.modules, threading.active_count() - before)
"""

# NVDA 2026.1 ships neither module, 2026.2 and 2026.3 lack zoneinfo.
WITHOUT_STANDARD_MODULES = """
import sys
from pathlib import Path


class Missing:
	def find_spec(self, name, path=None, target=None):
		if name in ("secrets", "zoneinfo", "_zoneinfo") and path is None:
			raise ModuleNotFoundError(f"No module named {name!r}", name=name)


sys.meta_path.insert(0, Missing())
sys.path.insert(0, sys.argv[1])
from tests import support
adapter = support.load("tiktok_adapter")
adapter.runtime()
lib = Path(adapter.LIB_DIR).resolve()
print(*(Path(sys.modules[name].__file__).resolve().is_relative_to(lib) for name in ("secrets", "zoneinfo")))
"""


FIRST_DECODE = """
import sys
sys.path.insert(0, sys.argv[1])
from tests import support
adapter = support.load("tiktok_adapter")
with adapter.library_scope():
	from TikTokLive.events import proto_events
	print(proto_events.LinkLayerEvent.parse(b"") is not None)
"""


class AddOnLibrary(unittest.TestCase):
	def test_a_link_layer_message_decodes_first_in_a_fresh_process(self):
		# Decoding it built pydantic's schema with betterproto2's local "data" in view.
		result = subprocess.run(
			[sys.executable, "-X", "utf8", "-W", "ignore", "-c", FIRST_DECODE, str(support.REPO)],
			capture_output=True,
			text=True,
			timeout=120,
		)
		self.assertEqual(result.stdout.split(), ["True"], result.stderr[-2000:])

	def test_the_library_loads_without_standard_modules_nvda_lacks(self):
		result = subprocess.run(
			[sys.executable, "-X", "utf8", "-W", "ignore", "-c", WITHOUT_STANDARD_MODULES, str(support.REPO)],
			capture_output=True,
			text=True,
			timeout=120,
		)
		self.assertEqual(result.stdout.split(), ["True", "True"], result.stderr)

	def test_nvda_start_does_not_load_the_library(self):
		# F18: in a fresh interpreter, as when NVDA starts.
		result = subprocess.run(
			[sys.executable, "-X", "utf8", "-c", STARTING, str(support.REPO)],
			capture_output=True,
			text=True,
			timeout=120,
		)
		self.assertEqual(result.stdout.split(), ["True", "False", "0"], result.stderr)

	def test_every_bundled_package_is_private(self):
		adapter = support.load("tiktok_adapter")
		names = adapter.runtime().names
		for name in ("TikTokLive", "httpx", "websockets", "idna", "certifi", "h11", "six", "dateutil"):
			self.assertIn(name, names)
			self.assertNotIn(name, sys.modules)
		self.assertNotIn("secrets", names)
		self.assertNotIn("zoneinfo", names)


if __name__ == "__main__":
	unittest.main()
