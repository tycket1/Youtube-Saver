"""Copies the ffmpeg and deno binaries into build_bin/ with plain names so
PyInstaller can pack them into the single .exe."""
import shutil
import sys
from pathlib import Path

out = Path(__file__).parent / "build_bin"
shutil.rmtree(out, ignore_errors=True)
out.mkdir()
ext = ".exe" if sys.platform == "win32" else ""

import imageio_ffmpeg
ff = Path(imageio_ffmpeg.get_ffmpeg_exe())
shutil.copy2(ff, out / f"ffmpeg{ext}")
print("ffmpeg:", ff)

deno_bin = shutil.which("deno")
if not deno_bin:
    scripts = Path(sys.prefix) / ("Scripts" if sys.platform == "win32" else "bin")
    for c in [scripts / f"deno{ext}"] + list(Path(sys.prefix).rglob(f"deno{ext}")):
        if c.is_file():
            deno_bin = str(c)
            break
if not deno_bin:
    sys.exit("Could not find the deno binary after installing it.")
shutil.copy2(deno_bin, out / f"deno{ext}")
print("deno:", deno_bin)
