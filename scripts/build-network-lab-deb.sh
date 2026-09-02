#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP_VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$PROJECT_ROOT/src/tuxindrive/__init__.py")
LAB_REVISION=${TUXINDRIVE_LAB_REVISION:-5}
case "$LAB_REVISION" in *[!0-9]*|'') echo "Lab revision must be a positive integer" >&2; exit 2;; esac
test "$LAB_REVISION" -ge 1
PACKAGE_VERSION="${APP_VERSION}+lab${LAB_REVISION}"
PACKAGE_ROOT="$PROJECT_ROOT/build/tuxindrive-network-lab_${PACKAGE_VERSION}_all"
OUTPUT="$PROJECT_ROOT/dist/tuxindrive-network-lab_${PACKAGE_VERSION}_all.deb"

rm -rf -- "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_ROOT/DEBIAN" "$PACKAGE_ROOT/usr/bin" \
  "$PACKAGE_ROOT/usr/lib/tuxindrive-network-lab/tuxindrive" \
  "$PACKAGE_ROOT/usr/share/applications" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$PACKAGE_ROOT/usr/share/doc/tuxindrive-network-lab" "$PROJECT_ROOT/dist"
cp "$PROJECT_ROOT/packaging/network-lab/DEBIAN/control" "$PACKAGE_ROOT/DEBIAN/control"
cp "$PROJECT_ROOT/packaging/network-lab/tuxindrive-network-lab" "$PACKAGE_ROOT/usr/bin/tuxindrive-network-lab"
cp "$PROJECT_ROOT/packaging/network-lab/tuxindrive-network-lab-cli" "$PACKAGE_ROOT/usr/bin/tuxindrive-network-lab-cli"
cp "$PROJECT_ROOT/packaging/network-lab/tuxindrive-network-lab.desktop" "$PACKAGE_ROOT/usr/share/applications/tuxindrive-network-lab.desktop"
cp "$PROJECT_ROOT/packaging/tuxindrive.svg" "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/tuxindrive-network-lab.svg"
cp -R "$PROJECT_ROOT/src/tuxindrive/." "$PACKAGE_ROOT/usr/lib/tuxindrive-network-lab/tuxindrive/"
find "$PACKAGE_ROOT/usr/lib/tuxindrive-network-lab" -type d -name __pycache__ -prune -exec rm -rf -- {} +
cp "$PROJECT_ROOT/docs/NETWORK_LAB.md" "$PACKAGE_ROOT/usr/share/doc/tuxindrive-network-lab/README.md"
cp "$PROJECT_ROOT/LICENSE" "$PACKAGE_ROOT/usr/share/doc/tuxindrive-network-lab/copyright"
sed -i "s/^Version: .*/Version: $PACKAGE_VERSION/" "$PACKAGE_ROOT/DEBIAN/control"
find "$PACKAGE_ROOT" -type d -exec chmod 0755 {} +
find "$PACKAGE_ROOT" -type f -exec chmod 0644 {} +
chmod 0755 "$PACKAGE_ROOT/usr/bin/tuxindrive-network-lab" "$PACKAGE_ROOT/usr/bin/tuxindrive-network-lab-cli"
PYTHONPATH="$PACKAGE_ROOT/usr/lib/tuxindrive-network-lab" /usr/bin/python3 -c \
  'import importlib.util; assert importlib.util.find_spec("tuxindrive.network_lab"); assert importlib.util.find_spec("tuxindrive.network_lab_gui")'
find "$PACKAGE_ROOT/usr/lib/tuxindrive-network-lab" -type d -name __pycache__ -prune -exec rm -rf -- {} +
dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT"
printf '%s\n' "$OUTPUT"
