# Docker

Service Dockerfiles are introduced after the corresponding processes work independently. Compose configuration is added after all four service boundaries are stable.

Current images:

- `docker/simulation/Dockerfile`: isolated Ubuntu 22.04 / Python 3.10 / SOFA v24.06.00 / LapGym runtime.

Build the Step 4 simulation image from the repository root:

```bash
docker build -f docker/simulation/Dockerfile -t interns2-robot-simulation:dev .
```

See `simulation/README.md` for smoke tests and server diagnostics.
