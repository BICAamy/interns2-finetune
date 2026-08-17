# syntax=docker/dockerfile:1.7

FROM node:22.14.0-alpine3.21 AS frontend

WORKDIR /frontend
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/frontend/ ./
RUN npm run build

FROM python:3.10-slim-bookworm

LABEL org.opencontainers.image.title="InternS2 surgical navigation agent-web"
LABEL org.opencontainers.image.description="FastAPI API and React console for confirmed simulation tasks"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace/packages/surgical_contracts:/workspace

WORKDIR /workspace

COPY web/backend/requirements.txt /tmp/agent-web-requirements.txt
COPY web/backend/asr-requirements.txt /tmp/asr-requirements.txt
RUN python3 -m pip install \
        --requirement /tmp/agent-web-requirements.txt \
        --requirement /tmp/asr-requirements.txt

COPY packages/surgical_contracts /workspace/packages/surgical_contracts
COPY agent /workspace/agent
COPY web/__init__.py /workspace/web/__init__.py
COPY web/backend /workspace/web/backend
COPY --from=frontend /frontend/dist /workspace/web/frontend/dist

RUN python3 -m compileall -q /workspace/agent /workspace/web/backend \
    && test -s /workspace/web/frontend/dist/index.html

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-m", "web.backend.healthcheck"]

CMD ["python3", "-m", "web.backend.main"]
