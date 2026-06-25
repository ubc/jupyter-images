ARG BASE_CONTAINER=quay.io/jupyter/scipy-notebook:hub-5.5.0
FROM $BASE_CONTAINER

LABEL maintainer="Jeff Longland <jeff.longland@ubc.ca>"
LABEL course="AI100"

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    git \
    tzdata \
    wkhtmltopdf && \
    apt-get clean && \
    apt-get autoremove -y

# Install Node.js 22 LTS via NodeSource (needed for the AI coding CLIs)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean

# Install AI coding agents. For each agent we install both:
#   - the standalone CLI (for terminal use), and
#   - the ACP adapter, which is how jupyter-ai v3 surfaces the agent as a chat
#     persona (jupyter-ai's ACP *client* is pulled in by the pip step below).
RUN npm install -g \
        @anthropic-ai/claude-code \
        @zed-industries/claude-agent-acp \
        @openai/codex \
        @zed-industries/codex-acp

USER ${NB_UID}

# Common JupyterLab extensions / tooling (includes nbgitpuller)
USER root
COPY install-common.sh /tmp/install-common.sh
RUN chown jovyan:users /tmp/install-common.sh && chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN /bin/bash -x /tmp/install-common.sh

# Python packages: jupyter-ai, jupyter-server-proxy, and GizmoApp runtime deps.
#
# jupyter-ai 3.x drives coding agents over ACP; it pulls in jupyter-ai-acp-client
# automatically, so the npm ACP adapters above (claude-agent-acp / codex-acp)
# appear as chat personas with no extra pip package. Pinned to <4 so a future
# major release can't silently change the agent stack under the course.
# jupyter-ai-jupyternaut adds the default (direct-LLM) Jupyternaut chat persona.
# GizmoApp's runtime deps are Flask + gunicorn (+ optional scikit-learn for ML),
# installed here so the nbgitpuller'd copy runs immediately via server-proxy.
RUN pip install --no-cache-dir \
    jupyter-server-proxy \
    "jupyter-ai>=3.0,<4.0" \
    jupyter-ai-jupyternaut \
    openai \
    anthropic \
    "Flask>=3.0,<4.0" \
    "gunicorn>=23.0,<24.0" \
    "scikit-learn>=1.4,<2.0"

# GizmoApp launcher: server-proxy starts it on demand from the student's
# nbgitpuller'd ~/GizmoApp copy and serves it under the Jupyter base URL.
USER root
COPY ai100-notebook/start-gizmoapp.sh /usr/local/bin/start-gizmoapp.sh
COPY ai100-notebook/gizmoapp_server_proxy_config.py /tmp/gizmoapp_server_proxy_config.py
RUN chmod 755 /usr/local/bin/start-gizmoapp.sh && \
    cat /tmp/gizmoapp_server_proxy_config.py >> /etc/jupyter/jupyter_server_config.py && \
    rm /tmp/gizmoapp_server_proxy_config.py

# Fix ownership in case root touched files
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
