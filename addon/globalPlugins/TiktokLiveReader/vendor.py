"""Keeps the libraries bundled in lib/ private to the add-on.

They are imported by their own names, but those names are in ``sys.modules`` (and
lib/ on ``sys.path``) only while add-on code runs inside ``scope``; the
connection holds it for the whole live. Outside, NVDA and other add-ons see their
own copies of the same packages, which are put back when the last scope ends.

Every top-level package and module in lib/ is private, found by looking at the
folder, except shared ones: copies of standard library modules (lib/secrets.py,
lib/zoneinfo) for Python builds without them, and packages named by the caller
that any version serves. ``load`` imports each before anything else, the
process's own where there is one, and they stay where Python puts them.
"""

import contextlib
import importlib
import importlib.machinery
import importlib.util
import sys
import threading
from pathlib import Path

_lock = threading.RLock()


def bundled_names(lib_dir):
	"""The private top-level names that can be imported from ``lib_dir``."""
	return _top_level_names(lib_dir) - set(sys.stdlib_module_names)


def standard_copies(lib_dir):
	"""The standard library modules ``lib_dir`` has copies of."""
	return _top_level_names(lib_dir) & set(sys.stdlib_module_names)


def _top_level_names(lib_dir):
	names = set()
	for entry in Path(lib_dir).iterdir():
		name = entry.name.split(".")[0]
		if entry.is_dir():
			if entry.name.isidentifier() and entry.name != "__pycache__" and _has_code(entry):
				names.add(entry.name)
		elif entry.suffix in (".py", ".pyd") and name.isidentifier():
			names.add(name)
	return names


def _has_code(folder):
	"""A package, or a namespace package such as google/, but not bin/."""
	if (folder / "__init__.py").exists():
		return True
	candidates = [folder, *(child for child in folder.iterdir() if child.is_dir())]
	return any(
		next(candidate.glob(pattern), None) for candidate in candidates for pattern in ("*.py", "*.pyd")
	)


class Runtime:
	"""The bundled modules, by full name, and how many scopes are using them."""

	def __init__(self, lib_dir, shared=()):
		self.lib_dir = str(Path(lib_dir).resolve())
		self.names = frozenset(bundled_names(self.lib_dir) - set(shared))
		self.modules = {}
		self._users = 0
		self._displaced = {}
		self._added_path = False

	def is_private(self, module_name):
		return module_name.partition(".")[0] in self.names

	def _enter(self):
		self._displaced = {
			name: module for name, module in list(sys.modules.items()) if self.is_private(name)
		}
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


def _import_shared(lib_dir, names):
	for name in sorted(names):
		if name in sys.modules:
			continue
		try:
			importlib.import_module(name)
		except ModuleNotFoundError as error:
			if error.name != name:
				raise
			spec = importlib.machinery.PathFinder.find_spec(name, [lib_dir])
			module = importlib.util.module_from_spec(spec)
			sys.modules[name] = module
			try:
				spec.loader.exec_module(module)
			except BaseException:
				del sys.modules[name]
				raise


def load(lib_dir, *modules, optional=(), shared=()):
	"""A runtime for ``lib_dir`` with ``modules`` imported (and ``optional`` ones
	when they import); the packages in ``shared`` are the process's if it has them."""
	runtime = Runtime(lib_dir, shared)
	_import_shared(runtime.lib_dir, standard_copies(runtime.lib_dir) | set(shared))
	with scope(runtime):
		for name in modules:
			importlib.import_module(name)
		for name in optional:
			with contextlib.suppress(Exception):
				importlib.import_module(name)
	return runtime
