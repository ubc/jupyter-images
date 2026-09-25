ARG BASE_CONTAINER=quay.io/jupyter/tensorflow-notebook:hub-5.5.1@sha256:b0b757cab79d17a65400e03e2e837a2d7cc10d9cbc97a0b082a197f65e2cba4b
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

# pip
RUN pip install --no-cache-dir \
    jupyter \
    opencv-python-headless \
    plotly \
    skorch \
    torch \
    torchvision \
    torchaudio \
    torch-inspect \
    nbgrader \
    ngshare_exchange

# Add nbgrader config for nbshare (course_id comes from the
# NBGRADER_COURSE_ID env var set per-spawn by 13-nbgrader-course-id-env
# Patch formgrader to hide Manage Students and Course List menus
USER root
COPY tensorflow-notebook/nbgrader_config.py /etc/jupyter/nbgrader_config.py
COPY tensorflow-notebook/patch_formgrader.py /tmp/patch_formgrader.py
RUN chmod 644 /etc/jupyter/nbgrader_config.py && \
    chmod 755 /tmp/patch_formgrader.py
    
# Run the patch
USER ${NB_UID}
RUN python3 /tmp/patch_formgrader.py

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
