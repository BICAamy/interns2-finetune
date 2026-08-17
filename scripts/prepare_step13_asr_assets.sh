#!/usr/bin/env bash
set -euo pipefail

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
wheel_dir="${project_root}/third_party/asr-wheelhouse"
model_dir="${project_root}/models/asr/faster-whisper-small"
model_revision="536b0662742c02347bc0e980a01041f333bce120"
asset_venv=$(mktemp -d /tmp/interns2-step13-assets.XXXXXX)

cleanup() {
  rm -rf -- "${asset_venv}"
}
trap cleanup EXIT

mkdir -p "${wheel_dir}" "${model_dir}"

python3 -m pip download \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --python-version 310 \
  --implementation cp \
  --abi cp310 \
  --dest "${wheel_dir}" \
  --requirement "${project_root}/web/backend/asr-requirements.txt"

python3 - "${wheel_dir}" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

directory = Path(sys.argv[1])
files = sorted(directory.glob("*.whl"), key=lambda path: path.name.lower())
if not files:
    raise SystemExit("no ASR wheels were downloaded")

def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

lines = []
for path in files:
    lines.append(f"{digest(path)}  {path.name}\n")
(directory / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
print(f"prepared {len(files)} wheels in {directory}")
PY

python3 -m venv "${asset_venv}/venv"
"${asset_venv}/venv/bin/python" -m pip install --quiet \
  "huggingface-hub==0.27.1"
"${asset_venv}/venv/bin/python" - "${model_dir}" "${model_revision}" <<'PY'
from huggingface_hub import snapshot_download
from pathlib import Path
import sys

destination = Path(sys.argv[1])
revision = sys.argv[2]
snapshot_download(
    repo_id="Systran/faster-whisper-small",
    revision=revision,
    local_dir=destination,
    local_dir_use_symlinks=False,
    allow_patterns=[
        "README.md",
        "config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.txt",
    ],
)
(destination / "MODEL_REVISION").write_text(revision + "\n", encoding="utf-8")
PY

python3 - "${model_dir}" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

directory = Path(sys.argv[1])
required = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
missing = [name for name in required if not (directory / name).is_file()]
if missing:
    raise SystemExit(f"ASR model is incomplete: {', '.join(missing)}")

def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

lines = []
for name in sorted(required + ["MODEL_REVISION"]):
    path = directory / name
    lines.append(f"{digest(path)}  {name}\n")
(directory / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
print(f"prepared pinned ASR model in {directory}")
PY

printf '%s\n' \
  "Step 13 assets are ready." \
  "Wheels: ${wheel_dir}" \
  "Model:  ${model_dir}"
