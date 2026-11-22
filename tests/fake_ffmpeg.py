"""Stands in for FFmpeg in the recorder tests: the output path is the last
argument; an input address containing "fail" ends it at once with an error, one
containing "cut" ends by itself soon after starting (the stream was cut), and
otherwise it writes "recording" to the output, waits for "q" on its input and
writes "done". With FAKE_FFMPEG_DEAF set it ignores "q". With "-f concat" it
joins the listed files' text into the output (with FAKE_FFMPEG_JOIN_FAILS set it
fails instead)."""

import os
import sys
import time

source = sys.argv[sys.argv.index("-i") + 1]
output = sys.argv[-1]
if "concat" in sys.argv:
	if os.environ.get("FAKE_FFMPEG_JOIN_FAILS"):
		sys.stderr.write("Invalid data found when processing input\n")
		sys.exit(1)
	with open(source, encoding="utf-8") as listing:
		files = [line.strip()[len("file '") : -1].replace("'\\''", "'") for line in listing if line.strip()]
	with open(output, "w", encoding="utf-8") as out:
		for name in files:
			with open(name, encoding="utf-8") as part:
				out.write(part.read())
	sys.exit(0)
if "fail" in source:
	sys.stderr.write("Server returned 404 Not Found\n")
	sys.exit(1)
with open(output, "w", encoding="utf-8") as out:
	out.write("recording\n")
	out.write(" ".join(sys.argv[1:]) + "\n")
if "cut" in source:
	time.sleep(0.5)
	sys.stderr.write("Error during demuxing: I/O error\n")
	with open(output, "a", encoding="utf-8") as out:
		out.write("cut\n")
	sys.exit(0)
if os.environ.get("FAKE_FFMPEG_DEAF"):
	time.sleep(60)
sys.stdin.read(1)
with open(output, "a", encoding="utf-8") as out:
	out.write("done\n")
