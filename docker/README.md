# Docker

Service Dockerfiles are introduced after the corresponding processes work independently. Compose configuration is added after all four service boundaries are stable.

Current image:

- `docker/simulation/Dockerfile`: connected, from-scratch Ubuntu 22.04 / Python 3.10 / SOFA v24.06.00 runtime;
- `docker/simulation/Dockerfile.offline`: laboratory-server Step 5/6 image built on the preserved `interns2-robot-simulation:step4-base` image and project wheelhouse.
- `docker/planner-adapter/Dockerfile`: lightweight connected Step 9 build;
- `docker/planner-adapter/Dockerfile.offline`: laboratory-server Step 9 build that reuses the already validated `interns2-robot-simulation:dev` Python/FastAPI base without network access.
- `docker/agent-web/Dockerfile`: connected multi-stage React + FastAPI Step 11 build;
- `docker/agent-web/Dockerfile.offline`: laboratory-server Step 11 build that uses committed React assets and the validated Step 6 Python image.

The laboratory server must use the offline entry point:

```bash
docker build --network=none \
  -f docker/simulation/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:step4-base \
  -t interns2-robot-simulation:dev .
```

See `simulation/README.md` for smoke tests and server diagnostics.

The laboratory server can build the planner adapter without network access:

```bash
docker build --network=none \
  -f docker/planner-adapter/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:dev \
  -t interns2-planner-adapter:dev .
```

See `planner_adapter/README.md` for its API and acceptance commands.

The Step 11 web image can also be built without network access:

```bash
docker build --network=none \
  -f docker/agent-web/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:dev \
  -t interns2-agent-web:dev .
```

See `web/README.md` for networking, SSH port forwarding, and acceptance tests.
