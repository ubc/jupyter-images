# Soci 428 — RStudio Server image for JupyterHub (Z2JH)
# Base: rocker/tidyverse pins R version + tidyverse + RStudio Server
FROM rocker/tidyverse:4.6.1

# ---- System dependencies for JupyterHub integration ----
# We need Python + pip to install jupyterhub-singleuser and jupyter-rsession-proxy,
# which is the bridge that lets JupyterHub spawn and proxy to RStudio Server.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---- JupyterHub plumbing ----
# jupyterhub-singleuser is what Z2JH's KubeSpawner actually launches.
# jupyter-rsession-proxy is the extension that proxies RStudio through it.
# Pinning versions to match the Hub (5.5.0) keeps the image reproducible across rebuilds.
# Using --break-system-packages because Debian 12 marks /usr as externally managed;
# acceptable here since the container is single-purpose.
RUN pip3 install --break-system-packages --no-cache-dir \
        jupyterhub==5.5.0 \
        jupyter-server==2.19.0 \
        jupyter-rsession-proxy==2.4.0 \
        notebook==7.5.7

# ---- Enable GitHub Copilot in RStudio Server ----
# This is the admin-side toggle. Each student still authenticates their own
# GitHub Education account from inside RStudio (Tools > Global Options > Copilot).
RUN echo "copilot-enabled=1" >> /etc/rstudio/rsession.conf

# ---- Course-specific R packages ----
# Rocker is wired to Posit Package Manager, so these are fast binary installs.
# Add/remove packages as the syllabus evolves; rebuilding the image is cheap.
RUN R -e "install.packages(c( \
        'haven', \
        'survey', \
        'srvyr', \
        'broom', \
        'modelsummary', \
        'marginaleffects', \
        'performance', \
        'see', \
        'car', \
        'lmtest', \
        'sandwich', \
        'estimatr', \
        'fixest', \
        'ggeffects', \
        'gtsummary', \
        'janitor', \
        'skimr', \
        'corrr' \
    ), repos = 'https://packagemanager.posit.co/cran/__linux__/jammy/latest')"

# ---- Shared course datasets (optional pattern) ----
# Bake common datasets into the image so every student has them at /srv/data.
# Alternatively, mount a read-only PVC at /srv/data via Z2JH — more flexible.
RUN mkdir -p /srv/data
# COPY datasets/ /srv/data/
RUN chmod -R a+r /srv/data

# ---- Home directory symlink for Z2JH compatibility ----
# Z2JH mounts the persistent home volume at /home/jovyan (hub-wide default).
# Rocker/RStudio expects the user's home at /home/rstudio.
# We create /home/jovyan as the real directory and symlink /home/rstudio to it,
# so RStudio's reads/writes land in the persistent volume at runtime.
RUN mkdir -p /home/jovyan \
    && chown rstudio:rstudio /home/jovyan \
    && rm -rf /home/rstudio \
    && ln -s /home/jovyan /home/rstudio

# ---- Fix RStudio Server state-directory ownership for non-root launch ----
# rocker/tidyverse creates these owned by the 'rstudio-server' system account,
# for its normal root-launched/s6-supervised startup path. jupyter-rsession-proxy
# instead launches rserver directly as the singleuser process (uid 1000, user
# 'rstudio'), which needs write access to its own state DB and session key.
RUN chown -R rstudio:rstudio /var/lib/rstudio-server /var/run/rstudio-server

# ---- Persistent user package library ----
# Rocker installs packages to /usr/local, which is NOT persisted across sessions.
# This creates a user-writable library inside the persistent home volume so
# student-installed packages survive logout. The Renviron file points R there.
RUN mkdir -p /home/rstudio/R/library \
    && chown -R rstudio:rstudio /home/jovyan \
    && echo "R_LIBS_USER=/home/rstudio/R/library" >> /usr/local/lib/R/etc/Renviron.site

# ---- Default working directory ----
WORKDIR /home/rstudio

# ---- Switch to non-root user for runtime ----
# Rocker creates the 'rstudio' user (UID 1000) in the base image.
# jupyter-server refuses to run as root, and Z2JH expects UID 1000 by default,
# so we explicitly switch before the container's CMD runs.
USER rstudio

# Z2JH's KubeSpawner will call `jupyterhub-singleuser` as the container command;
# no CMD/ENTRYPOINT override needed here. RStudio is launched on demand via
# jupyter-rsession-proxy when the user hits /rstudio.
