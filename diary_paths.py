"""Where FacebookDiary keeps its database, settings and media cache.

Linux: data/ beside the program.  Windows: %LOCALAPPDATA%\\FacebookDiary.
macOS: ~/Library/Application Support/FacebookDiary.  FACEBOOKDIARY_DATA overrides all three."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def default_data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "FacebookDiary")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FacebookDiary")
    return os.path.join(HERE, "data")


def data_dir():
    d = os.environ.get("FACEBOOKDIARY_DATA") or default_data_dir()
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        # A folder copied over from Linux carries the user's topics in data/: bring them along
        # (the index itself is rebuilt from the export zips; Linux settings hold Linux paths).
        old = os.path.join(HERE, "data", "topics.json")
        if os.path.abspath(d) != os.path.join(HERE, "data") and os.path.isfile(old):
            import shutil
            shutil.copy2(old, os.path.join(d, "topics.json"))
    return d


def db_path():
    return os.path.join(data_dir(), "diary.sqlite")


def cache_dir():
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def topics_path():
    return os.path.join(data_dir(), "topics.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    tmp = settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, settings_path())


def default_source():
    s = load_settings().get("source")
    if s and os.path.isdir(s):
        return s
    return os.path.join(os.path.dirname(HERE), "facebook_posts")
