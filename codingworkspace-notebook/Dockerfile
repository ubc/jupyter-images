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
# Pin a version; COPY a vendored binary instead of curl|bash for reproducibility.
RUN curl -fsSL https://opencode.ai/install | bash && \
    install -m 0755 /root/.opencode/bin/opencode /usr/local/bin/opencode

# Shared jupyter-images tooling (nbgitpuller, etc.), run as the notebook user.
COPY install-common.sh /tmp/install-common.sh
RUN chown ${NB_UID}:${NB_GID} /tmp/install-common.sh && chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN /bin/bash -x /tmp/install-common.sh

# --- jupyter-server-proxy + CodingWorkspace (NOT jupyter-ai / ACP agents) ---
# CodingWorkspace is the controlled UI; OpenCode is the agent. We deliberately do
# not install jupyter-ai or the npm ACP adapters that ai100-notebook uses.
# TODO: pin @<tag-or-sha> once the jupyterhub-port branch is merged/tagged.
# Add ",psycopg[binary]" style extra only if using Postgres (codingworkspace[postgres]).
RUN pip install --no-cache-dir \
        jupyter-server-proxy \
        "codingworkspace @ git+https://github.com/kevinlb1/CodingWorkspace.git@jupyterhub-port"

# Append the server-proxy + default_url config to the base image's config.
# DO NOT overwrite /etc/jupyter/jupyter_server_config.py — that clobbers the hub config.
USER root
COPY codingworkspace-notebook/codingworkspace_server_proxy_config.py /tmp/cw_config.py
RUN cat /tmp/cw_config.py >> /etc/jupyter/jupyter_server_config.py && rm /tmp/cw_config.py

USER ${NB_UID}
ENV HOME=/home/jovyan
WORKDIR $HOME
