"""Installing FFmpeg (ffmpeg_setup.py), from a download served on this machine."""

import hashlib
import http.server
import io
import shutil
import threading
import unittest
import zipfile

from . import support

setup = support.load("ffmpeg_setup")


def archive(exe=b"MZ fake ffmpeg"):
	data = io.BytesIO()
	with zipfile.ZipFile(data, "w") as zipped:
		for name, member in setup.MEMBERS.items():
			zipped.writestr(member, exe if name == "ffmpeg.exe" else b"license")
		zipped.writestr("ffmpeg-9.0.2-essentials_build/bin/ffplay.exe", b"not kept")
	return data.getvalue()


class _Server:
	def __init__(self, body):
		class Handler(http.server.BaseHTTPRequestHandler):
			def do_GET(handler):
				handler.send_response(200)
				handler.send_header("Content-Length", str(len(body)))
				handler.end_headers()
				handler.wfile.write(body)

			def log_message(handler, *args):
				pass

		self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
		threading.Thread(target=self.server.serve_forever, daemon=True).start()
		self.url = f"http://127.0.0.1:{self.server.server_port}/ffmpeg.zip"

	def close(self):
		self.server.shutdown()
		self.server.server_close()


class Install(unittest.TestCase):
	def setUp(self):
		self.saved = (setup.URL, setup.SIZE, setup.SHA256, setup.CHUNK)
		shutil.rmtree(setup.folder(), ignore_errors=True)

	def tearDown(self):
		setup.URL, setup.SIZE, setup.SHA256, setup.CHUNK = self.saved
		shutil.rmtree(setup.folder(), ignore_errors=True)
		self.server.close()

	def serve(self, body, digest=None):
		self.server = _Server(body)
		setup.URL, setup.SIZE = self.server.url, len(body)
		setup.SHA256 = digest or hashlib.sha256(body).hexdigest()
		setup.CHUNK = 64

	def test_downloaded_checked_and_unpacked_with_progress(self):
		body = archive()
		self.serve(body)
		seen = []
		path = setup.install(progress=lambda done, total: seen.append((done, total)))
		self.assertEqual(path, setup.executable())
		self.assertEqual(path.read_bytes(), b"MZ fake ffmpeg")
		self.assertEqual(sorted(p.name for p in setup.folder().iterdir()), ["LICENSE.txt", "ffmpeg.exe"])
		self.assertEqual(seen[-1], (len(body), len(body)))
		self.assertGreater(len(seen), 1)
		self.assertFalse(setup.folder().with_name(setup.folder().name + ".download").exists())

	def test_a_download_that_is_not_the_expected_file_is_refused(self):
		self.serve(archive(), digest="0" * 64)
		with self.assertRaises(ValueError):
			setup.install()
		self.assertIsNone(setup.executable())

	def test_cancelling_leaves_nothing(self):
		self.serve(archive())
		with self.assertRaises(setup.Cancelled):
			setup.install(cancelled=lambda: True)
		self.assertIsNone(setup.executable())
		self.assertFalse(setup.folder().with_name(setup.folder().name + ".download").exists())

	def test_the_size_asked_about_is_in_megabytes(self):
		self.server = _Server(b"")
		self.assertEqual(setup.size_mb(), round(self.saved[1] / 1048576))


if __name__ == "__main__":
	unittest.main()
