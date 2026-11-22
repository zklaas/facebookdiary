#!/usr/bin/env bash
# Install the `facebookdiary` command, icon and desktop menu entry for this user.
set -euo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$HERE/run.sh" ~/.local/bin/facebookdiary
for s in 16 24 32 48 64 128 256 512; do
  d=~/.local/share/icons/hicolor/${s}x${s}/apps; mkdir -p "$d"
  cp "$HERE/icons/facebookdiary-$s.png" "$d/facebookdiary.png"
done
cat > ~/.local/share/applications/facebookdiary.desktop <<DESK
[Desktop Entry]
Type=Application
Version=1.0
Name=FacebookDiary
GenericName=Post Diary
Comment=Browse your Facebook posts day by day, time by time, by topic or by text
Keywords=facebook;diary;posts;archive;journal;search;
Exec=$HOME/.local/bin/facebookdiary
Icon=facebookdiary
Terminal=false
Categories=Office;Utility;
StartupNotify=true
StartupWMClass=facebookdiary
DESK
gtk-update-icon-cache -q ~/.local/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q ~/.local/share/applications 2>/dev/null || true
echo "Installed: run 'facebookdiary'"
