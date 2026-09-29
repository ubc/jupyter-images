ARG BASE_CONTAINER=quay.io/jupyter/r-notebook:hub-5.5.1@sha256:68692c9b09177a2ea0841172674eddfdb7c3f230812e25cb8ec57b6eb402fa24
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    tzdata && \
#    cmake && \
    apt-get clean && \
    apt-get autoremove -y

USER ${NB_UID}

# Shared pip constraints apply at build time only: each pip-running RUN below
# sets PIP_CONSTRAINT inline. Deliberately not an ENV, so student pods can
# install any package version (a server restart returns them to the pins).
COPY constraints.txt /tmp/constraints.txt

# R packages via mamba (conda-forge)
RUN mamba install --yes -c conda-forge \
    r-stargazer \
    r-quanteda \
    r-quanteda.textmodels \
    r-quanteda.textplots \
    r-quanteda.textstats \
    r-caret \
    r-ggiraph \
    r-ggextra \
    r-isocodes \
    r-urltools \
    r-ggthemes \
    r-modelsummary \
    r-nsyllable \
    r-proxyc \
    r-tidytext \
    r-car \
    r-units \
    r-sf && \
    mamba clean --all -f -y

# R packages from CRAN (source)
RUN R -e "install.packages(c( \
    'ggiraphExtra', \
    'sandwich' \
), repos='https://cloud.r-project.org')" && \
    R -e "install.packages('https://cran.r-project.org/src/contrib/Archive/lisp/lisp_0.1.tar.gz', repos=NULL, type='source')" && \
    R -e "install.packages('https://cran.r-project.org/src/contrib/Archive/translate/translate_0.1.2.tar.gz', repos=NULL, type='source')"

# Copy and run common install script
USER root
COPY install-common.sh /tmp/install-common.sh
RUN chown jovyan:users /tmp/install-common.sh && chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN PIP_CONSTRAINT=/tmp/constraints.txt /bin/bash -x /tmp/install-common.sh

# Node gets its own layer, placed after the heavy R/CRAN/install-common
# layers (not folded into the mamba solve above), so a node bump doesn't
# force a re-download of the R conda stack or a CRAN recompile.
RUN mamba install -y -c conda-forge nodejs=22 && \
    mamba clean --all -f -y

# Install AI CLI tools. Versions are sourced from RUNTIME_PINS.env (repo root,
# shared with scipy-notebook), baked in at /etc/runtime-pins.env so a running
# container can be checked against its own pins. The :? guards fail the build
# if a pin is missing, instead of npm silently installing latest.
# Placed below the heavy R/CRAN/install-common layers so a CLI version bump
# only costs this layer, not a recompile of everything above it.
COPY RUNTIME_PINS.env /etc/runtime-pins.env
RUN . /etc/runtime-pins.env && \
    : "${CLAUDE_CODE_VERSION:?missing in RUNTIME_PINS.env}" \
      "${GEMINI_CLI_VERSION:?missing in RUNTIME_PINS.env}" \
      "${CODEX_ACP_VERSION:?missing in RUNTIME_PINS.env}" && \
    npm install -g \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
        "@zed-industries/codex-acp@${CODEX_ACP_VERSION}"

# pip - single resolution against the shared requirements, governed by the
# shared constraints (build-time only, set inline)
COPY requirements.txt /tmp/requirements-common.txt
RUN PIP_CONSTRAINT=/tmp/constraints.txt pip install --no-cache-dir \
        -r /tmp/requirements-common.txt

# Fix R locale issue
RUN echo "LC_ALL=en_US.UTF-8" >> /opt/conda/lib/R/etc/Renviron

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
