"""Load the add-on outside NVDA.

NVDA's modules are replaced by stand-ins that record what the add-on asks of
NVDA, NVDA's configuration folder is a temporary folder, and the files the
add-on would keep in its own folder are moved there too, so a test run never
reads or writes the developer's real settings.
"""

import atexit
import collections
import importlib
import shutil
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADDON = REPO / "addon" / "globalPlugins" / "TiktokLiveReader"
PACKAGE = "tiktokAddon"

ROOT = Path(tempfile.mkdtemp(prefix="tiktokAddonTests-"))
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)
NVDA_CONFIG = ROOT / "nvdaConfig"
NVDA_CONFIG.mkdir()

spoken = []
dialogs = []


def _module(name, **attributes):
	module = types.ModuleType(name)
	module.__dict__.update(attributes)
	sys.modules[name] = module
	return module


def _identity(text):
	return text


def _initTranslation():
	caller = sys._getframe(1).f_globals
	caller["_"] = _identity
	caller["ngettext"] = lambda singular, plural, n: singular if n == 1 else plural
	caller["pgettext"] = lambda context, text: text


class _GlobalPlugin:
	def __init__(self):
		self.boundGestures = {}

	def bindGesture(self, gesture, scriptName):
		self.boundGestures[gesture] = scriptName

	def bindGestures(self, gestures):
		self.boundGestures.update(gestures)

	def clearGestureBindings(self):
		self.boundGestures = {}

	def terminate(self):
		pass


def _script(**kwargs):
	def decorate(function):
		function.__scriptKwargs = kwargs
		return function

	return decorate


Button = collections.namedtuple(
	"Button",
	"id label callback defaultFocus fallbackAction closesDialog returnCode",
	defaults=(None, False, False, True, None),
)


class _DefaultButton:
	class YES:
		value = Button(id="yes", label="&Yes")

	class NO:
		value = Button(id="no", label="&No")


class _MessageDialog:
	def __init__(self, parent, message, title=None, dialogType=None, *, buttons=()):
		self.message = message
		self.title = title
		self.buttons = buttons

	def Show(self):
		dialogs.append(self)

	def press(self, buttonId):
		for button in self.buttons:
			if button.id == buttonId and button.callback:
				button.callback(None)


def _install_nvda_stand_ins():
	_module("addonHandler", initTranslation=_initTranslation)
	_module("globalPluginHandler", GlobalPlugin=_GlobalPlugin)
	_module("scriptHandler", script=_script)
	_module("ui", message=spoken.append)
	message = _module(
		"gui.message",
		DefaultButton=_DefaultButton,
		DialogType=types.SimpleNamespace(WARNING="warning", STANDARD="standard"),
		MessageDialog=_MessageDialog,
	)
	_module("gui", mainFrame=None, message=message)
	# The settings dialog is tested in the sandbox; here wx only has to import.
	_module(
		"wx",
		CallAfter=lambda function, *args, **kwargs: function(*args, **kwargs),
		Dialog=type("Dialog", (), {}),
	)
	_module("NVDAState", WritePaths=types.SimpleNamespace(configDir=str(NVDA_CONFIG)))


def _mount():
	if PACKAGE not in sys.modules:
		_install_nvda_stand_ins()
		package = types.ModuleType(PACKAGE)
		package.__path__ = [str(ADDON)]
		sys.modules[PACKAGE] = package
	return sys.modules[PACKAGE]


def load(name):
	"""Import one of the add-on's modules, for example ``load("session")``."""
	_mount()
	module = importlib.import_module(f"{PACKAGE}.{name}")
	_keep_out_of_addon_folder()
	return module


def _keep_out_of_addon_folder():
	settings = sys.modules.get(f"{PACKAGE}.settings")
	if settings is not None:
		settings.LEGACY_CONFIG_PATH = ROOT / "legacy-config.ini"
		settings.LEGACY_POSITIONS_PATH = ROOT / "legacy-positions.json"
