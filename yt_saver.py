"""
YT Saver - a small, local, no-ads video/audio downloader.

Everything runs on your own computer. No accounts, no telemetry, no browser
extensions. It is a thin window around yt-dlp (open source, github.com/yt-dlp)
plus bundled ffmpeg (for merging/converting) and deno (which YouTube now needs).
"""

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "YT Saver"
FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

if os.name == "nt":
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "YTSaver"
else:
    DATA_DIR = Path.home() / ".ytsaver"
LIB_DIR = DATA_DIR / "lib"            # newer yt-dlp downloaded by "Update downloader"
SETTINGS_FILE = DATA_DIR / "settings.json"
DEFAULT_DIR = str(Path.home() / "Downloads")

# A newer yt-dlp from "Update downloader" takes priority over the bundled one.
if (LIB_DIR / "yt_dlp").is_dir():
    sys.path.insert(0, str(LIB_DIR))

# ---------- output choices ----------

VIDEO_FORMATS = {
    "MP4  (plays everywhere)": "mp4",
    "MKV  (any codec, best quality)": "mkv",
    "WEBM": "webm",
}
AUDIO_FORMATS = {
    "MP3": "mp3",
    "M4A  (AAC)": "m4a",
    "Opus": "opus",
    "FLAC  (lossless)": "flac",
    "WAV  (uncompressed)": "wav",
}
RESOLUTIONS = ["Best available", "2160p (4K)", "1440p", "1080p", "720p", "480p", "360p"]
BITRATES = ["Best", "320 kbps", "256 kbps", "192 kbps", "128 kbps"]


# ---------- helper tools ----------

def _find_bundled(name):
    exe = name + (".exe" if os.name == "nt" else "")
    for folder in (BUNDLE_DIR / "bin", BUNDLE_DIR):
        p = folder / exe
        if p.is_file():
            return p
    return None


def find_ffmpeg():
    p = _find_bundled("ffmpeg")
    if p:
        return str(p)
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ensure_deno_on_path():
    """YouTube requires a JavaScript runtime; yt-dlp looks for deno on PATH."""
    p = _find_bundled("deno")
    if p:
        os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")
        return True
    if shutil.which("deno"):
        return True
    scripts = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    for c in (scripts / "deno.exe", scripts / "deno"):
        if c.is_file():
            os.environ["PATH"] = str(c.parent) + os.pathsep + os.environ.get("PATH", "")
            return True
    return False


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def download_latest_wheel(package, dest_dir, log):
    """Fetch the newest wheel of a pure-Python package from PyPI and unpack it."""
    ctx = _ssl_context()
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", context=ctx, timeout=30) as r:
        meta = json.load(r)
    version = meta["info"]["version"]
    wheel = next(u for u in meta["urls"]
                 if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("none-any.whl"))
    log(f"Downloading {package} {version}...")
    tmp = dest_dir.parent / (wheel["filename"] + ".part")
    with urllib.request.urlopen(wheel["url"], context=ctx, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(dest_dir)
    tmp.unlink(missing_ok=True)
    return version


# ---------- the app ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("660x470")
        self.minsize(560, 420)

        s = load_settings()
        self.url = tk.StringVar()
        self.kind = tk.StringVar(value=s.get("kind", "video"))
        self.vformat = tk.StringVar(value=s.get("vformat", next(iter(VIDEO_FORMATS))))
        self.aformat = tk.StringVar(value=s.get("aformat", next(iter(AUDIO_FORMATS))))
        self.resolution = tk.StringVar(value=s.get("resolution", RESOLUTIONS[0]))
        self.bitrate = tk.StringVar(value=s.get("bitrate", BITRATES[0]))
        self.folder = tk.StringVar(value=s.get("folder", DEFAULT_DIR))
        self.playlist = tk.BooleanVar(value=False)
        self.busy = False

        self._build_ui()
        self._kind_changed()

        self.ffmpeg = find_ffmpeg()
        self.has_js = ensure_deno_on_path()
        try:
            import yt_dlp
            self.log(f"Ready. Downloader version {yt_dlp.version.__version__}.")
        except Exception as e:
            self.log(f"Could not load yt-dlp: {e}")
        if not self.ffmpeg:
            self.log("Warning: ffmpeg not found - merging and converting won't work.")
        if not self.has_js:
            self.log("Warning: deno not found - some YouTube videos may fail.")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- layout -----
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=8, pady=8)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Video link:").grid(row=0, column=0, sticky="w", **pad)
        entry = ttk.Entry(frm, textvariable=self.url)
        entry.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        entry.focus()
        ttk.Button(frm, text="Paste", command=self._paste).grid(row=0, column=3, **pad)

        ttk.Label(frm, text="Download:").grid(row=1, column=0, sticky="w", **pad)
        kinds = ttk.Frame(frm)
        kinds.grid(row=1, column=1, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(kinds, text="Video", variable=self.kind, value="video",
                        command=self._kind_changed).pack(side="left", padx=(0, 15))
        ttk.Radiobutton(kinds, text="Audio only", variable=self.kind, value="audio",
                        command=self._kind_changed).pack(side="left")

        ttk.Label(frm, text="File type:").grid(row=2, column=0, sticky="w", **pad)
        self.fmt_box = ttk.Combobox(frm, state="readonly", width=30)
        self.fmt_box.grid(row=2, column=1, sticky="w", **pad)
        self.fmt_box.bind("<<ComboboxSelected>>", lambda e: self._fmt_changed())

        self.q_label = ttk.Label(frm, text="Resolution:")
        self.q_label.grid(row=3, column=0, sticky="w", **pad)
        self.q_box = ttk.Combobox(frm, state="readonly", width=30)
        self.q_box.grid(row=3, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Whole playlist", variable=self.playlist).grid(
            row=3, column=2, columnspan=2, sticky="w", **pad)

        self.hint = ttk.Label(frm, text="", foreground="gray")
        self.hint.grid(row=4, column=1, columnspan=3, sticky="w", padx=10)

        ttk.Label(frm, text="Save to:").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.folder).grid(row=5, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(frm, text="Browse", command=self._browse).grid(row=5, column=3, **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=4, sticky="ew", **pad)
        self.dl_btn = ttk.Button(btns, text="Download", command=self.start_download)
        self.dl_btn.pack(side="left")
        ttk.Button(btns, text="Open folder", command=self._open_folder).pack(side="left", padx=8)
        self.up_btn = ttk.Button(btns, text="Update downloader", command=self.update_ytdlp)
        self.up_btn.pack(side="right")

        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.progress.grid(row=7, column=0, columnspan=4, sticky="ew", **pad)
        self.status = ttk.Label(frm, text="Ready.")
        self.status.grid(row=8, column=0, columnspan=4, sticky="w", padx=10)

        self.log_box = tk.Text(frm, height=7, wrap="word", state="disabled")
        self.log_box.grid(row=9, column=0, columnspan=4, sticky="nsew", **pad)
        frm.rowconfigure(9, weight=1)

        self.bind("<Return>", lambda e: self.start_download())

    def _kind_changed(self):
        if self.kind.get() == "video":
            self.fmt_box.configure(values=list(VIDEO_FORMATS), textvariable=self.vformat)
            if self.vformat.get() not in VIDEO_FORMATS:
                self.vformat.set(next(iter(VIDEO_FORMATS)))
            self.q_label.configure(text="Resolution:")
            self.q_box.configure(values=RESOLUTIONS, textvariable=self.resolution)
        else:
            self.fmt_box.configure(values=list(AUDIO_FORMATS), textvariable=self.aformat)
            if self.aformat.get() not in AUDIO_FORMATS:
                self.aformat.set(next(iter(AUDIO_FORMATS)))
            self.q_label.configure(text="Audio quality:")
            self.q_box.configure(values=BITRATES, textvariable=self.bitrate)
        self._fmt_changed()

    def _fmt_changed(self):
        hint = ""
        state = "readonly"
        if self.kind.get() == "video":
            ext = VIDEO_FORMATS.get(self.vformat.get())
            if ext == "mp4":
                hint = "MP4 above 1080p may use AV1/VP9, which some older players can't open - MKV is safer for 4K."
            elif ext == "webm":
                hint = "WEBM plays in browsers and VLC; not in the built-in Windows player on every PC."
        else:
            ext = AUDIO_FORMATS.get(self.aformat.get())
            if ext in ("flac", "wav"):
                state = "disabled"
                hint = "Lossless output - no bitrate to choose. (YouTube's source audio is lossy, so files are just bigger.)"
            elif ext in ("m4a", "opus"):
                hint = "\"Best\" keeps YouTube's original audio with no re-encoding."
        self.q_box.configure(state=state)
        self.hint.configure(text=hint)

    # ----- small UI helpers -----
    def _paste(self):
        try:
            self.url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or DEFAULT_DIR)
        if d:
            self.folder.set(d)

    def _open_folder(self):
        path = self.folder.get()
        if not os.path.isdir(path):
            return
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _on_close(self):
        save_settings({
            "kind": self.kind.get(), "vformat": self.vformat.get(), "aformat": self.aformat.get(),
            "resolution": self.resolution.get(), "bitrate": self.bitrate.get(),
            "folder": self.folder.get(),
        })
        self.destroy()

    def log(self, msg):
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _do)

    def set_status(self, msg, pct=None):
        def _do():
            self.status.configure(text=msg)
            if pct is not None:
                self.progress["value"] = pct
        self.after(0, _do)

    def set_busy(self, busy):
        self.busy = busy
        st = "disabled" if busy else "normal"
        self.after(0, lambda: (self.dl_btn.configure(state=st), self.up_btn.configure(state=st)))

    # ----- download -----
    def _build_opts(self):
        folder = self.folder.get() or DEFAULT_DIR
        os.makedirs(folder, exist_ok=True)
        opts = {
            "outtmpl": os.path.join(folder, "%(title)s [%(id)s].%(ext)s"),
            "noplaylist": not self.playlist.get(),
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._pp_hook],
            "logger": _Logger(self),
            "windowsfilenames": True,
            "noprogress": True,
        }
        if self.ffmpeg:
            opts["ffmpeg_location"] = self.ffmpeg

        if self.kind.get() == "audio":
            ext = AUDIO_FORMATS[self.aformat.get()]
            br = self.bitrate.get()
            # Grab the source that needs the least conversion
            opts["format"] = {
                "m4a": "ba[ext=m4a]/ba/b",
                "opus": "ba[acodec=opus]/ba/b",
            }.get(ext, "ba/b")
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": ext}
            if ext not in ("flac", "wav"):
                pp["preferredquality"] = "0" if br == "Best" else br.split()[0]
            opts["postprocessors"] = [pp, {"key": "FFmpegMetadata"}]
        else:
            ext = VIDEO_FORMATS[self.vformat.get()]
            res = self.resolution.get()
            h = "" if res.startswith("Best") else f"[height<={res.split('p')[0]}]"
            if ext == "mp4":
                # Prefer H.264 + AAC so it plays everywhere; fall back to anything.
                opts["format"] = (f"bv*{h}[vcodec^=avc1]+ba[ext=m4a]/"
                                  f"bv*{h}+ba[ext=m4a]/bv*{h}+ba/b{h}/b")
                opts["merge_output_format"] = "mp4"
            elif ext == "webm":
                opts["format"] = f"bv*{h}[ext=webm]+ba[ext=webm]/bv*{h}+ba/b{h}/b"
                opts["merge_output_format"] = "webm/mkv"
            else:
                opts["format"] = f"bv*{h}+ba/b{h}/b"
                opts["merge_output_format"] = "mkv"
            # Single-file (no merge) downloads still end up in the chosen container
            opts["postprocessors"] = [
                {"key": "FFmpegVideoRemuxer", "preferedformat": opts["merge_output_format"]},
                {"key": "FFmpegMetadata"},
            ]
        return opts

    def start_download(self):
        if self.busy:
            return
        url = self.url.get().strip()
        if not re.match(r"^https?://", url):
            messagebox.showwarning(APP_NAME, "Paste a full video link (starting with https://).")
            return
        if not self.ffmpeg:
            messagebox.showwarning(APP_NAME, "ffmpeg is missing, so the file can't be converted.")
            return
        self.set_busy(True)
        self.progress["value"] = 0
        self.log(f"Starting: {url}")
        threading.Thread(target=self._download, args=(url,), daemon=True).start()

    def _download(self, url):
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(self._build_opts()) as ydl:
                ydl.download([url])
            self.set_status("Done.", 100)
            self.log("Finished.")
        except Exception as e:
            msg = str(e).replace("ERROR: ", "")
            self.set_status("Failed - see log.")
            self.log("Error: " + msg)
            self.log("Tip: click 'Update downloader' - YouTube changes often and updates usually fix this.")
        finally:
            self.set_busy(False)

    def _hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            pct = (done / total * 100) if total else None
            speed, eta = d.get("speed"), d.get("eta")
            parts = []
            if pct is not None:
                parts.append(f"{pct:.0f}%")
            if total:
                parts.append(f"of {total / 1048576:.1f} MB")
            if speed:
                parts.append(f"at {speed / 1048576:.1f} MB/s")
            if eta:
                parts.append(f"{int(eta)}s left")
            self.set_status("Downloading " + " ".join(parts), pct)
        elif d["status"] == "finished":
            self.set_status("Processing...", 100)

    def _pp_hook(self, d):
        if d["status"] == "started":
            self.set_status(f"Converting ({d.get('postprocessor', '')})...")
        elif d["status"] == "finished" and d.get("postprocessor") == "FFmpegMetadata":
            path = d.get("info_dict", {}).get("filepath")
            if path:
                self.log("Saved: " + os.path.basename(path))

    # ----- update -----
    def update_ytdlp(self):
        if self.busy:
            return
        self.set_busy(True)
        self.log("Checking for a newer downloader...")

        def run():
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                staging = DATA_DIR / "lib_new"
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir()
                v = download_latest_wheel("yt-dlp", staging, self.log)
                try:
                    download_latest_wheel("yt-dlp-ejs", staging, self.log)
                except Exception:
                    pass  # optional helper; bundled copy is used if this fails
                shutil.rmtree(LIB_DIR, ignore_errors=True)
                staging.rename(LIB_DIR)
                self.log(f"Updated to yt-dlp {v}. Close and reopen YT Saver to use it.")
            except Exception as e:
                self.log(f"Update failed: {e}")
            finally:
                self.set_busy(False)

        threading.Thread(target=run, daemon=True).start()


class _Logger:
    """Sends yt-dlp messages to the log box, skipping the noisy ones."""
    def __init__(self, app):
        self.app = app

    def debug(self, msg):
        if msg.startswith("[download] Destination"):
            self.app.log(msg.replace("[download] Destination: ", "Downloading: "))

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        self.app.log("Note: " + msg)

    def error(self, msg):
        pass  # surfaced via the exception handler


if __name__ == "__main__":
    App().mainloop()
