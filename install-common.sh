#!/bin/bash
set -e

echo "Upgrading setuptools and pip..."
pip install --upgrade pip setuptools

echo "Installing common Python packages..."
pip install nbgitpuller \
    jupyterlab-lsp \
    jupyterlab-code-formatter \
    jupyterlab-spreadsheet-editor \
    jupyterlab_templates \
    jupyter-resource-usage \
    otter-grader
    RUN pip install jupytext --upgrade

echo "Installation complete!"
