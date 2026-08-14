# Step 5 offline wheelhouse

This directory contains the pinned additions from
`simulation/step5-requirements.txt` for the validated Step 4 runtime:

- Linux x86_64 (`manylinux2014_x86_64`);
- CPython 3.10 (`cp310`);
- installation with `pip --no-index`.

`docker/simulation/Dockerfile.offline` verifies `SHA256SUMS` before installing
the wheels. These files must be transferred to the offline server together
with the repository.

To regenerate the wheelhouse on an Internet-connected machine, delete only
the `.whl` files, run the following command, then update `SHA256SUMS`:

```bash
python3 -m pip download \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --python-version 310 \
  --implementation cp \
  --abi cp310 \
  --dest third_party/wheelhouse \
  --requirement simulation/step5-requirements.txt
```
