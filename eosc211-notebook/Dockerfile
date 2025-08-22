ARG BASE_CONTAINER=quay.io/jupyter/base-notebook:latest  # Replace image and tag
FROM $BASE_CONTAINER

USER root

RUN apt-get update && \
    apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    git \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

USER $NB_UID

# Copy environment.yml and postBuild into the container
COPY environment.yml /tmp/environment.yml
COPY postBuild /tmp/postBuild

USER root
RUN conda install -y mamba -n base -c conda-forge && \
    mamba env create -f /tmp/environment.yml && \
    conda clean --all -y
RUN chmod +x /tmp/postBuild && /tmp/postBuild && rm /tmp/postBuild

USER $NB_UID
RUN echo "conda activate e211_notebook" >> /home/jovyan/.bashrc

# Fix ownership
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
