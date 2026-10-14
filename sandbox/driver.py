"""Drives NVDA with real key presses inside the sandbox and checks what it says.

    python driver.py <scenario> <nvda log> <results folder> <text files folder> <replay control file>

Runs only inside Windows Sandbox (SandboxAgent.ps1 starts NVDA with the
add-on and the replaying TikTok client first): it presses keys on the
sandbox's desktop. Speech is read from NVDA's log ("Speaking [...]" lines at
log level 12). Writes results.txt (one PASS/FAIL line per check, then the
transcript) and exits 1 if a check failed.
"""

import ast
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
EXTENDED = {"insert", "home", "end", "up", "down", "left", "right", "delete", "pageup", "pagedown"}
VK = {
	"nvda": 0x2D,
	"insert": 0x2D,
	"control": 0x11,
	"shift": 0x10,
	"alt": 0x12,
	"home": 0x24,
	"end": 0x23,
	"up": 0x26,
	"down": 0x28,
	"left": 0x25,
	"right": 0x27,
	"tab": 0x09,
	"enter": 0x0D,
	"escape": 0x1B,
	"space": 0x20,
}


class KEYBDINPUT(ctypes.Structure):
	_fields_ = [
		("wVk", wintypes.WORD),
		("wScan", wintypes.WORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ctypes.c_size_t),
	]


class INPUT(ctypes.Structure):
	class _U(ctypes.Union):
		_fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

	_anonymous_ = ("u",)
	_fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(name, up):
	vk = VK.get(name) or ord(name.upper())
	flags = (KEYEVENTF_KEYUP if up else 0) | (
		KEYEVENTF_EXTENDEDKEY if name in EXTENDED or name == "nvda" else 0
	)
	scan = user32.MapVirtualKeyW(vk, 0)
	event = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))
	user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))


def press(combo):
	"""Press a combination such as "nvda+control+shift+t"."""
	keys = combo.lower().split("+")
	for key in keys:
		_send(key, up=False)
		time.sleep(0.03)
	for key in reversed(keys):
		_send(key, up=True)
		time.sleep(0.03)


STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
# Speech commands in the log, e.g. "LangChangeCommand ('en')", "CancellableSpeech (still valid)".
COMMAND = re.compile(r"\b[A-Z]\w*\s?\((?:[^()'\"]|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")*\)")


class NvdaLog:
	def __init__(self, path):
		self.path = Path(path)

	def text(self):
		try:
			return self.path.read_text(encoding="utf-8", errors="replace")
		except OSError:
			return ""

	def speech(self):
		"""Everything spoken so far, one string per utterance."""
		spoken = []
		for line in self.text().splitlines():
			if line.startswith("Speaking ["):
				parts = [ast.literal_eval(match) for match in STRING.findall(COMMAND.sub("", line))]
				parts = [part for part in parts if part.strip()]
				if parts:
					spoken.append(" ".join(parts))
		return spoken

	def errors(self):
		lines, block = [], []
		for line in self.text().splitlines():
			if re.match(r"^(ERROR|CRITICAL) - ", line):
				block = [line]
				lines.append(block)
			elif block and line and not re.match(r"^[A-Z]+ - ", line):
				block.append(line)
			else:
				block = []
		return [text for text in ("\n".join(item) for item in lines) if not NVDA_OWN_ERRORS.search(text)]


# NVDA 2026.1.1 fails to echo a character typed as Unicode input (no language);
# fixed in 2026.2. The driver types that way, so the error is not the add-on's.
NVDA_OWN_ERRORS = re.compile(r"getSpeechSequenceWithLangs[\s\S]*normalizeLanguage")


class Run:
	def __init__(self, log, out, texts, control):
		self.log, self.out, self.texts, self.control = NvdaLog(log), Path(out), Path(texts), Path(control)
		self.results = []
		self.mark = 0

	def check(self, name, ok, detail=""):
		self.results.append(("PASS" if ok else "FAIL", name, detail))
		return ok

	def since_mark(self):
		return self.log.speech()[self.mark :]

	def press_and_hear(self, combo, pattern, name, timeout=8):
		"""Press keys and wait until an utterance after the press matches ``pattern``."""
		self.mark = len(self.log.speech())
		started = time.monotonic()
		press(combo)
		while time.monotonic() - started < timeout:
			for utterance in self.since_mark():
				if re.search(pattern, utterance):
					self.check(name, True, f"{utterance!r} after {time.monotonic() - started:.2f} s")
					return utterance
			time.sleep(0.05)
		self.check(name, False, f"heard {self.since_mark()!r}")
		return None

	def hear(self, pattern, name, timeout=20):
		started = time.monotonic()
		while time.monotonic() - started < timeout:
			for utterance in self.since_mark():
				if re.search(pattern, utterance):
					self.check(name, True, repr(utterance))
					return utterance
			time.sleep(0.1)
		self.check(name, False, f"heard {self.since_mark()!r}")
		return None

	def end_stream(self, how="end"):
		self.control.write_text(how, encoding="utf-8")

	def wait_for_nvda(self, timeout=90):
		started = time.monotonic()
		while time.monotonic() - started < timeout:
			if "NVDA initialized" in self.log.text():
				time.sleep(3)
				return self.check("NVDA started", True, f"{time.monotonic() - started:.1f} s")
			time.sleep(0.5)
		return self.check("NVDA started", False)

	def finish(self):
		errors = self.log.errors()
		self.check("no errors in NVDA's log", not errors, "\n".join(errors)[:4000])
		lines = [
			f"{status}  {name}" + (f"  - {detail}" if detail else "") for status, name, detail in self.results
		]
		lines += ["", "--- transcript ---"] + self.log.speech()
		(self.out / "results.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
		return 0 if all(status == "PASS" for status, _, _ in self.results) else 1


# What the add-on says in the scenarios, from its translations (addon/locale).
SAYS = {
	"en": {
		"on": "TikTok Live Reader On",
		"off": "TikTok Live Reader Off",
		"connected": "Connected to user: host",
		"of": "of",
		"events": "Events",
		"comments": "Comments",
		"viewers": "37 viewers",
	},
	"bg": {
		"on": "TikTok Live Reader е включен",
		"off": "TikTok Live Reader е изключен",
		"connected": "Свързан с потребител: host",
		"of": "от",
		"events": "Събития",
		"comments": "Коментари",
		"viewers": "37 зрители",
	},
}


def scenario_smoke(run, language="en"):
	"""The add-on loads, connects to the replay, navigates, reports, switches off."""
	says = SAYS[language]
	if not run.wait_for_nvda():
		return
	run.press_and_hear("nvda+control+shift+t", f"^{says['on']}$", "switching on")
	run.hear(f"^{says['connected']}$", "connected")
	time.sleep(4)
	run.press_and_hear(
		"control+shift+down", rf"^Alice: hello  \d\d:\d\d:\d\d \(1 {says['of']} \d+\)$", "first comment"
	)
	run.press_and_hear("control+shift+end", rf"\((\d+) {says['of']} \1\)$", "last comment")
	run.press_and_hear("control+shift+right", f"^{says['events']}$", "next file")
	run.press_and_hear("control+shift+left", f"^{says['comments']}$", "previous file")
	run.press_and_hear("nvda+control+shift+v", f"^{says['viewers']}$", "viewer count")

	run.mark = len(run.log.speech())
	started = time.monotonic()
	press("nvda+control+shift+t")
	run.hear(f"^{says['off']}$", "switching off", timeout=8)
	run.press_and_hear("nvda+t", r".", "NVDA answers right after switching off", timeout=10)
	run.results[-1] = run.results[-1][:2] + (
		run.results[-1][2] + f"; {time.monotonic() - started:.2f} s after the off key",
	)
	run.end_stream()


KEYEVENTF_UNICODE = 0x0004


def type_text(text):
	"""Type characters as themselves, whatever the keyboard layout (the sandbox
	takes the host's, here Bulgarian)."""
	for character in text:
		for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
			event = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, ord(character), flags, 0, 0))
			user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
			time.sleep(0.03)


def open_dialog(run, name):
	"""Open the settings dialog, with the focus on the user name. Windows can keep
	the first dialog of portable NVDA (no UIAccess) behind the focused window until
	it is raised again and a key is pressed (F35)."""
	if run.press_and_hear("nvda+control+shift+l", r"^User name edit", name, timeout=4):
		return True
	run.results.pop()
	press("nvda+control+shift+l")
	time.sleep(1)
	press("tab")
	time.sleep(1)
	return run.press_and_hear("shift+tab", r"^User name edit", f"{name} (raised, F35)")


def settings_file(run):
	# The agent keeps the run's NVDA configuration beside its text files folder.
	try:
		return (run.texts.parent / "config" / "tiktokLiveReader.ini").read_text(encoding="utf-8")
	except OSError:
		return ""


def wait_for_file(run, name, condition, timeout=10):
	started = time.monotonic()
	while time.monotonic() - started < timeout:
		text = settings_file(run)
		if condition(text):
			return run.check(name, True)
		time.sleep(0.2)
	return run.check(name, False, settings_file(run))


def tab_to(run, pattern, name, limit=14):
	"""Press Tab until the focus is on a control whose name matches."""
	for _attempt in range(limit):
		run.mark = len(run.log.speech())
		press("tab")
		started = time.monotonic()
		while time.monotonic() - started < 2:
			if any(re.search(pattern, utterance) for utterance in run.since_mark()):
				return run.check(name, True, repr(run.since_mark()[-1]))
			time.sleep(0.05)
	return run.check(name, False, f"heard {run.since_mark()!r}")


def scenario_settings(run):
	"""The settings dialog: its controls, OK saves, Cancel does not, a bad user name
	is refused, learning the sounds speaks, a new user name reconnects."""
	if not run.wait_for_nvda():
		return
	open_dialog(run, "dialog opens")
	tab_to(run, r"Text files destination", "destination field", limit=1)
	tab_to(run, r"Browse", "browse button", limit=1)
	tab_to(run, r"Clear text files on startup.*\bchecked", "clear on start checked", limit=1)
	tab_to(run, r"Clean user names.*\bchecked", "clean user names checked", limit=1)
	tab_to(run, r"Archive each live session.*not checked", "archive not checked", limit=1)
	run.press_and_hear("space", r"^checked$", "archive checked")
	tab_to(run, r"Connection retry count", "retry count", limit=1)
	press("enter")
	wait_for_file(run, "OK saves", lambda text: "backup_sessions = true" in text)

	saved = settings_file(run)
	open_dialog(run, "dialog opens again")
	run.press_and_hear("control+tab", r"^Comments check box", "events page")
	tab_to(run, r"Followers.*\bchecked", "followers on the events page", limit=1)
	run.press_and_hear("space", r"not checked", "followers unchecked")
	press("escape")
	time.sleep(1.5)
	unchanged = settings_file(run) == saved
	run.check("Cancel does not save", unchanged, "" if unchanged else settings_file(run))

	open_dialog(run, "dialog for a bad user name")
	time.sleep(0.5)
	press("control+a")
	type_text("a")
	run.press_and_hear("enter", r"^Please enter a valid username$", "bad user name refused")
	press("escape")
	time.sleep(1.5)

	open_dialog(run, "dialog for the sounds")
	run.press_and_hear("control+tab", r"^Comments check box", "events page again")
	run.press_and_hear("control+tab", r"^Auto speak selected events check box", "auto speak page")
	run.press_and_hear(
		"control+tab", r"^Play sounds for the selected events check box\s+not checked", "sounds page"
	)
	run.press_and_hear("space", r"^checked$", "play sounds checked")
	tab_to(run, r"^Learn sounds button", "learn sounds button")
	run.mark = len(run.log.speech())
	press("space")
	run.hear(r"^Comment$", "learning speaks the first sound's name", timeout=8)
	started = time.monotonic()
	run.hear(r"^Follower$", "learning goes on to the next", timeout=8)
	# The next name follows when the sound has played (about 2.5 s); the add-on
	# gives up on a sound after 5 s.
	gap = time.monotonic() - started
	run.check("the first sound played to its end", gap < 4.5, f"{gap:.1f} s from one name to the next")
	press("space")
	time.sleep(1)
	press("escape")
	time.sleep(1.5)
	discarded = "play_sounds = false" in settings_file(run)
	run.check("Cancel discards play sounds", discarded, "" if discarded else settings_file(run))

	run.press_and_hear("nvda+control+shift+t", r"^TikTok Live Reader On$", "switching on")
	run.hear(r"^Connected to user: host$", "connected")
	time.sleep(2)
	open_dialog(run, "dialog while connected")
	time.sleep(0.5)
	press("control+a")
	type_text("host2")
	run.mark = len(run.log.speech())
	press("enter")
	run.hear(r"^Connected to user: host2$", "a new user name reconnects", timeout=25)
	backups = run.texts / "Backups"
	archived = [folder.name for folder in backups.iterdir()] if backups.is_dir() else []
	run.check("the old session is archived", any(name.endswith(" host") for name in archived), repr(archived))
	wait_for_file(run, "the new user name is saved", lambda text: "username = host2" in text)
	run.press_and_hear("nvda+control+shift+t", r"^TikTok Live Reader Off$", "switching off")
	run.end_stream()


# The probe's imports made only when used resolve its names through sys.modules,
# which hold the add-on's copies while a live runs (docs/dev/testing.md).
LAZY = ("pydantic", "httpx")


def probe(run, when, live=False):
	"""What the conflict probe add-on (sandbox/probe) says: owners of the shared
	names, then whether its own code and NVDA's still work."""
	said = run.press_and_hear("nvda+control+alt+shift+k", r"^probe: ", f"probe answers {when}")
	if said:
		checks = said.partition("; checks: ")[2].split(", ")
		failed = [
			item for item in checks if not item.endswith(" ok") and not (live and item.split()[0] in LAZY)
		]
		run.check(f"the other add-on and NVDA work {when}", not failed, said)
	return said


def owners(said):
	return (said or "").partition(";")[0]


def probe_until_restored(run, when, before, timeout=6):
	"""Ask the probe until the owners are those from before the live: the
	connection thread gives the modules back when it has closed."""
	started = time.monotonic()
	while True:
		run.mark = len(run.log.speech())
		press("nvda+control+alt+shift+k")
		said = run.hear(r"^probe: ", f"probe answers {when}", timeout=5)
		if not said or owners(said) == owners(before) or time.monotonic() - started > timeout:
			break
		run.results.pop()
		time.sleep(0.5)
	run.check(
		f"the same owners as before, {when}",
		owners(said) == owners(before),
		f"{time.monotonic() - started:.1f} s; {said!r}",
	)
	failed = [
		item for item in (said or "").partition("; checks: ")[2].split(", ") if not item.endswith(" ok")
	]
	run.check(f"the other add-on and NVDA work {when}", bool(said) and not failed, said)


def scenario_conflicts(run):
	"""The add-on next to another add-on with its own pydantic, httpx, websockets
	and anyio, and NVDA's own certifi, idna, typing_extensions and attr: NVDA and
	what the other add-on holds keep working during a live, and everything is
	back after it, twice."""
	if not run.wait_for_nvda():
		return
	before = probe(run, "before the live")
	for live in ("first", "second"):
		run.press_and_hear("nvda+control+shift+t", r"^TikTok Live Reader On$", f"switching on, {live} live")
		run.hear(r"^Connected to user: host$", f"connected, {live} live")
		time.sleep(4)
		run.press_and_hear("control+shift+home", r"^Alice: hello  ", f"first comment, {live} live")
		probe(run, f"during the {live} live", live=True)
		run.press_and_hear("nvda+control+shift+t", r"^TikTok Live Reader Off$", f"switching off, {live} live")
		probe_until_restored(run, f"after the {live} live", before)
	run.end_stream()


def answer_delay(run, combo, pattern, timeout=10):
	"""Seconds until something said after pressing ``combo`` matches, or None."""
	run.mark = len(run.log.speech())
	started = time.monotonic()
	press(combo)
	while time.monotonic() - started < timeout:
		if any(re.search(pattern, utterance) for utterance in run.since_mark()):
			return time.monotonic() - started
		time.sleep(0.02)
	return None


def nvda_memory_mb():
	result = subprocess.run(
		["tasklist", "/FI", "IMAGENAME eq nvda.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True
	)
	sizes = [int(re.sub(r"\D", "", row.rsplit(",", 1)[-1]) or 0) for row in result.stdout.splitlines()]
	return max(sizes, default=0) // 1024


def replay_seconds():
	path = os.environ.get("TIKTOK_REPLAY")
	pace = float(os.environ.get("TIKTOK_REPLAY_PACE", "1"))
	rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()] if path else []
	times = [row["t"] for row in rows if "method" in row]
	return (times[-1] - times[0]) * pace if times else 0


def scenario_stress(run):
	"""A busy real live replayed fast with every event written, spoken and
	sounded: NVDA keeps answering, the add-on navigates and switches off at once,
	speech stops with it, nothing in the log."""
	if not run.wait_for_nvda():
		return
	memory = nvda_memory_mb()
	run.press_and_hear("nvda+control+shift+t", r"^TikTok Live Reader On$", "switching on")
	run.hear(r"^Connected to user: host$", "connected")
	length = replay_seconds()
	started = time.monotonic()
	delays = []
	while time.monotonic() - started < length:
		time.sleep(4)
		delays.append(answer_delay(run, "nvda+t", r"Program Manager"))
	answered = [delay for delay in delays if delay is not None]
	run.check(
		"NVDA answers during the live",
		bool(delays) and len(answered) == len(delays) and max(answered) < 1,
		f"{len(answered)} of {len(delays)} in {length:.0f} s, slowest {max(answered, default=0):.2f} s, "
		f"median {sorted(answered)[len(answered) // 2] if answered else 0:.2f} s",
	)
	delay = answer_delay(run, "control+shift+end", r"\((\d+) of \1\)$")
	run.check("the last comment during the live", delay is not None and delay < 1, f"{delay}")
	run.mark = len(run.log.speech())
	switched = time.monotonic()
	press("nvda+control+shift+t")
	run.hear(r"^TikTok Live Reader Off$", "switching off", timeout=8)
	delay = answer_delay(run, "nvda+t", r"Program Manager")
	run.check("NVDA answers right after switching off", delay is not None and delay < 1, f"{delay}")
	time.sleep(1)
	quiet_from = len(run.log.speech())
	time.sleep(4)
	late = run.log.speech()[quiet_from:]
	run.check(
		"speech stops with the add-on",
		not late,
		f"{time.monotonic() - switched:.1f} s after the key: {late[:5]!r}",
	)
	files = {
		path.name: len(path.read_text(encoding="utf-8").splitlines())
		for path in sorted(run.texts.glob("*.txt"))
	}
	run.check("text files", bool(files), repr(files))
	run.check("NVDA's memory", True, f"{memory} MB before, {nvda_memory_mb()} MB after")
	run.end_stream()


SCENARIOS = {
	"smoke": scenario_smoke,
	"smoke-bg": lambda run: scenario_smoke(run, "bg"),
	"settings": scenario_settings,
	"conflicts": scenario_conflicts,
	"conflicts-store": scenario_conflicts,
	"stress": scenario_stress,
}


def main():
	scenario, log, out, texts, control = sys.argv[1:6]
	run = Run(log, out, texts, control)
	try:
		SCENARIOS[scenario](run)
	except Exception as error:
		run.check("scenario ran to the end", False, repr(error))
	finally:
		run.end_stream()
	sys.exit(run.finish())


if __name__ == "__main__":
	main()
