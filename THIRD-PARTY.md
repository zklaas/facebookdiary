# Third-party sources

FacebookDiary uses these open-source sources, each under its own licence.

| Source | Licence | Note |
|---|---|---|
| Python package PIL | MIT-CMU | Pillow is only imported by make_icon.py to draw the icons; it is not copied into the project. Pillow's licence is the HPND/MIT-CMU-style licence. |
| Python package PyQt6 | GPL-3.0-only | PyQt6 is imported (GUI, optional QtWebEngine), not bundled. It is GPL-3.0 (or commercial), so the release licence must be GPL-3.0-compatible if distributed together. |
| Claude found: LICENSE | GPL-3.0-or-later | An AI-disclosure header naming Zachary Klaas as copyright holder, followed by the standard GPL-3.0 text, which the FSF lets everyone copy verbatim. It is the project's chosen licence, not borrowed code. |
