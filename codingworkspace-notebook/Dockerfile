# syntax=docker/dockerfile:1
# codingworkspace-notebook
#
# Instructor-controlled agentic-coding UI (a frontend for opencode.ai) packaged
# as a JupyterHub single-user image. A thin Jupyter Server hosts CodingWorkspace
# via jupyter-server-proxy and proxies each student's preview app (with websocket
# support) under /user/<name>/proxy/<port>/. Students land directly in
# CodingWorkspace and never see JupyterLab.
#
# Built by the repo's build.yml Action: context is the repo root, so COPY paths
# are directory-prefixed, and the ECR repo is named "codingworkspace-notebook".
ARG BASE_CONTAINER=quay.io/jupyter/base-notebook:hub-5.5.0
FROM $BASE_CONTAINER

LABEL maintainer="Jeff Longland <jeff.longland@ubc.ca>"
LABEL course="AI100"

USER root

# System deps: git (workspace clones / durable repos), node (OpenCode runtime +
# `node --check`), curl/ca-certificates (OpenCode install + outbound HTTPS to the
# model proxy).
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# --- OpenCode agent binary (the thing CodingWorkspace is a frontend for) ---
# The installer installs into $HOME/.opencode; the base image sets
# HOME=/home/jovyan, so install into a throwaway HOME and copy the binary out to
# a system path on PATH (avoids polluting the student home).
# (Pin a version / vendor the binary for reproducibility later.)
RUN export HOME=/tmp/opencode-install && \
    curl -fsSL https://opencode.ai/install | bash && \
    install -m 0755 "${HOME}/.opencode/bin/opencode" /usr/local/bin/opencode && \
    rm -rf /tmp/opencode-install

# Shared jupyter-images tooling (nbgitpuller, etc.), run as the notebook user.
COPY install-common.sh /tmp/install-common.sh
RUN chown ${NB_UID}:${NB_GID} /tmp/install-common.sh && chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN /bin/bash -x /tmp/install-common.sh

# --- jupyter-server-proxy + CodingWorkspace (NOT jupyter-ai / ACP agents) ---
# CodingWorkspace is the controlled UI; OpenCode is the agent. We deliberately do
# not install jupyter-ai or the npm ACP adapters that ai100-notebook uses.
#
# Install CodingWorkspace from a LOCAL checkout passed as the `cwsrc` build
# context (build-and-push.sh sets --build-context cwsrc=/path/to/CodingWorkspace).
# This needs no GitHub credential and builds exactly what is on disk. Add the
# [postgres] extra (pip install "/cwsrc[postgres]") only if using Postgres.
#
# CI alternative (source not on the build host): install from git instead, which
# needs a read credential for the private repo (deploy key or collaborator token):
#   RUN --mount=type=secret,id=cw_token \
#       pip install --no-cache-dir jupyter-server-proxy \
#         "codingworkspace @ git+https://x-access-token:$(cat /run/secrets/cw_token)@github.com/kevinlb1/CodingWorkspace.git@<ref>"
RUN --mount=type=bind,from=cwsrc,target=/cwsrc \
    pip install --no-cache-dir jupyter-server-proxy /cwsrc

# Append the server-proxy + default_url config to the base image's config.
# DO NOT overwrite /etc/jupyter/jupyter_server_config.py — that clobbers the hub config.
USER root
COPY codingworkspace-notebook/codingworkspace_server_proxy_config.py /tmp/cw_config.py
RUN cat /tmp/cw_config.py >> /etc/jupyter/jupyter_server_config.py && rm /tmp/cw_config.py

USER ${NB_UID}
ENV HOME=/home/jovyan
WORKDIR $HOME
