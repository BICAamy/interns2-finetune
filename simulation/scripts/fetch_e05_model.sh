#!/bin/sh
set -eu

repository_url="https://github.com/huayan-robotics/elfin_model.git"
source_commit="84baf18d37eefa46b6f092c7fa1f105f81f70ecb"
destination_dir="${1:-/opt/huayan-elfin-model}"

verify_assets() {
    checkout_dir="$1"
    actual_commit=$(git -C "$checkout_dir" rev-parse HEAD)
    if [ "$actual_commit" != "$source_commit" ]; then
        echo "Unexpected elfin_model commit: $actual_commit" >&2
        return 1
    fi

    mesh_dir="$checkout_dir/model/485/elfin5"
    (
        cd "$mesh_dir"
        sha256sum --check --strict <<'CHECKSUMS'
792afa9e61162fd025feabefc9efd0038086acf3eb60cc2ba8fb5fb25e7bf931  elfin_base.STL
d30400c5b3367fcc00c572b4609e8e4819fc6fdc8968f98c2e3615e995d1969b  elfin_end_link.STL
95cae5fdfbd9f5ed396a3d52f9b0be0662b58d6f36f043fe2e55c9d6955d1328  elfin_link1.STL
2132a3ee085e6785a861b9a4ffb3e5caec35cc7acd2d9b53bfc7997d60a083e7  elfin_link2.STL
c8f31091b1977c1d41698b688a2110596c23c60b5afec50a24dc9c6d9428b491  elfin_link3.STL
4e821980f76853cd30d21666d2a2397f6f4fa74cee27a9beac0e08cbc908777a  elfin_link4.STL
bd12092cb15f6ef119091726e78a277a43c1e833b8e92e404d9879af65945ebf  elfin_link5.STL
3c229dd4ec538ba125dfa7bc9af41f04f570bd6dd39fd9317a5a91a1d8d52f48  elfin_link6.STL
CHECKSUMS
    )
    printf '%s  %s\n' \
        "0f006772323d07d10a06d70b5f6823de1dab392fdbd80ee900e16a09516e255c" \
        "$checkout_dir/urdf/ROS2/485/elfin5.urdf.xacro" \
        | sha256sum --check --strict
}

if [ -d "$destination_dir/.git" ]; then
    verify_assets "$destination_dir"
    exit 0
fi

if [ -e "$destination_dir" ]; then
    echo "Refusing to overwrite non-repository path: $destination_dir" >&2
    exit 1
fi

temporary_dir=$(mktemp -d /tmp/huayan-elfin-model.XXXXXX)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM
checkout_dir="$temporary_dir/elfin_model"

git init --quiet "$checkout_dir"
git -C "$checkout_dir" remote add origin "$repository_url"
git -C "$checkout_dir" sparse-checkout init --cone
git -C "$checkout_dir" sparse-checkout set model/485/elfin5 urdf/ROS2/485
git -C "$checkout_dir" -c protocol.version=2 fetch \
    --quiet \
    --depth 1 \
    --filter=blob:none \
    origin "$source_commit"
git -C "$checkout_dir" checkout --quiet --detach FETCH_HEAD
verify_assets "$checkout_dir"

mkdir -p "$(dirname "$destination_dir")"
mv "$checkout_dir" "$destination_dir"
trap - EXIT HUP INT TERM
rm -rf "$temporary_dir"
