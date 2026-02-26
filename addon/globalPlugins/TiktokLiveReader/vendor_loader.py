import contextlib
import os
import sys
import threading
from dataclasses import dataclass
from types import ModuleType

_MISSING = object()
_LOCK = threading.RLock()
_CONFLICT_PREFIXES = (
	"TikTokLive",
	"websockets",
	"websockets_proxy",
	"httpx",
	"httpcore",
	"anyio",
	"sniffio",
	"google",
	"protobuf_to_dict",
	"betterproto",
	"grpclib",
	"python_socks",
	"pyee",
	"h2",
	"hpack",
	"hyperframe",
	"typing_extensions",
	"multidict",
	"async_timeout",
)


def _has_conflict_prefix(module_name):
	for prefix in _CONFLICT_PREFIXES:
		if module_name == prefix or module_name.startswith(f"{prefix}."):
			return True
	return False


def _collect_conflicting_modules():
	return {
		name: module
		for name, module in sys.modules.items()
		if module is not None and _has_conflict_prefix(name)
	}


@dataclass
class VendorRuntime:
	lib_dir: str
	modules: dict[str, ModuleType]


def load_runtime(lib_dir):
	abs_lib_dir = os.path.abspath(lib_dir)
	with _LOCK:
		original_path = list(sys.path)
		original_modules = _collect_conflicting_modules()
		try:
			sys.path = [abs_lib_dir] + [p for p in sys.path if p != abs_lib_dir]
			for module_name in list(sys.modules.keys()):
				if _has_conflict_prefix(module_name):
					sys.modules.pop(module_name, None)

			# Bootstrap-load TikTok package tree once in isolated context.
			import TikTokLive  # noqa: F401
			import httpx  # noqa: F401
			import websockets  # noqa: F401
			try:
				import google.protobuf  # noqa: F401
			except Exception:
				pass

			runtime_modules = _collect_conflicting_modules()
		finally:
			sys.path = original_path
			for module_name in list(sys.modules.keys()):
				if _has_conflict_prefix(module_name):
					sys.modules.pop(module_name, None)
			sys.modules.update(original_modules)

	return VendorRuntime(lib_dir=abs_lib_dir, modules=runtime_modules)


@contextlib.contextmanager
def runtime_scope(runtime):
	with _LOCK:
		original_path = list(sys.path)
		module_snapshot = {name: sys.modules.get(name, _MISSING) for name in runtime.modules}
		prefix_before = _collect_conflicting_modules()
		sys.path = [runtime.lib_dir] + [p for p in sys.path if p != runtime.lib_dir]
		sys.modules.update(runtime.modules)
	try:
		yield
	finally:
		with _LOCK:
			for name, module in list(sys.modules.items()):
				if module is not None and _has_conflict_prefix(name):
					runtime.modules[name] = module
			for name in list(sys.modules.keys()):
				if _has_conflict_prefix(name):
					sys.modules.pop(name, None)
			sys.modules.update(prefix_before)
			for name, value in module_snapshot.items():
				if value is _MISSING:
					sys.modules.pop(name, None)
				else:
					sys.modules[name] = value
			sys.path = original_path
