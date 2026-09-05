#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$PROJECT_ROOT/src/tuxindrive/__init__.py")
test -n "$VERSION"
PACKAGE_ROOT="$PROJECT_ROOT/build/tuxindrive_${VERSION}_all"
OUTPUT="$PROJECT_ROOT/dist/tuxindrive_${VERSION}_all.deb"
LEGACY_OUTPUT="$PROJECT_ROOT/dist/tuxdrive_${VERSION}_all.deb"

rm -rf -- "$PACKAGE_ROOT"
mkdir -p \
  "$PACKAGE_ROOT/DEBIAN" \
  "$PACKAGE_ROOT/usr/bin" \
  "$PACKAGE_ROOT/usr/lib/tuxindrive" \
  "$PACKAGE_ROOT/usr/share/applications" \
  "$PACKAGE_ROOT/usr/share/doc/tuxindrive" \
  "$PACKAGE_ROOT/usr/share/doc/tuxindrive/assets" \
  "$PACKAGE_ROOT/usr/share/nautilus-python/extensions" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/emblems" \
  "$PACKAGE_ROOT/usr/lib/systemd/user" \
  "$PROJECT_ROOT/dist"

cp "$PROJECT_ROOT/packaging/DEBIAN/control" "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_ROOT/packaging/DEBIAN/postinst" "$PACKAGE_ROOT/DEBIAN/postinst"
cp "$PROJECT_ROOT/packaging/tuxindrive-launcher" "$PACKAGE_ROOT/usr/bin/tuxindrive"
ln -s tuxindrive "$PACKAGE_ROOT/usr/bin/tuxindrive-doctor"
ln -s tuxindrive "$PACKAGE_ROOT/usr/bin/tuxdrive"
ln -s tuxindrive "$PACKAGE_ROOT/usr/bin/tuxdrive-doctor"
cp "$PROJECT_ROOT/packaging/tuxindrive-rclone-password" "$PACKAGE_ROOT/usr/lib/tuxindrive/rclone-password"
cp "$PROJECT_ROOT/packaging/tuxindrive-update-helper" "$PACKAGE_ROOT/usr/lib/tuxindrive/update-helper"
cp -R "$PROJECT_ROOT/src/tuxindrive/." "$PACKAGE_ROOT/usr/lib/tuxindrive/"
find "$PACKAGE_ROOT/usr/lib/tuxindrive" -type d -name __pycache__ -prune -exec rm -rf -- {} +
cp "$PROJECT_ROOT/packaging/io.github.tuxindrive.TuxInDrive.desktop" \
  "$PACKAGE_ROOT/usr/share/applications/io.github.tuxindrive.TuxInDrive.desktop"
cp "$PROJECT_ROOT/packaging/tuxindrive.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive.svg"
cp "$PROJECT_ROOT/packaging/tuxindrive-sync.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-sync.svg"
for FRAME in 0 1 2 3 4 5 6 7; do
  cp "$PROJECT_ROOT/packaging/tuxindrive-sync-${FRAME}.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-sync-${FRAME}.svg"
done
cp "$PROJECT_ROOT/packaging/tuxindrive-error.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-error.svg"
for STATE in synced syncing streaming paused pending error; do
  cp "$PROJECT_ROOT/packaging/emblem-tuxindrive-${STATE}.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/emblems/emblem-tuxindrive-${STATE}.svg"
  # A Nautilus process can keep the pre-rebrand extension loaded across a
  # package upgrade. Keep the old emblem identity available until that process
  # exits so overlays do not disappear between installation and its restart.
  ln -s "emblem-tuxindrive-${STATE}.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/emblems/emblem-tuxdrive-${STATE}.svg"
done
cp "$PROJECT_ROOT/packaging/tuxindrive-google-drive.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-google-drive.svg"
cp "$PROJECT_ROOT/packaging/tuxindrive-onedrive.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-onedrive.svg"
for PROVIDER in dropbox box pcloud mega proton-drive nextcloud github; do
  cp "$PROJECT_ROOT/packaging/tuxindrive-${PROVIDER}.svg" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-${PROVIDER}.svg"
done
for SIZE in 16 24 32 48 64 128 256; do
  mkdir -p "$PACKAGE_ROOT/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
  cp "$PROJECT_ROOT/packaging/icons/hicolor/${SIZE}x${SIZE}/apps/tuxindrive.png" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/tuxindrive.png"
done
cp "$PROJECT_ROOT/packaging/tuxindrive.service" \
  "$PACKAGE_ROOT/usr/lib/systemd/user/tuxindrive.service"
ln -s tuxindrive.service "$PACKAGE_ROOT/usr/lib/systemd/user/tuxdrive.service"
cp "$PROJECT_ROOT/packaging/nautilus-extension-tuxindrive.py" \
  "$PACKAGE_ROOT/usr/share/nautilus-python/extensions/tuxindrive.py"
cp "$PROJECT_ROOT/README.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/README.md"
cp "$PROJECT_ROOT/docs/USER_GUIDE.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/USER_GUIDE.md"
cp "$PROJECT_ROOT/docs/TESTING.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/TESTING.md"
cp "$PROJECT_ROOT/docs/ROADMAP.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/ROADMAP.md"
cp "$PROJECT_ROOT/CHANGELOG.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/CHANGELOG.md"
cp -R "$PROJECT_ROOT/docs/assets/." "$PACKAGE_ROOT/usr/share/doc/tuxindrive/assets/"
cp "$PROJECT_ROOT/branding/tuxindrive-logo.png" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/tuxindrive-logo.png"
cp "$PROJECT_ROOT/LICENSE" "$PACKAGE_ROOT/usr/share/doc/tuxindrive/copyright"
chmod 0755 "$PACKAGE_ROOT/usr/bin/tuxindrive"
chmod 0755 "$PACKAGE_ROOT/usr/lib/tuxindrive/rclone-password"
chmod 0755 "$PACKAGE_ROOT/usr/lib/tuxindrive/update-helper"
chmod 0755 "$PACKAGE_ROOT/DEBIAN/postinst"
chmod 0644 "$PACKAGE_ROOT/DEBIAN/control"
chmod 0644 "$PACKAGE_ROOT/usr/share/nautilus-python/extensions/tuxindrive.py"

# Verify the exact installed layout used by /usr/bin/tuxindrive. This catches
# PYTHONPATH/package-placement regressions before a .deb can be published.
TUXINDRIVE_BUILD_VERSION="$VERSION" PYTHONPATH="$PACKAGE_ROOT/usr/lib" /usr/bin/python3 -c \
  'import importlib.util, os, tuxindrive; assert tuxindrive.__version__ == os.environ["TUXINDRIVE_BUILD_VERSION"]; assert importlib.util.find_spec("tuxindrive.app"); assert importlib.util.find_spec("tuxindrive.proton"); assert importlib.util.find_spec("tuxindrive.cache_manager"); assert importlib.util.find_spec("tuxindrive.network_usage"); assert importlib.util.find_spec("tuxindrive.i18n"); assert importlib.util.find_spec("tuxindrive.help_content"); assert importlib.util.find_spec("tuxindrive.themes"); assert importlib.util.find_spec("tuxindrive.folder_layout"); assert importlib.util.find_spec("tuxindrive.collaboration"); assert importlib.util.find_spec("tuxindrive.platform_support"); assert importlib.util.find_spec("tuxindrive.updater"); assert importlib.util.find_spec("tuxindrive.update_helper"); assert importlib.util.find_spec("tuxindrive.peer"); assert importlib.util.find_spec("tuxindrive.tor"); assert importlib.util.find_spec("tuxindrive.recovery"); assert importlib.util.find_spec("tuxindrive.delta"); assert importlib.util.find_spec("tuxindrive.policies"); assert importlib.util.find_spec("tuxindrive.audit"); assert importlib.util.find_spec("tuxindrive.capabilities"); assert importlib.util.find_spec("tuxindrive.migration"); assert importlib.util.find_spec("tuxindrive.security"); assert importlib.util.find_spec("tuxindrive.github_sync"); assert importlib.util.find_spec("tuxindrive.nautilus_support")'
# Importing for the smoke test creates bytecode with the build host's Python
# version.  Distribution packages must let the target host generate its own
# cache rather than shipping that build-only directory.
find "$PACKAGE_ROOT/usr/lib/tuxindrive" -type d -name __pycache__ -prune -exec rm -rf -- {} +

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT"
cp "$OUTPUT" "$LEGACY_OUTPUT"
printf '%s\n' "$OUTPUT"
