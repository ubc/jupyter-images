ARG BASE_CONTAINER=quay.io/jupyter/julia-notebook:hub-5.5.1@sha256:3adc1ab4c71f9c532edc6ff6d6ae157e026aa4748b4166105c4dfd17a8899b56
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
    apt-get clean && \
    apt-get autoremove -y

USER ${NB_UID}

# Copy and run common install script
USER root
COPY install-common.sh /tmp/install-common.sh
RUN chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN /bin/bash -x /tmp/install-common.sh

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
