ARG BASE_CONTAINER=quay.io/jupyter/base-notebook:latest  # Replace image and tag
FROM $BASE_CONTAINER

USER root

RUN apt-get update
RUN apt-get install -y \
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
    libasound2t64 \
    git \
    curl 
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

USER root

RUN conda install -y -c conda-forge mamba
COPY environment.yml /tmp/environment.yml
RUN mamba env create -f /tmp/environment.yml -p /opt/conda/envs/my_notebook && conda clean --all -y

RUN conda run -n my_notebook playwright install chromium

USER $NB_UID
RUN echo "conda activate /opt/conda/envs/e211_notebook" >> /home/jovyan/.bashrc

# Fix ownership
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
