#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
version=$(PYTHONPATH=src python3 -c 'from tuxindrive import __version__; print(__version__)')
python_bin=${PYTHON_BIN:-python3}
rm -rf build/macos build/pyinstaller-macos build/pyinstaller-password-macos
mkdir -p build/macos dist
"$python_bin" -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name TuxInDrive --osx-bundle-identifier io.github.tuxindrive.TuxInDrive \
  --distpath build/macos --workpath build/pyinstaller-macos --specpath build \
  --icon "$project_root/branding/tuxindrive-icon.icns" \
  --collect-all gi --hidden-import=keyring.backends.macOS \
  --add-data "$project_root/branding/tuxindrive-logo.png:branding" packaging/desktop-entry.py
"$python_bin" -m PyInstaller --noconfirm --clean --console --onefile \
  --name rclone-password --distpath build/macos \
  --workpath build/pyinstaller-password-macos --specpath build \
  --hidden-import=keyring.backends.macOS src/tuxindrive/password_helper.py
app=build/macos/TuxInDrive.app
test -d "$app"
mkdir -p "$app/Contents/Resources"
mv build/macos/rclone-password "$app/Contents/Resources/rclone-password"
cp README.md LICENSE "$app/Contents/Resources/"
chmod 755 "$app/Contents/Resources/rclone-password"
identity=${APPLE_CODESIGN_IDENTITY:--}
codesign --force --deep --options runtime --sign "$identity" "$app"
codesign --verify --deep --strict "$app"
architecture=$(uname -m)
dmg="dist/TuxInDrive-$version-macos-$architecture.dmg"
rm -f "$dmg"
attempt=1
while ! hdiutil create -volname TuxInDrive -srcfolder "$app" -ov -format UDZO "$dmg"; do
  if [ "$attempt" -ge 3 ]; then
    echo "macOS disk image creation failed after $attempt attempts" >&2
    exit 1
  fi
  echo "Retrying macOS disk image creation after transient runner failure" >&2
  attempt=$((attempt + 1))
  sleep 3
done
test -s "$dmg"
hdiutil verify "$dmg"
echo "macOS package written to $dmg"
