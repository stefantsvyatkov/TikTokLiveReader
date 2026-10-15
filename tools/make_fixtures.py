"""Write the synthetic recordings the sandbox scenarios replay.

    python tools/make_fixtures.py

Real-format messages from tests/feed.py, written in the recorder's format to
artifacts/sandbox/fixtures/.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests import feed as f  # noqa: E402

FIXTURES = REPO / "artifacts" / "sandbox" / "fixtures"


def smoke():
	alice, bob = f.user("Alice"), f.user("Bob")
	return [
		f.viewers(37),
		0.5,
		f.comment(alice, "hello"),
		0.5,
		f.comment(bob, "hi there"),
		0.5,
		f.join(alice),
		f.join(bob),
		0.5,
		f.gift(alice, "Rose", 1, 3, repeat_end=1),
		0.5,
		f.like(bob, 5, 120),
		0.5,
		f.follow(bob),
		0.5,
		f.share(alice),
	]


def stream():
	"""stream.flv: ten minutes of a test picture and tone, which the sandbox's
	recording scenario serves in real time as the live's stream (FFmpeg from
	artifacts/tools/ffmpeg)."""
	path = FIXTURES / "stream.flv"
	ffmpeg = REPO / "artifacts" / "tools" / "ffmpeg" / "ffmpeg.exe"
	if not path.exists():
		subprocess.run(
			[
				str(ffmpeg),
				"-v",
				"error",
				"-y",
				"-f",
				"lavfi",
				"-i",
				"testsrc=size=360x640:rate=15",
				"-f",
				"lavfi",
				"-i",
				"sine=frequency=440:sample_rate=48000",
				"-t",
				"600",
				"-c:v",
				"libx264",
				"-preset",
				"veryfast",
				"-g",
				"30",
				"-c:a",
				"aac",
				"-b:a",
				"64k",
				"-f",
				"flv",
				str(path),
			],
			check=True,
		)
	print(path)


def main():
	FIXTURES.mkdir(parents=True, exist_ok=True)
	for name, build in {"smoke": smoke}.items():
		path = FIXTURES / f"{name}.jsonl"
		f.write_recording(path, *build())
		print(path)
	stream()


if __name__ == "__main__":
	main()
