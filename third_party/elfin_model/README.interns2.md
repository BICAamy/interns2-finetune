# Huayan E05 model snapshot

This directory contains only the E05 files required by the offline simulation
image.

- Upstream: <https://github.com/huayan-robotics/elfin_model>
- Commit: `84baf18d37eefa46b6f092c7fa1f105f81f70ecb`
- Variant: `485/elfin5`
- Included paths: `model/485/elfin5/*.STL` and
  `urdf/ROS2/485/elfin5.urdf.xacro`
- Local modifications to included files: none

The upstream commit does not contain a standalone license file. These files
are retained as a minimal vendor-provided/official-source snapshot for the
project's offline laboratory deployment. Confirm redistribution terms with
Huayan before publishing images or model files outside the project.

Run `simulation/scripts/verify_e05_model.sh third_party/elfin_model` to verify
the pinned files before building.
