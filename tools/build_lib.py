"""Build the add-on's lib/ from the pinned wheels of tools/lib-requirements.txt.

    python tools/build_lib.py [out folder]     (default artifacts/lib-build)

Run with a Python that has pip (the system one); the wheels are those for
CPython 3.13 on 64-bit Windows, NVDA 2026.1 and later, whatever Python runs this.
Every version is pinned, so nothing is resolved. Console scripts (bin/) and byte
code are left out; licence texts missing from a wheel (tools/lib-licenses/) are
added to its dist-info folder; lib/secrets.py, a copy of the standard library
module for Python builds without it, is kept from the current lib/.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CURRENT_LIB = REPO / "addon" / "globalPlugins" / "TiktokLiveReader" / "lib"
REQUIREMENTS = REPO / "tools" / "lib-requirements.txt"
LICENSES = REPO / "tools" / "lib-licenses"
KEPT = ("secrets.py",)


def main():
	out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "artifacts" / "lib-build"
	if out.exists():
		shutil.rmtree(out)
	subprocess.run(
		[
			sys.executable,
			"-m",
			"pip",
			"install",
			"--disable-pip-version-check",
			"--target",
			str(out),
			"--platform",
			"win_amd64",
			"--python-version",
			"3.13",
			"--implementation",
			"cp",
			"--abi",
			"cp313",
			"--only-binary=:all:",
			"--no-deps",
			"--no-compile",
			"-r",
			str(REQUIREMENTS),
		],
		check=True,
	)
	shutil.rmtree(out / "bin", ignore_errors=True)
	for cache in list(out.rglob("__pycache__")):
		shutil.rmtree(cache, ignore_errors=True)
	for licence in LICENSES.glob("*.txt"):
		(info,) = out.glob(f"{licence.stem}-*.dist-info")
		target = info / "licenses"
		target.mkdir(exist_ok=True)
		shutil.copy2(licence, target / "LICENSE")
	for name in KEPT:
		shutil.copy2(CURRENT_LIB / name, out / name)
	size = sum(file.stat().st_size for file in out.rglob("*") if file.is_file())
	print(f"{out}: {size / 1e6:.1f} MB")


if __name__ == "__main__":
	main()
