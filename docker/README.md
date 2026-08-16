# Docker

Service Dockerfiles are introduced after the corresponding processes work independently. Compose configuration is added after all four service boundaries are stable.

Current image:

- `docker/simulation/Dockerfile`: connected, from-scratch Ubuntu 22.04 / Python 3.10 / SOFA v24.06.00 runtime;
- `docker/simulation/Dockerfile.offline`: laboratory-server Step 5/6 image built on the preserved `interns2-robot-simulation:step4-base` image and project wheelhouse.

The laboratory server must use the offline entry point:

```bash
docker build --network=none \
  -f docker/simulation/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:step4-base \
  -t interns2-robot-simulation:dev .
```

See `simulation/README.md` for smoke tests and server diagnostics.
