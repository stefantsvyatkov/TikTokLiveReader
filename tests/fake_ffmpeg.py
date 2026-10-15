"""Stands in for FFmpeg in the recorder tests: the output path is the last
argument; an input address containing "fail" ends it at once with an error, and
otherwise it writes "recording" to the output, waits for "q" on its input and
writes "done". With FAKE_FFMPEG_DEAF set it ignores "q"."""

import os
import sys
import time

url = sys.argv[sys.argv.index("-i") + 1]
output = sys.argv[-1]
if "fail" in url:
	sys.stderr.write("Server returned 404 Not Found\n")
	sys.exit(1)
with open(output, "w", encoding="utf-8") as out:
	out.write("recording\n")
	out.write(" ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAKE_FFMPEG_DEAF"):
	time.sleep(60)
sys.stdin.read(1)
with open(output, "a", encoding="utf-8") as out:
	out.write("done\n")
