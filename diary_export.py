"""Saving posts' links and media files out of the archive into an export folder (no Qt here).

Layout of the export folder:
  Saved posts.html                 one entry per post saved from the viewer (appended, never duplicated)
  2016-05-03 14.32 1234567.mp4     videos/photos saved from the viewer
  <search name> (2026-11-22 15.04)/index.html + media   one subfolder per whole-search export
"""
import datetime as dt
import html
import json
import os
import re
import shutil

import diary_import

SAVED_PAGE = "Saved posts.html"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".ogv", ".avi", ".wmv", ".mkv", ".flv", ".mpg", ".mpeg", ".3gp")
URL_RE = re.compile(r"https?://[^\s<>\"]+")

PAGE_HEAD = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font:15px/1.45 sans-serif;max-width:820px;margin:24px auto;padding:0 16px;color:#222;background:#fff}}
h1{{font-size:22px}} .post{{border-top:1px solid #ddd;padding:12px 0}}
.when{{color:#666;font-size:13px}} .text{{white-space:pre-wrap;margin:6px 0}}
.to{{border-left:3px solid #999;padding-left:8px;color:#666;font-style:italic}}
ul{{margin:4px 0;padding-left:22px}} li{{word-break:break-all}} img{{max-width:100%;height:auto}}
@media (prefers-color-scheme: dark){{body{{background:#1b1b1b;color:#ddd}} a{{color:#8ab4f8}} .post{{border-color:#333}}}}
</style></head><body>
<h1>{title}</h1>
<p class="when">{note}</p>
"""


def default_export_dir():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    base = docs if os.path.isdir(docs) else os.path.expanduser("~")
    return os.path.join(base, "FacebookDiary export")


def export_dir(settings):
    return settings.get("export_dir") or default_export_dir()


def is_video(uri):
    return uri.lower().endswith(VIDEO_EXT)


def safe_name(s, limit=80):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:limit].rstrip(" .") or "export"


def media_name(p, uri):
    """'2016-05-03 14.32 1234567.mp4': sorts by date and keeps Facebook's file id (unique)."""
    d = dt.datetime.fromtimestamp(p["ts"])
    return f"{d:%Y-%m-%d %H.%M} {os.path.basename(uri)}"


def post_links(p):
    """Every web address in the post: attachments first, then ones written in the text."""
    out, seen = [], set()
    found = list(json.loads(p["links"] or "[]"))
    for field in ("text", "extra"):
        found += [m.group(0).rstrip(".,);") for m in URL_RE.finditer(p[field] or "")]
    for u in found:
        k = u.rstrip("/")
        if u and k not in seen:
            seen.add(k)
            out.append(u)
    return out


def fb_url_of(p):
    if "fb_url" in p.keys() and p["fb_url"]:
        return p["fb_url"]
    return diary_import.facebook_url(json.loads(p["media"] or "[]"))


def copy_media(opener, uri, dest):
    """Stream one file out of the export zips. Returns dest, or None when it isn't in the zips.
    A file already there with the same size is kept (saving twice costs nothing)."""
    got = opener(uri)          # (file object, size) or None
    if got is None:
        return None
    src, size = got
    with src:
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            return dest
        with open(dest + ".part", "wb") as f:
            shutil.copyfileobj(src, f, 1 << 20)
    os.replace(dest + ".part", dest)
    return dest


def entry_html(p, files=(), links=None):
    """One post as an HTML block. files: [(relative path, original uri)] already saved beside the page."""
    d = dt.datetime.fromtimestamp(p["ts"])
    when = f"{diary_import.long_day(d)}, {diary_import.short_clock(d)}"
    out = [f'<div class="post" id="post{p["id"]}"><!--post:{p["id"]}-->',
           f'<div class="when">{html.escape(when)} · {html.escape(p["kind"])}']
    fb = fb_url_of(p)
    if fb:
        out.append(f' · <a href="{html.escape(fb, quote=True)}">Open on Facebook</a>')
    out.append("</div>")
    if p["kind"] in ("Comment", "Reply") and p["title"]:
        out.append(f'<div class="to">↩ {html.escape(p["title"])}</div>')
    elif p["title"]:
        out.append(f"<div><i>{html.escape(p['title'])}</i></div>")
    for field in ("text", "extra"):
        if p[field]:
            out.append(f'<div class="text">{html.escape(p[field])}</div>')
    if p["place"]:
        out.append(f"<div>📍 {html.escape(p['place'])}</div>")
    links = post_links(p) if links is None else links
    if links:
        out.append("<ul>" + "".join(f'<li>🔗 <a href="{html.escape(u, quote=True)}">{html.escape(u)}</a></li>'
                                    for u in links) + "</ul>")
    for rel, uri in files:
        href = html.escape(rel.replace(os.sep, "/").replace(" ", "%20"), quote=True)
        if is_video(uri):
            out.append(f'<div>🎬 <a href="{href}">{html.escape(os.path.basename(rel))}</a></div>')
        else:
            out.append(f'<div><a href="{href}"><img src="{href}" loading="lazy" alt=""></a></div>')
    out.append("</div>\n")
    return "".join(out)


def _start_page(path, title, note):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(PAGE_HEAD.format(title=html.escape(title), note=html.escape(note)))


def saved_page_has(folder, pid):
    path = os.path.join(folder, SAVED_PAGE)
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        return f"<!--post:{pid}-->" in f.read()


def save_post(folder, p, opener, media="videos"):
    """Save one post into the export folder: its files (media='videos', 'all' or 'none') beside
    'Saved posts.html', and an entry on that page (once). Returns (page path, [saved files], [missing uris])."""
    os.makedirs(folder, exist_ok=True)
    files, missing = [], []
    for m in json.loads(p["media"] or "[]"):
        uri = m.get("uri", "")
        if not uri or media == "none" or (media == "videos" and not is_video(uri)):
            continue
        name = media_name(p, uri)
        if copy_media(opener, uri, os.path.join(folder, name)):
            files.append((name, uri))
        else:
            missing.append(uri)
    page = os.path.join(folder, SAVED_PAGE)
    _start_page(page, "Saved posts", "Saved from FacebookDiary. Videos and photos sit beside this page.")
    if not saved_page_has(folder, p["id"]):
        with open(page, "a", encoding="utf-8") as f:
            f.write(entry_html(p, files))
    return page, [os.path.join(folder, n) for n, _ in files], missing


def save_one_file(folder, p, opener, uri):
    os.makedirs(folder, exist_ok=True)
    return copy_media(opener, uri, os.path.join(folder, media_name(p, uri)))


def export_search(folder, name, description, posts, opener, videos=True, photos=False,
                  only_with=False, progress=None, cancelled=lambda: False):
    """Write a subfolder 'name (date time)' with index.html listing the posts, plus their media.
    only_with: keep only posts that have links or saved files. Returns (index path, posts written, files, missing)."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H.%M")
    sub = os.path.join(folder, f"{safe_name(name, 60)} ({stamp})")
    n = 1
    while os.path.exists(sub):
        n += 1
        sub = os.path.join(folder, f"{safe_name(name, 60)} ({stamp}) {n}")
    os.makedirs(sub)
    index = os.path.join(sub, "index.html")
    with open(index, "w", encoding="utf-8") as f:
        f.write(PAGE_HEAD.format(title=html.escape(name),
                                 note=html.escape(f"{description} — exported from FacebookDiary {stamp}")))
        written = saved = 0
        missing = []
        for i, p in enumerate(posts):
            if cancelled():
                break
            if progress:
                progress(i, len(posts))
            files = []
            for m in json.loads(p["media"] or "[]"):
                uri = m.get("uri", "")
                if uri and ((videos and is_video(uri)) or (photos and not is_video(uri))):
                    fname = media_name(p, uri)
                    if copy_media(opener, uri, os.path.join(sub, fname)):
                        files.append((fname, uri))
                    else:
                        missing.append(uri)
            links = post_links(p)
            if only_with and not (links or files):
                continue
            f.write(entry_html(p, files, links))
            written += 1
            saved += len(files)
        f.write("</body></html>\n")
    return index, written, saved, missing


def media_size(sizer, posts, videos=True, photos=False):
    """Total bytes the chosen media would take (sizer(uri) -> bytes or 0)."""
    total = 0
    for p in posts:
        for m in json.loads(p["media"] or "[]"):
            uri = m.get("uri", "")
            if uri and ((videos and is_video(uri)) or (photos and not is_video(uri))):
                total += sizer(uri)
    return total
