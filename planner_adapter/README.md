# Planner adapter

Step 9 provides a standalone, provider-neutral HTTP service for puncture path
planning. It is an adapter and fault simulator, not a path-planning algorithm.
The current Mock output contains only the requested entry and target points for
UI/API verification and is always marked `executable: false`.

## API

```text
GET  /health
POST /v1/plan
```

The planning request uses the shared versioned contract:

```json
{
  "schema_version": "1.0",
  "request_id": "plan-0001",
  "command_id": "cmd-0001",
  "entry_point": {
    "x": 20.0,
    "y": 35.0,
    "z": 80.0,
    "unit": "mm",
    "frame": "robot_base"
  },
  "target_point": {
    "x": 24.0,
    "y": 38.0,
    "z": 120.0,
    "unit": "mm",
    "frame": "robot_base"
  }
}
```

A successful Mock response has `planner_name: "mock"`,
`output_schema_version: "preview-v1"`, `control_mode: "mock_preview"`, and:

```json
{
  "control_payload": {
    "preview_points_mm": [
      [20.0, 35.0, 80.0],
      [24.0, 38.0, 120.0]
    ],
    "frame": "robot_base",
    "unit": "mm"
  },
  "executable": false
}
```

This is not a needle trajectory and must never be forwarded to a robot as
control data.

## Configuration

```dotenv
PLANNER_PROVIDER=mock
PLANNER_MOCK_OUTCOME=success
PLANNER_EXPECTED_OUTPUT_SCHEMA_VERSION=preview-v1
PLANNER_REQUEST_TIMEOUT=10
PLANNER_ADAPTER_HOST=0.0.0.0
PLANNER_ADAPTER_PORT=8002
PLANNER_ADAPTER_LOG_LEVEL=info
```

`PLANNER_REQUEST_TIMEOUT` is part of the stable adapter configuration for the
future external provider. The current Mock `timeout` mode raises a deterministic
timeout immediately, so tests do not sleep for ten seconds.

`PLANNER_MOCK_OUTCOME` supports:

- `success`;
- `failure`;
- `timeout`;
- `invalid_schema`;
- `version_mismatch`.

Invalid provider output is never returned directly. The adapter converts it to
a validated failure response with `INVALID_PLANNER_OUTPUT` and
`executable: false`. Even the Mock `invalid_schema` fixture itself keeps
`executable: false`; it simulates invalidity through missing/unknown fields.

`PLANNER_PROVIDER=external` selects only an intentional placeholder. It reports
`ready: false` and returns `PLANNER_UNAVAILABLE`; it does not guess whether the
future planner will use HTTP, gRPC, ROS 2, or a Python API.

## Local start

```bash
cd /home/xl/interns2-finetune
export PLANNER_PROVIDER=mock
export PLANNER_MOCK_OUTCOME=success
python3 -m planner_adapter.main
```

The service listens on port 8002 by default.

## Offline laboratory-server image

The server has no internet access, so build from the already validated Step 6
simulation image, which contains Python 3.10, FastAPI, Pydantic, and Uvicorn:

```bash
cd ~/interns2-finetune

docker image inspect interns2-robot-simulation:dev >/dev/null

docker build --network=none \
  -f docker/planner-adapter/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:dev \
  -t interns2-planner-adapter:dev .
```

Run it independently from SOFA; this container does not start Xvfb or the
simulation process:

```bash
docker run --rm -d \
  --name interns2-planner-adapter \
  -p 8002:8002 \
  -e PLANNER_PROVIDER=mock \
  -e PLANNER_MOCK_OUTCOME=success \
  interns2-planner-adapter:dev

curl -sS http://127.0.0.1:8002/health
```

Run the complete health/request/response-contract smoke check:

```bash
docker exec interns2-planner-adapter \
  python3 -m planner_adapter.scripts.check_planner_adapter
```

Expected top-level output is `"status": "ok"`; the planning result must be
`"status": "success"` and `"executable": false`.

Stop it with:

```bash
docker stop interns2-planner-adapter
```

## Tests

No GPU, SOFA, InternS2, robot-simulation process, or external planner is needed:

```bash
python3 -m pytest \
  tests/integration/test_planner_adapter.py \
  tests/unit/contracts/test_results.py \
  -q
```
