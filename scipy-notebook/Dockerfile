ARG BASE_CONTAINER=quay.io/jupyter/scipy-notebook:hub-5.5.1@sha256:41e9176dc64072976c43c037f853ae9a95ca34aeb0170c58a1b304d62fbde486
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    tzdata \
    wkhtmltopdf && \
    apt-get clean && \
    apt-get autoremove -y

USER ${NB_UID}

# Shared pip constraints apply at build time only: each pip-running RUN below
# sets PIP_CONSTRAINT inline. Deliberately not an ENV, so student pods can
# install any package version (a server restart returns them to the pins).
COPY constraints.txt /tmp/constraints.txt

# Copy and run common install script
USER root
COPY install-common.sh /tmp/install-common.sh
RUN chown jovyan:users /tmp/install-common.sh && chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN PIP_CONSTRAINT=/tmp/constraints.txt /bin/bash -x /tmp/install-common.sh

# conda
USER root
RUN mkdir -p /home/jovyan/.cache/conda/pkgs/cache/shards && \
    chown -R ${NB_UID}:users /home/jovyan/.cache
USER ${NB_UID}
RUN mamba install -y -c conda-forge \
    gdal \
    geos \
    proj && \
    mamba clean -afy

# Node gets its own layer so a version bump doesn't invalidate the geo-libs
# solve above it.
RUN mamba install -y -c conda-forge nodejs=22 && \
    mamba clean -afy

# Install AI CLI tools. Versions are sourced from RUNTIME_PINS.env (repo root,
# shared with r-notebook), baked in at /etc/runtime-pins.env so a running
# container can be checked against its own pins. The :? guards fail the build
# if a pin is missing, instead of npm silently installing latest.
COPY RUNTIME_PINS.env /etc/runtime-pins.env
RUN . /etc/runtime-pins.env && \
    : "${CLAUDE_CODE_VERSION:?missing in RUNTIME_PINS.env}" \
      "${GEMINI_CLI_VERSION:?missing in RUNTIME_PINS.env}" \
      "${CODEX_ACP_VERSION:?missing in RUNTIME_PINS.env}" && \
    npm install -g \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
        "@zed-industries/codex-acp@${CODEX_ACP_VERSION}"

# pip - single resolution against the shared + image requirements, governed
# by the shared constraints (build-time only, set inline)
COPY requirements.txt /tmp/requirements-common.txt
COPY scipy-notebook/requirements.txt /tmp/requirements-image.txt
RUN PIP_CONSTRAINT=/tmp/constraints.txt pip install --no-cache-dir \
        -r /tmp/requirements-common.txt -r /tmp/requirements-image.txt

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
