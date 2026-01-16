ARG BASE_CONTAINER=quay.io/jupyter/tensorflow-notebook:hub-5.4.3
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

RUN apt-get update && \
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
    nbgrader

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
