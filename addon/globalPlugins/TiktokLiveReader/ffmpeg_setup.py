"""FFmpeg for recording lives: downloaded when first needed and kept in NVDA's
configuration folder, so add-on updates keep it. A versioned release on GitHub,
checked against its SHA-256 before anything is unpacked (docs/dev/plan.md)."""

import hashlib
import shutil
import urllib.request
import zipfile

from . import settings

URL = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"
SIZE = 114_768_076
SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
# The archive's members kept, by their names in the FFmpeg folder.
MEMBERS = {
	"ffmpeg.exe": "ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe",
	"LICENSE.txt": "ffmpeg-9.0.2-essentials_build/LICENSE",
}
CHUNK = 256 * 1024


class Cancelled(Exception):
	pass


def folder():
	return settings.CONFIG_DIR / "tiktokLiveReader-ffmpeg"


def executable():
	"""FFmpeg's path when it is installed, else None."""
	path = folder() / "ffmpeg.exe"
	return path if path.is_file() else None


def size_mb():
	"""The download's size in megabytes, for the question asking to install it."""
	return round(SIZE / (1024 * 1024))


def install(progress=None, cancelled=lambda: False):
	"""Download, check and unpack FFmpeg; returns its path. ``progress(done, total)``
	gets the bytes downloaded; ``cancelled()`` returning True stops the download
	(Cancelled). Raises OSError or ValueError on failure, leaving nothing behind."""
	target = folder()
	work = target.with_name(target.name + ".download")
	shutil.rmtree(work, ignore_errors=True)
	work.mkdir(parents=True)
	try:
		archive = work / "ffmpeg.zip"
		digest = hashlib.sha256()
		done = 0
		request = urllib.request.Request(URL, headers={"User-Agent": "TikTok Live Reader"})
		with urllib.request.urlopen(request, timeout=30) as response, open(archive, "wb") as out:
			total = int(response.headers.get("Content-Length") or SIZE)
			while True:
				if cancelled():
					raise Cancelled()
				chunk = response.read(CHUNK)
				if not chunk:
					break
				out.write(chunk)
				digest.update(chunk)
				done += len(chunk)
				if progress:
					progress(done, total)
		if digest.hexdigest() != SHA256:
			raise ValueError("the download is not the expected FFmpeg (SHA-256 differs)")
		unpacked = work / "unpacked"
		unpacked.mkdir()
		with zipfile.ZipFile(archive) as zipped:
			for name, member in MEMBERS.items():
				with zipped.open(member) as source, open(unpacked / name, "wb") as copy:
					shutil.copyfileobj(source, copy)
		shutil.rmtree(target, ignore_errors=True)
		unpacked.rename(target)
	finally:
		shutil.rmtree(work, ignore_errors=True)
	return target / "ffmpeg.exe"
