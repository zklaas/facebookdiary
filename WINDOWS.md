# FacebookDiary on Windows

## What you need

- **Python 3.10 or newer.** If you don't have it, type this in **PowerShell**:
  `winget install --id Python.Python.3.13 -e --scope user`
- **This FacebookDiary folder**, copied anywhere you like, for example `Documents\FacebookDiary`.
- **Your Facebook export**: the zip file(s) from Facebook's *Download your information*, in a folder of their own. You don't need to unzip them.

## Install

In **PowerShell**, go to the FacebookDiary folder and run:

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

It doesn't need administrator rights. It installs PyQt6 into a `.venv` folder inside FacebookDiary, adds a `facebookdiary` command, and puts **FacebookDiary** in the Start menu.

## First start

Open FacebookDiary from the Start menu, or type `facebookdiary` in a **new** PowerShell or Command Prompt window. It asks for the folder holding your export zips and builds its index, which takes a minute or two. **File ▸ Re-import** does it again after a newer export.

- **Where things are kept:** the index, settings, topics and media cache go in `%LOCALAPPDATA%\FacebookDiary`. Exports (File ▸ Export, *Save to export folder*) go to `Documents\FacebookDiary export` unless you choose another folder.
- **Your topics from Linux:** if the copied folder has `data\topics.json`, it's brought over on first start.
- **Videos:** a video plays in FacebookDiary's own window if Windows' copy of the web engine can decode it. Most Facebook videos use a format it can't, so they open in Windows' own video player instead (Media Player or Films & TV).

## From the command line

```
facebookdiary                     the diary window
facebookdiary 2016-11 baseball    open with that search
facebookdiary --import FOLDER     rebuild the index from the zips in FOLDER
facebookdiary --check             run the built-in checks
```
