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
import re
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
	"nvda": 0x2D, "insert": 0x2D, "control": 0x11, "shift": 0x10, "alt": 0x12,
	"home": 0x24, "end": 0x23, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
	"tab": 0x09, "enter": 0x0D, "escape": 0x1B, "space": 0x20,
}


class KEYBDINPUT(ctypes.Structure):
	_fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
	class _U(ctypes.Union):
		_fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

	_anonymous_ = ("u",)
	_fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(name, up):
	vk = VK.get(name) or ord(name.upper())
	flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if name in EXTENDED or name == "nvda" else 0)
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
		return ["\n".join(item) for item in lines]


class Run:
	def __init__(self, log, out, texts, control):
		self.log, self.out, self.texts, self.control = NvdaLog(log), Path(out), Path(texts), Path(control)
		self.results = []
		self.mark = 0

	def check(self, name, ok, detail=""):
		self.results.append(("PASS" if ok else "FAIL", name, detail))
		return ok

	def since_mark(self):
		return self.log.speech()[self.mark:]

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
		lines = [f"{status}  {name}" + (f"  - {detail}" if detail else "") for status, name, detail in self.results]
		lines += ["", "--- transcript ---"] + self.log.speech()
		(self.out / "results.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
		return 0 if all(status == "PASS" for status, _, _ in self.results) else 1


def scenario_smoke(run):
	"""The add-on loads, connects to the replay, navigates, reports, switches off."""
	if not run.wait_for_nvda():
		return
	run.press_and_hear("nvda+control+shift+t", r"^TikTok Live Reader On$", "switching on")
	run.hear(r"^Connected to user: host$", "connected")
	time.sleep(4)
	run.press_and_hear("control+shift+down", r"^Alice: hello  \d\d:\d\d:\d\d \(1 of \d+\)$", "first comment")
	run.press_and_hear("control+shift+end", r"\((\d+) of \1\)$", "last comment")
	run.press_and_hear("control+shift+right", r"^Events$", "next file")
	run.press_and_hear("control+shift+left", r"^Comments$", "previous file")
	run.press_and_hear("nvda+control+shift+v", r"^37 viewers$", "viewer count")

	run.mark = len(run.log.speech())
	started = time.monotonic()
	press("nvda+control+shift+t")
	run.hear(r"^TikTok Live Reader Off$", "switching off", timeout=8)
	run.press_and_hear("nvda+t", r".", "NVDA answers right after switching off", timeout=10)
	run.results[-1] = run.results[-1][:2] + (run.results[-1][2] + f"; {time.monotonic() - started:.2f} s after the off key",)
	run.end_stream()


SCENARIOS = {"smoke": scenario_smoke}


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
