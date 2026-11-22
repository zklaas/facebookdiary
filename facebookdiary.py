#!/usr/bin/env python3
"""FacebookDiary — browse a Facebook archive day by day, time by time, by topic or by text."""
import datetime as dt
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile

if __name__ == "__main__" and sys.argv[1:2] == ["--check"]:      # headless checks (offscreen Qt)
    import runpy
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_facebookdiary_check.py"),
                   run_name="__main__")
    sys.exit(0)

from PyQt6.QtCore import (QAbstractTableModel, QDate, QModelIndex, QSize, Qt, QThread, QTimer, QUrl,
                          pyqtSignal)
from PyQt6.QtGui import (QAction, QBrush, QColor, QDesktopServices, QFont, QIcon, QImage, QKeySequence,
                         QPalette, QShortcut, QTextCharFormat, QTextDocument)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCalendarWidget, QCheckBox, QComboBox, QCompleter,
                             QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
                             QProgressDialog, QPushButton, QSlider, QSplitter, QTableView, QTextBrowser, QToolButton,
                             QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import diary_export  # noqa: E402
import diary_import  # noqa: E402
import diary_paths  # noqa: E402
import diary_query as Q  # noqa: E402

try:  # in-app video playback; must be imported before the QApplication exists
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEBENGINE = True
except ImportError:
    HAVE_WEBENGINE = False

APP = "FacebookDiary"
ICON_DIR = os.path.join(HERE, "icons")
THUMB_W = 520
SETTINGS = {}          # the main window's settings (holds "export_dir")


def export_folder():
    return diary_export.export_dir(SETTINGS)


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# --------------------------------------------------------------------------- data
class Archive:
    """The SQLite index plus random access to media inside the export zips."""

    def __init__(self, db_path):
        self.con = sqlite3.connect(db_path)
        self.con.row_factory = sqlite3.Row
        self.meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())
        self._zips = {}
        self.min_date = self.con.execute("SELECT min(date) FROM posts").fetchone()[0]
        self.max_date = self.con.execute("SELECT max(date) FROM posts").fetchone()[0]

    def search(self, qy, newest_first):
        sql, params = Q.build_sql(qy, "DESC" if newest_first else "ASC",
                                  "id, ts, date, time, kind, substr(text, 1, 400) AS text, "
                                  "substr(extra, 1, 200) AS extra, title, nmedia, links, place, target")
        return self.con.execute(sql, params).fetchall()

    def post(self, pid):
        return self.con.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()

    def neighbour(self, ts, pid, forward):
        if forward:
            r = self.con.execute("SELECT id FROM posts WHERE (ts, id) > (?, ?) ORDER BY ts, id LIMIT 1",
                                 (ts, pid)).fetchone()
        else:
            r = self.con.execute("SELECT id FROM posts WHERE (ts, id) < (?, ?) ORDER BY ts DESC, id DESC LIMIT 1",
                                 (ts, pid)).fetchone()
        return r[0] if r else None

    def day_counts(self, year, month):
        prefix = f"{year:04d}-{month:02d}-"
        return dict(self.con.execute("SELECT date, count(*) FROM posts WHERE date LIKE ? GROUP BY date",
                                     (prefix + "%",)).fetchall())

    def adjacent_day(self, date, forward):
        if forward:
            r = self.con.execute("SELECT min(date) FROM posts WHERE date > ?", (date,)).fetchone()
        else:
            r = self.con.execute("SELECT max(date) FROM posts WHERE date < ?", (date,)).fetchone()
        return r[0]

    def terms(self, kind):
        return [r[0] for r in self.con.execute(
            "SELECT term FROM terms WHERE kind = ? ORDER BY count DESC", (kind,))]

    def kinds(self):
        return [r[0] for r in self.con.execute("SELECT kind FROM posts GROUP BY kind ORDER BY count(*) DESC")]

    def media_bytes(self, uri):
        r = self.con.execute("SELECT zip FROM media_index WHERE uri = ?", (uri,)).fetchone()
        if not r:
            return None
        zf = self._zips.get(r[0])
        if zf is None:
            try:
                zf = self._zips[r[0]] = zipfile.ZipFile(r[0])
            except OSError:
                return None
        try:
            return zf.read(uri)
        except KeyError:
            return None

    def _zip_of(self, uri):
        r = self.con.execute("SELECT zip FROM media_index WHERE uri = ?", (uri,)).fetchone()
        if not r:
            return None
        zf = self._zips.get(r[0])
        if zf is None:
            try:
                zf = self._zips[r[0]] = zipfile.ZipFile(r[0])
            except OSError:
                return None
        return zf

    def media_open(self, uri):
        """(file object, size) streaming one media file from its zip, or None."""
        zf = self._zip_of(uri)
        try:
            return (zf.open(uri), zf.getinfo(uri).file_size) if zf else None
        except KeyError:
            return None

    def media_size(self, uri):
        zf = self._zip_of(uri)
        try:
            return zf.getinfo(uri).file_size if zf else 0
        except KeyError:
            return 0

    def full_posts(self, ids):
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            got = {r["id"]: r for r in self.con.execute(
                f"SELECT * FROM posts WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
            out += [got[x] for x in chunk if x in got]
        return out

    def media_file(self, uri):
        """Extract one media file to the cache (for videos and full-size photos)."""
        dest = os.path.join(diary_paths.cache_dir(), uri.replace("/", "_"))
        if not os.path.exists(dest):
            data = self.media_bytes(uri)
            if data is None:
                return None
            with open(dest + ".part", "wb") as f:
                f.write(data)
            os.replace(dest + ".part", dest)
        return dest


MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
               ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
               ".webp": "image/webp"}
BROWSERS = ("firefox", "chromium", "chromium-browser", "google-chrome", "microsoft-edge", "brave-browser")


if sys.platform.startswith("linux"):
    PLAYER_ADVICE = "Install a video player (e.g. 'sudo apt install vlc' or 'celluloid') or a web browser."
else:
    PLAYER_ADVICE = "Install a video player such as VLC (videolan.org), then try again."


def has_default_app(mime):
    """True when the desktop has a program registered for this file type (xdg-open silently fails otherwise)."""
    if not sys.platform.startswith("linux") or not mime or not shutil.which("xdg-mime"):
        return True
    try:
        out = subprocess.run(["xdg-mime", "query", "default", mime], capture_output=True, text=True, timeout=5)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return True


def open_media(path):
    """Open a photo/video with the desktop's default program, falling back to a web browser."""
    path = os.path.abspath(path)
    mime = MEDIA_TYPES.get(os.path.splitext(path)[1].lower())
    if has_default_app(mime) and QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        return True
    for b in BROWSERS:
        exe = shutil.which(b)
        if exe:
            try:
                subprocess.Popen([exe, QUrl.fromLocalFile(path).toString()], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return True
            except OSError:
                continue
    return False


# --------------------------------------------------------------------------- in-app video player
VIDEO_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#111;color:#ddd;font:14px sans-serif;text-align:center}
/* Shown at its own size (never enlarged, at most 640 px wide) and with no on-picture controls:
   on this VirtualBox VM a stretched video with the browser's own control bar made the host's
   audio stutter, while the same video at its own size played smoothly (listening tests, 2026-11-22). */
video,canvas{display:block;margin:12px auto 0;max-width:min(640px,100%);height:auto;background:#000}
body.light video{position:absolute;left:0;top:0;width:2px;height:2px;margin:0;opacity:0}
body:not(.light) canvas{display:none}
#cap{padding:8px 12px;white-space:pre-wrap;text-align:left}
</style></head><body><video id="v" src="__SRC__" preload="auto"></video><canvas id="c"></canvas><div id="cap">__CAP__</div>
<script>
var v = document.getElementById('v');
// start only once enough is buffered to play through, so the sound doesn't stutter while loading
v.addEventListener('canplaythrough', function f() { v.removeEventListener('canplaythrough', f); setLight(__FPS__); v.play(); });
v.addEventListener('error', function () { document.title = 'error:' + (v.error ? v.error.code : 0); });
v.addEventListener('playing', function () { document.title = 'playing'; });
v.addEventListener('click', function () { v.paused ? v.play() : v.pause(); });
// 'Light' picture: the video stays hidden and a canvas copies its frame a few times a second, so
// the screen changes less often (on a VM every screen change costs the host time it needs for sound)
var cv = document.getElementById('c'), cx = cv.getContext('2d'), lightTimer = null;
function draw() {
  if (!v.videoWidth) return;
  var w = Math.min(v.videoWidth, 640), h = Math.round(v.videoHeight * w / v.videoWidth);
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  cx.drawImage(v, 0, 0, w, h);
}
function setLight(fps) {
  clearInterval(lightTimer); lightTimer = null;
  document.body.classList.toggle('light', fps > 0);
  if (fps > 0) { draw(); lightTimer = setInterval(draw, 1000 / fps); }
}
v.addEventListener('seeked', draw); v.addEventListener('loadeddata', draw);
cv.addEventListener('click', function () { v.paused ? v.play() : v.pause(); });
function st() { return [v.currentTime, v.duration || 0, v.paused, v.ended, v.videoWidth, v.videoHeight]; }
</script></body></html>"""


LIGHT_FPS = 12


def in_virtual_machine():
    try:
        out = subprocess.run(["systemd-detect-virt", "--vm"], capture_output=True, text=True, timeout=3)
        return out.returncode == 0 and out.stdout.strip() not in ("", "none")
    except (OSError, subprocess.SubprocessError):
        return False


def light_default():
    choice = diary_paths.load_settings().get("video_picture")
    if choice in ("light", "full"):
        return choice == "light"
    return in_virtual_machine()


def clock(sec):
    sec = int(sec or 0)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


class VideoWindow(QMainWindow):
    """Plays a post's video inside FacebookDiary (Qt WebEngine). One window is reused, so two
    videos never play over each other. The controls are Qt widgets below the picture, polled twice
    a second, rather than the browser's control bar (see VIDEO_PAGE). Falls back to an outside
    player if the engine can't decode the file."""
    instance = None
    cant_decode = False      # set once the engine fails on a file: later videos go straight outside

    @classmethod
    def play(cls, path, title, caption, parent=None):
        if cls.instance is None:
            cls.instance = cls()
            if parent is not None:
                cls.instance.setWindowIcon(parent.windowIcon())
        w = cls.instance
        w.load(path, title, caption)
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def __init__(self):
        super().__init__()
        self.path = None
        self.duration = 0
        self.sized = False
        self.view = QWebEngineView()
        st = self.view.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.view.titleChanged.connect(self._state)
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        self.play_btn = QPushButton("⏸")
        self.play_btn.setFixedWidth(44)
        self.play_btn.setToolTip("Play / pause (Space)")
        self.play_btn.clicked.connect(self.toggle)
        bar.addWidget(self.play_btn)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderReleased.connect(lambda: self._js(f"v.currentTime = {self.seek.value() / 10}"))
        bar.addWidget(self.seek, 1)
        self.time = QLabel("0:00 / 0:00")
        self.time.setMinimumWidth(110)
        bar.addWidget(self.time)
        self.picture = QComboBox()
        self.picture.addItem("Picture: light", LIGHT_FPS)
        self.picture.addItem("Picture: full", 0)
        self.picture.setToolTip("Light shows about %d pictures a second, which leaves this computer more room to keep\n"
                                "the sound smooth (useful in a virtual machine). Full shows every frame." % LIGHT_FPS)
        self.picture.setCurrentIndex(0 if light_default() else 1)
        self.picture.currentIndexChanged.connect(lambda _i: self._apply_picture())
        bar.addWidget(self.picture)
        ext = QPushButton("Outside player")
        ext.setToolTip("Play this video with your desktop's video player (or a web browser) instead")
        ext.clicked.connect(self._external)
        bar.addWidget(ext)
        lay.addLayout(bar)
        self.setCentralWidget(central)
        self.resize(700, 560)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._poll)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Space"), self, activated=self.toggle)
        QShortcut(QKeySequence("Right"), self, activated=lambda: self._js("v.currentTime += 5"))
        QShortcut(QKeySequence("Left"), self, activated=lambda: self._js("v.currentTime -= 5"))

    def _js(self, code, cb=None):
        if cb:
            self.view.page().runJavaScript(code, cb)
        else:
            self.view.page().runJavaScript(code)

    def load(self, path, title, caption):
        self.path = path
        self.duration = 0
        self.sized = False
        self.light_applied = False
        self.seek.setRange(0, 0)
        self.time.setText("Loading…")
        self.setWindowTitle(f"{title} — {APP}")
        page = (VIDEO_PAGE.replace("__SRC__", html.escape(QUrl.fromLocalFile(path).toString(), quote=True))
                .replace("__CAP__", html.escape(caption or ""))
                .replace("__FPS__", str(self.picture.currentData())))
        self.view.setHtml(page, QUrl.fromLocalFile(os.path.dirname(path) + "/"))
        self.timer.start()

    def toggle(self):
        self._js("if (v.paused || v.ended) v.play(); else v.pause();")
        QTimer.singleShot(80, self._poll)

    def _poll(self):
        self._js("typeof st === 'function' ? st() : null", self._update)

    def _update(self, r):
        if not r:
            return
        cur, dur, paused, ended, vw, vh = r
        if dur and dur != self.duration:
            self.duration = dur
            self.seek.setRange(0, int(dur * 10))
        if not self.seek.isSliderDown():
            self.seek.setValue(int(cur * 10))
        self.time.setText(f"{clock(cur)} / {clock(dur)}")
        self.play_btn.setText("▶" if paused or ended else "⏸")
        if vw and not self.sized:      # fit the window to the picture once its size is known
            self.sized = True
            w = min(int(vw), 640)
            h = int(vh * w / vw) if vw else 360
            self.resize(max(w + 40, 480), h + 200)

    def _apply_picture(self):
        fps = self.picture.currentData()
        self._js(f"typeof setLight === 'function' && setLight({fps})")
        s = diary_paths.load_settings()
        s["video_picture"] = "light" if fps else "full"
        diary_paths.save_settings(s)

    def _state(self, t):
        if t == "playing" and not self.light_applied:
            self.light_applied = True
            self._js(f"setLight({self.picture.currentData()})")
        if t.startswith("error:"):
            # Qt WebEngine from pip (Windows, macOS) can't decode the H.264 video Facebook
            # uses; the system's own player can.  Hand this and later videos over to it.
            VideoWindow.cant_decode = True
            self.time.setText("Can't play here")
            self._external()
            self.close()

    def _external(self):
        if self.path:
            self._js("v.pause()")
            if not open_media(self.path):
                QMessageBox.warning(self, APP, f"No program on this computer can play this video.\n\nIt was saved to:\n{self.path}")

    def closeEvent(self, e):
        self.timer.stop()
        self.view.setHtml("")      # stop the sound when the window closes
        super().closeEvent(e)


# --------------------------------------------------------------------------- formatting
def when(ts):
    d = dt.datetime.fromtimestamp(ts)
    return diary_import.long_day(d), diary_import.short_clock(d)


def highlight_re(words):
    words = sorted({w for w in words if w and len(w) > 1}, key=len, reverse=True)
    if not words:
        return None
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words) + r")",
                      re.I)


def linkify_and_mark(text, hl):
    out, last = [], 0
    for m in re.finditer(r"https?://[^\s<>\"]+", text):
        out.append(mark(html.escape(text[last:m.start()]), hl))
        u = m.group(0).rstrip(".,);")
        out.append(f'<a href="{html.escape(u, quote=True)}">{html.escape(u)}</a>' + html.escape(m.group(0)[len(u):]))
        last = m.end()
    out.append(mark(html.escape(text[last:]), hl))
    return "".join(out).replace("\n", "<br>")


def mark(escaped, hl):
    if not hl:
        return escaped
    return hl.sub(lambda m: f'<span style="background:#ffe27a;color:#000">{m.group(1)}</span>', escaped)


facebook_url = diary_import.facebook_url


def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip().lower()


def repeats(caption, shown):
    """True when a photo caption only repeats text already on screen (Facebook copies the
    post's text into each photo's description)."""
    c = _norm(caption)
    return not c or any(c in _norm(t) for t in shown if t)


def preview_text(row):
    t = (row["text"] or "").strip()
    if not t:
        t = (row["extra"] or "").strip()
    if not t:
        links = json.loads(row["links"] or "[]")
        t = links[0] if links else (row["place"] or row["title"] or "")
    t = re.sub(r"\s+", " ", t)
    if row["kind"] in ("Comment", "Reply") and row["target"]:
        t = f"↩ {row['target']}: {t}"
    return t[:220]


# --------------------------------------------------------------------------- results model
class ResultsModel(QAbstractTableModel):
    HEAD = ["Date", "Time", "Type", "", "Post"]

    def __init__(self):
        super().__init__()
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEAD)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEAD[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return r["date"]
            if c == 1:
                return r["time"][:5]
            if c == 2:
                return r["kind"]
            if c == 3:
                return ("📷" if r["nmedia"] else "") + ("🔗" if r["links"] not in ("[]", None) else "")
            if c == 4:
                return preview_text(r)
        if role == Qt.ItemDataRole.ToolTipRole and c == 4:
            return html.escape(preview_text(r)[:220])
        if role == Qt.ItemDataRole.ToolTipRole and c == 0:
            return when(r["ts"])[0]
        return None

    def post_id(self, row):
        return self.rows[row]["id"] if 0 <= row < len(self.rows) else None

    def row_of(self, pid):
        for i, r in enumerate(self.rows):
            if r["id"] == pid:
                return i
        return -1


# --------------------------------------------------------------------------- post viewer
class PostView(QWidget):
    """Shows one post: header, text, link list, photos (from the zips), video buttons."""
    navigate = pyqtSignal(int)          # post id
    open_day = pyqtSignal(str)          # yyyy-mm-dd
    popout = pyqtSignal(int)

    def __init__(self, archive, parent=None, show_popout=True):
        super().__init__(parent)
        self.archive = archive
        self.pid = None
        self.hl = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Earlier")
        self.next_btn = QPushButton("Later ▶")
        self.day_btn = QPushButton("Whole day")
        self.pop_btn = QPushButton("Open in window")
        self.save_btn = QPushButton("Save to export folder")
        self.save_btn.setToolTip("Add this post (its text, links and Facebook address) to 'Saved posts.html' in the "
                                 "export folder, and copy its videos there.\nRight-click a link, photo or video for more.")
        self.saved_lbl = QLabel()
        self.saved_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.saved_lbl.linkActivated.connect(lambda _u: open_folder(export_folder()))
        self.prev_btn.setToolTip("The post or comment just before this one, whatever the search (Alt+Left)")
        self.next_btn.setToolTip("The post or comment just after this one, whatever the search (Alt+Right)")
        self.day_btn.setToolTip("Search for every post on this day")
        for b in (self.prev_btn, self.next_btn, self.day_btn, self.save_btn):
            bar.addWidget(b)
        bar.addWidget(self.saved_lbl)
        bar.addStretch()
        if show_popout:
            bar.addWidget(self.pop_btn)
        else:
            self.pop_btn.hide()
        lay.addLayout(bar)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._link)
        self.browser.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browser.customContextMenuRequested.connect(self._context_menu)
        self.save_btn.clicked.connect(lambda: self.save_post("videos"))
        lay.addWidget(self.browser)
        self.prev_btn.clicked.connect(lambda: self._step(False))
        self.next_btn.clicked.connect(lambda: self._step(True))
        self.day_btn.clicked.connect(self._day)
        self.pop_btn.clicked.connect(lambda: self.pid and self.popout.emit(self.pid))
        self.show_post(None)

    def _step(self, forward):
        if self.pid is None:
            return
        p = self.archive.post(self.pid)
        n = self.archive.neighbour(p["ts"], p["id"], forward)
        if n:
            self.navigate.emit(n)

    def _day(self):
        if self.pid is not None:
            self.open_day.emit(self.archive.post(self.pid)["date"])

    # ---- saving to the export folder
    def _saved(self, what):
        self.saved_lbl.setText(f'✓ {html.escape(what)} — <a href="open">open folder</a>')

    def _save_failed(self, e):
        QMessageBox.warning(self, APP, f"Could not save to the export folder\n{export_folder()}\n\n{e}")

    def save_post(self, media="videos"):
        if self.pid is None:
            return
        p = self.archive.post(self.pid)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            _page, files, missing = diary_export.save_post(export_folder(), p, self.archive.media_open, media)
        except OSError as e:
            QApplication.restoreOverrideCursor()
            return self._save_failed(e)
        QApplication.restoreOverrideCursor()
        what = "Post saved" + (f" with {len(files)} file{'s' if len(files) != 1 else ''}" if files else "")
        self._saved(what)
        if missing:
            QMessageBox.warning(self, APP, "Not found in the export zips:\n" + "\n".join(missing))

    def save_file(self, uri):
        p = self.archive.post(self.pid)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            path = diary_export.save_one_file(export_folder(), p, self.archive.media_open, uri)
        except OSError as e:
            QApplication.restoreOverrideCursor()
            return self._save_failed(e)
        QApplication.restoreOverrideCursor()
        if path:
            self._saved(f"Saved {os.path.basename(path)}")
        else:
            QMessageBox.warning(self, APP, f"Could not find {uri} in the export zips.")

    def _context_menu(self, pos):
        menu = self.browser.createStandardContextMenu(pos)
        href = self.browser.anchorAt(pos)
        if self.pid is not None:
            first = menu.actions()[0] if menu.actions() else None
            acts = []
            if href.startswith(("media:", "save:")):
                uri = QUrl(href).path().lstrip("/")
                kind = "video" if diary_export.is_video(uri) else "photo"
                a = QAction(f"Save this {kind} to the export folder", menu)
                a.triggered.connect(lambda _c=False, u=uri: self.save_file(u))
                acts.append(a)
            a = QAction("Save this post and its links to the export folder", menu)
            a.triggered.connect(lambda: self.save_post("videos"))
            acts.append(a)
            if json.loads(self.archive.post(self.pid)["media"] or "[]"):
                a = QAction("Save this post with all its photos and videos", menu)
                a.triggered.connect(lambda: self.save_post("all"))
                acts.append(a)
            a = QAction("Open the export folder", menu)
            a.triggered.connect(lambda: open_folder(export_folder()))
            acts.append(a)
            menu.insertActions(first, acts)
            if first:
                menu.insertSeparator(first)
        menu.exec(self.browser.viewport().mapToGlobal(pos))

    def _link(self, url):
        if url.scheme() == "save":
            return self.save_file(url.path().lstrip("/"))
        if url.scheme() == "media":
            uri = url.path().lstrip("/")
            is_video = uri.lower().endswith((".mp4", ".mov", ".webm"))
            if is_video:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)   # big videos take a moment to unzip
            try:
                path = self.archive.media_file(uri)
            finally:
                if is_video:
                    QApplication.restoreOverrideCursor()
            if path and is_video and HAVE_WEBENGINE and not VideoWindow.cant_decode:
                p = self.archive.post(self.pid)
                m = next((m for m in json.loads(p["media"] or "[]") if m.get("uri") == uri), {})
                day, clock = when(p["ts"])
                VideoWindow.play(path, m.get("title") or f"{day}, {clock}",
                                 m.get("description") or (p["text"] or "")[:600], self.window())
            elif path:
                if not open_media(path):
                    QMessageBox.warning(
                        self, APP, "No program on this computer can open this file, so it could not be shown.\n\n"
                        f"{PLAYER_ADVICE}\n\n"
                        f"The file was saved to:\n{path}")
            else:
                QMessageBox.warning(self, APP, f"Could not find {uri} in the export zips.")
        else:
            QDesktopServices.openUrl(url)

    def show_post(self, pid, highlight_words=()):
        self.pid = pid
        self.hl = highlight_re(highlight_words)
        for b in (self.prev_btn, self.next_btn, self.day_btn, self.pop_btn, self.save_btn):
            b.setEnabled(pid is not None)
        self.saved_lbl.clear()
        doc = self.browser.document()
        if pid is None:
            self.browser.setHtml('<p style="color:gray">Pick a post from the list.</p>')
            return
        p = self.archive.post(pid)
        day, clock = when(p["ts"])
        parts = [f'<h2 style="margin-bottom:2px">{html.escape(day)}</h2>',
                 f'<p style="color:gray;margin-top:0">{clock} &nbsp;·&nbsp; {html.escape(p["kind"])}']
        if p["edited_ts"] and abs(p["edited_ts"] - p["ts"]) > 120:
            ed, ec = when(p["edited_ts"])
            parts.append(f" &nbsp;·&nbsp; edited {html.escape(ed)} {ec}")
        fb = p["fb_url"] if "fb_url" in p.keys() else facebook_url(json.loads(p["media"] or "[]"))
        if fb:
            label = "Open on Facebook" if p["kind"] not in ("Comment", "Reply") else "Open the attachment on Facebook"
            parts.append(f' &nbsp;·&nbsp; <a href="{html.escape(fb, quote=True)}">{label}</a>')
        parts.append("</p>")
        if p["kind"] in ("Comment", "Reply"):
            parts.append(f'<p style="border-left:3px solid #999;padding-left:8px;color:#666">↩ '
                         f'<i>{mark(html.escape(p["title"]), self.hl)}</i><br>'
                         '<small>(Facebook\'s export keeps only who you answered, not their words.)</small></p>')
        elif p["title"]:
            parts.append(f'<p><i>{html.escape(p["title"])}</i></p>')
        if p["text"]:
            parts.append(f'<div style="font-size:12pt">{linkify_and_mark(p["text"], self.hl)}</div>')
        if p["extra"]:
            parts.append(f'<p style="color:#666">{linkify_and_mark(p["extra"], self.hl)}</p>')
        if p["place"]:
            parts.append(f'<p>📍 {mark(html.escape(p["place"]), self.hl)}</p>')
        if p["tags"]:
            parts.append(f'<p>With: {html.escape(p["tags"])}</p>')
        on_screen = (p["text"] or "") + "\n" + (p["extra"] or "")
        # list only addresses that aren't already clickable in the post's own text
        links = [u for u in json.loads(p["links"] or "[]") if u and u.rstrip("/") not in on_screen]
        if links:
            parts.append("<p>" + "<br>".join(f'🔗 <a href="{html.escape(u, quote=True)}">{html.escape(u[:120])}</a>'
                                             for u in links) + "</p>")
        shown = [p["text"] or "", p["extra"] or ""]    # captions that only repeat these are skipped
        for m in json.loads(p["media"] or "[]"):
            uri = m.get("uri", "")
            url = "media:/" + uri
            if uri.lower().endswith((".mp4", ".mov", ".webm")):
                label = html.escape(m.get("title") or os.path.basename(uri))
                save = html.escape("save:/" + uri, quote=True)
                parts.append(f'<p>🎬 <a href="{html.escape(url, quote=True)}">Play video: {label}</a>'
                             f' &nbsp;·&nbsp; <a href="{save}">Save video</a></p>')
            else:
                data = self.archive.media_bytes(uri)
                img = QImage()
                if data and img.loadFromData(data):
                    if img.width() > THUMB_W:
                        img = img.scaledToWidth(THUMB_W, Qt.TransformationMode.SmoothTransformation)
                    doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), img)
                    parts.append(f'<p><a href="{html.escape(url, quote=True)}"><img src="{html.escape(url, quote=True)}" '
                                 f'width="{img.width()}" height="{img.height()}"></a></p>')
                else:
                    parts.append(f'<p>🖼 <a href="{html.escape(url, quote=True)}">{html.escape(os.path.basename(uri))}</a></p>')
            if m.get("title") and not uri.lower().endswith(".mp4") and not repeats(m["title"], shown):
                parts.append(f'<p><b>{linkify_and_mark(m["title"], self.hl)}</b></p>')
                shown.append(m["title"])
            if m.get("description") and not repeats(m["description"], shown):
                parts.append(f'<p>{linkify_and_mark(m["description"], self.hl)}</p>')
                shown.append(m["description"])
        self.browser.setHtml("".join(parts))
        self.browser.verticalScrollBar().setValue(0)


class PostWindow(QMainWindow):
    """A separate window for one post, with its own earlier/later navigation."""

    def __init__(self, archive, pid, words, on_day):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.view = PostView(archive, show_popout=False)
        self.words = words
        self.view.navigate.connect(self.show_post)
        self.view.open_day.connect(on_day)
        self.setCentralWidget(self.view)
        self.resize(720, 820)
        self.archive = archive
        self.show_post(pid)

    def show_post(self, pid):
        self.view.show_post(pid, self.words)
        p = self.archive.post(pid)
        self.setWindowTitle(f"{p['date']} {p['time'][:5]} — {APP}")


# --------------------------------------------------------------------------- dialogs
class TopicsDialog(QDialog):
    """Edit 'my topics': each topic is a name plus words/phrases (one per line, word* = prefix)."""

    def __init__(self, topics, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My topics")
        self.topics = {k: list(v) for k, v in topics.items()}
        self.current = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.addItems(sorted(self.topics, key=str.lower))
        left.addWidget(self.list)
        row = QHBoxLayout()
        add, rem, ren = QPushButton("Add"), QPushButton("Remove"), QPushButton("Rename")
        for b in (add, ren, rem):
            row.addWidget(b)
        left.addLayout(row)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        self.editing = QLabel()
        f = self.editing.font(); f.setBold(True); self.editing.setFont(f)
        right.addWidget(self.editing)
        right.addWidget(QLabel("One per line; a post is in the topic if it matches any line. A line can be:\n"
                               "  • a word or phrase (end a word with * to match its beginnings, e.g. elect*)\n"
                               "  • a file type, e.g. .mp4 (posts with that kind of file attached or linked)\n"
                               "  • a search filter, e.g. has:video  type:photo  site:youtube.com  to:\"Alex Smith\""))
        self.terms = QPlainTextEdit()
        right.addWidget(self.terms)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        right.addWidget(bb)
        lay.addLayout(right, 2)
        self.resize(680, 460)
        self.list.currentTextChanged.connect(self._select)
        add.clicked.connect(self._add)
        rem.clicked.connect(self._remove)
        ren.clicked.connect(self._rename)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _commit(self):
        if self.current is not None and self.current in self.topics:
            self.topics[self.current] = [t.strip() for t in self.terms.toPlainText().splitlines() if t.strip()]

    def _select(self, name):
        self._commit()
        self.current = name or None
        self.terms.setPlainText("\n".join(self.topics.get(name, [])))
        self.terms.setEnabled(self.current is not None)
        self.editing.setText(f"Lines for the topic “{name}”:" if name else "Pick a topic on the left, or Add one.")

    def _ask_name(self, title, text=""):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, title, "Topic name:", text=text)
        name = name.strip()
        if not ok or not name:
            return None
        if name in self.topics and name != text:
            QMessageBox.warning(self, title, f"There is already a topic called {name}.")
            return None
        return name

    def _add(self):
        name = self._ask_name("New topic")
        if name:
            self._commit()
            self.topics[name] = []
            self.list.addItem(name)
            self.list.setCurrentRow(self.list.count() - 1)
            self.terms.setFocus()

    def _rename(self):
        if not self.current:
            return
        old = self.current
        name = self._ask_name("Rename topic", old)
        if name and name != old:
            self._commit()
            self.topics[name] = self.topics.pop(old)
            self.current = name
            self.list.currentItem().setText(name)

    def _remove(self):
        if not self.current:
            return
        self.topics.pop(self.current, None)
        self.current = None
        self.list.takeItem(self.list.currentRow())

    def _save(self):
        self._commit()
        self.accept()


class ExportDialog(QDialog):
    def __init__(self, n, folder, sizer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export the search results")
        self.sizer = sizer
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Write the <b>{n:,}</b> listed posts to a web page (<i>index.html</i>) with their "
                             "text, links and Facebook addresses, in a new subfolder of:"))
        self.folder = QLabel(f"<code>{html.escape(folder)}</code>")
        lay.addWidget(self.folder)
        self.videos = QCheckBox("Copy their videos beside the page")
        self.photos = QCheckBox("Copy their photos beside the page")
        self.only = QCheckBox("Leave out posts that have no links and no copied files")
        self.videos.setChecked(True)
        for c in (self.videos, self.photos, self.only):
            lay.addWidget(c)
            c.toggled.connect(self._size)
        self.size = QLabel()
        lay.addWidget(self.size)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._size()

    def _size(self):
        b = self.sizer(self.videos.isChecked(), self.photos.isChecked())
        self.size.setText(f"Files to copy: {b / 1e6:,.1f} MB" if b else "No files to copy.")


class ExportThread(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, folder, name, description, posts, zip_of, opts):
        super().__init__()
        self.args = (folder, name, description, posts)
        self.zip_of, self.opts = zip_of, opts
        self.stop = False

    def run(self):
        zips = {}

        def opener(uri):        # its own ZipFile objects: never share the GUI thread's
            z = self.zip_of.get(uri)
            if not z:
                return None
            try:
                zf = zips.get(z) or zips.setdefault(z, zipfile.ZipFile(z))
                return zf.open(uri), zf.getinfo(uri).file_size
            except (OSError, KeyError):
                return None
        try:
            self.finished_ok.emit(diary_export.export_search(
                *self.args, opener, progress=self.progress.emit, cancelled=lambda: self.stop, **self.opts))
        except OSError as e:
            self.failed.emit(str(e))
        finally:
            for zf in zips.values():
                zf.close()


class ImportThread(QThread):
    message = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, folder, db):
        super().__init__()
        self.folder, self.db = folder, db

    def run(self):
        try:
            diary_import.build(self.folder, self.db, progress=self.message.emit)
        except BaseException as e:  # SystemExit from build() carries a readable message
            self.failed.emit(str(e))


# --------------------------------------------------------------------------- main window
class DiaryWindow(QMainWindow):
    def __init__(self, initial_query=None):
        super().__init__()
        self.setWindowTitle(APP)
        self.settings = diary_paths.load_settings()
        global SETTINGS
        SETTINGS = self.settings
        self.topics = Q.load_topics(diary_paths.topics_path())
        self.archive = None
        self.windows = []
        self.current_query = None
        self._build_ui()
        self.resize(*self.settings.get("size", [1400, 860]))
        if os.path.exists(diary_paths.db_path()):
            self._open_archive()
            self.search_box.setText(initial_query if initial_query is not None else self.settings.get("query", ""))
            self.run_search()
        else:
            QTimer.singleShot(0, self.first_import)

    # ---- UI
    def _build_ui(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Dates, times and words — e.g.  2016-11-08 .. 2016-11-10 election   "
                                           "·  time:22:00-02:00 2020  ·  on:jan-17  ·  \"exact phrase\"")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(self.run_search)
        top.addWidget(self.search_box, 4)
        self.topic_box = QComboBox()
        self.topic_box.setEditable(True)
        self.topic_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.topic_box.setMinimumWidth(220)
        self.topic_box.setToolTip("Topic: one of your topics (Topics ▸ Edit my topics), a #hashtag, a site,\n"
                                  "or one of the words you use most. Type to filter.")
        self.topic_box.activated.connect(lambda _i: self.run_search())
        self.topic_box.lineEdit().returnPressed.connect(self.run_search)
        top.addWidget(self.topic_box, 1)
        self.kind_box = QComboBox()
        self.kind_box.setToolTip("Kind of post")
        self.kind_box.activated.connect(lambda _i: self.run_search())
        top.addWidget(self.kind_box)
        self.order_box = QComboBox()
        self.order_box.addItems(["Oldest first", "Newest first"])
        self.order_box.setCurrentIndex(1 if self.settings.get("newest_first") else 0)
        self.order_box.activated.connect(lambda _i: self.run_search())
        top.addWidget(self.order_box)
        go = QPushButton("Search")
        go.setDefault(True)
        go.clicked.connect(self.run_search)
        top.addWidget(go)
        helpb = QToolButton()
        helpb.setText("?")
        helpb.setToolTip("Search syntax")
        helpb.clicked.connect(self.show_help)
        top.addWidget(helpb)
        outer.addLayout(top)
        self.status = QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.clicked.connect(self.pick_day)
        self.calendar.currentPageChanged.connect(self.paint_calendar)
        ll.addWidget(self.calendar)
        dayrow = QHBoxLayout()
        self.prev_day = QPushButton("◀ Day")
        self.next_day = QPushButton("Day ▶")
        self.prev_day.setToolTip("Previous day with posts (Ctrl+Left)")
        self.next_day.setToolTip("Next day with posts (Ctrl+Right)")
        self.prev_day.clicked.connect(lambda: self.step_day(False))
        self.next_day.clicked.connect(lambda: self.step_day(True))
        dayrow.addWidget(self.prev_day)
        dayrow.addWidget(self.next_day)
        ll.addLayout(dayrow)
        otd = QPushButton("On this day (every year)")
        otd.setToolTip("Every post made on the calendar's selected month and day, in any year")
        otd.clicked.connect(self.on_this_day)
        ll.addWidget(otd)
        self.month_btn = QPushButton("Whole month shown")
        self.month_btn.clicked.connect(self.whole_month)
        ll.addWidget(self.month_btn)
        clear = QPushButton("Clear search")
        clear.clicked.connect(self.clear_search)
        ll.addWidget(clear)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: gray")
        ll.addWidget(self.info)
        ll.addStretch()
        split.addWidget(left)

        self.model = ResultsModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        for c in range(4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(self.table.fontMetrics().height() + 8)
        self.table.selectionModel().currentRowChanged.connect(self.row_changed)
        self.table.doubleClicked.connect(lambda idx: self.pop_out(self.model.post_id(idx.row())))
        split.addWidget(self.table)

        self.view_holder = QWidget()
        self.view_layout = QVBoxLayout(self.view_holder)
        self.view_layout.setContentsMargins(0, 0, 0, 0)
        split.addWidget(self.view_holder)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 3)
        split.setSizes(self.settings.get("splitter", [300, 560, 540]))
        self.splitter = split
        outer.addWidget(split, 1)
        self.setCentralWidget(central)

        m = self.menuBar().addMenu("&File")
        a = QAction("&Re-import from Facebook export…", self)
        a.triggered.connect(self.reimport)
        m.addAction(a)
        a = QAction("&Export the search results…", self)
        a.setShortcut(QKeySequence("Ctrl+E"))
        a.triggered.connect(self.export_results)
        m.addAction(a)
        a = QAction("&Open the export folder", self)
        a.triggered.connect(lambda: open_folder(export_folder()))
        m.addAction(a)
        a = QAction("C&hoose the export folder…", self)
        a.triggered.connect(self.choose_export_folder)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Open media &cache folder", self)
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(diary_paths.cache_dir())))
        m.addAction(a)
        a = QAction("C&lear media cache…", self)
        a.triggered.connect(self.clear_cache)
        m.addAction(a)
        m.addSeparator()
        a = QAction("&Quit", self)
        a.setShortcut(QKeySequence.StandardKey.Quit)
        a.triggered.connect(self.close)
        m.addAction(a)
        m = self.menuBar().addMenu("&Topics")
        a = QAction("&Edit my topics…", self)
        a.triggered.connect(self.edit_topics)
        m.addAction(a)
        m = self.menuBar().addMenu("&Help")
        a = QAction("&Search syntax", self)
        a.setShortcut(QKeySequence.StandardKey.HelpContents)
        a.triggered.connect(self.show_help)
        m.addAction(a)

        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: (self.search_box.setFocus(), self.search_box.selectAll()))
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.search_box.setFocus(), self.search_box.selectAll()))
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=lambda: self.step_day(False))
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=lambda: self.step_day(True))
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self.viewer and self.viewer._step(False))
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self.viewer and self.viewer._step(True))
        self.viewer = None

    def _open_archive(self):
        if self.archive:
            self.archive.con.close()
        self.archive = Archive(diary_paths.db_path())
        if self.viewer:
            self.viewer.setParent(None)
            self.viewer.deleteLater()
        self.viewer = PostView(self.archive)
        self.viewer.navigate.connect(self.go_to_post)
        self.viewer.open_day.connect(self.search_day)
        self.viewer.popout.connect(self.pop_out)
        self.view_layout.addWidget(self.viewer)
        lo, hi = QDate.fromString(self.archive.min_date, "yyyy-MM-dd"), QDate.fromString(self.archive.max_date, "yyyy-MM-dd")
        self.calendar.setDateRange(lo, hi)
        self.fill_topics()
        self.kind_box.clear()
        self.kind_box.addItem("Any kind", "")
        self.kind_box.addItem("Posts only", "__posts__")
        self.kind_box.addItem("Comments & replies only", "__comments__")
        for k in self.archive.kinds():
            self.kind_box.addItem(k, k)
        m = self.archive.meta
        nc = self.archive.con.execute("SELECT count(*) FROM posts WHERE kind IN ('Comment','Reply')").fetchone()[0]
        self.info.setText(f"{int(m.get('count', 0)) - nc:,} posts and {nc:,} comments,\n"
                          f"{self.archive.min_date} to {self.archive.max_date}.\n"
                          f"Times are local ({m.get('tz', '')}).\nIndexed {m.get('built', '')[:10]} from\n"
                          f"{m.get('source', '')}")
        self.paint_calendar(self.calendar.yearShown(), self.calendar.monthShown())

    def fill_topics(self):
        cur = self.topic_box.currentText()
        self.topic_box.clear()
        self.topic_box.addItem("Any topic", "")
        for name in sorted(self.topics, key=str.lower):
            self.topic_box.addItem(f"★ {name}", name)
        if self.archive:
            for t in self.archive.terms("hashtag"):
                self.topic_box.addItem(f"#{t}", f"#{t}")
            for s in self.archive.terms("site"):
                self.topic_box.addItem(f"site: {s}", f"site:{s}")
            for w in sorted(self.archive.terms("word")):
                self.topic_box.addItem(w, w)
        comp = QCompleter([self.topic_box.itemText(i) for i in range(self.topic_box.count())], self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.topic_box.setCompleter(comp)
        i = self.topic_box.findText(cur)
        self.topic_box.setCurrentIndex(max(i, 0))

    # ---- searching
    def topic_value(self):
        text = self.topic_box.currentText().strip()
        i = self.topic_box.findText(text)
        if i >= 0:
            return self.topic_box.itemData(i) or ""
        if text.startswith("★ "):
            text = text[2:]
        return "" if text.lower() in ("", "any topic") else text

    def run_search(self, keep_post=None):
        if not self.archive:
            return
        q = self.search_box.text().strip()
        try:
            qy = Q.parse(q, self.topics)
            tv = self.topic_value()
            if tv:
                qy.topics.append(tv)
                qy.topic_terms.append(Q.topic_expansion(tv, self.topics))
                qy.highlight += Q.topic_highlight(tv, self.topics)
            kind = self.kind_box.currentData()
            rows = self.archive.search(qy, self.order_box.currentIndex() == 1)
            if kind == "__posts__":
                rows = [r for r in rows if r["kind"] not in ("Comment", "Reply")]
            elif kind == "__comments__":
                rows = [r for r in rows if r["kind"] in ("Comment", "Reply")]
            elif kind:
                rows = [r for r in rows if r["kind"] == kind]
        except (Q.QueryError, sqlite3.OperationalError) as e:
            self.status.setText(f'<span style="color:#c0392b">⚠ {html.escape(str(e))}</span>')
            return
        self.current_query = qy
        self.model.set_rows(rows)
        n = len(rows)
        self.status.setText(f"<b>{n:,} post{'s' if n != 1 else ''}</b> — {html.escape(qy.describe())}")
        self.settings["query"] = q
        # focus the calendar on the search's start
        if qy.start is not None:
            d = Q.local_dt(qy.start).date()
            self.calendar.blockSignals(True)
            self.calendar.setSelectedDate(QDate(d.year, d.month, d.day))
            self.calendar.blockSignals(False)
            self.paint_calendar(d.year, d.month)
        target = self.model.row_of(keep_post) if keep_post else (0 if n else -1)
        if target >= 0:
            self.table.selectRow(target)
            self.table.scrollTo(self.model.index(target, 0), QAbstractItemView.ScrollHint.PositionAtCenter)
        else:
            self.viewer.show_post(None)

    def row_changed(self, cur, _prev):
        pid = self.model.post_id(cur.row())
        if pid is not None:
            self.viewer.show_post(pid, self.current_query.highlight if self.current_query else ())

    def go_to_post(self, pid):
        row = self.model.row_of(pid)
        if row >= 0:
            self.table.selectRow(row)
            self.table.scrollTo(self.model.index(row, 0))
        else:
            self.table.clearSelection()
            self.viewer.show_post(pid, self.current_query.highlight if self.current_query else ())

    def pop_out(self, pid):
        if pid is None:
            return
        w = PostWindow(self.archive, pid, self.current_query.highlight if self.current_query else (), self.search_day)
        w.setWindowIcon(self.windowIcon())
        self.windows = [x for x in self.windows if x.isVisible()] + [w]
        w.show()

    def set_dates(self, date_expr, keep_post=None):
        rest = Q.strip_dates(self.search_box.text())
        rest = re.sub(r"(?<!\S)on:\S+", "", rest).strip()
        self.search_box.setText((date_expr + " " + rest).strip())
        self.run_search(keep_post)

    def search_day(self, date):
        self.set_dates(date, keep_post=self.viewer.pid if self.viewer else None)

    def pick_day(self, qdate):
        self.set_dates(qdate.toString("yyyy-MM-dd"))

    def step_day(self, forward):
        if not self.archive:
            return
        cur = self.calendar.selectedDate().toString("yyyy-MM-dd")
        d = self.archive.adjacent_day(cur, forward)
        if d:
            self.calendar.setSelectedDate(QDate.fromString(d, "yyyy-MM-dd"))
            self.set_dates(d)

    def on_this_day(self):
        d = self.calendar.selectedDate()
        rest = Q.strip_dates(self.search_box.text())
        rest = re.sub(r"(?<!\S)on:\S+", "", rest).strip()
        self.search_box.setText((f"on:{d.month():02d}-{d.day():02d} " + rest).strip())
        self.run_search()

    def whole_month(self):
        self.set_dates(f"{self.calendar.yearShown():04d}-{self.calendar.monthShown():02d}")

    def clear_search(self):
        self.search_box.clear()
        self.topic_box.setCurrentIndex(0)
        self.kind_box.setCurrentIndex(0)
        self.run_search()

    def paint_calendar(self, year, month):
        if not self.archive:
            return
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        counts = self.archive.day_counts(year, month)
        hi = QApplication.palette().color(QPalette.ColorRole.Highlight)
        for date, n in counts.items():
            f = QTextCharFormat()
            f.setFontWeight(QFont.Weight.Bold)
            c = QColor(hi)
            c.setAlpha(min(40 + n * 25, 200))
            f.setBackground(QBrush(c))
            f.setToolTip(f"{n} post{'s' if n != 1 else ''}")
            self.calendar.setDateTextFormat(QDate.fromString(date, "yyyy-MM-dd"), f)
        total = sum(counts.values())
        self.month_btn.setText(f"Whole month shown ({total:,} posts)")

    # ---- export folder
    def choose_export_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the export folder", export_folder())
        if d:
            self.settings["export_dir"] = d
            diary_paths.save_settings(self.settings)

    def export_results(self):
        ids = [self.model.post_id(r) for r in range(self.model.rowCount())]
        if not self.archive or not ids:
            QMessageBox.information(self, APP, "Search for something first: the export takes the posts listed.")
            return
        posts = self.archive.full_posts(ids)
        folder = export_folder()
        dlg = ExportDialog(len(posts), folder,
                           lambda v, ph: diary_export.media_size(self.archive.media_size, posts, v, ph), self)
        if not dlg.exec():
            return
        opts = dict(videos=dlg.videos.isChecked(), photos=dlg.photos.isChecked(), only_with=dlg.only.isChecked())
        need = diary_export.media_size(self.archive.media_size, posts, opts["videos"], opts["photos"])
        try:
            os.makedirs(folder, exist_ok=True)
            free = shutil.disk_usage(folder).free
        except OSError as e:
            QMessageBox.warning(self, APP, f"Cannot use the export folder\n{folder}\n\n{e}")
            return
        if need > free - 200e6:
            QMessageBox.warning(self, APP, f"Not enough room: the files need {need / 1e6:,.0f} MB and "
                                f"{folder} has {free / 1e6:,.0f} MB free.")
            return
        uris = {m.get("uri") for p in posts for m in json.loads(p["media"] or "[]") if m.get("uri")}
        zip_of = {}
        for u in uris:
            r = self.archive.con.execute("SELECT zip FROM media_index WHERE uri = ?", (u,)).fetchone()
            if r:
                zip_of[u] = r[0]
        q = self.search_box.text().strip()
        tv = self.topic_box.currentText().strip().lstrip("★").strip() if self.topic_value() else ""
        name = " ".join(x for x in (q, tv) if x) or "All posts"
        desc = self.current_query.describe() if self.current_query else ""
        prog = QProgressDialog("Exporting…", "Stop", 0, len(posts), self)
        prog.setWindowTitle(APP)
        prog.setMinimumDuration(300)
        th = ExportThread(folder, name, desc, posts, zip_of, opts)
        th.progress.connect(lambda i, n: prog.setValue(i))
        prog.canceled.connect(lambda: setattr(th, "stop", True))

        def done(res):
            prog.reset()
            index, written, saved, missing = res
            msg = (f"Wrote {written:,} post{'s' if written != 1 else ''}"
                   + (f" and {saved:,} file{'s' if saved != 1 else ''}" if saved else "")
                   + (" (stopped early)" if th.stop else "") + f" to\n{os.path.dirname(index)}")
            if missing:
                msg += f"\n\n{len(missing)} file(s) were not in the export zips."
            box = QMessageBox(QMessageBox.Icon.Information, APP, msg, parent=self)
            show = box.addButton("Open the page", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Open the folder", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is show:
                QDesktopServices.openUrl(QUrl.fromLocalFile(index))
            elif box.clickedButton() is not None and box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.ActionRole:
                open_folder(os.path.dirname(index))

        th.finished_ok.connect(done)
        th.failed.connect(lambda e: (prog.reset(), QMessageBox.warning(self, APP, f"The export failed:\n{e}")))
        self._export_thread = th
        th.start()

    def clear_cache(self):
        d = diary_paths.cache_dir()
        files = [os.path.join(d, f) for f in os.listdir(d)]
        size = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
        if not files:
            QMessageBox.information(self, APP, "The media cache is already empty.")
            return
        if QMessageBox.question(self, APP, f"Delete {len(files)} cached video/photo file(s), {size / 1e6:,.0f} MB?\n"
                                "They stay in your Facebook export zips and are copied out again when clicked."
                                ) == QMessageBox.StandardButton.Yes:
            if VideoWindow.instance is not None:
                VideoWindow.instance.close()
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass

    # ---- topics, import, help
    def edit_topics(self):
        dlg = TopicsDialog(self.topics, self)
        if dlg.exec():
            self.topics = dlg.topics
            Q.save_topics(diary_paths.topics_path(), self.topics)
            self.fill_topics()
            self.run_search()

    def first_import(self):
        src = diary_paths.default_source()
        if os.path.isdir(src) and diary_import.find_zips(src):
            self.do_import(src)
        else:
            self.reimport()

    def reimport(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder holding the Facebook export zip(s)",
                                                  diary_paths.default_source())
        if folder:
            self.do_import(folder)

    def do_import(self, folder):
        prog = QProgressDialog("Indexing your Facebook export…", None, 0, 0, self)
        prog.setWindowTitle(APP)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()
        if self.archive:
            self.archive.con.close()
            self.archive = None
        th = ImportThread(folder, diary_paths.db_path())
        th.message.connect(prog.setLabelText)
        err = []
        th.failed.connect(err.append)

        def done():
            prog.close()
            if err:
                QMessageBox.critical(self, APP, f"Import failed:\n{err[0]}")
            else:
                self.settings["source"] = folder
                diary_paths.save_settings(self.settings)
            if os.path.exists(diary_paths.db_path()):
                self._open_archive()
                self.run_search()
        th.finished.connect(done)
        self._import_thread = th
        th.start()

    def show_help(self):
        box = QMessageBox(self)
        box.setWindowTitle("Search syntax")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(Q.__doc__.split("\n", 1)[1].strip() +
                    "\n\nCalendar: shaded days have posts (darker = more). Clicking a day keeps your words and "
                    "topic but replaces the dates.\nDouble-click a post (or 'Open in window') to read it in its "
                    "own window. Click a photo to open it full size; videos play in their own FacebookDiary window.\n"
                    "Saving: 'Save to export folder' adds the post (text, links, Facebook address) to "
                    "'Saved posts.html' and copies its videos; right-click a photo or video to save just it. "
                    "File ▸ Export the search results (Ctrl+E) writes every listed post to a page of its own, "
                    "with their videos (and photos if you like). File ▸ Choose the export folder changes where.\n"
                    "Keys: Ctrl+L search bar · Ctrl+←/→ previous/next day · Alt+←/→ earlier/later post.")
        box.exec()

    def closeEvent(self, e):
        self.settings["size"] = [self.width(), self.height()]
        self.settings["splitter"] = self.splitter.sizes()
        self.settings["newest_first"] = self.order_box.currentIndex() == 1
        diary_paths.save_settings(self.settings)
        super().closeEvent(e)


def app_icon():
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        p = os.path.join(ICON_DIR, f"facebookdiary-{s}.png")
        if os.path.exists(p):
            icon.addFile(p, QSize(s, s))
    return icon


def main(argv):
    if "--import" in argv:
        i = argv.index("--import")
        folder = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("-") else diary_paths.default_source()
        diary_import.build(folder, diary_paths.db_path())
        s = diary_paths.load_settings()
        s["source"] = os.path.abspath(folder)
        diary_paths.save_settings(s)
        return 0
    query = " ".join(a for a in argv if not a.startswith("-")) or None
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP)
    app.setDesktopFileName("facebookdiary")
    app.setWindowIcon(app_icon())
    w = DiaryWindow(query)
    w.setWindowIcon(app_icon())
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
