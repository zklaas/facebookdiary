# FacebookDiary on macOS

## What you need

- **Python 3.10 or newer**, from [python.org](https://www.python.org/downloads/macos/) or Homebrew (`brew install python@3.13`).
- **This FacebookDiary folder**, copied anywhere you like, for example `Documents/FacebookDiary`.
- **Your Facebook export**: the zip file(s) from Facebook's *Download your information*, in a folder of their own. You don't need to unzip them.

## Install

In **Terminal**, go to the FacebookDiary folder and run:

```
bash install-macos.sh
```

It doesn't need administrator rights. It installs PyQt6 into a `.venv` folder inside FacebookDiary, adds a `facebookdiary` command in `~/.local/bin`, and puts **FacebookDiary** in `~/Applications`, so it opens from Launchpad, Spotlight or the Dock.

## First start

Open FacebookDiary from Launchpad, or type `facebookdiary` in Terminal. It asks for the folder holding your export zips and builds its index, which takes a minute or two. **File ▸ Re-import** does it again after a newer export.

- **Where things are kept:** the index, settings, topics and media cache go in `~/Library/Application Support/FacebookDiary`. Exports go to `Documents/FacebookDiary export` unless you choose another folder.
- **Your topics from Linux:** if the copied folder has `data/topics.json`, it's brought over on first start.
- **Videos:** a video plays in FacebookDiary's own window if the Mac's copy of the web engine can decode it. Most Facebook videos use a format it can't, so they open in QuickTime Player instead.
- **First launch warning:** if macOS says the app can't be checked, right-click FacebookDiary in Applications and choose **Open**.

## From the command line

```
facebookdiary                     the diary window
facebookdiary 2016-11 baseball    open with that search
facebookdiary --import FOLDER     rebuild the index from the zips in FOLDER
facebookdiary --check             run the built-in checks
```
