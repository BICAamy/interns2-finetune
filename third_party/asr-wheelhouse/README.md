# Step 13 offline ASR wheelhouse

This directory is populated on an Internet-connected development machine by
`scripts/prepare_step13_asr_assets.sh`. Generated wheels and `SHA256SUMS` are
intentionally ignored by Git because they are about 110 MiB. Transfer the
complete generated directory to the same path on the offline server before
building `docker/agent-web/Dockerfile.offline`.

The wheel target is Linux x86_64, CPython 3.10 (`manylinux2014_x86_64`). The
offline Docker build verifies every generated wheel against `SHA256SUMS` and
installs with `--no-index`.
