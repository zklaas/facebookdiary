# FacebookDiary

Read your own Facebook posts as a diary. FacebookDiary opens the archive
Facebook gives you with *Download your information* and lets you browse your
posts, comments and replies day by day and hour by hour, by date range, by
topic, or by any words in them. Photos show with their posts, and videos play
in their own window.

Your posts stay on your computer. FacebookDiary reads the export zips where
they are, without unpacking them, and keeps its index on your own disk. It goes
online only when you click a link or **Open on Facebook**.

Runs on Linux, Windows and macOS.

## Download

Ready-to-run downloads (executable programs), with nothing else to install:

* **Windows:** [FacebookDiary-Setup-Windows.exe](https://github.com/zklaas/facebookdiary/releases/latest/download/FacebookDiary-Setup-Windows.exe)
* **macOS** (Apple silicon): [FacebookDiary-macOS.dmg](https://github.com/zklaas/facebookdiary/releases/latest/download/FacebookDiary-macOS.dmg)
* **Linux:** [FacebookDiary-Linux-x86_64.AppImage](https://github.com/zklaas/facebookdiary/releases/latest/download/FacebookDiary-Linux-x86_64.AppImage)

The first time, Windows or macOS asks before opening it; the
[release page](https://github.com/zklaas/facebookdiary/releases/latest) says what to click.
To install from the source code at the command line instead, see *Installing* below.

## Getting your Facebook export

1. On Facebook, find **Download your information** (in Settings, under *Accounts Center ▸ Your information and permissions*; Facebook moves it from time to time).
2. Ask for **your information**, with **Format: JSON** (FacebookDiary can't read the HTML format).
   *All time* gives you everything; choose high media quality if you want full-size photos and videos.
3. When Facebook says it's ready, download every zip file into one folder of their own. Don't unzip them.

## Installing

**Linux** (Ubuntu or Debian). In a terminal:

    sudo apt install python3-pyqt6 python3-pyqt6.qtwebengine
    bash install-desktop.sh

This adds the `facebookdiary` command and a FacebookDiary entry in your applications menu.

**Windows:** see [WINDOWS.md](WINDOWS.md). **macOS:** see [MACOS.md](MACOS.md).

On first start FacebookDiary asks for the folder holding your export zips and
builds its index, which takes a minute or two. **File ▸ Re-import** does it again
after you download a newer export.

## Using it

Type into the search bar, pick a day on the calendar, or both. The list shows
every post that matches; click one to read it, with its photos, links and videos.

- **Calendar:** shaded days have posts (darker = more). Clicking a day keeps your words and topic but changes the dates.
- **◀ Day / Day ▶** step through the days that have posts. **On this day** shows the same date in every year.
- **◀ Earlier / Later ▶** step through posts in time order, whatever the search.
- **Topics** (Topics ▸ Edit my topics): name a topic and give it words, file types such as `.mp4`, or search filters such as `has:video`. A post belongs to the topic if it matches any line.
- **Comments and replies** show who you were answering. Facebook's export keeps only that person's name, not their words.
- **Open on Facebook** opens the post itself, for photo and video posts and posts on other people's profiles.

### Search examples

    2013                       the whole year
    2013-01-17                 that day
    2013-01-17 14:30           that minute
    jan 2013 .. mar 2013       a range (also: since, before, until)
    time:22:00-02:00           posts written late at night, any day
    on:01-17                   January 17 in every year
    weekday:sat,sun            weekends
    type:photo  type:comment   kinds of entry
    has:video  has:link        entries with a video or a link
    site:youtube.com           links to a site
    to:"Alex Smith"            your comments and replies to that person
    topic:Baseball             one of your topics
    "exact phrase"  word*  this OR that  -excluded

**Help ▸ Search syntax** (F1) lists everything.

## Saving and exporting

- **Save to export folder** (in a post) adds the post, with its text, links and Facebook address, to *Saved posts.html*, and copies its videos beside it. Right-click a photo or video to save just that file.
- **File ▸ Export the search results** (Ctrl+E) writes every listed post to a web page of its own, with their videos and, if you like, their photos.
- Exports go to *Documents/FacebookDiary export* unless you choose another folder (**File ▸ Choose the export folder**).

## From the command line

    facebookdiary                     the diary window
    facebookdiary 2016-11 baseball    open with that search
    facebookdiary --import FOLDER     rebuild the index from the zips in FOLDER
    facebookdiary --check             run the built-in checks

## Where things are kept

| | Index, settings, topics, media cache |
|---|---|
| Linux | `data/` in the FacebookDiary folder (the downloaded AppImage: `~/.local/share/FacebookDiary`) |
| Windows | `%LOCALAPPDATA%\FacebookDiary` |
| macOS | `~/Library/Application Support/FacebookDiary` |

Videos and full-size photos are copied out of the zips into the media cache
when you open them. **File ▸ Clear media cache** empties it; they stay in your zips.

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE), which also says how AI was used to write it.
Third-party parts are listed in [THIRD-PARTY.md](THIRD-PARTY.md).
