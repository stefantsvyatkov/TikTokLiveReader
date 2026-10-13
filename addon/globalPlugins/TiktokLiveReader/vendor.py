"""Keeps the libraries bundled in lib/ private to the add-on.

They are imported by their own names, but those names are in ``sys.modules`` (and
lib/ on ``sys.path``) only while add-on code runs inside ``scope``; the
connection holds it for the whole live. Outside, NVDA and other add-ons see their
own copies of the same packages, which are put back when the last scope ends.

Every top-level package and module in lib/ is private, found by looking at the
folder, except copies of standard library modules (lib/secrets.py): those are a
fallback for Python builds without them and stay where Python puts them.
"""

import contextlib
import importlib
import sys
import threading
from pathlib import Path

_lock = threading.RLock()


def bundled_names(lib_dir):
	"""The top-level names that can be imported from ``lib_dir``."""
	names = set()
	for entry in Path(lib_dir).iterdir():
		name = entry.name.split(".")[0]
		if entry.is_dir():
			if entry.name.isidentifier() and entry.name != "__pycache__" and _has_code(entry):
				names.add(entry.name)
		elif entry.suffix in (".py", ".pyd") and name.isidentifier():
			names.add(name)
	return names - set(sys.stdlib_module_names)


def _has_code(folder):
	"""A package, or a namespace package such as google/, but not bin/."""
	if (folder / "__init__.py").exists():
		return True
	candidates = [folder, *(child for child in folder.iterdir() if child.is_dir())]
	return any(next(candidate.glob(pattern), None) for candidate in candidates for pattern in ("*.py", "*.pyd"))


class Runtime:
	"""The bundled modules, by full name, and how many scopes are using them."""

	def __init__(self, lib_dir):
		self.lib_dir = str(Path(lib_dir).resolve())
		self.names = frozenset(bundled_names(self.lib_dir))
		self.modules = {}
		self._users = 0
		self._displaced = {}
		self._added_path = False

	def is_private(self, module_name):
		return module_name.partition(".")[0] in self.names

	def _enter(self):
		self._displaced = {name: module for name, module in list(sys.modules.items()) if self.is_private(name)}
		for name in self._displaced:
			del sys.modules[name]
		sys.modules.update(self.modules)
		self._added_path = self.lib_dir not in sys.path
		if self._added_path:
			sys.path.insert(0, self.lib_dir)

	def _leave(self):
		for name, module in list(sys.modules.items()):
			if self.is_private(name):
				if module is not None:
					self.modules[name] = module
				del sys.modules[name]
		sys.modules.update(self._displaced)
		self._displaced = {}
		if self._added_path:
			with contextlib.suppress(ValueError):
				sys.path.remove(self.lib_dir)
			self._added_path = False


@contextlib.contextmanager
def scope(runtime):
	"""The bundled modules importable by their names; nested and concurrent scopes
	share one installation, removed when the last of them ends."""
	with _lock:
		if runtime._users == 0:
			runtime._enter()
		runtime._users += 1
	try:
		yield runtime
	finally:
		with _lock:
			runtime._users -= 1
			if runtime._users == 0:
				runtime._leave()


def load(lib_dir, *modules, optional=()):
	"""A runtime for ``lib_dir`` with ``modules`` imported (and ``optional`` ones
	when they import)."""
	runtime = Runtime(lib_dir)
	with scope(runtime):
		for name in modules:
			importlib.import_module(name)
		for name in optional:
			with contextlib.suppress(Exception):
				importlib.import_module(name)
	return runtime
