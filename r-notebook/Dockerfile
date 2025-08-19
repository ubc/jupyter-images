ARG BASE_CONTAINER=quay.io/jupyter/r-notebook:hub-5.3.0
FROM $BASE_CONTAINER

USER root

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    tzdata && \
    apt-get clean && \
    apt-get autoremove -y

USER ${NB_UID}

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
    r-tidytext && \
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
RUN chmod +x /tmp/install-common.sh
USER ${NB_UID}
RUN /bin/bash -x /tmp/install-common.sh

# Fix R locale issue
RUN echo "LC_ALL=en_US.UTF-8" >> /opt/conda/lib/R/etc/Renviron

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
