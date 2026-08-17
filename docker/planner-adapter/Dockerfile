FROM python:3.10-slim

LABEL org.opencontainers.image.title="InternS2 puncture planner adapter"
LABEL org.opencontainers.image.description="Provider-neutral, non-executable puncture planning API"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace/packages/surgical_contracts:/workspace

WORKDIR /workspace

COPY planner_adapter/requirements.txt /tmp/planner-adapter-requirements.txt
RUN python3 -m pip install --requirement /tmp/planner-adapter-requirements.txt

COPY packages/surgical_contracts /workspace/packages/surgical_contracts
COPY planner_adapter /workspace/planner_adapter

RUN python3 -m compileall -q /workspace/planner_adapter \
    && python3 -c "from planner_adapter.main import app; assert app.state.planner_adapter.health().ready"

EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-m", "planner_adapter.healthcheck"]

CMD ["python3", "-m", "planner_adapter.main"]
