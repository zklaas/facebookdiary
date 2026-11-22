"""Build the FacebookDiary database from a Facebook "Download your information" export.

The export zips are read in place (nothing is unpacked): post JSON is parsed into a
SQLite database with an FTS5 full-text index, and every photo/video path is mapped to
the zip that holds it so the viewer can load media straight from the archive.

Usage:  python3 diary_import.py [folder-with-zips] [--db path]
"""
import collections
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import zipfile
from urllib.parse import urlparse

SCHEMA_VERSION = 3

POST_FILES = re.compile(r"your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_\d+\.json$")
OTHER_FILE = "your_facebook_activity/posts/posts_on_other_pages_and_profiles.json"
COMMENT_FILES = ("your_facebook_activity/comments_and_reactions/comments.json",
                 "your_facebook_activity/groups/your_comments_in_groups.json")
GROUP_POSTS_FILE = "your_facebook_activity/groups/group_posts_and_comments.json"
# "Sam Jones replied to Alex Smith's comment." -> ("replied to", "Alex Smith's comment")
TARGET_RE = re.compile(r"\b(commented on|replied to) (.+?)\.?$")
MEDIA_PREFIX = "your_facebook_activity/posts/"

STOPWORDS = set("""
a about above after again against all almost also although always am among an and another any anyone
anything are aren't around as at away back be because been before being below between both but by
can can't cannot could couldn't did didn't do does doesn't doing don't done down during each either
else enough even ever every everyone everything few for from further get gets getting go goes going
gone got had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him
himself his how how's however i i'd i'll i'm i've if in into is isn't it it's its itself just know
let let's like made make makes making many may maybe me might more most much must my myself need
never new no nor not nothing now of off often oh ok okay on once one only or other others otherwise
ought our ours ourselves out over own people per perhaps quite rather really right said same say says
see seem seems seen shall shan't she she'd she'll she's should shouldn't since so some someone
something still such sure take than that that's the their theirs them themselves then there there's
these they they'd they'll they're they've thing things think this those though through thus to too
two under until up upon us use used very want was wasn't way we we'd we'll we're we've well went
were weren't what what's whatever when when's where where's whether which while who who's whole whom
whose why why's will with within without won't would wouldn't yes yet you you'd you'll you're you've
your yours yourself yourselves actually already anyway around got gonna good great lot lots little
look looks pretty probably put thought time times today yeah year years day days going come comes
came first last long better best bad back point kind keep given give doesn't trying try tell told
called call sort part far ago least real reason means mean word words getting less different shared
post posted http https www com html amp
""".split())

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{3,}")
HASHTAG_RE = re.compile(r"(?<![\w&])#(\w{2,})")



def long_day(d):
    """'Tuesday, May 3, 2016' (strftime's %-d is not on Windows)."""
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def short_clock(d):
    """'2:05 pm' (strftime's %-I is not on Windows)."""
    return f"{(d.hour % 12) or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"

def fix_text(s):
    """Facebook exports UTF-8 text with each byte escaped as a Latin-1 code point."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def fix(obj):
    if isinstance(obj, str):
        return fix_text(obj)
    if isinstance(obj, list):
        return [fix(x) for x in obj]
    if isinstance(obj, dict):
        return {k: fix(v) for k, v in obj.items()}
    return obj


def classify(title):
    t = (title or "").lower()
    rules = [
        ("updated his status", "Status"), ("updated her status", "Status"), ("updated their status", "Status"),
        ("shared a post", "Shared post"), ("shared a link", "Link"), ("shared a memory", "Memory"),
        ("shared a reel", "Reel"), ("shared a group", "Group"), ("shared an episode", "Episode"),
        ("shared a quote", "Quote"), ("shared a note", "Note"), ("shared an album", "Album"),
        ("shared an event", "Event"), ("shared a photo", "Shared photo"), ("shared a video", "Shared video"),
        ("new photo", "Photo"), ("new video", "Video"), (" photos", "Photo"), ("added a photo", "Photo"),
        (" videos", "Video"), ("was with", "Status"), ("answered a question", "Status"), ("wrote on", "Wall post"), ("posted in", "Group post"),
        ("is at", "Check-in"), ("was at", "Check-in"), ("checked in", "Check-in"), ("posted something via", "App post"),
        ("is celebrating", "Friendversary"), ("celebrating", "Friendversary"), ("feeling", "Status"),
    ]
    for needle, kind in rules:
        if needle in t:
            return kind
    if "shared" in t:
        return "Shared"
    return "Post" if not t else "Other"


def domain(url):
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    for p in ("www.", "m.", "mobile.", "media1.", "media.", "amp."):
        if host.startswith(p):
            host = host[len(p):]
    return host


def local_fields(ts):
    d = dt.datetime.fromtimestamp(ts)
    return d.strftime("%Y-%m-%d"), d.strftime("%H:%M:%S"), d.strftime("%m-%d"), d.year, d.isoweekday()


def parse_post(p):
    texts, links, media, places, events, extras = [], [], [], [], [], []
    edited = None
    for x in p.get("data", []) or []:
        if "post" in x and x["post"]:
            texts.append(x["post"])
        if "update_timestamp" in x:
            edited = x["update_timestamp"]
    for a in p.get("attachments", []) or []:
        for x in a.get("data", []) or []:
            if "external_context" in x:
                ec = x["external_context"]
                if ec.get("url"):
                    links.append(ec["url"])
                if ec.get("name"):
                    extras.append(ec["name"])
            if "media" in x:
                m = x["media"]
                media.append({
                    "uri": m.get("uri", ""),
                    "title": m.get("title", ""),
                    "description": m.get("description", ""),
                    "ts": m.get("creation_timestamp"),
                })
            if "place" in x:
                pl = x["place"]
                name = pl.get("name") or ""
                addr = pl.get("address") or ""
                places.append(name if (not addr or addr == name) else f"{name}, {addr}")
            if "text" in x and x["text"]:
                extras.append(x["text"])
            if "name" in x and isinstance(x["name"], str):
                extras.append(x["name"])
            if "event" in x:
                ev = x["event"]
                events.append(ev.get("name", ""))
            if "poll" in x:
                q = x["poll"].get("question", "")
                opts = [o.get("option", "") for o in x["poll"].get("options", []) or []]
                extras.append("Poll: " + q + ("\n  • " + "\n  • ".join(opts) if opts else ""))
            if "fun_fact" in x:
                ff = x["fun_fact"]
                extras.append(f"{ff.get('question', '')}\n{ff.get('answer', '')}")
    tags = [t.get("name", "") if isinstance(t, dict) else str(t) for t in p.get("tags", []) or []]
    return texts, links, media, places, events, extras, tags, edited


def parse_other(p):
    """posts_on_other_pages_and_profiles.json uses the label_values layout."""
    text, edited, links, target = "", None, [], ""
    for lv in p.get("label_values", []):
        lab = lv.get("label") or lv.get("title") or ""
        if lab == "Message":
            text = lv.get("value", "")
        elif lab == "Last modified":
            edited = lv.get("timestamp_value")
        elif lab == "Target" and lv.get("value"):
            target = lv["value"]
        for sub in lv.get("dict", []) or []:
            for leaf in sub.get("dict", []) or [sub]:
                if leaf.get("label") == "URL" and leaf.get("value"):
                    links.append(leaf["value"])
    return text, edited, links, target


def facebook_url(media):
    """The export has no post links, but photo/video files are named by their Facebook ID, and the
    photo/video page on Facebook shows the whole post (photo form confirmed by the user, 2026-11-22).
    Posts on other people's profiles carry an fbid instead: facebook.com/<fbid> (also confirmed)."""
    for m in media:
        fid, ext = os.path.splitext(os.path.basename(m.get("uri", "")))
        if fid.isdigit():
            if ext.lower() in (".mp4", ".mov", ".webm"):
                return f"https://www.facebook.com/watch/?v={fid}"
            return f"https://www.facebook.com/photo/?fbid={fid}"
    return None


def comment_target(title, owner_hint=None):
    """Who/what a comment answered, from the export's title (the other person's words aren't exported)."""
    m = TARGET_RE.search(title or "")
    if not m:
        return ""
    t = m.group(2).strip()
    t = re.sub(r"^(his|her|their) own ", "your own ", t)
    return t


def parse_comment(c):
    text, author, group = "", "", ""
    for e in c.get("data", []) or []:
        cm = e.get("comment") or {}
        if cm.get("comment"):
            text = cm["comment"]
        author = cm.get("author", author)
        group = cm.get("group", group) or group
    texts, links, media, places, events, extras, tags, edited = parse_post({"attachments": c.get("attachments", [])})
    return text, group, links, media, extras


def create_schema(con):
    con.executescript("""
    DROP TABLE IF EXISTS posts; DROP TABLE IF EXISTS posts_fts; DROP TABLE IF EXISTS media_index;
    DROP TABLE IF EXISTS terms; DROP TABLE IF EXISTS meta;
    CREATE TABLE posts(
        id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, edited_ts INTEGER,
        date TEXT, time TEXT, md TEXT, year INTEGER, weekday INTEGER,
        kind TEXT, title TEXT, text TEXT, extra TEXT, place TEXT, tags TEXT,
        links TEXT, domains TEXT, media TEXT, nmedia INTEGER, source TEXT, target TEXT, fb_url TEXT);
    CREATE INDEX posts_ts ON posts(ts); CREATE INDEX posts_date ON posts(date);
    CREATE INDEX posts_md ON posts(md); CREATE INDEX posts_kind ON posts(kind);
    CREATE VIRTUAL TABLE posts_fts USING fts5(
        text, extra, title, place, links, content='posts', content_rowid='id',
        tokenize="unicode61 remove_diacritics 2");
    CREATE TABLE media_index(uri TEXT PRIMARY KEY, zip TEXT, size INTEGER);
    CREATE TABLE terms(term TEXT, kind TEXT, count INTEGER, PRIMARY KEY(kind, term));
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)


def find_zips(folder):
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".zip"))


def build(folder, db_path, progress=print):
    zips = find_zips(folder)
    if not zips:
        raise SystemExit(f"No .zip files found in {folder}")
    tmp = db_path + ".building"
    if os.path.exists(tmp):
        os.remove(tmp)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(tmp)
    create_schema(con)

    raw_posts, raw_other, raw_comments, raw_group_posts, media_rows = [], [], [], [], []
    for z in zips:
        progress(f"Reading {os.path.basename(z)} …")
        with zipfile.ZipFile(z) as zf:
            for info in zf.infolist():
                n = info.filename
                if POST_FILES.search(n):
                    raw_posts += json.loads(zf.read(n))
                elif n.endswith(OTHER_FILE):
                    raw_other += json.loads(zf.read(n))
                elif n.endswith(COMMENT_FILES):
                    d = json.loads(zf.read(n))
                    raw_comments += next(iter(d.values())) if isinstance(d, dict) else d
                elif n.endswith(GROUP_POSTS_FILE):
                    d = json.loads(zf.read(n))
                    raw_group_posts += next(iter(d.values())) if isinstance(d, dict) else d
                elif n.startswith(MEDIA_PREFIX) and not n.endswith("/") and not n.endswith(".json"):
                    media_rows.append((n, z, info.file_size))
    if not raw_posts:
        raise SystemExit("No your_posts__check_ins__photos_and_videos_*.json found in the zips.")
    progress(f"Indexing {len(raw_posts) + len(raw_other) + len(raw_group_posts):,} posts and "
             f"{len(raw_comments):,} comments …")
    con.executemany("INSERT OR REPLACE INTO media_index VALUES(?,?,?)", media_rows)

    df_words, df_tags, df_domains = collections.Counter(), collections.Counter(), collections.Counter()
    rows = []
    seen = set()
    for p in raw_posts + raw_group_posts:
        p = fix(p)
        ts = p.get("timestamp")
        if not ts:
            continue
        texts, links, media, places, events, extras, tags, edited = parse_post(p)
        title = p.get("title", "") or ""
        text = "\n\n".join(texts)
        # a lone photo's caption is the post when there is no status text
        if not text and len(media) == 1 and media[0]["description"]:
            text = media[0]["description"]
            media[0]["description"] = ""
        extra = "\n".join(e for e in extras + [f"Event: {e}" for e in events] if e)
        key = (ts, text, tuple(links), tuple(m["uri"] for m in media))
        if key in seen:
            continue
        seen.add(key)
        rows.append((ts, edited, classify(title) if title else "Group post", title, text, extra, "; ".join(places),
                     ", ".join(tags), links, media, "posts", "", None))
    by_text = {}
    for i, r in enumerate(rows):
        if r[4]:
            by_text.setdefault(" ".join(r[4].split()), i)
    for p in raw_other:
        p = fix(p)
        ts = p.get("timestamp")
        if not ts:
            continue
        text, edited, links, target = parse_other(p)
        title = f"Wrote on {target}'s profile." if target else "Post on another page or profile"
        fbid = str(p.get("fbid") or "")
        url = f"https://www.facebook.com/{fbid}" if fbid.isdigit() else None
        # the same post often also sits in the main posts file ("wrote on X's timeline"): keep that
        # copy (it has the person's name and any photos) and give it this file's Facebook link
        twin = by_text.get(" ".join((text or "").split()))
        if twin is not None and abs(rows[twin][0] - ts) <= 300:
            r = rows[twin]
            rows[twin] = r[:12] + (r[12] or url,)
            continue
        rows.append((ts, edited, "Wall post", title, text, "", "", "", links, [], "other", target, url))
    skipped = 0
    for c in raw_comments:
        c = fix(c)
        ts = c.get("timestamp")
        if not ts:
            continue
        text, group, links, media, extras = parse_comment(c)
        if not (text or links or media):
            skipped += 1        # title only: a sticker/GIF or a comment Facebook didn't keep the words of
            continue
        title = c.get("title", "") or ""
        target = comment_target(title)
        kind = "Reply" if "replied to" in title else "Comment"
        if group:
            title = f"{title.rstrip('.')} in the group {group}."
        key = ("c", ts, text)
        if key in seen:
            continue
        seen.add(key)
        rows.append((ts, None, kind, title, text, "\n".join(e for e in extras if e), "", "", links, media,
                     "group comments" if group else "comments", target, None))

    rows.sort(key=lambda r: r[0])
    out = []
    for i, (ts, edited, kind, title, text, extra, place, tags, links, media, source, target, fb_url) in enumerate(rows, 1):
        date, time, md, year, wd = local_fields(ts)
        doms = sorted({domain(u) for u in links} - {""})
        out.append((i, ts, edited, date, time, md, year, wd, kind, title, text, extra, place, tags,
                    json.dumps(links, ensure_ascii=False), " ".join(doms),
                    json.dumps(media, ensure_ascii=False), len(media), source, target,
                    fb_url or facebook_url(media)))
        body = f"{text}\n{extra}\n" + " ".join(m["description"] + " " + m["title"] for m in media)
        df_words.update({w.lower().strip("'-") for w in WORD_RE.findall(body)})
        df_tags.update({h.lower() for h in HASHTAG_RE.findall(body)})
        df_domains.update(doms)
    con.executemany("INSERT INTO posts VALUES(" + ",".join("?" * 21) + ")", out)
    con.execute("""INSERT INTO posts_fts(rowid, text, extra, title, place, links)
                   SELECT id, text || ' ' || COALESCE((SELECT group_concat(value, ' ') FROM
                          (SELECT json_extract(j.value,'$.description') || ' ' || json_extract(j.value,'$.title') AS value
                           FROM json_each(posts.media) j)), ''),
                          extra, title, place, links || ' ' || domains FROM posts""")

    words = [(w, "word", c) for w, c in df_words.most_common()
             if c >= 15 and w not in STOPWORDS and len(w) >= 4 and not w.isdigit()][:600]
    con.executemany("INSERT OR REPLACE INTO terms VALUES(?,?,?)", words)
    con.executemany("INSERT OR REPLACE INTO terms VALUES(?,?,?)",
                    [(t, "hashtag", c) for t, c in df_tags.items() if c >= 2])
    con.executemany("INSERT OR REPLACE INTO terms VALUES(?,?,?)",
                    [(d, "site", c) for d, c in df_domains.items() if c >= 3])
    meta = {"schema": str(SCHEMA_VERSION), "source": os.path.abspath(folder),
            "built": dt.datetime.now().isoformat(timespec="seconds"),
            "tz": dt.datetime.now().astimezone().tzname() or "", "count": str(len(out))}
    con.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
    con.commit()
    con.close()
    os.replace(tmp, db_path)
    nc = sum(1 for r in out if r[8] in ("Comment", "Reply"))
    progress(f"Done: {len(out) - nc:,} posts and {nc:,} comments/replies ({skipped:,} comments with no saved "
             f"words left out), {len(media_rows):,} media files indexed.")
    return len(out)


def main(argv):
    import diary_paths
    args = [a for a in argv if not a.startswith("--")]
    db = diary_paths.db_path()
    if "--db" in argv:
        db = argv[argv.index("--db") + 1]
        args = [a for a in args if a != db]
    folder = args[0] if args else diary_paths.default_source()
    build(folder, db)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main(sys.argv[1:])
