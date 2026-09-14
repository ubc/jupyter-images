ARG BASE_CONTAINER=quay.io/jupyter/scipy-notebook:2026-08-10
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

# Install AI CLI tools (pinned)
RUN npm install -g \
        @anthropic-ai/claude-code@2.1.270 \
        @google/gemini-cli@0.59.0 \
        @zed-industries/codex-acp@0.16.0

# pip - single resolution against the locked requirements/constraints pair
COPY scipy-notebook/requirements.txt scipy-notebook/constraints.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -c /tmp/constraints.txt

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
