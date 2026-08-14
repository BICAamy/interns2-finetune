# syntax=docker/dockerfile:1.7

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG SOFA_VERSION=v24.06.00
ARG SOFA_ARCHIVE=SOFA_v24.06.00_Linux.zip
ARG SOFA_DOWNLOAD_URL=https://github.com/sofa-framework/sofa/releases/download/v24.06.00/SOFA_v24.06.00_Linux.zip
ARG SOFA_ARCHIVE_SHA256=9d515e2f25f657c744821be8a5361e22803c18947b33af7a0b357c259202236a

LABEL org.opencontainers.image.title="InternS2 SOFA/LapGym simulation"
LABEL org.opencontainers.image.description="Pinned SOFA and sofa_env runtime for surgical navigation simulation"
LABEL org.opencontainers.image.version="${SOFA_VERSION}"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libdbus-1-3 \
        libegl-mesa0 \
        libegl1 \
        libfontconfig1 \
        libfreetype6 \
        libgl1 \
        libgl1-mesa-dri \
        libgles2 \
        libglew2.2 \
        libglib2.0-0 \
        libglu1-mesa \
        libglx-mesa0 \
        libice6 \
        libopengl0 \
        libsm6 \
        libx11-6 \
        libx11-xcb1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxinerama1 \
        libxkbcommon0 \
        libxrandr2 \
        libxrender1 \
        libxxf86vm1 \
        mesa-utils \
        pkg-config \
        python3.10 \
        python3.10-dev \
        python3-distutils \
        python3-pip \
        unzip \
        wget \
        xauth \
        x11-utils \
        xvfb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN test "$(uname -m)" = "x86_64" \
    && python3 -c "import sys; assert sys.version_info[:2] == (3, 10), sys.version"

WORKDIR /opt

RUN curl --fail --location --retry 5 --retry-all-errors \
        --output "/tmp/${SOFA_ARCHIVE}" "${SOFA_DOWNLOAD_URL}" \
    && echo "${SOFA_ARCHIVE_SHA256}  /tmp/${SOFA_ARCHIVE}" | sha256sum --check --strict \
    && unzip -q "/tmp/${SOFA_ARCHIVE}" -d /opt \
    && mv "/opt/SOFA_${SOFA_VERSION}_Linux" /opt/sofa \
    && rm "/tmp/${SOFA_ARCHIVE}" \
    && test -x /opt/sofa/bin/runSofa \
    && test -d /opt/sofa/plugins/SofaPython3/lib/python3/site-packages/Sofa

ENV SOFA_ROOT=/opt/sofa \
    SOFAPYTHON3_ROOT=/opt/sofa/plugins/SofaPython3

ENV PATH="${SOFA_ROOT}/bin:${PATH}" \
    PYTHONPATH="${SOFAPYTHON3_ROOT}/lib/python3/site-packages:/workspace/third_party/sofa_env" \
    LD_LIBRARY_PATH="${SOFA_ROOT}/bin:${SOFA_ROOT}/lib:${SOFAPYTHON3_ROOT}/lib" \
    LIBGL_ALWAYS_SOFTWARE=1 \
    QT_QPA_PLATFORM=offscreen \
    OMP_NUM_THREADS=1

# Use a project-owned bounded launcher rather than xvfb-run's retry loop.
COPY simulation/scripts/run_with_xvfb.sh /usr/local/bin/run-with-xvfb
RUN chmod 0755 /usr/local/bin/run-with-xvfb \
    && timeout --signal=INT --kill-after=5s 30s run-with-xvfb glxinfo -B

COPY simulation/requirements.txt /tmp/simulation-requirements.txt

RUN python3 -m pip install \
        pip==24.0 \
        setuptools==69.5.1 \
        wheel==0.43.0 \
    && python3 -m pip install --requirement /tmp/simulation-requirements.txt

WORKDIR /workspace

COPY third_party/sofa_env /workspace/third_party/sofa_env
COPY simulation /workspace/simulation

# sofa_env's custom develop command downloads SOFA unless SKIP_SOFA is set.
# SOFA has already been downloaded, checksum-verified, and configured above.
RUN SKIP_SOFA=1 python3 -m pip install \
        --no-deps \
        --editable /workspace/third_party/sofa_env \
    && python3 simulation/scripts/check_sofa_imports.py

CMD ["python3", "simulation/scripts/check_sofa_imports.py"]
