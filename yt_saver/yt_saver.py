"""
YT Saver - a small, local, no-ads video/audio downloader.

Everything runs on your own computer. No accounts, no telemetry, no browser
extensions. It is a window around yt-dlp (open source, github.com/yt-dlp)
plus bundled ffmpeg (merging/converting) and deno (which YouTube now needs).
"""

import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageDraw

APP_NAME = "YT Saver"
APP_VERSION = "1.2.0"
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

# ---------- look ----------

ACCENT = ("#4f46e5", "#6366f1")
ACCENT_HOVER = ("#4338ca", "#4f46e5")
MUTED = ("#6b7280", "#9ca3af")
CARD = ("#ffffff", "#1f2430")
BG = ("#f3f4f8", "#151821")
BORDER = ("#e5e7eb", "#2b3140")
OK_GREEN = ("#059669", "#34d399")
ERR_RED = ("#dc2626", "#f87171")
FONT = "Segoe UI" if os.name == "nt" else ("SF Pro Text" if sys.platform == "darwin" else "Inter")

# ---------- output choices ----------

VIDEO_FORMATS = {
    "MP4": ("mp4", "Plays everywhere: Windows, phones, editors."),
    "MKV": ("mkv", "Keeps the best quality with any codec. Best pick for 4K."),
    "WEBM": ("webm", "Web format. Plays in browsers and VLC."),
}
AUDIO_FORMATS = {
    "MP3": ("mp3", "Works on every device and car stereo."),
    "M4A": ("m4a", "AAC audio. 'Best' keeps YouTube's original with no re-encoding."),
    "Opus": ("opus", "Smallest files. 'Best' keeps YouTube's original with no re-encoding."),
    "FLAC": ("flac", "Lossless container. Source audio is lossy, so files are just bigger."),
    "WAV": ("wav", "Uncompressed, for audio editors. Large files."),
}
ALL_RESOLUTIONS = [2160, 1440, 1080, 720, 480, 360]
BITRATES = ["Best", "320 kbps", "256 kbps", "192 kbps", "128 kbps"]


def res_label(h):
    return {2160: "2160p  4K", 1440: "1440p  2K"}.get(h, f"{h}p")


# ---------- helper tools ----------

def asset(name):
    for folder in (BUNDLE_DIR / "assets", BUNDLE_DIR):
        if (folder / name).is_file():
            return folder / name
    return None


def _find_bundled(name):
    exe = name + (".exe" if os.name == "nt" else "")
    for folder in (BUNDLE_DIR / "bin", BUNDLE_DIR):
        if (folder / exe).is_file():
            return folder / exe
    return None


def find_ffmpeg():
    p = _find_bundled("ffmpeg")
    if p:
        return str(p)
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ensure_deno_on_path():
    """YouTube requires a JavaScript runtime; yt-dlp looks for deno on PATH."""
    p = _find_bundled("deno")
    if not p and not shutil.which("deno"):
        scripts = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
        p = next((c for c in (scripts / "deno.exe", scripts / "deno") if c.is_file()), None)
    if p:
        os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")
    return bool(p or shutil.which("deno"))


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


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as r:
        return r.read()


def download_latest_wheel(package, dest_dir, log):
    """Fetch the newest wheel of a pure-Python package from PyPI and unpack it."""
    meta = json.loads(http_get(f"https://pypi.org/pypi/{package}/json"))
    version = meta["info"]["version"]
    wheel = next(u for u in meta["urls"]
                 if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("none-any.whl"))
    log(f"Downloading {package} {version}...")
    with zipfile.ZipFile(io.BytesIO(http_get(wheel["url"], timeout=180))) as z:
        z.extractall(dest_dir)
    return version


def rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *img.size], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def fmt_duration(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_count(n):
    if not n:
        return ""
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + suf
    return str(n)


# ---------- the app ----------

class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        s = load_settings()
        ctk.set_appearance_mode(s.get("theme", "System"))

        self.title(APP_NAME)
        self.geometry("760x700")
        self.minsize(640, 620)
        self._set_icon()

        self.kind = ctk.StringVar(value=s.get("kind", "Video"))
        self.vformat = ctk.StringVar(value=s.get("vformat", "MP4"))
        self.aformat = ctk.StringVar(value=s.get("aformat", "MP3"))
        self.resolution = ctk.StringVar(value=s.get("resolution", "Best"))
        self.bitrate = ctk.StringVar(value=s.get("bitrate", "Best"))
        self.folder = s.get("folder", DEFAULT_DIR)
        self.playlist = ctk.BooleanVar(value=False)
        self.busy = False
        self.info = None
        self.last_file = None
        self._lookup_id = 0
        self._after_id = None
        self.available_heights = list(ALL_RESOLUTIONS)

        self.f_title = ctk.CTkFont(FONT, 22, "bold")
        self.f_head = ctk.CTkFont(FONT, 14, "bold")
        self.f_body = ctk.CTkFont(FONT, 13)
        self.f_small = ctk.CTkFont(FONT, 12)
        self.f_btn = ctk.CTkFont(FONT, 15, "bold")

        self._build_ui()
        self._kind_changed()

        self.ffmpeg = find_ffmpeg()
        self.has_js = ensure_deno_on_path()
        try:
            import yt_dlp
            self.ytdlp_version = yt_dlp.version.__version__
        except Exception as e:
            self.ytdlp_version = None
            self.log(f"Could not load yt-dlp: {e}")
        self.version_lbl.configure(
            text=f"v{APP_VERSION}  ·  downloader {self.ytdlp_version or 'missing'}")
        if not self.ffmpeg:
            self.log("Warning: ffmpeg not found - merging and converting won't work.")
        if not self.has_js:
            self.log("Warning: deno not found - some YouTube videos may fail.")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_icon(self):
        ico, png = asset("icon.ico"), asset("icon.png")
        if os.name == "nt":
            try:  # own taskbar group + icon instead of Python's
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YTSaver.App")
            except Exception:
                pass
            if ico:  # customtkinter resets the icon shortly after start, so set it again
                self.iconbitmap(str(ico))
                self.after(250, lambda: self.iconbitmap(str(ico)))
        elif png:
            from PIL import ImageTk
            self._icon_photo = ImageTk.PhotoImage(Image.open(png))
            self.iconphoto(True, self._icon_photo)

    # ----- layout -----
    def _card(self, parent):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)

    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=22, pady=18)

        # header
        head = ctk.CTkFrame(root, fg_color="transparent")
        head.pack(fill="x", pady=(0, 14))
        png = asset("icon.png")
        if png:
            logo = ctk.CTkImage(Image.open(png), size=(44, 44))
            ctk.CTkLabel(head, image=logo, text="").pack(side="left", padx=(0, 12))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=APP_NAME, font=self.f_title).pack(anchor="w")
        ctk.CTkLabel(titles, text="Save videos and audio to your PC. No ads, no accounts.",
                     font=self.f_small, text_color=MUTED).pack(anchor="w")
        self.theme_menu = ctk.CTkSegmentedButton(
            head, values=["Light", "Dark", "System"], command=self._theme_changed,
            font=self.f_small, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            fg_color=("#e2e5ec", "#2a3040"), unselected_color=("#e2e5ec", "#2a3040"),
            unselected_hover_color=("#d5d9e2", "#343b4e"), text_color=("#111827", "#e5e7eb"))
        self.theme_menu.set(ctk.get_appearance_mode() if load_settings().get("theme", "System") != "System" else "System")
        self.theme_menu.pack(side="right")

        # link + preview
        link = self._card(root)
        link.pack(fill="x", pady=(0, 12))
        row = ctk.CTkFrame(link, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(16, 12))
        self.url = ctk.CTkEntry(row, placeholder_text="Paste a video or playlist link…",
                                font=self.f_body, height=42, corner_radius=10, border_color=BORDER)
        self.url.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url.bind("<KeyRelease>", lambda e: self._schedule_lookup())
        self.url.bind("<<Paste>>", lambda e: self.after(50, self._schedule_lookup))
        self.url.bind("<Return>", lambda e: self.start_download())
        ctk.CTkButton(row, text="Paste", width=84, height=42, corner_radius=10, font=self.f_body,
                      fg_color=("#eef0f4", "#2a3040"), hover_color=("#e2e5ec", "#343b4e"),
                      text_color=("#111827", "#e5e7eb"), command=self._paste).pack(side="left")

        self.preview = ctk.CTkFrame(link, fg_color="transparent")
        self.preview.pack(fill="x", padx=16, pady=(0, 16))
        light_ph = rounded(Image.new("RGB", (352, 198), (238, 240, 244)), 20)
        dark_ph = rounded(Image.new("RGB", (352, 198), (42, 48, 64)), 20)
        self._placeholder = ctk.CTkImage(light_ph, dark_ph, size=(176, 99))
        self.thumb = ctk.CTkLabel(self.preview, text="", image=self._placeholder, fg_color="transparent")
        self.thumb.pack(side="left")
        meta = ctk.CTkFrame(self.preview, fg_color="transparent")
        meta.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.p_title = ctk.CTkLabel(meta, text="Nothing selected yet", font=self.f_head,
                                    anchor="w", justify="left", wraplength=470)
        self.p_title.pack(anchor="w", fill="x")
        self.p_sub = ctk.CTkLabel(meta, text="Paste a link and a preview appears here.",
                                  font=self.f_small, text_color=MUTED, anchor="w", justify="left")
        self.p_sub.pack(anchor="w", pady=(4, 0))
        self.playlist_chk = ctk.CTkCheckBox(meta, text="Download the whole playlist", font=self.f_small,
                                            variable=self.playlist, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                            checkbox_width=18, checkbox_height=18)

        # options
        opts = self._card(root)
        opts.pack(fill="x", pady=(0, 12))
        top = ctk.CTkFrame(opts, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(16, 10))
        ctk.CTkLabel(top, text="Output", font=self.f_head).pack(side="left")
        self.kind_btn = ctk.CTkSegmentedButton(
            top, values=["Video", "Audio"], variable=self.kind, command=lambda v: self._kind_changed(),
            font=self.f_body, width=200, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            fg_color=("#e2e5ec", "#2a3040"), unselected_color=("#e2e5ec", "#2a3040"),
            unselected_hover_color=("#d5d9e2", "#343b4e"), text_color=("#111827", "#e5e7eb"))
        self.kind_btn.pack(side="right")

        grid = ctk.CTkFrame(opts, fg_color="transparent")
        grid.pack(fill="x", padx=16)
        grid.columnconfigure((0, 1), weight=1, uniform="c")
        ctk.CTkLabel(grid, text="File type", font=self.f_small, text_color=MUTED).grid(row=0, column=0, sticky="w")
        self.q_label = ctk.CTkLabel(grid, text="Resolution", font=self.f_small, text_color=MUTED)
        self.q_label.grid(row=0, column=1, sticky="w", padx=(12, 0))
        menu_kw = dict(height=38, corner_radius=10, font=self.f_body, dropdown_font=self.f_body,
                       fg_color=("#eef0f4", "#2a3040"), button_color=("#e2e5ec", "#343b4e"),
                       button_hover_color=("#d5d9e2", "#3d4559"), text_color=("#111827", "#e5e7eb"),
                       dynamic_resizing=False)
        self.fmt_menu = ctk.CTkOptionMenu(grid, values=list(VIDEO_FORMATS), command=lambda v: self._fmt_changed(),
                                          **menu_kw)
        self.fmt_menu.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.q_menu = ctk.CTkOptionMenu(grid, values=["Best"], command=lambda v: self._q_changed(v), **menu_kw)
        self.q_menu.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        self.hint = ctk.CTkLabel(opts, text="", font=self.f_small, text_color=MUTED, anchor="w",
                                 justify="left", wraplength=660)
        self.hint.pack(fill="x", padx=16, pady=(8, 4))

        frow = ctk.CTkFrame(opts, fg_color="transparent")
        frow.pack(fill="x", padx=16, pady=(4, 16))
        ctk.CTkLabel(frow, text="Save to", font=self.f_small, text_color=MUTED).pack(side="left")
        self.folder_lbl = ctk.CTkLabel(frow, text=self._short(self.folder), font=self.f_body, anchor="w")
        self.folder_lbl.pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkButton(frow, text="Change…", width=90, height=32, corner_radius=8, font=self.f_small,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=("#111827", "#e5e7eb"), hover_color=("#eef0f4", "#2a3040"),
                      command=self._browse).pack(side="right")

        # download + progress
        self.dl_btn = ctk.CTkButton(root, text="Download", height=50, corner_radius=12, font=self.f_btn,
                                    fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color_disabled=("#e0e7ff", "#e0e7ff"),
                                    command=self.start_download)
        self.dl_btn.pack(fill="x", pady=(2, 10))
        self.progress = ctk.CTkProgressBar(root, height=8, corner_radius=4, progress_color=ACCENT,
                                         fg_color=("#e2e5ec", "#2a3040"))
        self.progress.set(0)
        self.progress.pack(fill="x")
        srow = ctk.CTkFrame(root, fg_color="transparent")
        srow.pack(fill="x", pady=(8, 0))
        self.status = ctk.CTkLabel(srow, text="Ready", font=self.f_small, text_color=MUTED, anchor="w")
        self.status.pack(side="left")
        self.open_btn = ctk.CTkButton(srow, text="Show in folder", width=120, height=28, corner_radius=8,
                                      font=self.f_small, fg_color="transparent", border_width=1,
                                      border_color=BORDER, text_color=("#111827", "#e5e7eb"),
                                      hover_color=("#eef0f4", "#2a3040"), command=self._show_file)

        # footer
        foot = ctk.CTkFrame(root, fg_color="transparent")
        foot.pack(side="bottom", fill="x", pady=(8, 0))
        self.version_lbl = ctk.CTkLabel(foot, text="", font=self.f_small, text_color=MUTED)
        self.version_lbl.pack(side="left")
        self.up_btn = ctk.CTkButton(foot, text="Update downloader", width=150, height=28, corner_radius=8,
                                    font=self.f_small, fg_color="transparent", text_color=ACCENT,
                                    hover_color=("#eef0f4", "#2a3040"), command=self.update_ytdlp)
        self.up_btn.pack(side="right")
        self.log_toggle = ctk.CTkButton(foot, text="Show details", width=110, height=28, corner_radius=8,
                                        font=self.f_small, fg_color="transparent", text_color=MUTED,
                                        hover_color=("#eef0f4", "#2a3040"), command=self._toggle_log)
        self.log_toggle.pack(side="right", padx=6)

        self.log_box = ctk.CTkTextbox(root, height=110, font=ctk.CTkFont("Consolas" if os.name == "nt" else "DejaVu Sans Mono", 11),
                                      corner_radius=10, border_width=1, border_color=BORDER, fg_color=CARD)
        self.log_box.configure(state="disabled")
        self._log_visible = False

    # ----- option logic -----
    def _kind_changed(self):
        if self.kind.get() == "Video":
            self.fmt_menu.configure(values=list(VIDEO_FORMATS), variable=self.vformat)
            if self.vformat.get() not in VIDEO_FORMATS:
                self.vformat.set("MP4")
            self.q_label.configure(text="Resolution")
            self._refresh_resolutions()
        else:
            self.fmt_menu.configure(values=list(AUDIO_FORMATS), variable=self.aformat)
            if self.aformat.get() not in AUDIO_FORMATS:
                self.aformat.set("MP3")
            self.q_label.configure(text="Audio quality")
            self.q_menu.configure(values=BITRATES)
            if self.bitrate.get() not in BITRATES:
                self.bitrate.set("Best")
            self.q_menu.set(self.bitrate.get())
        self._fmt_changed()

    def _refresh_resolutions(self):
        vals = ["Best"] + [res_label(h) for h in self.available_heights]
        self.q_menu.configure(values=vals)
        cur = self.resolution.get()
        if cur not in vals:
            cur = "Best"
            self.resolution.set(cur)
        self.q_menu.set(cur)

    def _q_changed(self, v):
        (self.resolution if self.kind.get() == "Video" else self.bitrate).set(v)
        self._fmt_changed()

    def _fmt_changed(self):
        if self.kind.get() == "Video":
            ext, hint = VIDEO_FORMATS[self.vformat.get()]
            if ext == "mp4" and self.resolution.get().startswith(("2160", "1440", "Best")):
                hint = "Plays everywhere. Above 1080p it may use AV1/VP9 - pick MKV for 4K."
            self.q_menu.configure(state="normal")
        else:
            ext, hint = AUDIO_FORMATS[self.aformat.get()]
            self.q_menu.configure(state="disabled" if ext in ("flac", "wav") else "normal")
        self.hint.configure(text=hint)

    # ----- link lookup / preview -----
    def _schedule_lookup(self):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(600, self._lookup)

    def _lookup(self):
        url = self.url.get().strip()
        if not re.match(r"^https?://\S+\.\S+", url) or (self.info and self.info.get("_url") == url):
            return
        self._lookup_id += 1
        my_id = self._lookup_id
        self.p_title.configure(text="Looking up video…")
        self.p_sub.configure(text=url)
        self.thumb.configure(image=self._placeholder)

        def work():
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                                       "extract_flat": "in_playlist", "logger": _Quiet()}) as ydl:
                    info = ydl.extract_info(url, download=False)
                info["_url"] = url
                img = None
                thumb_url = info.get("thumbnail") or next(
                    (t.get("url") for t in reversed(info.get("thumbnails") or []) if t.get("url")), None)
                if thumb_url:
                    try:
                        im = Image.open(io.BytesIO(http_get(thumb_url, 15))).convert("RGB")
                        w, h = im.size  # center-crop to 16:9
                        th = int(w * 9 / 16)
                        if th < h:
                            im = im.crop((0, (h - th) // 2, w, (h - th) // 2 + th))
                        img = rounded(im.resize((352, 198), Image.LANCZOS), 20)
                    except Exception:
                        pass
                self.after(0, lambda: my_id == self._lookup_id and self._show_preview(info, img))
            except Exception as e:
                msg = str(e).replace("ERROR: ", "").split("\n")[0][:160]
                self.after(0, lambda: my_id == self._lookup_id and self._show_preview_error(msg))

        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, info, img):
        self.info = info
        is_list = info.get("_type") == "playlist"
        self.p_title.configure(text=info.get("title") or "Untitled")
        bits = [info.get("channel") or info.get("uploader") or ""]
        if is_list:
            bits.append(f"{info.get('playlist_count') or len(info.get('entries') or [])} videos")
        else:
            bits += [fmt_duration(info.get("duration")),
                     (fmt_count(info.get("view_count")) + " views") if info.get("view_count") else ""]
        self.p_sub.configure(text="  ·  ".join(b for b in bits if b))
        if img:
            self._thumb_img = ctk.CTkImage(img, size=(176, 99))
            self.thumb.configure(image=self._thumb_img)
        if is_list or "list=" in info.get("_url", ""):
            self.playlist_chk.pack(anchor="w", pady=(8, 0))
            if is_list:
                self.playlist.set(True)
        else:
            self.playlist_chk.pack_forget()
            self.playlist.set(False)
        heights = sorted({f.get("height") for f in info.get("formats") or []
                          if f.get("height") and f.get("vcodec") not in (None, "none")}, reverse=True)
        self.available_heights = [h for h in ALL_RESOLUTIONS if any(x >= h for x in heights)] or list(ALL_RESOLUTIONS)
        if self.kind.get() == "Video":
            self._refresh_resolutions()

    def _show_preview_error(self, msg):
        self.info = None
        self.p_title.configure(text="Couldn't read that link")
        self.p_sub.configure(text=msg)
        self.thumb.configure(image=self._placeholder)

    # ----- small UI helpers -----
    def _short(self, path):
        home = str(Path.home())
        return ("~" + path[len(home):]) if path.startswith(home) else path

    def _paste(self):
        try:
            self.url.delete(0, "end")
            self.url.insert(0, self.clipboard_get().strip())
            self._lookup()
        except Exception:
            pass

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.folder or DEFAULT_DIR)
        if d:
            self.folder = d
            self.folder_lbl.configure(text=self._short(d))

    def _show_file(self):
        target = self.last_file if self.last_file and os.path.exists(self.last_file) else self.folder
        if os.name == "nt":
            if os.path.isfile(target):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            else:
                os.startfile(target)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target] if os.path.isfile(target) else ["open", target])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(target) if os.path.isfile(target) else target])

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_box.pack(fill="both", expand=True, pady=(10, 0))
            self.log_toggle.configure(text="Hide details")
        else:
            self.log_box.pack_forget()
            self.log_toggle.configure(text="Show details")

    def _theme_changed(self, v):
        ctk.set_appearance_mode(v)

    def _on_close(self):
        save_settings({
            "kind": self.kind.get(), "vformat": self.vformat.get(), "aformat": self.aformat.get(),
            "resolution": self.resolution.get(), "bitrate": self.bitrate.get(),
            "folder": self.folder, "theme": self.theme_menu.get(),
        })
        self.destroy()

    def log(self, msg):
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _do)

    def set_status(self, msg, pct=None, color=MUTED):
        def _do():
            self.status.configure(text=msg, text_color=color)
            if pct is not None:
                self.progress.set(max(0.0, min(1.0, pct / 100)))
        self.after(0, _do)

    def set_busy(self, busy, label="Download"):
        self.busy = busy
        def _do():
            self.dl_btn.configure(state="disabled" if busy else "normal", text=label)
            self.up_btn.configure(state="disabled" if busy else "normal")
        self.after(0, _do)

    # ----- download -----
    def _build_opts(self):
        folder = self.folder or DEFAULT_DIR
        os.makedirs(folder, exist_ok=True)
        tmpl = "%(title)s [%(id)s].%(ext)s"
        if self.playlist.get():
            tmpl = os.path.join("%(playlist_title)s", "%(playlist_index)03d - " + tmpl)
        opts = {
            "outtmpl": os.path.join(folder, tmpl),
            "noplaylist": not self.playlist.get(),
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._pp_hook],
            "logger": _Logger(self),
            "windowsfilenames": True,
            "noprogress": True,
        }
        if self.ffmpeg:
            opts["ffmpeg_location"] = self.ffmpeg

        if self.kind.get() == "Audio":
            ext = AUDIO_FORMATS[self.aformat.get()][0]
            br = self.bitrate.get()
            opts["format"] = {"m4a": "ba[ext=m4a]/ba/b", "opus": "ba[acodec=opus]/ba/b"}.get(ext, "ba/b")
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": ext}
            if ext not in ("flac", "wav"):
                pp["preferredquality"] = "0" if br == "Best" else br.split()[0]
            opts["postprocessors"] = [pp, {"key": "FFmpegMetadata"}]
        else:
            ext = VIDEO_FORMATS[self.vformat.get()][0]
            res = self.resolution.get()
            h = "" if res == "Best" else f"[height<={res.split('p')[0]}]"
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
            self.set_status("Paste a full link first (starting with https://).", color=ERR_RED)
            return
        if not self.ffmpeg:
            self.set_status("ffmpeg is missing, so the file can't be converted.", color=ERR_RED)
            return
        self.open_btn.pack_forget()
        self.set_busy(True, "Downloading…")
        self.progress.set(0)
        self.last_file = None
        self.log(f"Starting: {url}")
        threading.Thread(target=self._download, args=(url,), daemon=True).start()

    def _download(self, url):
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(self._build_opts()) as ydl:
                ydl.download([url])
            name = os.path.basename(self.last_file) if self.last_file else "Download"
            self.set_status(f"✓  Saved: {name}", 100, OK_GREEN)
            self.after(0, lambda: self.open_btn.pack(side="right"))
            self.log("Finished.")
        except Exception as e:
            msg = str(e).replace("ERROR: ", "").split("\n")[0]
            self.set_status("Download failed. Try 'Update downloader', then again.", color=ERR_RED)
            self.log("Error: " + msg)
        finally:
            self.set_busy(False)

    def _hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            pct = (done / total * 100) if total else None
            speed, eta = d.get("speed"), d.get("eta")
            parts = []
            info = d.get("info_dict") or {}
            if info.get("playlist_index") and info.get("n_entries"):
                parts.append(f"[{info['playlist_index']}/{info['n_entries']}]")
            if pct is not None:
                parts.append(f"{pct:.0f}%")
            if total:
                parts.append(f"of {total / 1048576:.1f} MB")
            if speed:
                parts.append(f"·  {speed / 1048576:.1f} MB/s")
            if eta:
                parts.append(f"·  {fmt_duration(eta)} left")
            self.set_status("Downloading  " + " ".join(parts), pct)
        elif d["status"] == "finished":
            self.set_status("Finishing up…", 100)

    def _pp_hook(self, d):
        if d["status"] == "started":
            name = {"FFmpegExtractAudio": "Converting audio", "FFmpegMerger": "Merging video and audio",
                    "FFmpegVideoRemuxer": "Packaging file", "FFmpegMetadata": "Adding title info"}
            self.set_status(name.get(d.get("postprocessor"), "Processing") + "…")
        elif d["status"] == "finished":
            path = (d.get("info_dict") or {}).get("filepath")
            if path:
                self.last_file = path
                if d.get("postprocessor") == "FFmpegMetadata":
                    self.log("Saved: " + path)

    # ----- update -----
    def update_ytdlp(self):
        if self.busy:
            return
        self.set_busy(True)
        self.set_status("Checking for a newer downloader…")

        def run():
            try:
                meta = json.loads(http_get("https://pypi.org/pypi/yt-dlp/json"))
                latest = meta["info"]["version"]
                if self.ytdlp_version and latest.lstrip("0") == self.ytdlp_version.lstrip("0"):
                    self.set_status(f"✓  Downloader is up to date ({latest}).", color=OK_GREEN)
                    return
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
                self.set_status(f"✓  Updated to {v}. Close and reopen YT Saver to use it.", color=OK_GREEN)
            except Exception as e:
                self.set_status("Update failed. Check your internet connection.", color=ERR_RED)
                self.log(f"Update failed: {e}")
            finally:
                self.set_busy(False)

        threading.Thread(target=run, daemon=True).start()


class _Logger:
    """Sends yt-dlp messages to the details box, skipping the noisy ones."""
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


class _Quiet:
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass


if __name__ == "__main__":
    App().mainloop()
