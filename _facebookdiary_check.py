"""Headless checks for FacebookDiary (run: facebookdiary --check). Uses the real index in data/."""
import html
import json
import zipfile
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import diary_paths  # noqa: E402
import diary_query as Q  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    fails += not cond


def span(q):
    p = Q.parse(q)
    f = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t is not None else None
    return f(p.start), f(p.end)


# ---- parser
check("year", span("2013") == ("2013-01-01 00:00", "2014-01-01 00:00"))
check("month", span("2013-02") == ("2013-02-01 00:00", "2013-03-01 00:00"))
check("day", span("2013-01-17") == ("2013-01-17 00:00", "2013-01-18 00:00"))
check("named day", span("Jan 17 2013") == span("17 January 2013") == span("2013/1/17"))
check("hour", span("2013-01-17 14") == ("2013-01-17 14:00", "2013-01-17 15:00"))
check("minute", span("2013-01-17 2:30pm") == ("2013-01-17 14:30", "2013-01-17 14:31"))
check("range", span("2016-11-08 .. 2016-11-10") == ("2016-11-08 00:00", "2016-11-11 00:00"))
check("range to", span("2016-11 to 2017-01") == ("2016-11-01 00:00", "2017-02-01 00:00"))
check("since", span("since 2025-06") == ("2025-06-01 00:00", None))
check("before", span("before 2009") == (None, "2009-01-01 00:00"))
check("open end", span("2012..") == ("2012-01-01 00:00", None))
check("quoted year is text", Q.parse('"1984"').start is None and Q.parse('"1984"').fts == '"1984"')
check("time filter wraps", Q.parse("time:22:00-02:00").tod == (1320, 120))
check("bare time span", Q.parse("9pm-11pm").tod == (1260, 1380))
check("on:", Q.parse("on:jan-17,12/25").md == ["01-17", "12-25"])
check("weekday", Q.parse("weekday:sat,sun").weekdays == [6, 7])
check("OR + negative", (lambda p: p.fts == '("nietzsche" OR "kant")' and p.negatives == ['"hegel"'])(Q.parse("nietzsche OR kant -hegel")))
check("prefix", Q.parse("democ*").fts == '"democ"*')
_te = Q.topic_expansion("Muppets", Q.DEFAULT_TOPICS)
check("topic expands", _te[0] == "sql" and _te[2][-1].startswith('"muppets" OR'), str(_te))
_tv = Q.topic_expansion("V", {"V": [".mp4", "has:photo", "kermit"]})
check("topic mixes file types, filters and words", 'lower(media) LIKE' in _tv[1] and _tv[1].count('id IN (') == 2 and '%.mp4"%' in _tv[2] and '"kermit"' in _tv[2], str(_tv))
check("strip dates keeps words", Q.strip_dates("trump 2016-11-08 .. 2016-11-10 time:9am-5pm") == "trump time:9am-5pm")
for bad in ("2013-02-30", "on:13-01", "2014 .. 2013", "time:25:00-26:00"):
    try:
        Q.parse(bad)
        check(f"rejects {bad}", False)
    except Q.QueryError:
        check(f"rejects {bad}", True)

# ---- GUI against the real index
if not os.path.exists(diary_paths.db_path()):
    print("no index yet: run  facebookdiary --import")
    sys.exit(1 if fails else 0)
from PyQt6.QtWidgets import QApplication  # noqa: E402
import facebookdiary as F  # noqa: E402

app = QApplication(sys.argv[:1])
w = F.DiaryWindow("")
a = w.archive
total = int(a.meta["count"])
check("all posts listed", w.model.rowCount() == total, f"{w.model.rowCount()} vs {total}")
w.search_box.setText("2016-11-08")
w.run_search()
n = w.model.rowCount()
check("one day", n > 0 and all(r["date"] == "2016-11-08" for r in w.model.rows), str(n))
check("viewer shows first post", w.viewer.pid == w.model.post_id(0))
html_ = w.viewer.browser.toHtml()
check("viewer has date header", "November 8, 2016" in html_)
w.step_day(True)
check("next day", w.model.rows and w.model.rows[0]["date"] > "2016-11-08", w.search_box.text())
w.search_box.setText("trump 2016")
w.run_search()
check("words survive calendar click", (w.pick_day(F.QDate(2016, 11, 9)), w.search_box.text())[1] == "2016-11-09 trump")
# a photo post renders an image from the zip
pid = a.con.execute("SELECT id FROM posts WHERE nmedia = 1 AND media NOT LIKE '%.mp4%' LIMIT 1").fetchone()[0]
w.viewer.show_post(pid)
check("Facebook link for photo post", "Open on Facebook" in w.viewer.browser.toPlainText()
      and "facebook.com/photo/?fbid=" in w.viewer.browser.toHtml())
wp = a.con.execute("SELECT id FROM posts WHERE source = 'other' AND fb_url IS NOT NULL LIMIT 1").fetchone()
check("profile posts have a Facebook link", wp is not None and (w.viewer.show_post(wp[0]) or True)
      and "Open on Facebook" in w.viewer.browser.toPlainText())
w.viewer.show_post(pid)
lp = a.con.execute("SELECT id, links FROM posts WHERE links != '[]' AND instr(text, json_extract(links, '$[0]')) > 0 "
                   "AND json_array_length(links) = 1 LIMIT 1").fetchone()
w.viewer.show_post(lp[0])
_u = json.loads(lp[1])[0]
check("link in text not repeated", w.viewer.browser.toHtml().count('href="' + html.escape(_u, quote=True)) == 1, _u)
w.viewer.show_post(pid)
check("photo loaded from zip", "<img" in w.viewer.browser.toHtml())
dpid = a.con.execute("SELECT id FROM posts WHERE nmedia = 1 AND text != '' AND media LIKE '%description%' "
                      "AND instr(media, substr(text, 1, 30)) > 0 LIMIT 1").fetchone()[0]
w.viewer.show_post(dpid)
_t = a.post(dpid)["text"].strip().splitlines()[0][:40]
check("photo caption not repeated", w.viewer.browser.toPlainText().count(_t) == 1, _t)
vid = a.con.execute("SELECT id FROM posts WHERE media LIKE '%.mp4%' LIMIT 1").fetchone()[0]
w.viewer.show_post(vid)
check("video link", "Play video" in w.viewer.browser.toPlainText())
p = a.post(pid)
nxt = a.neighbour(p["ts"], p["id"], True)
check("chronological neighbour", nxt and a.post(nxt)["ts"] >= p["ts"])
w.topic_box.setCurrentIndex(w.topic_box.findData("Baseball"))
w.search_box.setText("2018")
w.run_search()
check("topic search", 0 < w.model.rowCount() < 200, str(w.model.rowCount()))
w.topic_box.setCurrentIndex(0)
w.kind_box.setCurrentIndex(w.kind_box.findData("Status"))
w.search_box.setText("on:01-17")
w.run_search()
check("kind + on-this-day", w.model.rowCount() > 0 and all(r["kind"] == "Status" and r["date"][5:] == "01-17" for r in w.model.rows))
w.search_box.setText("2014 .. 2013")
w.run_search()
check("error shown, not raised", "⚠" in w.status.text())
w.pop_out(pid)
check("pop-out window", w.windows and w.windows[-1].view.pid == pid)
if F.HAVE_WEBENGINE:
    from PyQt6.QtCore import QEventLoop, QTimer as _T
    vuri = a.con.execute("SELECT json_extract(j.value,'$.uri') FROM posts, json_each(posts.media) j "
                         "WHERE json_extract(j.value,'$.uri') LIKE '%.mp4' LIMIT 1").fetchone()[0]
    vw = F.VideoWindow.play(a.media_file(vuri), "test", "caption")
    vw.view.page().setAudioMuted(True)
    loop = QEventLoop(); vw.view.titleChanged.connect(lambda t: t in ("playing",) or t.startswith("error") and loop.quit())
    vw.view.titleChanged.connect(lambda t: t == "playing" and loop.quit()); _T.singleShot(15000, loop.quit); loop.exec()
    check("in-app video plays", vw.view.title() == "playing", vw.view.title())
    vw.close()
w.kind_box.setCurrentIndex(w.kind_box.findData("__comments__"))
# a person from the user's own index (no names in the code: this file is published)
_who = a.con.execute("SELECT target FROM posts WHERE kind IN ('Comment','Reply') AND target != '' "
                     "AND target NOT LIKE 'your own%' GROUP BY target ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
_who = _who.split("'s ")[0].split("\u2019s ")[0]
w.search_box.setText(f'to:"{_who}"')
w.run_search()
check("comments to a person", w.model.rowCount() > 0 and all(r["kind"] in ("Comment", "Reply") and _who in r["target"]
                                                            for r in w.model.rows), str(w.model.rowCount()))
check("comment preview names the target", F.preview_text(w.model.rows[0]).startswith("↩ "))
w.table.selectRow(0)
check("viewer explains the missing original", "only who you answered" in w.viewer.browser.toPlainText())
w.kind_box.setCurrentIndex(w.kind_box.findData("__posts__"))
w.search_box.setText("2016-11-08")
w.run_search()
check("posts only hides comments", w.model.rows and all(r["kind"] not in ("Comment", "Reply") for r in w.model.rows))
check("type:comment parses", Q.parse("type:comments").kinds == ["comments"])
from PyQt6.QtWidgets import QDialog as _QD  # noqa: E402
_td = F.TopicsDialog({"Baseball": ["baseball"], "Zoo": ["lion"]})
check("topic editor says which topic", "Baseball" in _td.editing.text())
import tempfile as _tf, shutil as _sh, diary_export as E  # noqa: E401,E402
_xd = _tf.mkdtemp(prefix="fbd-export-")
F.SETTINGS["export_dir"] = _xd
try:
    _vp = a.con.execute("SELECT id FROM posts WHERE media LIKE '%.mp4%' AND links != '[]' LIMIT 1").fetchone() or \
        a.con.execute("SELECT id FROM posts WHERE media LIKE '%.mp4%' LIMIT 1").fetchone()
    w.viewer.show_post(_vp[0])
    check("viewer offers Save video", "save:/" in w.viewer.browser.toHtml())
    w.viewer.save_post("videos")
    _page = open(os.path.join(_xd, E.SAVED_PAGE), encoding="utf-8").read()
    _mp4 = [f for f in os.listdir(_xd) if f.endswith(".mp4")]
    check("save post writes page + video", f"<!--post:{_vp[0]}-->" in _page and _mp4, str(os.listdir(_xd)))
    w.viewer.save_post("videos")
    check("saving twice adds no duplicate", open(os.path.join(_xd, E.SAVED_PAGE), encoding="utf-8").read()
          .count(f"<!--post:{_vp[0]}-->") == 1)
    _vf = os.path.join(_xd, _mp4[0])
    _orig = a.media_bytes(json.loads(a.post(_vp[0])["media"])[0]["uri"])
    check("saved video is byte-identical", open(_vf, "rb").read() == _orig)
    _lp = a.post(a.con.execute("SELECT id FROM posts WHERE text LIKE '%https://%' AND links = '[]' LIMIT 1").fetchone()[0])
    check("links written in the text are exported", E.post_links(_lp) and E.post_links(_lp)[0] in _lp["text"])
    w.kind_box.setCurrentIndex(0)
    w.search_box.setText("2016-11")
    w.topic_box.setCurrentText("")
    w.run_search()
    _posts = a.full_posts([w.model.post_id(r) for r in range(w.model.rowCount())])
    _z = {}
    def _opener(u):
        r = a.con.execute("SELECT zip FROM media_index WHERE uri = ?", (u,)).fetchone()
        zf = _z.get(r[0]) or _z.setdefault(r[0], zipfile.ZipFile(r[0]))
        return zf.open(u), zf.getinfo(u).file_size
    _idx, _n, _nf, _miss = E.export_search(_xd, "2016-11", "November 2016", _posts, _opener, videos=True, photos=True)
    _html = open(_idx, encoding="utf-8").read()
    check("search export writes every post", _n == len(_posts) and _html.count("<!--post:") == len(_posts),
          f"{_n} of {len(_posts)}")
    check("search export copies media", _nf == len(os.listdir(os.path.dirname(_idx))) - 1 and not _miss, f"{_nf} {_miss}")
    _idx2, _n2, _, _ = E.export_search(_xd, "2016-11", "", _posts, _opener, videos=False, only_with=True)
    check("only-with-links export", 0 < _n2 < _n and os.path.dirname(_idx2) != os.path.dirname(_idx), f"{_n2}/{_n}")
finally:
    F.SETTINGS.pop("export_dir", None)
    _sh.rmtree(_xd, ignore_errors=True)
# ---- Windows / macOS behaviour, imitated on Linux
import datetime as _dt, unittest.mock as _mock  # noqa: E401,E402
import diary_import as _DI, diary_query as _DQ  # noqa: E401,E402
check("Linux data folder unchanged", diary_paths.default_data_dir() == os.path.join(diary_paths.HERE, "data"))
with _mock.patch.object(diary_paths.os, "name", "nt"), _mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}):
    check("Windows data folder", diary_paths.default_data_dir().endswith("FacebookDiary")
          and diary_paths.default_data_dir().startswith(r"C:\Users\u\AppData\Local"))
with _mock.patch.object(diary_paths.sys, "platform", "darwin"):
    check("macOS data folder", "Library/Application Support/FacebookDiary" in diary_paths.default_data_dir())
_d = _dt.datetime(2016, 5, 3, 14, 5)
check("portable long date", _DI.long_day(_d) == "Tuesday, May 3, 2016", _DI.long_day(_d))
check("portable clock", (_DI.short_clock(_d), _DI.short_clock(_d.replace(hour=0)), _DI.short_clock(_d.replace(hour=12)))
      == ("2:05 pm", "12:05 am", "12:05 pm"))
import re as _re  # noqa: E402
check("no Linux-only date codes left", not any(_re.search(r"strftime\([^)]*%-|:%-", open(os.path.join(HERE, f), encoding="utf-8").read())
                                              for f in ("facebookdiary.py", "diary_export.py", "diary_query.py", "diary_import.py")))
_want = _DQ.epoch(_dt.datetime(1965, 7, 1))
def _no_negative(*a):
    raise OSError(22, "Invalid argument")
with _mock.patch.object(_DQ.time, "mktime", _no_negative):
    check("pre-1970 search without mktime", abs(_DQ.epoch(_dt.datetime(1965, 7, 1)) - _want) <= 3600)
_q = Q.parse("1965-07")
check("pre-1970 search describes", "1965" in _q.describe() and _DQ.local_dt(_q.start).year == 1965)
if F.HAVE_WEBENGINE:
    _bad = os.path.join(diary_paths.cache_dir(), "not-a-video.mp4")
    open(_bad, "wb").write(b"this is not a video")
    _opened = []
    with _mock.patch.object(F, "open_media", lambda p: _opened.append(p) or True):
        _vw = F.VideoWindow.play(_bad, "bad", "")
        _loop = QEventLoop(); _T.singleShot(8000, _loop.quit)
        _vw.view.titleChanged.connect(lambda t: t.startswith("error") and _T.singleShot(200, _loop.quit)); _loop.exec()
    check("undecodable video goes to the system player", _opened == [_bad] and F.VideoWindow.cant_decode
          and not _vw.isVisible(), f"{_opened} {_vw.view.title()}")
    F.VideoWindow.cant_decode = False
    os.remove(_bad)
mojibake = a.con.execute("SELECT count(*) FROM posts WHERE text LIKE '%â€%' OR text LIKE '%Ã©%'").fetchone()[0]
check("text decoded (no mojibake)", mojibake == 0, str(mojibake))
w.settings = {}   # don't overwrite the user's saved window state
w.closeEvent = lambda e: None
print("\nall checks passed" if not fails else f"\n{fails} check(s) failed")
sys.exit(1 if fails else 0)
