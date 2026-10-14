"""Another add-on, as add-ons with bundled packages usually are, for the sandbox's
conflicts scenario.

At NVDA's start it imports its own pydantic, httpx, websockets and anyio from its
lib/ (lib/ on sys.path only for the import, the modules left in sys.modules) and
keeps NVDA's own certifi, idna, typing_extensions and attr. NVDA+control+alt+shift+k
says who owns each name in sys.modules now and whether code holding the modules
from the start still works, including imports it makes only when used.
"""

import importlib
import os
import sys
from pathlib import Path

import globalPluginHandler
import ui
from logHandler import log
from scriptHandler import script

LIB = str(Path(__file__).resolve().parent / "lib")
OWN = ("pydantic", "httpx", "websockets", "anyio")
NVDAS = ("certifi", "idna", "typing_extensions", "attr")

sys.path.insert(0, LIB)
try:
	held = {name: importlib.import_module(name) for name in OWN}
finally:
	sys.path.remove(LIB)
nvdas = {}
for name in NVDAS:
	try:
		nvdas[name] = importlib.import_module(name)
	except ImportError:
		pass


def owner(name):
	module = sys.modules.get(name)
	if module is None:
		return "none"
	if module is held.get(name) or module is nvdas.get(name):
		return "own"
	if "TiktokLiveReader" in str(getattr(module, "__file__", "")):
		return "tiktok"
	return "other"


def checks():
	yield "pydantic", lambda: held["pydantic"].Model.WHO == "probe"
	yield "httpx", lambda: held["httpx"].client_owner() == "probe"
	yield "websockets", lambda: held["websockets"].WHO == "probe"
	if "idna" in nvdas:
		yield "idna", lambda: nvdas["idna"].encode("bücher.example", uts46=True) == b"xn--bcher-kva.example"
	if "certifi" in nvdas:
		yield "certifi", lambda: os.path.isfile(nvdas["certifi"].where())


def run_checks():
	results = []
	for name, check in checks():
		try:
			results.append(f"{name} {'ok' if check() else 'wrong'}")
		except Exception:
			log.info(f"conflict probe: {name} failed", exc_info=True)
			results.append(f"{name} failed")
	return results


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	@script(gesture="kb:NVDA+control+alt+shift+k")
	def script_probe(self, gesture):
		owners = ", ".join(f"{name} {owner(name)}" for name in OWN + NVDAS)
		ui.message(f"probe: {owners}; checks: {', '.join(run_checks())}")
