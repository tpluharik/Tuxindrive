#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 jammy|noble" >&2
  exit 2
fi

suite=$1
case "$suite" in
  jammy|noble) ;;
  *) echo "Unsupported Ubuntu suite: $suite" >&2; exit 2 ;;
esac

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
upstream_version=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$project_root/src/tuxindrive/__init__.py")
test -n "$upstream_version"
package_version="${upstream_version}-1~ppa1~${suite}1"
fingerprint=${TUXINDRIVE_PPA_GPG_FINGERPRINT:-876EA8329116387E9FAF7880C3FDEBCEA697D211}
output_dir="$project_root/dist/ppa/$suite"
work_root=$(mktemp -d)
trap 'rm -rf -- "$work_root"' EXIT HUP INT TERM
source_dir="$work_root/tuxindrive-$upstream_version"
packaging_dir="$work_root/debian"

mkdir -p "$source_dir" "$output_dir"
git -C "$project_root" archive --format=tar HEAD | tar -xf - -C "$source_dir"
cp -a "$source_dir/debian" "$packaging_dir"
# Debian source uploads must not embed the repository's historical binary
# artifacts.  The build recreates only the current binary in its temporary
# workspace.
rm -rf "$source_dir/debian" "$source_dir/dist"
tar -C "$work_root" -czf "$work_root/tuxindrive_${upstream_version}.orig.tar.gz" "tuxindrive-$upstream_version"
cp -a "$packaging_dir" "$source_dir/debian"

cat > "$source_dir/debian/changelog" <<EOF
tuxindrive ($package_version) $suite; urgency=medium

  * Publish TuxInDrive $upstream_version for Ubuntu $suite.

 -- Tomas Pluharik <tpluharik@gmail.com>  $(date -R)
EOF

(cd "$source_dir" && dpkg-buildpackage -S -sa -k"$fingerprint")
cp "$work_root"/tuxindrive_"$package_version"_source.changes "$output_dir/"
cp "$work_root"/tuxindrive_"$package_version"_source.buildinfo "$output_dir/"
cp "$work_root"/tuxindrive_"$package_version".dsc "$output_dir/"
cp "$work_root"/tuxindrive_"$package_version".debian.tar.* "$output_dir/"
cp "$work_root"/tuxindrive_"$upstream_version".orig.tar.gz "$output_dir/"
printf '%s\n' "$output_dir/tuxindrive_${package_version}_source.changes"
