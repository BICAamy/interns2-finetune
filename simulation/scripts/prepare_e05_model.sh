#!/bin/sh
set -eu

model_root="${1:-/opt/huayan-elfin-model}"
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
mesh_dir="$model_root/model/485/elfin5"

# Keep the vendor snapshot byte-for-byte intact and verify it before creating
# compatibility aliases. sofa_env v1.0.0 performs a case-sensitive extension
# lookup and therefore rejects Huayan's official uppercase .STL filenames.
sh "$script_dir/verify_e05_model.sh" "$model_root"

for stem in \
    elfin_base \
    elfin_end_link \
    elfin_link1 \
    elfin_link2 \
    elfin_link3 \
    elfin_link4 \
    elfin_link5 \
    elfin_link6
do
    source_name="$stem.STL"
    alias_path="$mesh_dir/$stem.stl"

    if [ -L "$alias_path" ]; then
        if [ "$(readlink "$alias_path")" != "$source_name" ]; then
            echo "Unexpected E05 mesh alias target: $alias_path" >&2
            exit 1
        fi
    elif [ -e "$alias_path" ]; then
        echo "Refusing to overwrite non-symlink E05 mesh alias: $alias_path" >&2
        exit 1
    else
        ln -s "$source_name" "$alias_path"
    fi

    test -f "$alias_path"
done

echo "E05 lowercase mesh aliases: OK"
