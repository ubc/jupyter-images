ARG BASE_CONTAINER=quay.io/jupyter/scipy-notebook:2026-08-10
FROM $BASE_CONTAINER

# Values come from RUNTIME_PINS.env at the repo root, passed in by CI as
# --build-arg (see build.yml / build-pr.yml), shared with r-notebook.
ARG CLAUDE_CODE_VERSION
ARG GEMINI_CLI_VERSION
ARG CODEX_ACP_VERSION

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

# Shared pip constraints govern every pip install below, including
# install-common.sh's, via PIP_CONSTRAINT.
COPY constraints.txt /tmp/constraints.txt
ENV PIP_CONSTRAINT=/tmp/constraints.txt

# Copy and run common install script
USER root
COPY install-common.sh /tmp/install-common.sh
RUN chown jovyan:users /tmp/install-common.sh && chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN /bin/bash -x /tmp/install-common.sh

# conda
USER root
RUN mkdir -p /home/jovyan/.cache/conda/pkgs/cache/shards && \
    chown -R ${NB_UID}:users /home/jovyan/.cache
USER ${NB_UID}
RUN mamba install -y -c conda-forge \
    gdal \
    geos \
    proj \
    nodejs=22 && \
    mamba clean -afy

# Install AI CLI tools. Versions come from the ARGs above (CI reads them out
# of RUNTIME_PINS.env and passes them as --build-arg). The raw file is also
# baked in so a running container can be checked against its own pins.
COPY RUNTIME_PINS.env /etc/runtime-pins.env
RUN npm install -g \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
        "@zed-industries/codex-acp@${CODEX_ACP_VERSION}"

# pip - single resolution against the shared + image requirements, governed
# by the shared constraints via PIP_CONSTRAINT above
COPY requirements.txt /tmp/requirements-common.txt
COPY scipy-notebook/requirements.txt /tmp/requirements-image.txt
RUN pip install --no-cache-dir -r /tmp/requirements-common.txt -r /tmp/requirements-image.txt

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
