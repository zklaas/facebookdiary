"""Search-bar language for FacebookDiary (no Qt here, so it can be tested headless).

Dates and times (local time):
    2013                 the whole year          2013-01        the whole month
    2013-01-17           that day                2013-01-17 14  that hour
    2013-01-17 14:30     that minute             Jan 17 2013 / 17 January 2013 / 2013/1/17
    A .. B   A to B      a range (inclusive; each end keeps its own precision)
    since A / after A / from A        before B / until B        A..   ..B
Filters:
    time:22:00-02:00     time of day (wraps past midnight); a bare 9pm-11pm or 14:00-16:00 works too
    on:01-17 / on:jan-17 that calendar day in every year
    weekday:sat,sun      type:photo   type:comment (comments + replies)   has:photo|video|link|place|media
    site:youtube.com     to:"Alex Smith"  comments/replies to that person's posts or comments
    topic:"US politics"  one of your topics (Topics menu), a #hashtag, or any word
Text (everything else, full-text over post text, captions, link titles, places):
    word  "exact phrase"  word*  (prefix)  this OR that  -excluded  "1984" (quoted = text, not a year)
"""
import calendar
import datetime as dt
import json
import os
import re
import time

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
CLOCK = r"\d{1,2}(?::\d{2}(?::\d{2})?)?\s*(?:am|pm)|\d{1,2}:\d{2}(?::\d{2})?"
TIME_PART = rf"(?:(?:[ T]+|\s*,\s*|\s+at\s+)(?:{CLOCK}|\d{{1,2}}h|\d{{2}}(?=\s*(?:\.\.|to\b|$))))?"
DATE_CORE = (rf"(?:\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|\d{{4}}[-/]\d{{1,2}}(?![-/\d])"
             rf"|{MON}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|\d{{1,2}}(?:st|nd|rd|th)?\s+{MON},?\s+\d{{4}}"
             rf"|{MON}\s+\d{{4}}|(?<![\w\"])\d{{4}}(?![\w\"]))")
DATE = rf"(?:{DATE_CORE}){TIME_PART}"
SEP = r"\s*(?:\.\.|–|—|\bto\b|\bthrough\b|\bthru\b)\s*"
RANGE_RE = re.compile(rf"(?P<a>{DATE})?{SEP}(?P<b>{DATE})?", re.I)
OPEN_RE = re.compile(rf"\b(?P<w>since|after|from|before|until|till)\s+(?P<d>{DATE})", re.I)
SINGLE_RE = re.compile(DATE, re.I)
TOD_RE = re.compile(rf"(?<![\w:])(?P<a>{CLOCK})\s*(?:-|–|\.\.|to)\s*(?P<b>{CLOCK})(?![\w:])", re.I)
FILTER_RE = re.compile(r'(?<!\S)(?P<k>time|on|weekday|day|type|kind|has|site|topic|tag|to):(?P<v>"[^"]*"|\S+)', re.I)
TOKEN_RE = re.compile(r'-?"[^"]+"|\S+')

WEEKDAYS = {d.lower()[:3]: i + 1 for i, d in enumerate(calendar.day_abbr)}


class QueryError(ValueError):
    pass


def year_ok(y):
    return 1990 <= y <= 2100


def parse_clock(s):
    """'9pm', '21:30', '9:15am', '7h' -> minutes after midnight."""
    s = s.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?(am|pm|h)?", s)
    if not m:
        raise QueryError(f"Not a time: {s}")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(4) == "pm" and h < 12:
        h += 12
    if m.group(4) == "am" and h == 12:
        h = 0
    if h > 24 or mi > 59 or (h == 24 and mi):
        raise QueryError(f"Not a time: {s}")
    return h * 60 + mi, (m.group(2) is not None)


def parse_date(s):
    """Return (start datetime, end datetime exclusive) for one date expression."""
    s = s.strip().rstrip(",")
    tpart = None
    m = re.match(rf"(?P<d>.*?)(?:[ T]+|\s*,\s*|\s+at\s+)(?P<t>{CLOCK}|\d{{1,2}}h|\d{{2}})$", s, re.I)
    if m and re.fullmatch(DATE_CORE, m.group("d"), re.I):
        s, tpart = m.group("d").strip().rstrip(","), m.group("t")
    s_l = s.lower()
    y = mo = d = None
    if (m := re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)):
        y, mo, d = map(int, m.groups())
    elif (m := re.fullmatch(r"(\d{4})[-/](\d{1,2})", s)):
        y, mo = map(int, m.groups())
    elif (m := re.fullmatch(rf"({MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", s_l)):
        mo, d, y = month_num(m.group(1)), int(m.group(2)), int(m.group(3))
    elif (m := re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({MON}),?\s+(\d{{4}})", s_l)):
        d, mo, y = int(m.group(1)), month_num(m.group(2)), int(m.group(3))
    elif (m := re.fullmatch(rf"({MON})\s+(\d{{4}})", s_l)):
        mo, y = month_num(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"\d{4}", s):
        y = int(s)
    else:
        raise QueryError(f"Not a date: {s}")
    try:
        if d is not None:
            start = dt.datetime(y, mo, d)
            end = start + dt.timedelta(days=1)
        elif mo is not None:
            start = dt.datetime(y, mo, 1)
            end = dt.datetime(y + (mo == 12), mo % 12 + 1, 1)
        else:
            start, end = dt.datetime(y, 1, 1), dt.datetime(y + 1, 1, 1)
    except ValueError as e:
        raise QueryError(f"Not a date: {s} ({e})")
    if tpart is not None:
        if d is None:
            raise QueryError(f"A time needs a full date: {s} {tpart}")
        if re.fullmatch(r"\d{2}", tpart) or tpart.lower().endswith("h"):
            mins, precise = int(tpart.rstrip("hH")) * 60, False
        else:
            mins, precise = parse_clock(tpart)
        start = start + dt.timedelta(minutes=mins)
        end = start + (dt.timedelta(minutes=1) if precise else dt.timedelta(hours=1))
    return start, end


def month_num(s):
    s = s.rstrip(".").lower()[:3]
    if s in MONTHS:
        return MONTHS[s]
    raise QueryError(f"Not a month: {s}")


def epoch(d):
    try:
        return int(time.mktime(d.timetuple()))
    except (OverflowError, OSError, ValueError):      # Windows, before 1970
        return int((dt.datetime(*d.timetuple()[:6]) - dt.datetime.fromtimestamp(0)).total_seconds())


def local_dt(ts):
    try:
        return dt.datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):      # Windows, before 1970
        return dt.datetime.fromtimestamp(0) + dt.timedelta(seconds=ts)


def fts_term(tok):
    neg = tok.startswith("-") and len(tok) > 1
    if neg:
        tok = tok[1:]
    prefix = tok.endswith("*") and not tok.startswith('"')
    core = tok.strip('"').rstrip("*")
    words = re.findall(r"[\w']+", core)
    if not words:
        return None, neg
    phrase = '"' + " ".join(w.replace('"', "") for w in words) + '"'
    return (phrase + "*" if prefix else phrase), neg


class Query:
    def __init__(self):
        self.start = None          # epoch, inclusive
        self.end = None            # epoch, exclusive
        self.tod = None            # (from_min, to_min) inclusive-exclusive, may wrap
        self.md = []               # ["01-17", ...]
        self.weekdays = []
        self.kinds = []
        self.has = []
        self.sites = []
        self.to = []               # whose post/comment a comment answered
        self.topics = []
        self.fts = None
        self.negatives = []
        self.highlight = []        # words to highlight in the viewer
        self.date_text = ""        # the date expression the user typed

    def describe(self):
        parts = []
        if self.start is not None or self.end is not None:
            a = local_dt(self.start).strftime("%Y-%m-%d %H:%M") if self.start is not None else "…"
            b = local_dt(self.end - 1).strftime("%Y-%m-%d %H:%M") if self.end is not None else "…"
            parts.append(f"{a} → {b}")
        if self.tod:
            parts.append("between %02d:%02d and %02d:%02d" % (self.tod[0] // 60, self.tod[0] % 60,
                                                             self.tod[1] // 60 % 24, self.tod[1] % 60))
        if self.md:
            parts.append("on " + ", ".join(dt.date(2000, *map(int, m.split("-"))).strftime("%B ") + str(int(m.split("-")[1])) for m in self.md))
        if self.weekdays:
            parts.append(", ".join(calendar.day_name[w - 1] for w in self.weekdays))
        for label, vals in (("type", self.kinds), ("has", self.has), ("site", self.sites), ("to", self.to), ("topic", self.topics)):
            if vals:
                parts.append(f"{label}: " + ", ".join(vals))
        if self.fts:
            parts.append("text: " + self.fts)
        if self.negatives:
            parts.append("not: " + ", ".join(self.negatives))
        return "; ".join(parts) or "all posts"


def parse(q, topics=None):
    """Parse the search bar. `topics` maps topic name -> list of terms."""
    topics = topics or {}
    out = Query()
    rest = q

    def cut(m):
        nonlocal rest
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]

    # explicit filters first (their values may look like dates or times)
    for m in list(FILTER_RE.finditer(rest)):
        k, v = m.group("k").lower(), m.group("v").strip('"')
        if k == "time":
            tm = re.fullmatch(rf"({CLOCK})\s*(?:-|–|\.\.|to)\s*({CLOCK})", v, re.I)
            if not tm:
                raise QueryError(f"time: wants a span such as time:22:00-02:00, not {v}")
            out.tod = (parse_clock(tm.group(1))[0], parse_clock(tm.group(2))[0])
        elif k == "on":
            for item in v.split(","):
                item = item.strip().lower().replace("/", "-")
                if (mm := re.fullmatch(r"(\d{1,2})-(\d{1,2})", item)):
                    mo, d = map(int, mm.groups())
                elif (mm := re.fullmatch(rf"({MON})-?(\d{{1,2}})", item)) or (mm := re.fullmatch(rf"(\d{{1,2}})-?({MON})", item)):
                    a, b = mm.groups()
                    mo, d = (month_num(a), int(b)) if not a.isdigit() else (month_num(b), int(a))
                else:
                    raise QueryError(f"on: wants a month and day such as on:01-17 or on:jan-17, not {item}")
                try:
                    dt.date(2000, mo, d)
                except ValueError:
                    raise QueryError(f"No such day: {item}")
                out.md.append(f"{mo:02d}-{d:02d}")
        elif k in ("weekday", "day"):
            for item in v.lower().split(","):
                if item[:3] in WEEKDAYS:
                    out.weekdays.append(WEEKDAYS[item[:3]])
                elif item in ("weekend", "weekends"):
                    out.weekdays += [6, 7]
                elif item in ("weekday", "weekdays"):
                    out.weekdays += [1, 2, 3, 4, 5]
                else:
                    raise QueryError(f"Not a weekday: {item}")
        elif k in ("type", "kind"):
            out.kinds += [x for x in v.split(",") if x]
        elif k == "has":
            for x in v.lower().split(","):
                x = x.rstrip("s")
                if x not in ("photo", "video", "link", "place", "media", "image"):
                    raise QueryError("has: is one of photo, video, link, place, media")
                out.has.append("photo" if x == "image" else x)
        elif k == "site":
            out.sites.append(v.lower())
        elif k == "to":
            out.to.append(v)
        elif k in ("topic", "tag"):
            out.topics.append(v)
        cut(m)

    # date ranges, open-ended dates, single dates
    found = False
    for rx in (RANGE_RE, OPEN_RE):
        for m in list(rx.finditer(rest)):
            if rx is RANGE_RE:
                if not (m.group("a") or m.group("b")):
                    continue
                if m.group("a"):
                    out.start = epoch(parse_date(m.group("a"))[0])
                if m.group("b"):
                    out.end = epoch(parse_date(m.group("b"))[1])
            else:
                w = m.group("w").lower()
                s, e = parse_date(m.group("d"))
                if w in ("since", "from"):
                    out.start = epoch(s)
                elif w == "after":
                    out.start = epoch(e)
                else:
                    out.end = epoch(s)
            out.date_text = (out.date_text + " " + m.group(0).strip()).strip()
            found = True
            cut(m)
    if not found:
        for m in list(SINGLE_RE.finditer(rest)):
            text = m.group(0).strip()
            if re.fullmatch(r"\d{4}", text) and not year_ok(int(text)):
                continue
            s, e = parse_date(text)
            out.start, out.end = epoch(s), epoch(e)
            out.date_text = text
            cut(m)
            break
    if out.start is not None and out.end is not None and out.end <= out.start:
        raise QueryError("The range ends before it starts.")

    # bare time-of-day span
    if out.tod is None and (m := TOD_RE.search(rest)):
        out.tod = (parse_clock(m.group("a"))[0], parse_clock(m.group("b"))[0])
        cut(m)

    # free text -> FTS5
    pos, alt = [], []
    toks = TOKEN_RE.findall(rest)
    i = 0
    groups = []   # list of lists joined by OR
    while i < len(toks):
        t = toks[i]
        if t.upper() == "OR" and groups:
            i += 1
            if i < len(toks):
                term, neg = fts_term(toks[i])
                if term and not neg:
                    groups[-1].append(term)
                    out.highlight.append(toks[i].strip('"').rstrip("*"))
            i += 1
            continue
        term, neg = fts_term(t)
        if term:
            if neg:
                out.negatives.append(term)
            else:
                groups.append([term])
                out.highlight.append(t.strip('"').rstrip("*"))
        i += 1
    if groups:
        out.fts = " AND ".join(g[0] if len(g) == 1 else "(" + " OR ".join(g) + ")" for g in groups)
    out.topic_terms = []
    for t in out.topics:
        out.topic_terms.append(topic_expansion(t, topics))
        out.highlight += [x for x in topic_highlight(t, topics)]
    return out


def topic_terms_list(name, topics):
    for k, v in topics.items():
        if k.lower() == name.lower():
            return v
    return None


def topic_expansion(name, topics):
    """-> ('sql', clause, params): a post is in the topic when it matches ANY of the topic's lines.
    A line can be a word or phrase (word* = prefix), a file type such as .mp4 (an attached or linked
    file of that type), or a search filter such as has:video, type:photo, site:youtube.com, to:"Name"."""
    terms = topic_terms_list(name, topics)
    if terms is None:
        if name.lower().startswith("site:"):
            terms = [name]
        else:
            terms = [name.lstrip("#")]
    ors, params, words = [], [], []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        if re.fullmatch(r"\.[A-Za-z0-9]{2,5}", t):
            ext = t.lower()
            ors.append("(lower(media) LIKE ? OR lower(links) LIKE ?)")
            params += [f'%{ext}"%', f"%{ext}%"]
        elif FILTER_RE.fullmatch(t):
            sub = parse(t, topics)
            sql, p = build_sql(sub, columns="id")
            ors.append("id IN (" + sql.split(" ORDER BY ")[0] + ")")
            params += p
        else:
            term, _neg = fts_term('"' + t.lstrip("#") + '"' if not t.endswith("*") else t)
            if term:
                words.append(term)
    if words:
        ors.append("id IN (SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?)")
        params.append(" OR ".join(words))
    if not ors:
        raise QueryError(f"Topic {name} has no terms")
    return ("sql", "(" + " OR ".join(ors) + ")", params)


def topic_highlight(name, topics):
    terms = topic_terms_list(name, topics)
    if terms is None:
        return [] if name.lower().startswith("site:") else [name.lstrip("#")]
    return [t.lstrip("#").rstrip("*") for t in terms
            if not FILTER_RE.fullmatch(t.strip()) and not re.fullmatch(r"\.[A-Za-z0-9]{2,5}", t.strip())]


def build_sql(qy, order="ASC", columns="id"):
    where, params = [], []
    if qy.start is not None:
        where.append("ts >= ?"); params.append(qy.start)
    if qy.end is not None:
        where.append("ts < ?"); params.append(qy.end)
    if qy.tod:
        a, b = qy.tod
        fa, fb = "%02d:%02d:00" % (a // 60 % 24, a % 60), "%02d:%02d:00" % (b // 60 % 24, b % 60)
        if a < b or b == 24 * 60:
            where.append("time >= ? AND time < ?" if b < 24 * 60 else "time >= ?")
            params += [fa, fb] if b < 24 * 60 else [fa]
        else:
            where.append("(time >= ? OR time < ?)"); params += [fa, fb]
    if qy.md:
        where.append("md IN (%s)" % ",".join("?" * len(qy.md))); params += qy.md
    if qy.weekdays:
        where.append("weekday IN (%s)" % ",".join("?" * len(set(qy.weekdays)))); params += sorted(set(qy.weekdays))
    if qy.kinds:
        ors = []
        for k in qy.kinds:
            k = k.lower().rstrip("s")
            if k in ("comment", "reply", "replie"):
                ors.append("kind IN ('Comment', 'Reply')")
            elif k == "__post__":
                ors.append("kind NOT IN ('Comment', 'Reply')")
            else:
                ors.append("lower(kind) LIKE ?"); params.append(f"%{k}%")
        where.append("(" + " OR ".join(ors) + ")")
    for h in qy.has:
        if h == "photo":
            where.append("EXISTS(SELECT 1 FROM json_each(media) j WHERE json_extract(j.value,'$.uri') NOT LIKE '%.mp4')")
        elif h == "video":
            where.append("EXISTS(SELECT 1 FROM json_each(media) j WHERE json_extract(j.value,'$.uri') LIKE '%.mp4')")
        elif h == "media":
            where.append("nmedia > 0")
        elif h == "link":
            where.append("links != '[]'")
        elif h == "place":
            where.append("place != ''")
    for s in qy.sites:
        where.append("(' ' || domains || ' ') LIKE ?"); params.append(f"% %{s}%")
    for t in qy.to:
        where.append("target LIKE ?"); params.append(f"%{t}%")
    fts = [qy.fts] if qy.fts else []
    for _kind, clause, cparams in getattr(qy, "topic_terms", []):
        where.append(clause); params += cparams
    for neg in qy.negatives:
        where.append("id NOT IN (SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?)"); params.append(neg)
    if fts:
        where.append("id IN (SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?)"); params.append(" AND ".join(fts))
    sql = f"SELECT {columns} FROM posts"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY ts {order}, id {order}"
    return sql, params


DEFAULT_TOPICS = {
    "US politics": ["trump", "biden", "obama", "clinton", "democrats", "republicans", "gop", "congress",
                    "senate", "white house", "kamala", "harris", "bernie", "sanders", "maga"],
    "Canadian politics": ["canada", "canadian", "trudeau", "carney", "poilievre", "harper", "scheer",
                          "singh", "ndp", "liberals", "conservatives", "parliament", "ottawa", "ontario", "ford"],
    "Elections": ["election", "elections", "vote", "voters", "voting", "poll", "polls", "ballot", "campaign",
                  "first past the post", "proportional representation"],
    "Baseball": ["baseball", "mlb", "red sox", "redsox", "blue jays", "yankees", "pitcher", "inning",
                 "home run", "world series", "fenway"],
    "Philosophy": ["philosophy", "philosopher", "nietzsche", "kant", "hegel", "marx", "plato", "aristotle",
                   "ethics", "moral", "morality", "epistemology"],
    "Music & theatre": ["music", "song", "songs", "album", "band", "broadway", "hamilton", "musical", "concert"],
    "Muppets": ["muppets", "muppet", "kermit", "jim henson", "themuppets"],
    "Birthdays & anniversaries": ["birthday", "anniversary", "friendversary", "happy birthday"],
    "Family": ["mom", "dad", "mother", "father", "brother", "sister", "son", "daughter", "family"],
}


def load_topics(path):
    try:
        with open(path, encoding="utf-8") as f:
            t = json.load(f)
        if isinstance(t, dict):
            return {str(k): [str(x) for x in v] for k, v in t.items() if isinstance(v, list)}
    except (OSError, ValueError):
        pass
    save_topics(path, DEFAULT_TOPICS)
    return dict(DEFAULT_TOPICS)


def save_topics(path, topics):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(topics, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def strip_dates(q):
    """The query without its date expression(s) — used when the calendar picks a day."""
    for rx in (RANGE_RE, OPEN_RE, SINGLE_RE):
        while True:
            m = None
            for cand in rx.finditer(q):
                inside_filter = any(f.start() <= cand.start() < f.end() for f in FILTER_RE.finditer(q))
                inside_quote = any(f.start() <= cand.start() < f.end() for f in re.finditer(r'"[^"]*"', q))
                if inside_filter or inside_quote or not cand.group(0).strip():
                    continue
                if rx is RANGE_RE and not (cand.group("a") or cand.group("b")):
                    continue
                if rx is SINGLE_RE and re.fullmatch(r"\d{4}", cand.group(0).strip()) and not year_ok(int(cand.group(0))):
                    continue
                m = cand
                break
            if not m:
                break
            q = (q[:m.start()] + " " + q[m.end():])
    return re.sub(r"\s+", " ", q).strip()
