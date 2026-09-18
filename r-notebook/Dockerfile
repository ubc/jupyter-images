ARG BASE_CONTAINER=quay.io/jupyter/r-notebook:hub-5.5.0@sha256:240544c252d9aec828dca9a54652d2388f922796c8bd0b31ae8bd918731688fd
FROM $BASE_CONTAINER

# Values come from RUNTIME_PINS.env at the repo root, passed in by CI as
# --build-arg (see build.yml / build-pr.yml), shared with scipy-notebook.
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
    tzdata && \
#    cmake && \
    apt-get clean && \
    apt-get autoremove -y

USER ${NB_UID}

# Shared pip constraints govern every pip install below, including
# install-common.sh's, via PIP_CONSTRAINT.
COPY constraints.txt /tmp/constraints.txt
ENV PIP_CONSTRAINT=/tmp/constraints.txt

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
RUN /bin/bash -x /tmp/install-common.sh

# Node gets its own layer, placed after the heavy R/CRAN/install-common
# layers (not folded into the mamba solve above), so a node bump doesn't
# force a re-download of the R conda stack or a CRAN recompile.
RUN mamba install -y -c conda-forge nodejs=22 && \
    mamba clean --all -f -y

# Install AI CLI tools. Versions come from the ARGs above (CI reads them out
# of RUNTIME_PINS.env and passes them as --build-arg). The raw file is also
# baked in so a running container can be checked against its own pins.
# Placed below the heavy R/CRAN/install-common layers so a CLI version bump
# only costs this layer, not a recompile of everything above it.
COPY RUNTIME_PINS.env /etc/runtime-pins.env
RUN npm install -g \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
        "@zed-industries/codex-acp@${CODEX_ACP_VERSION}"

# pip - single resolution against the shared requirements, governed by the
# shared constraints via PIP_CONSTRAINT above
COPY requirements.txt /tmp/requirements-common.txt
RUN pip install --no-cache-dir -r /tmp/requirements-common.txt

# Fix R locale issue
RUN echo "LC_ALL=en_US.UTF-8" >> /opt/conda/lib/R/etc/Renviron

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
